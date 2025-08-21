import asyncio
import os
from typing import Optional, Set, List, Dict, Any, Pattern

# 常量定义
MAX_ITEMS = 20
TRUNCATION_INDICATOR = '...'
DEFAULT_IGNORED_FOLDERS = {'node_modules', '.git', 'dist'}

# 类型定义和接口
class FolderStructureOptions:
    def __init__(self,
                 max_items: Optional[int] = None,
                 ignored_folders: Optional[Set[str]] = None,
                 file_include_pattern: Optional[Pattern] = None,
                 file_service: Optional[Any] = None,
                 file_filtering_options: Optional[Dict[str, bool]] = None):
        self.max_items = max_items
        self.ignored_folders = ignored_folders
        self.file_include_pattern = file_include_pattern
        self.file_service = file_service
        self.file_filtering_options = file_filtering_options

class FullFolderInfo:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.files: List[str] = []
        self.sub_folders: List[FullFolderInfo] = []
        self.total_children = 0
        self.total_files = 0
        self.is_ignored: Optional[bool] = None
        self.has_more_files: Optional[bool] = None
        self.has_more_subfolders: Optional[bool] = None

# 辅助函数
async def read_full_structure(root_path: str, options: Dict[str, Any]) -> Optional[FullFolderInfo]:
    root_name = os.path.basename(root_path)
    root_node = FullFolderInfo(root_name, root_path)

    queue = [(root_node, root_path)]
    current_item_count = 0
    processed_paths = set()  # 避免处理相同路径（如果有符号链接造成循环）

    while queue:
        folder_info, current_path = queue.pop(0)

        if current_path in processed_paths:
            continue
        processed_paths.add(current_path)

        if current_item_count >= options['maxItems']:
            continue

        try:
            # 使用 asyncio.to_thread 包装同步文件操作
            entries = await asyncio.to_thread(os.scandir, current_path)
            # 按名称排序以保持一致的处理顺序
            entries = sorted(entries, key=lambda e: e.name)
        except PermissionError as e:
            print(f"Warning: Could not read directory {current_path}: Permission denied")
            if current_path == root_path:
                return None
            continue
        except FileNotFoundError as e:
            print(f"Warning: Could not read directory {current_path}: Not found")
            if current_path == root_path:
                return None
            continue
        except Exception as e:
            print(f"Warning: Error reading directory {current_path}: {str(e)}")
            continue

        files_in_current_dir = []
        sub_folders_in_current_dir = []

        # 先处理当前目录中的文件
        for entry in entries:
            if entry.is_file():
                if current_item_count >= options['maxItems']:
                    folder_info.has_more_files = True
                    break
                file_name = entry.name
                file_path = os.path.join(current_path, file_name)

                should_ignore = False
                if options['fileService']:
                    fs = options['fileService']
                    ff_options = options['fileFilteringOptions'] or {}
                    if ff_options.get('respectGitIgnore', False) and fs.should_git_ignore_file(file_path):
                        should_ignore = True
                    if ff_options.get('respectGeminiIgnore', False) and fs.should_gemini_ignore_file(file_path):
                        should_ignore = True

                if should_ignore:
                    continue

                if not options['fileIncludePattern'] or options['fileIncludePattern'].match(file_name):
                    files_in_current_dir.append(file_name)
                    current_item_count += 1
                    folder_info.total_files += 1
                    folder_info.total_children += 1

        folder_info.files = files_in_current_dir

        # 然后处理目录并将它们加入队列
        for entry in entries:
            if entry.is_dir():
                if current_item_count >= options['maxItems']:
                    folder_info.has_more_subfolders = True
                    break

                sub_folder_name = entry.name
                sub_folder_path = os.path.join(current_path, sub_folder_name)

                is_ignored = False
                if options['fileService']:
                    fs = options['fileService']
                    ff_options = options['fileFilteringOptions'] or {}
                    if ff_options.get('respectGitIgnore', False) and fs.should_git_ignore_file(sub_folder_path):
                        is_ignored = True
                    if ff_options.get('respectGeminiIgnore', False) and fs.should_gemini_ignore_file(sub_folder_path):
                        is_ignored = True

                if sub_folder_name in options['ignoredFolders'] or is_ignored:
                    ignored_sub_folder = FullFolderInfo(sub_folder_name, sub_folder_path)
                    ignored_sub_folder.is_ignored = True
                    sub_folders_in_current_dir.append(ignored_sub_folder)
                    current_item_count += 1
                    folder_info.total_children += 1
                    continue

                sub_folder_node = FullFolderInfo(sub_folder_name, sub_folder_path)
                sub_folders_in_current_dir.append(sub_folder_node)
                current_item_count += 1
                folder_info.total_children += 1

                # 添加到队列以便稍后处理其子项
                queue.append((sub_folder_node, sub_folder_path))

        folder_info.sub_folders = sub_folders_in_current_dir

    return root_node


def format_structure(node: FullFolderInfo,
                     current_indent: str,
                     is_last_child_of_parent: bool,
                     is_processing_root_node: bool,
                     builder: List[str]) -> None:
    connector = '└───' if is_last_child_of_parent else '├───'

    # 根节点本身不使用连接线打印，只打印其名称作为标题
    # 被忽略的根节点确实使用连接线打印
    if not is_processing_root_node or node.is_ignored:
        line = f"{current_indent}{connector}{node.name}{os.sep}"
        if node.is_ignored:
            line += TRUNCATION_INDICATOR
        builder.append(line)

    # 确定当前节点子节点的缩进
    indent_for_children = ''
    if is_processing_root_node:
        indent_for_children = ''
    else:
        indent_for_children = current_indent + ('    ' if is_last_child_of_parent else '│   ')

    # 渲染当前节点的文件
    file_count = len(node.files)
    for i in range(file_count):
        is_last_file = i == file_count - 1 and len(node.sub_folders) == 0 and not node.has_more_subfolders
        file_connector = '└───' if is_last_file else '├───'
        builder.append(f"{indent_for_children}{file_connector}{node.files[i]}")

    if node.has_more_files:
        is_last_indicator = len(node.sub_folders) == 0 and not node.has_more_subfolders
        file_connector = '└───' if is_last_indicator else '├───'
        builder.append(f"{indent_for_children}{file_connector}{TRUNCATION_INDICATOR}")

    # 渲染当前节点的子文件夹
    sub_folder_count = len(node.sub_folders)
    for i in range(sub_folder_count):
        is_last_subfolder = i == sub_folder_count - 1 and not node.has_more_subfolders
        format_structure(
            node.sub_folders[i],
            indent_for_children,
            is_last_subfolder,
            False,
            builder
        )

    if node.has_more_subfolders:
        builder.append(f"{indent_for_children}└───{TRUNCATION_INDICATOR}")


def is_truncated(node: FullFolderInfo) -> bool:
    if node.has_more_files or node.has_more_subfolders or node.is_ignored:
        return True
    for sub in node.sub_folders:
        if is_truncated(sub):
            return True
    return False

# 主要导出函数
async def get_folder_structure(directory: str, options: Optional[FolderStructureOptions] = None) -> str:
    resolved_path = os.path.abspath(directory)

    # 合并选项
    merged_options = {
        'maxItems': options.max_items if options and options.max_items is not None else MAX_ITEMS,
        'ignoredFolders': options.ignored_folders if options and options.ignored_folders is not None else DEFAULT_IGNORED_FOLDERS,
        'fileIncludePattern': options.file_include_pattern if options else None,
        'fileService': options.file_service if options else None,
        'fileFilteringOptions': options.file_filtering_options if options and options.file_filtering_options is not None else {'respectGitIgnore': True, 'respectGeminiIgnore': True}
    }

    try:
        # 1. 使用 BFS 读取结构，遵守 maxItems 限制
        structure_root = await read_full_structure(resolved_path, merged_options)

        if not structure_root:
            return f"Error: Could not read directory \"{resolved_path}\". Check path and permissions."

        # 2. 将结构格式化为字符串
        structure_lines = []
        # 为初始调用传递 is_processing_root_node 为 True
        format_structure(structure_root, '', True, True, structure_lines)

        # 3. 构建最终输出字符串
        summary = f"Showing up to {merged_options['maxItems']} items (files + folders)."

        if is_truncated(structure_root):
            summary += f" Folders or files indicated with {TRUNCATION_INDICATOR} contain more items not shown, were ignored, or the display limit ({merged_options['maxItems']} items) was reached."

        return f"{summary}\n\n{resolved_path}{os.sep}\n{chr(10).join(structure_lines)}"
    except Exception as e:
        print(f"Error getting folder structure for {resolved_path}: {str(e)}")
        return f"Error processing directory \"{resolved_path}\": {str(e)}"