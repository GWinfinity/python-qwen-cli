import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import asyncio
import markdown

# 简单的控制台日志记录器
logger = {
    'debug': lambda *args: print(f"[DEBUG] [ImportProcessor] {' '.join(map(str, args))}"),
    'warn': lambda *args: print(f"[WARN] [ImportProcessor] {' '.join(map(str, args))}"),
    'error': lambda *args: print(f"[ERROR] [ImportProcessor] {' '.join(map(str, args))}"),
}

# 定义类型别名以提高可读性
MemoryFileDict = Dict[str, Any]
ProcessImportsResultDict = Dict[str, Any]
ImportStateDict = Dict[str, Any]

async def find_project_root(start_dir: str) -> str:
    """查找项目根目录（查找.git目录）"""
    current_dir = os.path.resolve(start_dir)
    while True:
        git_path = os.path.join(current_dir, '.git')
        try:
            if os.path.isdir(git_path):
                return current_dir
        except Exception:
            # .git 未找到，继续向上查找
            pass
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            # 到达文件系统根目录
            break
        current_dir = parent_dir
    # 如果未找到.git，回退到起始目录
    return os.path.resolve(start_dir)


def has_message(err: Any) -> bool:
    """检查错误对象是否有message属性"""
    return isinstance(err, object) and err is not None and hasattr(err, 'message') and isinstance(err.message, str)


def find_imports(content: str) -> List[Dict[str, Any]]:
    """查找内容中的所有导入语句
    返回格式: [{'start': 起始位置, '_end': 结束位置, 'path': 导入路径}, ...]
    """
    imports = []
    i = 0
    content_len = len(content)

    while i < content_len:
        # 查找下一个@符号
        i = content.find('@', i)
        if i == -1:
            break

        # 检查是否是单词边界（不是其他单词的一部分）
        if i > 0 and not content[i-1].isspace():
            i += 1
            continue

        # 查找导入路径的结束位置（空格或换行符）
        j = i + 1
        while j < content_len and not content[j].isspace() and content[j] != '\n' and content[j] != '\r':
            j += 1

        # 提取路径（@后面的所有内容）
        import_path = content[i+1:j]

        # 基本验证（以./或/或字母开头）
        if len(import_path) > 0 and (import_path[0] == '.' or import_path[0] == '/' or import_path[0].isalpha()):
            imports.append({
                'start': i,
                '_end': j,
                'path': import_path
            })

        i = j + 1

    return imports


def is_whitespace(char: str) -> bool:
    """检查字符是否为空白字符"""
    return char in [' ', '\t', '\n', '\r']


def is_letter(char: str) -> bool:
    """检查字符是否为字母"""
    return char.isalpha()


def find_code_regions(content: str) -> List[Tuple[int, int]]:
    """查找所有代码块和内联代码区域"""
    regions = []
    # 使用markdown库解析内容
    from markdown.treeprocessors import Treeprocessor
    from markdown.extensions import Extension
    import xml.etree.ElementTree as ET

    class CodeBlockProcessor(Treeprocessor):
        def run(self, root):
            # 查找所有代码块
            for code_block in root.findall(".//pre/code"):
                # 获取原始内容
                raw_code = code_block.text
                if not raw_code:
                    continue
                # 查找原始内容在原文中的位置
                start_pos = content.find(raw_code)
                if start_pos != -1:
                    end_pos = start_pos + len(raw_code)
                    regions.append((start_pos, end_pos))
            # 查找所有内联代码
            for inline_code in root.findall(".//code"):
                if inline_code.getparent().tag == 'pre':
                    continue  # 已经处理过
                raw_code = inline_code.text
                if not raw_code:
                    continue
                start_pos = content.find(raw_code)
                if start_pos != -1:
                    end_pos = start_pos + len(raw_code)
                    regions.append((start_pos, end_pos))
            return root

    class CodeRegionExtension(Extension):
        def extendMarkdown(self, md):
            md.treeprocessors.register(CodeBlockProcessor(md), 'code_block', 175)

    # 解析Markdown内容
    md = markdown.Markdown(extensions=[CodeRegionExtension()])
    md.convert(content)

    return regions


async def process_imports(
    content: str,
    base_path: str,
    debug_mode: bool = False,
    import_state: Optional[ImportStateDict] = None,
    project_root: Optional[str] = None,
    import_format: str = 'tree'
) -> ProcessImportsResultDict:
    """处理QWEN.md内容中的导入语句
    支持@path/to/file语法导入其他文件的内容
    """
    if import_state is None:
        import_state = {
            'processed_files': set(),
            'max_depth': 5,
            'current_depth': 0
        }

    if not project_root:
        project_root = await find_project_root(base_path)

    if import_state['current_depth'] >= import_state['max_depth']:
        if debug_mode:
            logger['warn'](f"达到最大导入深度 ({import_state['max_depth']})。停止导入处理。")
        return {
            'content': content,
            'import_tree': {'path': import_state.get('current_file', 'unknown')}
        }

    # --- 扁平化格式逻辑 ---
    if import_format == 'flat':
        # 使用队列按首次遇到的顺序处理文件，并使用集合避免重复
        flat_files = []
        # 跟踪整个操作中已处理的文件
        processed_files = set()

        # 递归处理导入的辅助函数
        async def process_flat(file_content: str, file_base_path: str, file_path: str, depth: int):
            # 标准化文件路径以确保一致比较
            normalized_path = os.path.normpath(file_path)

            # 如果已处理过则跳过
            if normalized_path in processed_files:
                return

            # 在处理前标记为已处理以防止无限递归
            processed_files.add(normalized_path)

            # 将此文件添加到扁平列表
            flat_files.append({'path': normalized_path, 'content': file_content})

            # 查找此文件中的导入
            code_regions = find_code_regions(file_content)
            imports = find_imports(file_content)

            # 反向顺序处理导入以正确处理索引
            for i in range(len(imports) - 1, -1, -1):
                imp = imports[i]
                start = imp['start']
                _end = imp['_end']
                import_path = imp['path']

                # 如果在代码区域内则跳过
                if any(region_start <= start < region_end for region_start, region_end in code_regions):
                    continue

                # 验证导入路径
                if not validate_import_path(import_path, file_base_path, [project_root]):
                    continue

                full_path = os.path.resolve(file_base_path, import_path)
                normalized_full_path = os.path.normpath(full_path)

                # 如果已处理过则跳过
                if normalized_full_path in processed_files:
                    continue

                try:
                    # 检查文件是否存在
                    if os.path.exists(full_path):
                        with open(full_path, 'r', encoding='utf-8') as f:
                            imported_content = f.read()

                        # 处理导入的文件
                        await process_flat(
                            imported_content,
                            os.path.dirname(full_path),
                            normalized_full_path,
                            depth + 1
                        )
                except Exception as error:
                    if debug_mode:
                        error_msg = error.message if has_message(error) else '未知错误'
                        logger['warn'](f"导入 {full_path} 失败: {error_msg}")
                # 即使一个导入失败，也继续处理其他导入

        # 从根文件开始（当前文件）
        root_path = os.path.normpath(import_state.get('current_file') or os.path.resolve(base_path))
        await process_flat(content, base_path, root_path, 0)

        # 按顺序连接所有唯一文件，Claude风格
        flat_content = '\n\n'.join([
            f"--- File: {f['path']} ---\n{f['content'].strip()}\n--- End of File: {f['path']} ---"
            for f in flat_files
        ])

        return {
            'content': flat_content,
            'import_tree': {'path': root_path}  # 扁平模式下树结构无意义
        }

    # --- 树形格式逻辑（原有） ---
    code_regions = find_code_regions(content)
    result = ''
    last_index = 0
    imports = []
    imports_list = find_imports(content)

    for imp in imports_list:
        start = imp['start']
        _end = imp['_end']
        import_path = imp['path']

        # 添加此导入之前的内容
        result += content[last_index:start]
        last_index = _end

        # 如果在代码区域内则跳过
        if any(region_start <= start < region_end for region_start, region_end in code_regions):
            result += f"@{import_path}"

        # 验证导入路径以防止路径遍历攻击
        if not validate_import_path(import_path, base_path, [project_root]):
            result += f"<!-- Import failed: {import_path} - Path traversal attempt -->"

        full_path = os.path.resolve(base_path, import_path)
        if full_path in import_state['processed_files']:
            result += f"<!-- File already processed: {import_path} -->"

        try:
            # 检查文件是否存在
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()

                # 标记此文件为已处理
                new_import_state = {
                    'processed_files': set(import_state['processed_files']),
                    'max_depth': import_state['max_depth'],
                    'current_depth': import_state['current_depth'] + 1,
                    'current_file': full_path
                }
                new_import_state['processed_files'].add(full_path)

                imported = await process_imports(
                    file_content,
                    os.path.dirname(full_path),
                    debug_mode,
                    new_import_state,
                    project_root,
                    import_format
                )

                result += f"<!-- Imported from: {import_path} -->\n{imported['content']}\n<!-- End of import from: {import_path} -->"
                imports.append(imported['import_tree'])
        except Exception as err:
            message = '未知错误'
            if has_message(err):
                message = err.message
            elif isinstance(err, str):
                message = err
            logger['error'](f"导入 {import_path} 失败: {message}")
            result += f"<!-- Import failed: {import_path} - {message} -->"

    # 添加最后一个匹配项之后的所有剩余内容
    result += content[last_index:]

    return {
        'content': result,
        'import_tree': {
            'path': import_state.get('current_file', 'unknown'),
            'imports': imports if len(imports) > 0 else None
        }
    }


def validate_import_path(import_path: str, base_path: str, allowed_directories: List[str]) -> bool:
    """验证导入路径，防止路径遍历攻击"""
    # 拒绝URLs
    if re.match(r'^(file|https?):\/\/', import_path):
        return False

    resolved_path = os.path.resolve(base_path, import_path)

    for allowed_dir in allowed_directories:
        normalized_allowed_dir = os.path.resolve(allowed_dir)
        is_same_path = resolved_path == normalized_allowed_dir
        is_sub_path = resolved_path.startswith(normalized_allowed_dir + os.path.sep)
        if is_same_path or is_sub_path:
            return True

    return False


# 主函数演示
async def main():
    # 示例用法
    content = "# 测试文档\n\n@imports/test.md\n\n这是一个测试。"
    base_path = os.path.dirname(os.path.abspath(__file__))
    result = await process_imports(content, base_path)
    print(result['content'])


if __name__ == '__main__':
    asyncio.run(main())