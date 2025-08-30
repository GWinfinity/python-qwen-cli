"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional

# 从对应模块导入需要的配置和类型
def import_telemetry_deps():
    # 这是一个模拟导入函数，实际使用时需要替换为正确的导入路径
    try:
        from ..config.config import Config
        from .constants import (
            EVENT_API_ERROR,
            EVENT_API_REQUEST,
            EVENT_API_RESPONSE,
            EVENT_CLI_CONFIG,
            EVENT_TOOL_CALL,
            EVENT_USER_PROMPT,
            EVENT_FLASH_FALLBACK,
            EVENT_NEXT_SPEAKER_CHECK,
            SERVICE_NAME,
            EVENT_SLASH_COMMAND,
        )
        from .types import (
            ApiErrorEvent,
            ApiRequestEvent,
            ApiResponseEvent,
            StartSessionEvent,
            ToolCallEvent,
            UserPromptEvent,
            FlashFallbackEvent,
            NextSpeakerCheckEvent,
            LoopDetectedEvent,
            SlashCommandEvent,
        )
        from .metrics import (
            record_api_error_metrics,
            record_token_usage_metrics,
            record_api_response_metrics,
            record_tool_call_metrics,
        )
        from .sdk import is_telemetry_sdk_initialized
        from .uiTelemetry import ui_telemetry_service, UiEvent
        from .clearcut_logger.clearcut_logger import ClearcutLogger
        from ..utils.safeJsonStringify import safe_json_stringify
        
        # 假设的 OpenTelemetry 相关导入
        # 实际项目中需要根据 Python 的 OpenTelemetry API 进行调整
        from opentelemetry.api.logs import logs
        from opentelemetry.semantic_conventions import SemanticAttributes
        
        return {
            'Config': Config,
            'EVENT_API_ERROR': EVENT_API_ERROR,
            'EVENT_API_REQUEST': EVENT_API_REQUEST,
            'EVENT_API_RESPONSE': EVENT_API_RESPONSE,
            'EVENT_CLI_CONFIG': EVENT_CLI_CONFIG,
            'EVENT_TOOL_CALL': EVENT_TOOL_CALL,
            'EVENT_USER_PROMPT': EVENT_USER_PROMPT,
            'EVENT_FLASH_FALLBACK': EVENT_FLASH_FALLBACK,
            'EVENT_NEXT_SPEAKER_CHECK': EVENT_NEXT_SPEAKER_CHECK,
            'SERVICE_NAME': SERVICE_NAME,
            'EVENT_SLASH_COMMAND': EVENT_SLASH_COMMAND,
            'record_api_error_metrics': record_api_error_metrics,
            'record_token_usage_metrics': record_token_usage_metrics,
            'record_api_response_metrics': record_api_response_metrics,
            'record_tool_call_metrics': record_tool_call_metrics,
            'is_telemetry_sdk_initialized': is_telemetry_sdk_initialized,
            'ui_telemetry_service': ui_telemetry_service,
            'UiEvent': UiEvent,
            'ClearcutLogger': ClearcutLogger,
            'safe_json_stringify': safe_json_stringify,
            'logs': logs,
            'SemanticAttributes': SemanticAttributes
        }
    except ImportError as e:
        # 在实际应用中，这里应该有更合适的错误处理
        print(f"Import error: {e}")
        return None

# 获取导入的依赖
deps = import_telemetry_deps()

# 定义一个安全获取依赖项的函数
def get_dep(name: str) -> Any:
    if deps and name in deps:
        return deps[name]
    # 对于未找到的依赖，返回默认值或引发异常
    # 在实际应用中，这里应该有更合适的错误处理
    return None

# 从依赖中获取常量和函数
logs = get_dep('logs')
SemanticAttributes = get_dep('SemanticAttributes')
EVENT_API_ERROR = get_dep('EVENT_API_ERROR')
EVENT_API_REQUEST = get_dep('EVENT_API_REQUEST')
EVENT_API_RESPONSE = get_dep('EVENT_API_RESPONSE')
EVENT_CLI_CONFIG = get_dep('EVENT_CLI_CONFIG')
EVENT_TOOL_CALL = get_dep('EVENT_TOOL_CALL')
EVENT_USER_PROMPT = get_dep('EVENT_USER_PROMPT')
EVENT_FLASH_FALLBACK = get_dep('EVENT_FLASH_FALLBACK')
EVENT_NEXT_SPEAKER_CHECK = get_dep('EVENT_NEXT_SPEAKER_CHECK')
SERVICE_NAME = get_dep('SERVICE_NAME')
EVENT_SLASH_COMMAND = get_dep('EVENT_SLASH_COMMAND')
record_api_error_metrics = get_dep('record_api_error_metrics')
record_token_usage_metrics = get_dep('record_token_usage_metrics')
record_api_response_metrics = get_dep('record_api_response_metrics')
record_tool_call_metrics = get_dep('record_tool_call_metrics')
is_telemetry_sdk_initialized = get_dep('is_telemetry_sdk_initialized')
ui_telemetry_service = get_dep('ui_telemetry_service')
UiEvent = get_dep('UiEvent')
ClearcutLogger = get_dep('ClearcutLogger')
safe_json_stringify = get_dep('safe_json_stringify')


def should_log_user_prompts(config: Any) -> bool:
    """检查是否应该记录用户提示"""
    return config.get_telemetry_log_prompts_enabled()


def get_common_attributes(config: Any) -> Dict[str, Any]:
    """获取通用的日志属性"""
    return {
        'session.id': config.get_session_id(),
    }

def log_cli_configuration(config: Any, event: Any) -> None:
    """记录CLI配置信息"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_start_session_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        'event.name': EVENT_CLI_CONFIG,
        'event.timestamp': datetime.now().isoformat(),
        'model': event.model,
        'embedding_model': event.embedding_model,
        'sandbox_enabled': event.sandbox_enabled,
        'core_tools_enabled': event.core_tools_enabled,
        'approval_mode': event.approval_mode,
        'api_key_enabled': event.api_key_enabled,
        'vertex_ai_enabled': event.vertex_ai_enabled,
        'log_user_prompts_enabled': event.telemetry_log_user_prompts_enabled,
        'file_filtering_respect_git_ignore': event.file_filtering_respect_git_ignore,
        'debug_mode': event.debug_enabled,
        'mcp_servers': event.mcp_servers,
    }

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': 'CLI configuration loaded.',
        'attributes': attributes,
    }
    logger.emit(log_record)

def log_user_prompt(config: Any, event: Any) -> None:
    """记录用户提示信息"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_new_prompt_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        'event.name': EVENT_USER_PROMPT,
        'event.timestamp': datetime.now().isoformat(),
        'prompt_length': event.prompt_length,
    }

    if should_log_user_prompts(config):
        attributes['prompt'] = event.prompt

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': f'User prompt. Length: {event.prompt_length}.',
        'attributes': attributes,
    }
    logger.emit(log_record)

def log_tool_call(config: Any, event: Any) -> None:
    """记录工具调用信息"""
    ui_event = {
        **vars(event),  # 将事件对象转换为字典
        'event.name': EVENT_TOOL_CALL,
        'event.timestamp': datetime.now().isoformat(),
    }
    if ui_telemetry_service:
        ui_telemetry_service.add_event(ui_event)
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_tool_call_event(event)
    if not is_telemetry_sdk_initialized():
        return

    # 安全处理function_args
    function_args_str = ''
    if hasattr(event, 'function_args'):
        if safe_json_stringify:
            function_args_str = safe_json_stringify(event.function_args, 2)
        else:
            try:
                function_args_str = json.dumps(event.function_args, ensure_ascii=False, indent=2)
            except Exception:
                function_args_str = 'Failed to serialize function_args'

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),  # 将事件对象的属性添加到字典
        'event.name': EVENT_TOOL_CALL,
        'event.timestamp': datetime.now().isoformat(),
        'function_args': function_args_str,
    }

    if hasattr(event, 'error') and event.error:
        attributes['error.message'] = event.error
        if hasattr(event, 'error_type') and event.error_type:
            attributes['error.type'] = event.error_type

    logger = logs.get_logger(SERVICE_NAME)
    decision_text = f'. Decision: {event.decision}' if hasattr(event, 'decision') and event.decision else ''
    log_record = {
        'body': f'Tool call: {event.function_name}{decision_text}. Success: {event.success}. Duration: {event.duration_ms}ms.',
        'attributes': attributes,
    }
    logger.emit(log_record)
    
    if record_tool_call_metrics:
        record_tool_call_metrics(
            config,
            event.function_name,
            event.duration_ms,
            event.success,
            event.decision if hasattr(event, 'decision') else None,
        )

def log_api_request(config: Any, event: Any) -> None:
    """记录API请求信息"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_api_request_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
        'event.name': EVENT_API_REQUEST,
        'event.timestamp': datetime.now().isoformat(),
    }

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': f'API request to {event.model}.',
        'attributes': attributes,
    }
    logger.emit(log_record)

def log_flash_fallback(config: Any, event: Any) -> None:
    """记录Flash回退事件"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_flash_fallback_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
        'event.name': EVENT_FLASH_FALLBACK,
        'event.timestamp': datetime.now().isoformat(),
    }

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': 'Switching to flash as Fallback.',
        'attributes': attributes,
    }
    logger.emit(log_record)

def log_api_error(config: Any, event: Any) -> None:
    """记录API错误信息"""
    ui_event = {
        **vars(event),
        'event.name': EVENT_API_ERROR,
        'event.timestamp': datetime.now().isoformat(),
    }
    if ui_telemetry_service:
        ui_telemetry_service.add_event(ui_event)
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_api_error_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
        'event.name': EVENT_API_ERROR,
        'event.timestamp': datetime.now().isoformat(),
        'error.message': event.error,
        'model_name': event.model,
        'duration': event.duration_ms,
    }

    if hasattr(event, 'error_type') and event.error_type:
        attributes['error.type'] = event.error_type
    if hasattr(event, 'status_code') and isinstance(event.status_code, (int, float)):
        if SemanticAttributes:
            attributes[SemanticAttributes.HTTP_STATUS_CODE] = event.status_code

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': f'API error for {event.model}. Error: {event.error}. Duration: {event.duration_ms}ms.',
        'attributes': attributes,
    }
    logger.emit(log_record)
    
    if record_api_error_metrics:
        record_api_error_metrics(
            config,
            event.model,
            event.duration_ms,
            event.status_code if hasattr(event, 'status_code') else None,
            event.error_type if hasattr(event, 'error_type') else None,
        )

def log_api_response(config: Any, event: Any) -> None:
    """记录API响应信息"""
    ui_event = {
        **vars(event),
        'event.name': EVENT_API_RESPONSE,
        'event.timestamp': datetime.now().isoformat(),
    }
    if ui_telemetry_service:
        ui_telemetry_service.add_event(ui_event)
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_api_response_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
        'event.name': EVENT_API_RESPONSE,
        'event.timestamp': datetime.now().isoformat(),
    }
    
    if hasattr(event, 'response_text') and event.response_text:
        attributes['response_text'] = event.response_text
    if hasattr(event, 'error') and event.error:
        attributes['error.message'] = event.error
    elif hasattr(event, 'status_code') and event.status_code:
        if isinstance(event.status_code, (int, float)) and SemanticAttributes:
            attributes[SemanticAttributes.HTTP_STATUS_CODE] = event.status_code

    logger = logs.get_logger(SERVICE_NAME)
    status_code_text = event.status_code if hasattr(event, 'status_code') else 'N/A'
    log_record = {
        'body': f'API response from {event.model}. Status: {status_code_text}. Duration: {event.duration_ms}ms.',
        'attributes': attributes,
    }
    logger.emit(log_record)
    
    if record_api_response_metrics:
        record_api_response_metrics(
            config,
            event.model,
            event.duration_ms,
            event.status_code if hasattr(event, 'status_code') else None,
            event.error if hasattr(event, 'error') else None,
        )
    
    if record_token_usage_metrics:
        # 记录各种token使用量
        if hasattr(event, 'input_token_count'):
            record_token_usage_metrics(config, event.model, event.input_token_count, 'input')
        if hasattr(event, 'output_token_count'):
            record_token_usage_metrics(config, event.model, event.output_token_count, 'output')
        if hasattr(event, 'cached_content_token_count'):
            record_token_usage_metrics(config, event.model, event.cached_content_token_count, 'cache')
        if hasattr(event, 'thoughts_token_count'):
            record_token_usage_metrics(config, event.model, event.thoughts_token_count, 'thought')
        if hasattr(event, 'tool_token_count'):
            record_token_usage_metrics(config, event.model, event.tool_token_count, 'tool')

def log_loop_detected(config: Any, event: Any) -> None:
    """记录检测到的循环事件"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_loop_detected_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
    }

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': f'Loop detected. Type: {event.loop_type}.',
        'attributes': attributes,
    }
    logger.emit(log_record)

def log_next_speaker_check(config: Any, event: Any) -> None:
    """记录下一个发言者检查事件"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_next_speaker_check(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
        'event.name': EVENT_NEXT_SPEAKER_CHECK,
    }

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': 'Next speaker check.',
        'attributes': attributes,
    }
    logger.emit(log_record)

def log_slash_command(config: Any, event: Any) -> None:
    """记录斜杠命令事件"""
    if ClearcutLogger:
        ClearcutLogger.get_instance(config).log_slash_command_event(event)
    if not is_telemetry_sdk_initialized():
        return

    attributes: Dict[str, Any] = {
        **get_common_attributes(config),
        **vars(event),
        'event.name': EVENT_SLASH_COMMAND,
    }

    logger = logs.get_logger(SERVICE_NAME)
    log_record = {
        'body': f'Slash command: {event.command}.',
        'attributes': attributes,
    }
    logger.emit(log_record)