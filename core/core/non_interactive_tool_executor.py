from datetime import datetime
from typing import Optional, Any

from ..index import ToolCallRequestInfo, ToolCallResponseInfo, ToolErrorType, ToolRegistry, ToolResult
from turn import ToolCallRequestInfo, ToolCallResponseInfo
from ..tools.tool_error import ToolErrorType
from ..tools.tool_registry import ToolRegistry
from ..tools.tools import ToolResult
from ..telemetry.loggers import log_tool_call
from ..config.config import Config
from .core_tool_scheduler import convert_to_function_response


async def execute_tool_call(
    config: Config,
    tool_call_request: ToolCallRequestInfo,
    tool_registry: ToolRegistry,
    abort_signal: Optional[Any] = None
) -> ToolCallResponseInfo:
    """
    Executes a single tool call non-interactively.
    It does not handle confirmations, multiple calls, or live updates.
    """
    tool = tool_registry.get_tool(tool_call_request.name)

    start_time = datetime.now().timestamp() * 1000  # Convert to milliseconds
    if not tool:
        error = Exception(f"Tool '{tool_call_request.name}' not found in registry.")
        duration_ms = datetime.now().timestamp() * 1000 - start_time
        log_tool_call(config, {
            'event.name': 'tool_call',
            'event.timestamp': datetime.now().isoformat(),
            'function_name': tool_call_request.name,
            'function_args': tool_call_request.args,
            'duration_ms': duration_ms,
            'success': False,
            'error': str(error),
            'prompt_id': tool_call_request.prompt_id,
        })
        # Ensure the response structure matches what the API expects for an error
        return {
            'callId': tool_call_request.callId,
            'responseParts': [
                {
                    'functionResponse': {
                        'id': tool_call_request.callId,
                        'name': tool_call_request.name,
                        'response': {'error': str(error)}
                    }
                }
            ],
            'resultDisplay': str(error),
            'error': error,
            'errorType': ToolErrorType.TOOL_NOT_REGISTERED
        }

    try:
        # Directly execute without confirmation or live output handling
        # In Python, we don't have AbortSignal by default, so we'll just pass it if provided
        # Assuming tool.execute is an async function
        tool_result: ToolResult = await tool.execute(
            tool_call_request.args,
            abort_signal,
            # No live output callback for non-interactive mode
        )

        tool_output = tool_result.llm_content
        tool_display = tool_result.return_display

        duration_ms = datetime.now().timestamp() * 1000 - start_time
        log_tool_call(config, {
            'event.name': 'tool_call',
            'event.timestamp': datetime.now().isoformat(),
            'function_name': tool_call_request.name,
            'function_args': tool_call_request.args,
            'duration_ms': duration_ms,
            'success': tool_result.error is None,
            'error': None if tool_result.error is None else tool_result.error.message,
            'error_type': None if tool_result.error is None else tool_result.error.type,
            'prompt_id': tool_call_request.prompt_id,
        })

        response = convert_to_function_response(
            tool_call_request.name,
            tool_call_request.callId,
            tool_output,
        )

        return {
            'callId': tool_call_request.callId,
            'responseParts': response,
            'resultDisplay': tool_display,
            'error': None if tool_result.error is None else Exception(tool_result.error.message),
            'errorType': None if tool_result.error is None else tool_result.error.type
        }
    except Exception as e:
        error = e
        duration_ms = datetime.now().timestamp() * 1000 - start_time
        log_tool_call(config, {
            'event.name': 'tool_call',
            'event.timestamp': datetime.now().isoformat(),
            'function_name': tool_call_request.name,
            'function_args': tool_call_request.args,
            'duration_ms': duration_ms,
            'success': False,
            'error': str(error),
            'error_type': ToolErrorType.UNHANDLED_EXCEPTION,
            'prompt_id': tool_call_request.prompt_id,
        })
        return {
            'callId': tool_call_request.callId,
            'responseParts': [
                {
                    'functionResponse': {
                        'id': tool_call_request.callId,
                        'name': tool_call_request.name,
                        'response': {'error': str(error)}
                    }
                }
            ],
            'resultDisplay': str(error),
            'error': error,
            'errorType': ToolErrorType.UNHANDLED_EXCEPTION
        }