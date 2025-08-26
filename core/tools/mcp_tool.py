import re
import json
from typing import Dict, Any, Optional, Set, Union, List, Protocol
from ..tools.tools import   BaseTool,ToolResult,ToolCallConfirmationDetails,ToolConfirmationOutcome,ToolMcpConfirmationDetails,Icon
from google.genai.types import Type,Part,FunctionCall, FunctionDeclaration

# 类型别名定义
tool_params = Dict[str, Any]


class CallableTool(Protocol):
    """
    可被Gemini调用的工具接口
    """
    
    async def tool(self) -> Tool:
        """
        返回可被Gemini调用的工具
        """
        ...
    
    async def call_tool(self, function_calls: List[FunctionCall]) -> List[Part]:
        """
        使用给定的函数调用参数执行可调用工具，并返回工具执行的响应部分
        
        参数:
            function_calls: 要执行的函数调用列表
        
        返回:
            工具执行后的响应部分列表
        """


class DiscoveredMCPTool(BaseTool):
    """发现的 MCP 工具类，用于执行来自 MCP 服务器的工具"""
    allowlist: Set[str] = set()
    
    def __init__(self, 
                 mcp_tool: CallableTool, 
                 server_name: str, 
                 server_tool_name: str, 
                 description: str, 
                 parameter_schema_json: Any, 
                 timeout: Optional[int] = None, 
                 trust: Optional[bool] = None, 
                 name_override: Optional[str] = None):
        """初始化 MCP 工具"""
        # 为 MCP 工具创建一个虚拟的参数模式
        dummy_schema = {'type': Type.OBJECT}
        
        # 使用有效的名称或覆盖名称
        tool_name = name_override if name_override else generate_valid_name(server_tool_name)
        
        super().__init__(
            tool_name,
            f"{server_tool_name} ({server_name} MCP Server)",
            description,
            Icon.Hammer,
            dummy_schema,  # 这是一个虚拟的模式，不会用于构建 FunctionDeclaration
            True,  # is_output_markdown
            False  # can_update_output
        )
        
        self.mcp_tool = mcp_tool
        self.server_name = server_name
        self.server_tool_name = server_tool_name
        self.parameter_schema_json = parameter_schema_json
        self.timeout = timeout
        self.trust = trust
    
    def as_fully_qualified_tool(self) -> 'DiscoveredMCPTool':
        """返回一个使用完全限定名称的工具实例"""
        return DiscoveredMCPTool(
            self.mcp_tool,
            self.server_name,
            self.server_tool_name,
            self.description,
            self.parameter_schema_json,
            self.timeout,
            self.trust,
            f"{self.server_name}__{self.server_tool_name}"
        )
    
    @property
    def schema(self) -> FunctionDeclaration:
        """重写基础模式以在构建 FunctionDeclaration 时使用 parametersJsonSchema"""
        return {
            'name': self.name,
            'description': self.description,
            'parametersJsonSchema': self.parameter_schema_json
        }
    
    async def should_confirm_execute(
        self, 
        params: tool_params, 
        abort_signal
    ) -> Union[ToolCallConfirmationDetails, bool]:
        """判断是否需要确认执行"""
        server_allow_list_key = self.server_name
        tool_allow_list_key = f"{self.server_name}.{self.server_tool_name}"
        
        if self.trust:
            return False  # 服务器受信任，不需要确认
        
        if (server_allow_list_key in DiscoveredMCPTool.allowlist or 
            tool_allow_list_key in DiscoveredMCPTool.allowlist):
            return False  # 服务器和/或工具已经在允许列表中
        
        async def on_confirm(outcome: str) -> None:
            if outcome == ToolConfirmationOutcome.ProceedAlwaysServer:
                DiscoveredMCPTool.allowlist.add(server_allow_list_key)
            elif outcome == ToolConfirmationOutcome.ProceedAlwaysTool:
                DiscoveredMCPTool.allowlist.add(tool_allow_list_key)
        
        confirmation_details: ToolMcpConfirmationDetails = {
            'type': 'mcp',
            'title': 'Confirm MCP Tool Execution',
            'serverName': self.server_name,
            'toolName': self.server_tool_name,  # 在确认中显示原始工具名称
            'toolDisplayName': self.name,  # 显示暴露给模型和用户的全局注册表名称
            'onConfirm': on_confirm
        }
        return confirmation_details
    
    async def execute(self, params: tool_params) -> ToolResult:
        """执行 MCP 工具"""
        function_calls = [
            {
                'name': self.server_tool_name,
                'args': params
            }
        ]
        
        response_parts = await self.mcp_tool.call_tool(function_calls)
        
        return {
            'llm_content': response_parts,
            'return_display': get_stringified_result_for_display(response_parts)
        }


def get_stringified_result_for_display(result: List[Dict[str, Any]]) -> str:
    """处理 `Part` 对象数组，主要来自工具的执行结果，
    生成用户友好的字符串表示，通常用于在 CLI 中显示。"""
    if not result or len(result) == 0:
        return '```json\n[]\n```'
    
    def process_function_response(part: Dict[str, Any]) -> Any:
        """处理函数响应部分"""
        if 'functionResponse' in part:
            function_response = part['functionResponse']
            response_content = function_response.get('response', {}).get('content')
            
            if response_content and isinstance(response_content, list):
                # 检查 responseContent 中的所有部分是否都是简单的 TextParts
                all_text_parts = all('text' in p for p in response_content)
                if all_text_parts:
                    return ''.join(p['text'] for p in response_content)
                # 如果不是所有简单文本部分，则返回这些内容部分的数组用于 JSON 字符串化
                return response_content
            
            # 如果没有内容，或者不是数组，或者不是 functionResponse，则对整个 functionResponse 部分进行字符串化以供检查
            return function_response
        
        return part  # 用于意外结构或非 FunctionResponsePart 的后备方案
    
    if len(result) == 1:
        processed_results = process_function_response(result[0])
    else:
        processed_results = [process_function_response(part) for part in result]
        
    if isinstance(processed_results, str):
        return processed_results
    
    return '```json\n' + json.dumps(processed_results, indent=2, ensure_ascii=False) + '\n```'

def generate_valid_name(name: str) -> str:
    """生成有效的工具名称
    将无效字符（基于 Gemini API 的 400 错误消息）替换为下划线。
    如果长度超过 63 个字符，用 '___' 替换中间部分。"""
    # 替换无效字符（基于 Gemini API 的 400 错误消息）为下划线
    valid_toolname = re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
    
    # 如果超过 63 个字符，用 '___' 替换中间部分
    # (Gemini API 说最大长度为 64，但实际限制似乎是 63)
    if len(valid_toolname) > 63:
        valid_toolname = valid_toolname[:28] + '___' + valid_toolname[-32:]
        
    return valid_toolname