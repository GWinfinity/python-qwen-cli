from __future__ import annotations
import asyncio
import time
from typing import Dict, List, Union, Optional, Callable, Any, Tuple, TypeVar, Generic
from enum import Enum
from datetime import datetime

from core.core.core_tool_scheduler import ToolCall
from turn import ToolCallRequestInfo, ToolCallResponseInfo
from ..tools.tools import ToolConfirmationPayload,ToolCallConfirmationDetails,Tool, ToolResult,ToolResultDisplay
from ..tools.tool_registry import ToolRegistry
from ..tools.tool_error import ToolErrorType
from ..config.config import ApprovalMode,Config
from ..telemetry.loggers import log_tool_call
from ..telemetry.types import ToolCallEvent
from ..utils.generate_content_response_utilities import get_response_text_from_parts
from ..utils.editor import EditorType
from ..tools.modifiable_tool import is_modifiable_tool, ModifyContext, modify_with_editor
from google.genai.types import Part,PartUnion

# 第三方库
from diff import create_patch  # 假设使用类似的Python diff库


class ToolCallStatus(Enum):
    VALIDATING = 'validating'
    SCHEDULED = 'scheduled'
    ERROR = 'error'
    SUCCESS = 'success'
    EXECUTING = 'executing'
    CANCELLED = 'cancelled'
    AWAITING_APPROVAL = 'awaiting_approval'


class ValidatingToolCall:
    def __init__(self, request: ToolCallRequestInfo, tool: Tool):
        self.status = ToolCallStatus.VALIDATING
        self.request = request
        self.tool = tool
        self.start_time: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


class ScheduledToolCall:
    def __init__(self, request: ToolCallRequestInfo, tool: Tool):
        self.status = ToolCallStatus.SCHEDULED
        self.request = request
        self.tool = tool
        self.start_time: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


class ErroredToolCall:
    def __init__(self, request: ToolCallRequestInfo, response: ToolCallResponseInfo):
        self.status = ToolCallStatus.ERROR
        self.request = request
        self.response = response
        self.duration_ms: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


class SuccessfulToolCall:
    def __init__(self, request: ToolCallRequestInfo, tool: Tool, response: ToolCallResponseInfo):
        self.status = ToolCallStatus.SUCCESS
        self.request = request
        self.tool = tool
        self.response = response
        self.duration_ms: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


class ExecutingToolCall:
    def __init__(self, request: ToolCallRequestInfo, tool: Tool):
        self.status = ToolCallStatus.EXECUTING
        self.request = request
        self.tool = tool
        self.live_output: Optional[str] = None
        self.start_time: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


class CancelledToolCall:
    def __init__(self, request: ToolCallRequestInfo, tool: Tool, response: ToolCallResponseInfo):
        self.status = ToolCallStatus.CANCELLED
        self.request = request
        self.response = response
        self.tool = tool
        self.duration_ms: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


class WaitingToolCall:
    def __init__(self, request: ToolCallRequestInfo, tool: Tool, confirmation_details: ToolCallConfirmationDetails):
        self.status = ToolCallStatus.AWAITING_APPROVAL
        self.request = request
        self.tool = tool
        self.confirmation_details = confirmation_details
        self.start_time: Optional[float] = None
        self.outcome: Optional[ToolConfirmationOutcome] = None


ToolCall = Union[
    ValidatingToolCall, ScheduledToolCall, ErroredToolCall,
    SuccessfulToolCall, ExecutingToolCall, CancelledToolCall, WaitingToolCall
]

CompletedToolCall = Union[SuccessfulToolCall, CancelledToolCall, ErroredToolCall]

ConfirmHandler = Callable[[WaitingToolCall], asyncio.Future[ToolConfirmationOutcome]]
OutputUpdateHandler = Callable[[str, str], None]
AllToolCallsCompleteHandler = Callable[[List[CompletedToolCall]], None]
ToolCallsUpdateHandler = Callable[[List[ToolCall]], None]

Status = ToolCall['status']
def create_function_response_part(call_id: str, tool_name: str, output: str) -> Dict[str, Any]:
    """Formats tool output for a Gemini FunctionResponse."""
    return {
        'functionResponse': {
            'id': call_id,
            'name': tool_name,
            'response': {'output': output}
        }
    }


def convert_to_function_response(tool_name: str, call_id: str, llm_content: Any) -> Any:
    content_to_process = llm_content[0] if isinstance(llm_content, list) and len(llm_content) == 1 else llm_content

    if isinstance(content_to_process, str):
        return create_function_response_part(call_id, tool_name, content_to_process)

    if isinstance(content_to_process, list):
        function_response = create_function_response_part(call_id, tool_name, 'Tool execution succeeded.')
        return [function_response] + content_to_process

    # After this point, content_to_process is a single Part object.
    if 'functionResponse' in content_to_process:
        if 'content' in content_to_process['functionResponse'].get('response', {}):
            stringified_output = getResponseTextFromParts(
                content_to_process['functionResponse']['response']['content']
            ) or ''
            return create_function_response_part(call_id, tool_name, stringified_output)
        # It's a functionResponse that we should pass through as is.
        return content_to_process

    if 'inlineData' in content_to_process or 'fileData' in content_to_process:
        mime_type = (
            content_to_process.get('inlineData', {}).get('mimeType') or
            content_to_process.get('fileData', {}).get('mimeType') or
            'unknown'
        )
        function_response = create_function_response_part(
            call_id, tool_name, f'Binary content of type {mime_type} was processed.'
        )
        return [function_response, content_to_process]

    if 'text' in content_to_process:
        return create_function_response_part(call_id, tool_name, content_to_process['text'])

    # Default case for other kinds of parts.
    return create_function_response_part(call_id, tool_name, 'Tool execution succeeded.')


def create_error_response(
    request: ToolCallRequestInfo,
    error: Exception,
    error_type: Optional[ToolErrorType]
) -> ToolCallResponseInfo:
    return {
        'callId': request['callId'],
        'error': error,
        'responseParts': {
            'functionResponse': {
                'id': request['callId'],
                'name': request['name'],
                'response': {'error': str(error)}
            }
        },
        'resultDisplay': str(error),
        'errorType': error_type
    }


class CoreToolScheduler:
    def __init__(
        self,
        tool_registry: asyncio.Future[ToolRegistry],
        output_update_handler: Optional[OutputUpdateHandler] = None,
        on_all_tool_calls_complete: Optional[AllToolCallsCompleteHandler] = None,
        on_tool_calls_update: Optional[ToolCallsUpdateHandler] = None,
        get_preferred_editor: Callable[[], Optional[EditorType]] = lambda: None,
        config: Config = None):
        self.tool_registry = tool_registry
        self.tool_calls: List[ToolCall] = []
        self.output_update_handler = output_update_handler
        self.on_all_tool_calls_complete = on_all_tool_calls_complete
        self.on_tool_calls_update = on_tool_calls_update
        self.get_preferred_editor = get_preferred_editor
        self.config = config

    def set_status_internal(
        self,
        target_call_id: str,
        new_status: ToolCallStatus,
        auxiliary_data: Any = None
    ) -> None:
        updated_tool_calls = []
        for current_call in self.tool_calls:
            if (
                current_call.request['callId'] != target_call_id or
                current_call.status in [ToolCallStatus.SUCCESS, ToolCallStatus.ERROR, ToolCallStatus.CANCELLED]
            ):
                updated_tool_calls.append(current_call)
                continue

            # current_call is a non-terminal state here and should have start_time and tool.
            existing_start_time = getattr(current_call, 'start_time', None)
            tool_instance = getattr(current_call, 'tool', None)
            outcome = getattr(current_call, 'outcome', None)

            if new_status == ToolCallStatus.SUCCESS:
                duration_ms = existing_start_time and (time.time() * 1000 - existing_start_time * 1000) or None
                success_call = SuccessfulToolCall(
                    current_call.request,
                    tool_instance,
                    auxiliary_data
                )
                success_call.duration_ms = duration_ms
                success_call.outcome = outcome
                updated_tool_calls.append(success_call)

            elif new_status == ToolCallStatus.ERROR:
                duration_ms = existing_start_time and (time.time() * 1000 - existing_start_time * 1000) or None
                error_call = ErroredToolCall(
                    current_call.request,
                    auxiliary_data
                )
                error_call.duration_ms = duration_ms
                error_call.outcome = outcome
                updated_tool_calls.append(error_call)

            elif new_status == ToolCallStatus.AWAITING_APPROVAL:
                waiting_call = WaitingToolCall(
                    current_call.request,
                    tool_instance,
                    auxiliary_data
                )
                waiting_call.start_time = existing_start_time
                waiting_call.outcome = outcome
                updated_tool_calls.append(waiting_call)

            elif new_status == ToolCallStatus.SCHEDULED:
                scheduled_call = ScheduledToolCall(
                    current_call.request,
                    tool_instance
                )
                scheduled_call.start_time = existing_start_time
                scheduled_call.outcome = outcome
                updated_tool_calls.append(scheduled_call)

            elif new_status == ToolCallStatus.CANCELLED:
                duration_ms = existing_start_time and (time.time() * 1000 - existing_start_time * 1000) or None

                # Preserve diff for cancelled edit operations
                result_display: Optional[ToolResultDisplay] = None
                if current_call.status == ToolCallStatus.AWAITING_APPROVAL:
                    waiting_call = current_call  # type: ignore
                    if waiting_call.confirmation_details.get('type') == 'edit':
                        result_display = {
                            'fileDiff': waiting_call.confirmation_details.get('fileDiff'),
                            'fileName': waiting_call.confirmation_details.get('fileName'),
                            'originalContent': waiting_call.confirmation_details.get('originalContent'),
                            'newContent': waiting_call.confirmation_details.get('newContent')
                        }

                response = {
                    'callId': current_call.request['callId'],
                    'responseParts': {
                        'functionResponse': {
                            'id': current_call.request['callId'],
                            'name': current_call.request['name'],
                            'response': {
                                'error': f'[Operation Cancelled] Reason: {auxiliary_data}'
                            }
                        }
                    },
                    'resultDisplay': result_display,
                    'error': None,
                    'errorType': None
                }

                cancelled_call = CancelledToolCall(
                    current_call.request,
                    tool_instance,
                    response
                )
                cancelled_call.duration_ms = duration_ms
                cancelled_call.outcome = outcome
                updated_tool_calls.append(cancelled_call)

            elif new_status == ToolCallStatus.VALIDATING:
                validating_call = ValidatingToolCall(
                    current_call.request,
                    tool_instance
                )
                validating_call.start_time = existing_start_time
                validating_call.outcome = outcome
                updated_tool_calls.append(validating_call)

            elif new_status == ToolCallStatus.EXECUTING:
                executing_call = ExecutingToolCall(
                    current_call.request,
                    tool_instance
                )
                executing_call.start_time = existing_start_time
                executing_call.outcome = outcome
                updated_tool_calls.append(executing_call)

            else:
                # Handle unexpected status
                updated_tool_calls.append(current_call)

        self.tool_calls = updated_tool_calls
        self.notify_tool_calls_update()
        self.check_and_notify_completion()

    def set_args_internal(self, target_call_id: str, args: Dict[str, Any]) -> None:
        self.tool_calls = [
            {
                **call,
                'request': {**call['request'], 'args': args}
            } if call.request['callId'] == target_call_id else call
            for call in self.tool_calls
        ]

    def is_running(self) -> bool:
        return any(
            call.status == ToolCallStatus.EXECUTING or call.status == ToolCallStatus.AWAITING_APPROVAL
            for call in self.tool_calls
        )

    async def schedule(
        self,
        request: Union[ToolCallRequestInfo, List[ToolCallRequestInfo]],
        signal: asyncio.Event
    ) -> None:
        if self.is_running():
            raise Exception(
                'Cannot schedule new tool calls while other tool calls are actively running (executing or awaiting approval).'
            )

        requests_to_process = request if isinstance(request, list) else [request]
        tool_registry = await self.tool_registry

        new_tool_calls: List[ToolCall] = []
        for req_info in requests_to_process:
            tool_instance = tool_registry.getTool(req_info['name'])
            if not tool_instance:
                error_call = ErroredToolCall(
                    req_info,
                    create_error_response(
                        req_info,
                        Exception(f'Tool "{req_info['name']}" not found in registry.'),
                        ToolErrorType.TOOL_NOT_REGISTERED
                    )
                )
                error_call.duration_ms = 0
                new_tool_calls.append(error_call)
            else:
                validating_call = ValidatingToolCall(req_info, tool_instance)
                validating_call.start_time = time.time()
                new_tool_calls.append(validating_call)

        self.tool_calls.extend(new_tool_calls)
        self.notify_tool_calls_update()

        for tool_call in new_tool_calls:
            if tool_call.status != ToolCallStatus.VALIDATING:
                continue

            req_info = tool_call.request
            tool_instance = tool_call.tool
            try:
                if self.config.getApprovalMode() == ApprovalMode.YOLO:
                    self.set_status_internal(req_info['callId'], ToolCallStatus.SCHEDULED)
                else:
                    confirmation_details = await tool_instance.shouldConfirmExecute(
                        req_info['args'],
                        signal
                    )

                    if confirmation_details:
                        original_on_confirm = confirmation_details['onConfirm']

                        async def wrapped_on_confirm(
                            outcome: ToolConfirmationOutcome,
                            payload: Optional[ToolConfirmationPayload] = None
                        ) -> None:
                            await original_on_confirm(outcome)
                            await self.handle_confirmation_response(
                                req_info['callId'],
                                original_on_confirm,
                                outcome,
                                signal,
                                payload
                            )

                        wrapped_confirmation_details = {
                            **confirmation_details,
                            'onConfirm': wrapped_on_confirm
                        }
                        self.set_status_internal(
                            req_info['callId'],
                            ToolCallStatus.AWAITING_APPROVAL,
                            wrapped_confirmation_details
                        )
                    else:
                        self.set_status_internal(req_info['callId'], ToolCallStatus.SCHEDULED)
            except Exception as error:
                self.set_status_internal(
                    req_info['callId'],
                    ToolCallStatus.ERROR,
                    create_error_response(
                        req_info,
                        error,
                        ToolErrorType.UNHANDLED_EXCEPTION
                    )
                )

        self.attempt_execution_of_scheduled_calls(signal)
        self.check_and_notify_completion()

    async def handle_confirmation_response(
        self,
        call_id: str,
        original_on_confirm: Callable[[ToolConfirmationOutcome], asyncio.Future[None]],
        outcome: ToolConfirmationOutcome,
        signal: asyncio.Event,
        payload: Optional[ToolConfirmationPayload] = None
    ) -> None:
        tool_call = next(
            (c for c in self.tool_calls if c.request['callId'] == call_id and c.status == ToolCallStatus.AWAITING_APPROVAL),
            None
        )

        if tool_call and tool_call.status == ToolCallStatus.AWAITING_APPROVAL:
            await original_on_confirm(outcome)

        # Update outcome for the tool call
        for i, call in enumerate(self.tool_calls):
            if call.request['callId'] == call_id:
                self.tool_calls[i].outcome = outcome
                break

        if outcome == ToolConfirmationOutcome.Cancel or signal.is_set():
            self.set_status_internal(
                call_id,
                ToolCallStatus.CANCELLED,
                'User did not allow tool call'
            )
        elif outcome == ToolConfirmationOutcome.ModifyWithEditor:
            if tool_call and isModifiableTool(tool_call.tool):
                modify_context = tool_call.tool.getModifyContext(signal)
                editor_type = self.get_preferred_editor()
                if not editor_type:
                    return

                self.set_status_internal(
                    call_id,
                    ToolCallStatus.AWAITING_APPROVAL,
                    {
                        **tool_call.confirmation_details,
                        'isModifying': True
                    }
                )

                updated_params, updated_diff = await modifyWithEditor(
                    tool_call.request['args'],
                    modify_context,
                    editor_type,
                    signal
                )
                self.set_args_internal(call_id, updated_params)
                self.set_status_internal(
                    call_id,
                    ToolCallStatus.AWAITING_APPROVAL,
                    {
                        **tool_call.confirmation_details,
                        'fileDiff': updated_diff,
                        'isModifying': False
                    }
                )
        else:
            # If the client provided new content, apply it before scheduling.
            if payload and payload.get('newContent') and tool_call:
                await self._apply_inline_modify(
                    tool_call,
                    payload,
                    signal
                )
            self.set_status_internal(call_id, ToolCallStatus.SCHEDULED)

        self.attempt_execution_of_scheduled_calls(signal)

    async def _apply_inline_modify(
        self,
        tool_call: WaitingToolCall,
        payload: ToolConfirmationPayload,
        signal: asyncio.Event
    ) -> None:
        if (
            tool_call.confirmation_details.get('type') != 'edit' or
            not isModifiableTool(tool_call.tool)
        ):
            return

        modify_context = tool_call.tool.getModifyContext(signal)
        current_content = await modify_context.getCurrentContent(
            tool_call.request['args']
        )

        updated_params = modify_context.createUpdatedParams(
            current_content,
            payload['newContent'],
            tool_call.request['args']
        )
        updated_diff = create_patch(
            modify_context.getFilePath(tool_call.request['args']),
            current_content,
            payload['newContent'],
            'Current',
            'Proposed'
        )

        self.set_args_internal(tool_call.request['callId'], updated_params)
        self.set_status_internal(
            tool_call.request['callId'],
            ToolCallStatus.AWAITING_APPROVAL,
            {
                **tool_call.confirmation_details,
                'fileDiff': updated_diff
            }
        )

    def attempt_execution_of_scheduled_calls(self, signal: asyncio.Event) -> None:
        all_calls_final_or_scheduled = all(
            call.status in [
                ToolCallStatus.SCHEDULED,
                ToolCallStatus.CANCELLED,
                ToolCallStatus.SUCCESS,
                ToolCallStatus.ERROR
            ]
            for call in self.tool_calls
        )

        if all_calls_final_or_scheduled:
            calls_to_execute = [
                call for call in self.tool_calls if call.status == ToolCallStatus.SCHEDULED
            ]

            for tool_call in calls_to_execute:
                if tool_call.status != ToolCallStatus.SCHEDULED:
                    continue

                call_id = tool_call.request['callId']
                tool_name = tool_call.request['name']
                self.set_status_internal(call_id, ToolCallStatus.EXECUTING)

                live_output_callback = None
                if tool_call.tool.canUpdateOutput and self.output_update_handler:
                    def callback(output_chunk: str):
                        if self.output_update_handler:
                            self.output_update_handler(call_id, output_chunk)
                        # Update live_output for the tool call
                        for i, tc in enumerate(self.tool_calls):
                            if tc.request['callId'] == call_id and tc.status == ToolCallStatus.EXECUTING:
                                self.tool_calls[i].live_output = output_chunk
                                break
                        self.notify_tool_calls_update()

                    live_output_callback = callback

                # Execute tool in a separate task
                async def execute_tool():
                    try:
                        tool_result = await tool_call.tool.execute(
                            tool_call.request['args'],
                            signal,
                            live_output_callback
                        )

                        if signal.is_set():
                            self.set_status_internal(
                                call_id,
                                ToolCallStatus.CANCELLED,
                                'User cancelled tool execution.'
                            )
                            return

                        if tool_result.get('error') is None:
                            response = convert_to_function_response(
                                tool_name,
                                call_id,
                                tool_result['llmContent']
                            )
                            success_response = {
                                'callId': call_id,
                                'responseParts': response,
                                'resultDisplay': tool_result['returnDisplay'],
                                'error': None,
                                'errorType': None
                            }
                            self.set_status_internal(call_id, ToolCallStatus.SUCCESS, success_response)
                        else:
                            # It is a failure
                            error = Exception(tool_result['error']['message'])
                            error_response = create_error_response(
                                tool_call.request,
                                error,
                                tool_result['error']['type']
                            )
                            self.set_status_internal(call_id, ToolCallStatus.ERROR, error_response)
                    except Exception as execution_error:
                        self.set_status_internal(
                            call_id,
                            ToolCallStatus.ERROR,
                            create_error_response(
                                tool_call.request,
                                execution_error,
                                ToolErrorType.UNHANDLED_EXCEPTION
                            )
                        )

                # Start execution
                asyncio.create_task(execute_tool())

    def check_and_notify_completion(self) -> None:
        all_calls_are_terminal = all(
            call.status in [
                ToolCallStatus.SUCCESS,
                ToolCallStatus.ERROR,
                ToolCallStatus.CANCELLED
            ]
            for call in self.tool_calls
        )

        if self.tool_calls and all_calls_are_terminal:
            completed_calls = self.tool_calls.copy()
            self.tool_calls = []

            for call in completed_calls:
                logToolCall(self.config, ToolCallEvent(call))

            if self.on_all_tool_calls_complete:
                self.on_all_tool_calls_complete(completed_calls)
            self.notify_tool_calls_update()

    def notify_tool_calls_update(self) -> None:
        if self.on_tool_calls_update:
            self.on_tool_calls_update(self.tool_calls.copy())