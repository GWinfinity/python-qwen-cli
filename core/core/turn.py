from enum import Enum
from typing import (Dict, List, Any, Union, Optional, Generator, AsyncGenerator,
                    Protocol, Literal, TypedDict)
import re
import time
import random
from google.genai.types import PartUnion, GenerateContentResponse, FunctionCall, FunctionDeclaration, FinishReason, PartUnion
from ..tools.tools import ToolCallConfirmationDetails, ToolResult, ToolResultDisplay
from ..tools.tool_error import ToolErrorType
from ..utils.generate_content_response_utilities import get_response_text
from ..utils.error_reporting import report_error
from ..utils.errors import get_error_message, UnauthorizedError, to_friendly_error
from .gemini_chat import GeminiChat

type PartListUnion = List[PartUnion]

# 定义服务器工具结构
class ServerTool(Protocol):
    name: str
    schema: FunctionDeclaration  # 在实际实现中应替换为具体的类型
    
    async def execute(self, params: Dict[str, Any], signal: Optional[Any] = None) -> ToolResult:
        ...
        
    async def should_confirm_execute(self, params: Dict[str, Any], 
                                    abort_signal: Any) -> Union[ToolCallConfirmationDetails, bool]:
        ...


# 定义 Gemini 事件类型枚举
class GeminiEventType(Enum):
    CONTENT = 'content'
    TOOL_CALL_REQUEST = 'tool_call_request'
    TOOL_CALL_RESPONSE = 'tool_call_response'
    TOOL_CALL_CONFIRMATION = 'tool_call_confirmation'
    USER_CANCELLED = 'user_cancelled'
    ERROR = 'error'
    CHAT_COMPRESSED = 'chat_compressed'
    THOUGHT = 'thought'
    MAX_SESSION_TURNS = 'max_session_turns'
    SESSION_TOKEN_LIMIT_EXCEEDED = 'session_token_limit_exceeded'
    FINISHED = 'finished'
    LOOP_DETECTED = 'loop_detected'


# 定义结构化错误类型
class StructuredError(TypedDict):
    message: str
    status: Optional[int]


# 定义错误事件值类型
class GeminiErrorEventValue(TypedDict):
    error: StructuredError


# 定义会话令牌超出限制值类型
class SessionTokenLimitExceededValue(TypedDict):
    current_tokens: int
    limit: int
    message: str


# 定义工具调用请求信息类型
class ToolCallRequestInfo(TypedDict):
    call_id: str
    responseParts: PartListUnion
    args: Dict[str, Any]
    is_client_initiated: bool
    prompt_id: str


# 定义工具调用响应信息类型
class ToolCallResponseInfo(TypedDict):
    call_id: str
    response_parts: PartListUnion  # 在实际实现中应替换为具体的类型
    result_display: Optional[ToolResultDisplay]
    error: Optional[Exception]
    error_type: Optional[ToolErrorType]


# 定义服务器工具调用确认详情类型
class ServerToolCallConfirmationDetails(TypedDict):
    request: ToolCallRequestInfo
    details: ToolCallConfirmationDetails


# 定义思考摘要类型
class ThoughtSummary(TypedDict):
    subject: str
    description: str


# 定义聊天压缩信息类型
class ChatCompressionInfo(TypedDict):
    original_token_count: int
    new_token_count: int


# 定义服务器 Gemini 事件类型的联合类型
ServerGeminiStreamEvent = Union[
    Dict[Literal['type'], Literal[GeminiEventType.CONTENT]] & 
    Dict[Literal['value'], str],
    Dict[Literal['type'], Literal[GeminiEventType.THOUGHT]] & 
    Dict[Literal['value'], ThoughtSummary],
    Dict[Literal['type'], Literal[GeminiEventType.TOOL_CALL_REQUEST]] & 
    Dict[Literal['value'], ToolCallRequestInfo],
    Dict[Literal['type'], Literal[GeminiEventType.TOOL_CALL_RESPONSE]] & 
    Dict[Literal['value'], ToolCallResponseInfo],
    Dict[Literal['type'], Literal[GeminiEventType.TOOL_CALL_CONFIRMATION]] & 
    Dict[Literal['value'], ServerToolCallConfirmationDetails],
    Dict[Literal['type'], Literal[GeminiEventType.USER_CANCELLED]],
    Dict[Literal['type'], Literal[GeminiEventType.ERROR]] & 
    Dict[Literal['value'], GeminiErrorEventValue],
    Dict[Literal['type'], Literal[GeminiEventType.CHAT_COMPRESSED]] & 
    Dict[Literal['value'], Optional[ChatCompressionInfo]],
    Dict[Literal['type'], Literal[GeminiEventType.MAX_SESSION_TURNS]],
    Dict[Literal['type'], Literal[GeminiEventType.SESSION_TOKEN_LIMIT_EXCEEDED]] & 
    Dict[Literal['value'], SessionTokenLimitExceededValue],
    Dict[Literal['type'], Literal[GeminiEventType.FINISHED]] & 
    Dict[Literal['value'], str],  # 在实际实现中应替换为具体的 FinishReason 类型
    Dict[Literal['type'], Literal[GeminiEventType.LOOP_DETECTED]]
]


# Turn 类管理服务器上下文中的代理循环
class Turn:
    def __init__(self, chat: GeminiChat, prompt_id: str):
        self.chat = chat
        self.prompt_id = prompt_id
        self.pending_tool_calls: List[ToolCallRequestInfo] = []
        self.debug_responses: List[GenerateContentResponse] = []  # 在实际实现中应替换为具体的 GenerateContentResponse 类型
        self.finish_reason: Optional[FinishReason] = None  # 在实际实现中应替换为具体的 FinishReason 类型
    
    # run 方法产生适合服务器逻辑的更简单事件
    async def run(self, req: PartListUnion, signal: Any) -> AsyncGenerator[ServerGeminiStreamEvent, None]:
        try:
            response_stream = await self.chat.send_message_stream(
                {
                    'message': req,
                    'config': {
                        'abortSignal': signal,
                    },
                },
                self.prompt_id,
            )

            async for resp in response_stream:
                if signal and getattr(signal, 'aborted', False):
                    yield {'type': GeminiEventType.USER_CANCELLED}
                    # 如果在处理前中止，不将 resp 添加到 debugResponses
                    return
                
                self.debug_responses.append(resp)

                # 处理思考部分
                thought_part = None
                if hasattr(resp, 'candidates') and resp.candidates:
                    candidate = resp.candidates[0]
                    if hasattr(candidate, 'content') and candidate.content:
                        content = candidate.content
                        if hasattr(content, 'parts') and content.parts:
                            thought_part = content.parts[0]
                
                if thought_part and hasattr(thought_part, 'thought'):
                    # 思考始终有一个用双星号括起来的粗体"主题"部分
                    # （例如，**主题**）。字符串的其余部分被视为描述。
                    raw_text = getattr(thought_part, 'text', '') or ''
                    subject_string_matches = re.search(r'\*\*(.*?)\*\*', raw_text, re.DOTALL)
                    subject = subject_string_matches.group(1).strip() if subject_string_matches else ''
                    description = re.sub(r'\*\*(.*?)\*\*', '', raw_text, flags=re.DOTALL).strip()
                    
                    thought: ThoughtSummary = {
                        'subject': subject,
                        'description': description,
                    }

                    yield {
                        'type': GeminiEventType.THOUGHT,
                        'value': thought,
                    }
                    continue

                # 处理文本内容
                text = get_response_text(resp)
                if text:
                    yield {'type': GeminiEventType.CONTENT, 'value': text}

                # 处理函数调用（请求工具执行）
                function_calls = getattr(resp, 'functionCalls', None) or []
                for fn_call in function_calls:
                    event = self._handle_pending_function_call(fn_call)
                    if event:
                        yield event

                # 检查响应是否因为各种原因被截断或停止
                finish_reason = None
                if hasattr(resp, 'candidates') and resp.candidates:
                    candidate = resp.candidates[0]
                    finish_reason = getattr(candidate, 'finishReason', None)

                if finish_reason:
                    self.finish_reason = finish_reason
                    yield {
                        'type': GeminiEventType.FINISHED,
                        'value': finish_reason,
                    }

        except Exception as e:
            error = to_friendly_error(e)
            if isinstance(error, UnauthorizedError):
                raise error
            if signal and getattr(signal, 'aborted', False):
                yield {'type': GeminiEventType.USER_CANCELLED}
                # 常规取消错误，优雅地失败
                return

            context_for_report = [*self.chat.get_history(curated=True), req]
            await report_error(
                error,
                'Error when talking to Gemini API',
                context_for_report,
                'Turn.run-sendMessageStream',
            )
            
            # 构建结构化错误
            status = None
            if isinstance(error, object) and hasattr(error, 'status'):
                error_status = getattr(error, 'status')
                if isinstance(error_status, int):
                    status = error_status
            
            structured_error: StructuredError = {
                'message': get_error_message(error),
                'status': status,
            }
            
            yield {
                'type': GeminiEventType.ERROR,
                'value': {'error': structured_error}
            }
            return

    def _handle_pending_function_call(self, fn_call: FunctionCall) -> Optional[ServerGeminiStreamEvent]:
        # 生成调用 ID
        fn_call_id = getattr(fn_call, 'id', None)
        if not fn_call_id:
            fn_call_id = f"{getattr(fn_call, 'name', 'undefined')}-{int(time.time())}-{random.random().hex()[2:]}"
        
        name = getattr(fn_call, 'name', 'undefined_tool_name')
        args = getattr(fn_call, 'args', {}) or {}

        tool_call_request: ToolCallRequestInfo = {
            'call_id': fn_call_id,
            'name': name,
            'args': args,
            'is_client_initiated': False,
            'prompt_id': self.prompt_id,
        }

        self.pending_tool_calls.append(tool_call_request)

        # 返回工具调用请求事件
        return {
            'type': GeminiEventType.TOOL_CALL_REQUEST,
            'value': tool_call_request
        }

    def get_debug_responses(self) -> List[Any]:
        return self.debug_responses