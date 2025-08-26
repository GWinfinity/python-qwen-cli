import os
import tempfile
import difflib
import asyncio
from typing import Protocol, Dict, Any
from ..utils.editor import EditorType, open_diff
from ..utils.errors import is_node_error
from ..tool.tool import Tool


class ModifiableTool(Tool[toolParams], Protocol[toolParams]):
    def get_modify_context(self, abort_signal: Future) -> ModifyContext[toolParams]:
        """获取修改上下文
        
        Args:
            abort_signal: 用于取消操作的信号
        
        Returns:
            修改上下文对象
        """
        pass
# 定义 ModifiableTool 接口
def is_modifiable_tool(tool: Tool[ToolParams]) -> bool:
    """检查工具是否实现了 ModifiableTool 接口"""
    return hasattr(tool, 'get_modify_context')


# 定义 ModifyContext 接口
class ModifyContext(Protocol[ToolParams]):
    def get_file_path(self, params: ToolParams) -> str:
        """获取文件路径"""
        ...
        
    async def get_current_content(self, params: ToolParams) -> str:
        """获取当前内容"""
        ...
        
    async def get_proposed_content(self, params: ToolParams) -> str:
        """获取建议内容"""
        ...
        
    def create_updated_params(
        self,
        old_content: str,
        modified_proposed_content: str,
        original_params: ToolParams
    ) -> ToolParams:
        """创建更新后的参数"""
        ...

# 定义 ModifyResult 类型
typing.ModifyResult = Dict[str, Any]  # 简化表示，实际应根据需要定义更具体的类型

# 假设 DEFAULT_DIFF_OPTIONS 已在其他文件中定义
# 这里设置一个简单的默认值
DEFAULT_DIFF_OPTIONS = {
    'ignore_blank_lines': False,
    'ignore_case': False,
    'ignore_space_change': False
}

# 假设 open_diff 和 EditorType 已在其他文件中定义
# 这里定义一个模拟的 EditorType 枚举
class EditorType:
    VSCODE = 'vscode'
    INTELLIJ = 'intellij'
    # 其他编辑器类型...

# 创建临时文件用于修改
def create_temp_files_for_modify(
    current_content: str,
    proposed_content: str,
    file_path: str
) -> Dict[str, str]:
    """创建临时文件用于修改操作"""
    # 获取系统临时目录
    temp_dir = tempfile.gettempdir()
    diff_dir = os.path.join(temp_dir, 'qwen-code-tool-modify-diffs')
    
    # 确保差异目录存在
    os.makedirs(diff_dir, exist_ok=True)
    
    # 获取文件扩展名和基本名称
    ext = os.path.splitext(file_path)[1]
    file_name = os.path.splitext(os.path.basename(file_path))[0]
    timestamp = str(int(asyncio.get_event_loop().time() * 1000))  # 获取毫秒时间戳
    
    # 创建临时文件路径
    temp_old_path = os.path.join(
        diff_dir,
        f'qwen-code-modify-{file_name}-old-{timestamp}{ext}'
    )
    temp_new_path = os.path.join(
        diff_dir,
        f'qwen-code-modify-{file_name}-new-{timestamp}{ext}'
    )
    
    # 写入临时文件
    with open(temp_old_path, 'w', encoding='utf-8') as f:
        f.write(current_content)
    with open(temp_new_path, 'w', encoding='utf-8') as f:
        f.write(proposed_content)
    
    return {'old_path': temp_old_path, 'new_path': temp_new_path}


# 获取更新后的参数
def get_updated_params(
    tmp_old_path: str,
    temp_new_path: str,
    original_params: ToolParams,
    modify_context: ModifyContext[ToolParams]
) -> Dict[str, Any]:
    """获取更新后的参数和差异"""
    old_content = ''
    new_content = ''
    
    # 读取旧内容
    try:
        with open(tmp_old_path, 'r', encoding='utf-8') as f:
            old_content = f.read()
    except Exception as err:
        if not (is_node_error(err) and getattr(err, 'code') == 'ENOENT'):
            raise
        old_content = ''
    
    # 读取新内容
    try:
        with open(temp_new_path, 'r', encoding='utf-8') as f:
            new_content = f.read()
    except Exception as err:
        if not (is_node_error(err) and getattr(err, 'code') == 'ENOENT'):
            raise
        new_content = ''
    
    # 创建更新后的参数
    updated_params = modify_context.create_updated_params(
        old_content,
        new_content,
        original_params
    )
    
    # 创建差异补丁
    file_name = os.path.basename(modify_context.get_file_path(original_params))
    
    # 使用 difflib 创建统一格式的差异
    diff_lines = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f'Current\t{file_name}',
        tofile=f'Proposed\t{file_name}',
        # difflib 不直接支持与 diff.createPatch 相同的选项，这里是简化处理
    )
    
    updated_diff = ''.join(diff_lines)
    
    return {
        'updated_params': updated_params,
        'updated_diff': updated_diff
    }


# 删除临时文件
def delete_temp_files(old_path: str, new_path: str) -> None:
    """删除临时文件"""
    try:
        os.remove(old_path)
    except Exception as e:
        print(f"Error deleting temp diff file: {old_path}", e)
    
    try:
        os.remove(new_path)
    except Exception as e:
        print(f"Error deleting temp diff file: {new_path}", e)


# 使用编辑器修改内容
async def modify_with_editor(
    original_params: ToolParams,
    modify_context: ModifyContext[ToolParams],
    editor_type: EditorType,
    _abort_signal: asyncio.AbstractEventLoop  # Python 中没有直接对应的 AbortSignal
) -> Dict[str, Any]:
    """触发外部编辑器让用户修改建议内容，并返回更新后的工具参数和差异"""
    # 获取当前内容和建议内容
    current_content = await modify_context.get_current_content(original_params)
    proposed_content = await modify_context.get_proposed_content(original_params)
    
    # 创建临时文件
    temp_files = create_temp_files_for_modify(
        current_content,
        proposed_content,
        modify_context.get_file_path(original_params)
    )
    
    try:
        # 打开差异编辑器
        await open_diff(temp_files['old_path'], temp_files['new_path'], editor_type)
        
        # 获取更新后的参数和差异
        result = get_updated_params(
            temp_files['old_path'],
            temp_files['new_path'],
            original_params,
            modify_context
        )
        
        return result
    finally:
        # 确保删除临时文件
        delete_temp_files(temp_files['old_path'], temp_files['new_path'])