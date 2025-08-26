import os
import difflib
import json
from typing import Dict, Any, List, Set, Union
from ..tools.tools import BaseTool, ToolResult,ToolEditConfirmationDetails, ToolConfirmationOutcome, Icon
from google.genai.types import FunctionDeclaration,Type
from ..utils.path import tildeify_path
from .diff_options import DEFAULT_DIFF_OPTIONS
from .modifiable_tool import ModifiableTool, ModifyContext

# 常量定义
gemini_config_dir = '.qwen'
default_context_filename = 'QWEN.md'
memory_section_header = '## Qwen Added Memories'

# 当前配置的文件名，默认为默认文件名
current_gemini_md_filename: Union[str, List[str]] = default_context_filename

def set_gemini_md_filename(new_filename: Union[str, List[str]]) -> None:
    if isinstance(new_filename, list):
        if new_filename:
            current_gemini_md_filename = [name.strip() for name in new_filename]
    elif new_filename and new_filename.strip():
        current_gemini_md_filename = new_filename.strip()

def get_current_gemini_md_filename() -> str:
    if isinstance(current_gemini_md_filename, list):
        return current_gemini_md_filename[0]
    return current_gemini_md_filename

def get_all_gemini_md_filenames() -> List[str]:
    if isinstance(current_gemini_md_filename, list):
        return current_gemini_md_filename
    return [current_gemini_md_filename]

# 工具模式数据
memory_tool_schema_data: FunctionDeclaration = {
    'name': 'save_memory',
    'description': (
        'Saves a specific piece of information or fact to your long-term memory. ' 
        'Use this when the user explicitly asks you to remember something, or when ' 
        'they state a clear, concise fact that seems important to retain for future interactions.'
    ),
    'parameters': {
        'type': Type.OBJECT,
        'properties': {
            'fact': {
                'type': Type.STRING,
                'description': (
                    'The specific fact or piece of information to remember. ' 
                    'Should be a clear, self-contained statement.'
                ),
            },
        },
        'required': ['fact'],
    },
}

memory_tool_description = """
Saves a specific piece of information or fact to your long-term memory.

Use this tool:

- When the user explicitly asks you to remember something (e.g., "Remember that I like pineapple on pizza", "Please save this: my cat's name is Whiskers").
- When the user states a clear, concise fact about themselves, their preferences, or their environment that seems important for you to retain for future interactions to provide a more personalized and effective assistance.

Do NOT use this tool:

- To remember conversational context that is only relevant for the current session.
- To save long, complex, or rambling pieces of text. The fact should be relatively short and to the point.
- If you are unsure whether the information is a fact worth remembering long-term. If in doubt, you can ask the user, "Should I remember that for you?"

## Parameters

- `fact` (string, required): The specific fact or piece of information to remember. This should be a clear, self-contained statement. For example, if the user says "My favorite color is blue", the fact would be "My favorite color is blue".
"""

def get_global_memory_file_path() -> str:
    """获取全局记忆文件的路径"""
    home_dir = os.path.expanduser('~')
    return os.path.join(home_dir, gemini_config_dir, get_current_gemini_md_filename())

def ensure_newline_separation(current_content: str) -> str:
    """确保在追加内容前有适当的换行符分隔"""
    if not current_content:
        return ''
    if current_content.endswith('\n\n') or current_content.endswith('\r\n\r\n'):
        return ''
    if current_content.endswith('\n') or current_content.endswith('\r\n'):
        return '\n'
    return '\n\n'

# 定义用于参数类型注解的类型别名
class SaveMemoryParams(TypedDict, total=False):
    fact: str
    modified_by_user: bool
    modified_content: str


class MemoryTool(BaseTool, ModifiableTool):
    """记忆工具类，用于保存信息到长期记忆"""
    allowlist: Set[str] = set()
    Name: str = memory_tool_schema_data['name']
    
    def __init__(self):
        super().__init__(
            MemoryTool.Name,
            'Save Memory',
            memory_tool_description,
            Icon.LightBulb,
            memory_tool_schema_data['parameters']
        )
    
    def get_description(self, params: SaveMemoryParams) -> str:
        """获取工具描述"""
        memory_file_path = get_global_memory_file_path()
        return f"in {tildeify_path(memory_file_path)}"
    
    async def read_memory_file_content(self) -> str:
        """读取记忆文件的当前内容"""
        try:
            file_path = get_global_memory_file_path()
            if not os.path.exists(file_path):
                return ''
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            # 仅忽略文件不存在的错误
            if isinstance(e, FileNotFoundError):
                return ''
            raise
    
    def compute_new_content(self, current_content: str, fact: str) -> str:
        """计算添加记忆条目后的新内容"""
        processed_text = fact.strip()
        # 移除可能被误解为markdown列表项的前导连字符和空格
        while processed_text.startswith('-'):
            processed_text = processed_text[1:].lstrip()
        new_memory_item = f'- {processed_text}'
        
        header_index = current_content.find(memory_section_header)
        
        if header_index == -1:
            # 未找到标题，追加标题和条目
            separator = ensure_newline_separation(current_content)
            return f"{current_content}{separator}{memory_section_header}\n{new_memory_item}\n"
        else:
            # 找到标题，确定插入新记忆条目的位置
            start_of_section_content = header_index + len(memory_section_header)
            end_of_section_index = current_content.find('\n## ', start_of_section_content)
            if end_of_section_index == -1:
                end_of_section_index = len(current_content)  # 文件末尾
            
            before_section_marker = current_content[:start_of_section_content].rstrip()
            section_content = current_content[start_of_section_content:end_of_section_index].rstrip()
            after_section_marker = current_content[end_of_section_index:]
            
            section_content += f"\n{new_memory_item}"
            return f"{before_section_marker}\n{section_content.lstrip()}\n{after_section_marker}".rstrip() + '\n'
    
    async def should_confirm_execute(
        self, 
        params: SaveMemoryParams, 
        abort_signal
    ) -> Union[ToolEditConfirmationDetails, bool]:
        """判断是否需要确认执行"""
        memory_file_path = get_global_memory_file_path()
        allowlist_key = memory_file_path
        
        if allowlist_key in MemoryTool.allowlist:
            return False
        
        # 读取记忆文件的当前内容
        current_content = await self.read_memory_file_content()
        
        # 计算将写入记忆文件的新内容
        new_content = self.compute_new_content(current_content, params['fact'])
        
        file_name = os.path.basename(memory_file_path)
        
        # 创建差异补丁
        diff_lines = difflib.unified_diff(
            current_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f'Current',
            tofile=f'Proposed',
            lineterm=DEFAULT_DIFF_OPTIONS
        )
        file_diff = ''.join(diff_lines)
        
        async def on_confirm(outcome: str) -> None:
            if outcome == ToolConfirmationOutcome.ProceedAlways:
                MemoryTool.allowlist.add(allowlist_key)
        
        confirmation_details: ToolEditConfirmationDetails = {
            'type': 'edit',
            'title': f"Confirm Memory Save: {tildeify_path(memory_file_path)}",
            'fileName': memory_file_path,
            'fileDiff': file_diff,
            'originalContent': current_content,
            'newContent': new_content,
            'onConfirm': on_confirm
        }
        return confirmation_details
    
    @staticmethod
    async def perform_add_memory_entry(
        text: str, 
        memory_file_path: str,
        fs_adapter: Dict[str, Any]
    ) -> None:
        """执行添加记忆条目的操作"""
        processed_text = text.strip()
        # 移除可能被误解为markdown列表项的前导连字符和空格
        while processed_text.startswith('-'):
            processed_text = processed_text[1:].lstrip()
        new_memory_item = f'- {processed_text}'
        
        try:
            # 创建目录
            await fs_adapter['mkdir'](os.path.dirname(memory_file_path), {'recursive': True})
            
            content = ''
            try:
                content = await fs_adapter['readFile'](memory_file_path, 'utf-8')
            except Exception:
                # 文件不存在，将创建带标题和条目的文件
                pass
            
            header_index = content.find(memory_section_header)
            
            if header_index == -1:
                # 未找到标题，追加标题和条目
                separator = ensure_newline_separation(content)
                content += f"{separator}{memory_section_header}\n{new_memory_item}\n"
            else:
                # 找到标题，确定插入新记忆条目的位置
                start_of_section_content = header_index + len(memory_section_header)
                end_of_section_index = content.find('\n## ', start_of_section_content)
                if end_of_section_index == -1:
                    end_of_section_index = len(content)  # 文件末尾
                
                before_section_marker = content[:start_of_section_content].rstrip()
                section_content = content[start_of_section_content:end_of_section_index].rstrip()
                after_section_marker = content[end_of_section_index:]
                
                section_content += f"\n{new_memory_item}"
                content = f"{before_section_marker}\n{section_content.lstrip()}\n{after_section_marker}".rstrip() + '\n'
            
            await fs_adapter['writeFile'](memory_file_path, content, 'utf-8')
        except Exception as error:
            print(f"[MemoryTool] Error adding memory entry to {memory_file_path}: {error}")
            raise Exception(f"[MemoryTool] Failed to add memory entry: {str(error)}")
    
    async def execute(
        self, 
        params: SaveMemoryParams, 
        signal
    ) -> ToolResult:
        """执行保存记忆的操作"""
        fact = params.get('fact')
        modified_by_user = params.get('modified_by_user', False)
        modified_content = params.get('modified_content')
        
        if not fact or not isinstance(fact, str) or fact.strip() == '':
            error_message = 'Parameter "fact" must be a non-empty string.'
            return {
                'llm_content': json.dumps({'success': False, 'error': error_message}),
                'return_display': f'Error: {error_message}'
            }
        
        try:
            if modified_by_user and modified_content is not None:
                # 用户在外部编辑器中修改了内容，直接写入
                file_path = get_global_memory_file_path()
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                success_message = "Okay, I've updated the memory file with your modifications."
                return {
                    'llm_content': json.dumps({'success': True, 'message': success_message}),
                    'return_display': success_message
                }
            else:
                # 使用正常的记忆条目逻辑
                # 创建一个模拟的fs_adapter，因为Python的文件操作是同步的
                class FsAdapter:
                    @staticmethod
                    async def read_file(path, encoding):
                        with open(path, 'r', encoding=encoding) as f:
                            return f.read()
                    
                    @staticmethod
                    async def write_file(path, data, encoding):
                        with open(path, 'w', encoding=encoding) as f:
                            f.write(data)
                    
                    @staticmethod
                    async def mkdir(path, options):
                        os.makedirs(path, exist_ok=options.get('recursive', False))
                
                fs_adapter = {
                    'readFile': FsAdapter.read_file,
                    'writeFile': FsAdapter.write_file,
                    'mkdir': FsAdapter.mkdir
                }
                
                await MemoryTool.perform_add_memory_entry(
                    fact,
                    get_global_memory_file_path(),
                    fs_adapter
                )
                success_message = f"Okay, I've remembered that: \"{fact}\""
                return {
                    'llm_content': json.dumps({'success': True, 'message': success_message}),
                    'return_display': success_message
                }
        except Exception as error:
            error_message = str(error)
            print(f"[MemoryTool] Error executing save_memory for fact \"{fact}\": {error_message}")
            return {
                'llm_content': json.dumps({'success': False, 'error': f'Failed to save memory. Detail: {error_message}'}),
                'return_display': f'Error saving memory: {error_message}'
            }
    
    def get_modify_context(self, abort_signal) -> ModifyContext:
        """获取修改上下文"""
        class MemoryModifyContext(ModifyContext):
            def __init__(self, memory_tool):
                self.memory_tool = memory_tool
            
            def get_file_path(self, params: SaveMemoryParams) -> str:
                return get_global_memory_file_path()
            
            async def get_current_content(self, params: SaveMemoryParams) -> str:
                return await self.memory_tool.read_memory_file_content()
            
            async def get_proposed_content(self, params: SaveMemoryParams) -> str:
                current_content = await self.memory_tool.read_memory_file_content()
                return self.memory_tool.compute_new_content(current_content, params['fact'])
            
            def create_updated_params(self, old_content: str, modified_proposed_content: str, original_params: SaveMemoryParams) -> SaveMemoryParams:
                updated_params = original_params.copy()
                updated_params['modified_by_user'] = True
                updated_params['modified_content'] = modified_proposed_content
                return updated_params
        
        return MemoryModifyContext(self)