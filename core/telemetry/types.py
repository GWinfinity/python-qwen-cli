import enum
from datetime import datetime
from typing import Optional, Union
from google.genai.types import GenerateContentResponseUsageMetadata
from ..config.config import Config
from ..tool.tool import ToolConfirmationOutcome
from ..core.core_tool_scheduler import CompletedToolCall
from ..core.content_generator import AuthType


# 假设这些是已定义的导入类型
# 实际项目中可能需要根据情况调整导入

class CompletedToolCall:
    pass
class AuthType:
    USE_GEMINI = "use_gemini"
    USE_VERTEX_AI = "use_vertex_ai"


class ToolCallDecision(enum.Enum):
    ACCEPT = 'accept'
    REJECT = 'reject'
    MODIFY = 'modify'


def get_decision_from_outcome(outcome: str) -> ToolCallDecision:
    if outcome in [
        ToolConfirmationOutcome.ProceedOnce,
        ToolConfirmationOutcome.ProceedAlways,
        ToolConfirmationOutcome.ProceedAlwaysServer,
        ToolConfirmationOutcome.ProceedAlwaysTool
    ]:
        return ToolCallDecision.ACCEPT
    elif outcome == ToolConfirmationOutcome.ModifyWithEditor:
        return ToolCallDecision.MODIFY
    elif outcome == ToolConfirmationOutcome.Cancel:
        return ToolCallDecision.REJECT
    else:
        return ToolCallDecision.REJECT


class StartSessionEvent:
    def __init__(self, config: Config):
        generator_config = config.get_content_generator_config()
        mcp_servers = config.get_mcp_servers()

        use_gemini = False
        use_vertex = False
        if generator_config and hasattr(generator_config, 'auth_type'):
            use_gemini = generator_config.auth_type == AuthType.USE_GEMINI
            use_vertex = generator_config.auth_type == AuthType.USE_VERTEX_AI

        self.event_name = 'cli_config'
        self.event_timestamp = datetime.now().isoformat()
        self.model = config.get_model()
        self.embedding_model = config.get_embedding_model()
        self.sandbox_enabled = isinstance(config.get_sandbox(), str) or bool(config.get_sandbox())
        self.core_tools_enabled = ','.join(config.get_core_tools() or [])
        self.approval_mode = config.get_approval_mode()
        self.api_key_enabled = use_gemini or use_vertex
        self.vertex_ai_enabled = use_vertex
        self.debug_enabled = config.get_debug_mode()
        self.mcp_servers = ','.join(mcp_servers.keys()) if mcp_servers else ''
        self.telemetry_enabled = config.get_telemetry_enabled()
        self.telemetry_log_user_prompts_enabled = config.get_telemetry_log_prompts_enabled()
        self.file_filtering_respect_git_ignore = config.get_file_filtering_respect_git_ignore()


class EndSessionEvent:
    def __init__(self, config: Optional[Config] = None):
        self.event_name = 'end_session'
        self.event_timestamp = datetime.now().isoformat()
        self.session_id = config.get_session_id() if config else None


class UserPromptEvent:
    def __init__(self,
                 prompt_length: int,
                 prompt_id: str,
                 auth_type: Optional[str] = None,
                 prompt: Optional[str] = None):
        self.event_name = 'user_prompt'
        self.event_timestamp = datetime.now().isoformat()
        self.prompt_length = prompt_length
        self.prompt_id = prompt_id
        self.auth_type = auth_type
        self.prompt = prompt


class ToolCallEvent:
    def __init__(self, call: CompletedToolCall):
        self.event_name = 'tool_call'
        self.event_timestamp = datetime.now().isoformat()
        self.function_name = call.request.name
        self.function_args = call.request.args
        self.duration_ms = call.durationMs if hasattr(call, 'durationMs') else 0
        self.success = call.status == 'success'
        self.decision = get_decision_from_outcome(call.outcome) if hasattr(call, 'outcome') else None
        self.error = call.response.error.message if hasattr(call.response, 'error') and call.response.error else None
        self.error_type = call.response.errorType if hasattr(call.response, 'errorType') else None
        self.prompt_id = call.request.prompt_id


class ApiRequestEvent:
    def __init__(self,
                 model: string,
                 prompt_id: string,
                 request_text: Optional[str] = None):
        self.event_name = 'api_request'
        self.event_timestamp = datetime.now().isoformat()
        self.model = model
        self.prompt_id = prompt_id
        self.request_text = request_text


class ApiErrorEvent:
    def __init__(self,
                 model: string,
                 error: string,
                 duration_ms: number,
                 prompt_id: string,
                 auth_type: Optional[str] = None,
                 error_type: Optional[str] = None,
                 status_code: Optional[Union[number, string]] = None):
        self.event_name = 'api_error'
        self.event_timestamp = datetime.now().isoformat()
        self.model = model
        self.error = error
        self.error_type = error_type
        self.status_code = status_code
        self.duration_ms = duration_ms
        self.prompt_id = prompt_id
        self.auth_type = auth_type


class ApiResponseEvent:
    def __init__(self,
                 model: string,
                 duration_ms: number,
                 prompt_id: string,
                 auth_type: Optional[str] = None,
                 usage_data: Optional[GenerateContentResponseUsageMetadata] = None,
                 response_text: Optional[str] = None,
                 error: Optional[str] = None):
        self.event_name = 'api_response'
        self.event_timestamp = datetime.now().isoformat()
        self.model = model
        self.duration_ms = duration_ms
        self.status_code = 200
        self.input_token_count = usage_data.promptTokenCount if usage_data else 0
        self.output_token_count = usage_data.candidatesTokenCount if usage_data else 0
        self.cached_content_token_count = usage_data.cachedContentTokenCount if usage_data else 0
        self.thoughts_token_count = usage_data.thoughtsTokenCount if usage_data else 0
        self.tool_token_count = usage_data.toolUsePromptTokenCount if usage_data else 0
        self.total_token_count = usage_data.totalTokenCount if usage_data else 0
        self.response_text = response_text
        self.error = error
        self.prompt_id = prompt_id
        self.auth_type = auth_type


class FlashFallbackEvent:
    def __init__(self, auth_type: string):
        self.event_name = 'flash_fallback'
        self.event_timestamp = datetime.now().isoformat()
        self.auth_type = auth_type


class LoopType(enum.Enum):
    CONSECUTIVE_IDENTICAL_TOOL_CALLS = 'consecutive_identical_tool_calls'
    CHANTING_IDENTICAL_SENTENCES = 'chanting_identical_sentences'
    LLM_DETECTED_LOOP = 'llm_detected_loop'


class LoopDetectedEvent:
    def __init__(self, loop_type: LoopType, prompt_id: string):
        self.event_name = 'loop_detected'
        self.event_timestamp = datetime.now().isoformat()
        self.loop_type = loop_type
        self.prompt_id = prompt_id


class NextSpeakerCheckEvent:
    def __init__(self, prompt_id: string, finish_reason: string, result: string):
        self.event_name = 'next_speaker_check'
        self.event_timestamp = datetime.now().isoformat()
        self.prompt_id = prompt_id
        self.finish_reason = finish_reason
        self.result = result


class SlashCommandEvent:
    def __init__(self, command: string, subcommand: Optional[string] = None):
        self.event_name = 'slash_command'
        self.event_timestamp = datetime.now().isoformat()
        self.command = command
        self.subcommand = subcommand


class MalformedJsonResponseEvent:
    def __init__(self, model: string):
        self.event_name = 'malformed_json_response'
        self.event_timestamp = datetime.now().isoformat()
        self.model = model


# Python 中使用 Union 类型提示代替 TypeScript 的联合类型
TelemetryEvent = Union[
    StartSessionEvent,
    EndSessionEvent,
    UserPromptEvent,
    ToolCallEvent,
    ApiRequestEvent,
    ApiErrorEvent,
    ApiResponseEvent,
    FlashFallbackEvent,
    LoopDetectedEvent,
    NextSpeakerCheckEvent,
    SlashCommandEvent,
    MalformedJsonResponseEvent
]