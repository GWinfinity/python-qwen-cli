import json
import time
import asyncio
import requests
import threading
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from aiohttp_socks import ProxyConnector

from ..types import (ApiErrorEvent, FlashFallbackEvent, NextSpeakerCheckEvent, StartSessionEvent, EndSessionEvent,
    UserPromptEvent,ToolCallEvent,ApiRequestEvent,ApiResponseEvent,
    ApiErrorEvent,FlashFallbackEvent,LoopDetectedEvent,NextSpeakerCheckEvent,SlashCommandEvent,MalformedJsonResponseEvent)

# 常量定义
start_session_event_name = 'start_session'
new_prompt_event_name = 'new_prompt'
tool_call_event_name = 'tool_call'
api_request_event_name = 'api_request'
api_response_event_name = 'api_response'
api_error_event_name = 'api_error'
end_session_event_name = 'end_session'
flash_fallback_event_name = 'flash_fallback'
loop_detected_event_name = 'loop_detected'
next_speaker_check_event_name = 'next_speaker_check'
slash_command_event_name = 'slash_command'
malformed_json_response_event_name = 'malformed_json_response'

class LogResponse:
    def __init__(self, next_request_wait_ms: Optional[int] = None):
        self.next_request_wait_ms = next_request_wait_ms

# 单例类，用于向 Clearcut 批量发送日志事件
class ClearcutLogger:
    _instance: Optional['ClearcutLogger'] = None
    _lock = threading.Lock()

    def __new__(cls, config: Optional[Config] = None):
        with cls._lock:
            if cls._instance is None:
                if config is None or not config.getUsageStatisticsEnabled():
                    return None
                cls._instance = super(ClearcutLogger, cls).__new__(cls)
                cls._instance._initialize(config)
            return cls._instance

    def _initialize(self, config: Config):
        self.config = config
        self.events: List[Any] = []
        self.last_flush_time = time.time()
        self.flush_interval_ms = 1000 * 60  # 至少等待一分钟后刷新事件

    @staticmethod
    def getInstance(config: Optional[Config] = None) -> Optional['ClearcutLogger']:
        if config is None or not config.getUsageStatisticsEnabled():
            return None
        return ClearcutLogger(config)

    def enqueue_log_event(self, event: Dict[str, Any]) -> None:
        self.events.append([{
            'event_time_ms': int(time.time() * 1000),
            'source_extension_json': json.dumps(event)
        }])

    def create_log_event(self, name: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 模拟 getCachedGoogleAccount 和 getLifetimeGoogleAccounts 函数
        email = self._get_cached_google_account()
        total_accounts = self._get_lifetime_google_accounts()
        data.append({
            'gemini_cli_key': EventMetadataKey.GEMINI_CLI_GOOGLE_ACCOUNTS_COUNT,
            'value': str(total_accounts)
        })

        log_event = {
            'console_type': 'GEMINI_CLI',
            'application': 102,
            'event_name': name,
            'event_metadata': [data]
        }

        # 应该记录电子邮件或安装 ID，而不是两者都记录
        if email:
            log_event['client_email'] = email
        else:
            log_event['client_install_id'] = self._get_installation_id()

        return log_event

    def flush_if_needed(self) -> None:
        if time.time() - self.last_flush_time < self.flush_interval_ms / 1000:
            return

        asyncio.run(self.flush_to_clearcut())

    async def flush_to_clearcut(self) -> LogResponse:
        if self.config.getDebugMode():
            logger.info('Flushing log events to Clearcut.')
        events_to_send = self.events.copy()
        if not events_to_send:
            return LogResponse()

        try:
            response_buffer = await self._retry_with_backoff(self._make_flush_request, events_to_send)
            self.events = []
            self.last_flush_time = time.time()
            return self._decode_log_response(response_buffer) or LogResponse()
        except Exception as error:
            if self.config.getDebugMode():
                logger.error(f'Clearcut flush failed after multiple retries: {error}')
            return LogResponse()

    async def _retry_with_backoff(self, func, *args, max_attempts=3, initial_delay_ms=200):
        attempts = 0
        while attempts < max_attempts:
            try:
                return await func(*args)
            except Exception as error:
                attempts += 1
                if attempts >= max_attempts:
                    raise

                # 检查是否应该重试
                if not self._should_retry(error):
                    raise

                delay = initial_delay_ms * (2 ** (attempts - 1))
                if self.config.getDebugMode():
                    logger.info(f'Retrying Clearcut flush after {delay}ms due to error: {error}')
                await asyncio.sleep(delay / 1000)

    def _should_retry(self, error: Exception) -> bool:
        if isinstance(error, HttpError):
            status = error.status
            # 对 429（请求过多）和 5xx 服务器错误进行重试
            return status == 429 or (status is not None and status >= 500 and status < 600)
        # 网络错误也重试
        return True

    async def _make_flush_request(self, events_to_send: List[Any]) -> bytes:
        request = [{
            'log_source_name': 'CONCORD',
            'request_time_ms': int(time.time() * 1000),
            'log_event': events_to_send
        }]
        body = json.dumps(request)

        headers = {'Content-Length': str(len(body))}
        proxies = None
        proxy_url = self.config.getProxy()
        if proxy_url:
            if proxy_url.startswith('http'):
                proxies = {'https': proxy_url}
            else:
                raise ValueError('Unsupported proxy type')

        # 使用 aiohttp 或 requests? 这里为了简化使用 requests，但在实际异步环境中应使用 aiohttp
        # 注意：requests 不支持真正的异步，这里只是模拟
        response = requests.post(
            url='https://play.googleapis.com/log',
            data=body,
            headers=headers,
            proxies=proxies
        )

        if response.status_code < 200 or response.status_code >= 300:
            raise HttpError(f'Request failed with status {response.status_code}', response.status_code)

        return response.content

    def _decode_log_response(self, buf: bytes) -> Optional[LogResponse]:
        if len(buf) < 1:
            return None

        # 第一个字节是 `field<<3 | type`。我们要找的是字段 1，类型为 varint，由 type=0 表示
        if buf[0] != 8:
            return None

        ms = 0
        cont = True

        # 在每个字节中，最高位是连续位。如果设置了，我们继续。最低7位是数据位
        for i in range(1, len(buf)):
            if not cont:
                break
            byte = [i]
            ms |= (byte & 0x7f) << (7 * (i - 1))
            cont = (byte & 0x80) != 0

        if cont:
            return None

        return_val = {"nextRequestWaitMs": int(ms)}
        return return_val

    def log_start_session_event(self, event: StartSessionEvent) -> None:
        surface = "CLOUD_SHELL" if os.environ.get('CLOUD_SHELL') == 'true' else (os.environ.get('SURFACE') or "SURFACE_NOT_SET")

        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_MODEL,
                "value": event.model,
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SESSION_ID,
                "value": self.config.get_session_id() if self.config else "",
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_EMBEDDING_MODEL,
                "value": event.embedding_model,
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_SANDBOX,
                "value": str(event.sandbox_enabled),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_CORE_TOOLS,
                "value": event.core_tools_enabled,
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_APPROVAL_MODE,
                "value": event.approval_mode,
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_API_KEY_ENABLED,
                "value": str(event.api_key_enabled),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_VERTEX_API_ENABLED,
                "value": str(event.vertex_ai_enabled),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_DEBUG_MODE_ENABLED,
                "value": str(event.debug_enabled),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_MCP_SERVERS,
                "value": event.mcp_servers,
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_TELEMETRY_ENABLED,
                "value": str(event.telemetry_enabled),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_START_SESSION_TELEMETRY_LOG_USER_PROMPTS_ENABLED,
                "value": str(event.telemetry_log_user_prompts_enabled),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SURFACE,
                "value": surface,
            },
        ]
    
    def log_new_prompt_event(self, event: UserPromptEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_USER_PROMPT_LENGTH,
                "value": json.dumps(event.prompt_length),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SESSION_ID,
                "value": self.config.get_session_id() if self.config else "",
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_AUTH_TYPE,
                "value": json.dumps(event.auth_type),
            },
        ]

        self.enqueue_log_event(self.create_log_event(new_prompt_event_name, data))
        self.flush_if_needed()

    def log_tool_call_event(self, event: ToolCallEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_TOOL_CALL_NAME,
                "value": json.dumps(event.function_name),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_TOOL_CALL_DECISION,
                "value": json.dumps(event.decision),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_TOOL_CALL_SUCCESS,
                "value": json.dumps(event.success),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_TOOL_CALL_DURATION_MS,
                "value": json.dumps(event.duration_ms),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_TOOL_ERROR_MESSAGE,
                "value": json.dumps(event.error),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_TOOL_CALL_ERROR_TYPE,
                "value": json.dumps(event.error_type),
            },
        ]

        log_event = self.create_log_event(tool_call_event_name, data)
        self.enqueue_log_event(log_event)
        self.flush_if_needed()

    def log_api_request_event(self, event: ApiRequestEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_REQUEST_MODEL,
                "value": json.dumps(event.model),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
        ]

        self.enqueue_log_event(self.create_log_event(api_request_event_name, data))
        self.flush_if_needed()

    def log_api_response_event(self, event: ApiResponseEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_MODEL,
                "value": json.dumps(event.model),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_STATUS_CODE,
                "value": json.dumps(event.status_code),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_DURATION_MS,
                "value": json.dumps(event.duration_ms),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_ERROR_MESSAGE,
                "value": json.dumps(event.error),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_INPUT_TOKEN_COUNT,
                "value": json.dumps(event.input_token_count),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_OUTPUT_TOKEN_COUNT,
                "value": json.dumps(event.output_token_count),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_CACHED_TOKEN_COUNT,
                "value": json.dumps(event.cached_content_token_count),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_THINKING_TOKEN_COUNT,
                "value": json.dumps(event.thoughts_token_count),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_RESPONSE_TOOL_TOKEN_COUNT,
                "value": json.dumps(event.tool_token_count),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_AUTH_TYPE,
                "value": json.dumps(event.auth_type),
            },
        ]

        self.enqueue_log_event(self.create_log_event(api_response_event_name, data))
        self.flush_if_needed()

    def log_api_error_event(self, event: ApiErrorEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_ERROR_MODEL,
                "value": json.dumps(event.model),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_ERROR_TYPE,
                "value": json.dumps(event.error_type),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_ERROR_STATUS_CODE,
                "value": json.dumps(event.status_code),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_API_ERROR_DURATION_MS,
                "value": json.dumps(event.duration_ms),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_AUTH_TYPE,
                "value": json.dumps(event.auth_type),
            },
        ]

        self.enqueue_log_event(self.create_log_event(api_error_event_name, data))
        self.flush_if_needed()

    def log_flash_fallback_event(self, event: FlashFallbackEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_AUTH_TYPE,
                "value": json.dumps(event.auth_type),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SESSION_ID,
                "value": self.config.get_session_id() if self.config else "",
            },
        ]

        self.enqueue_log_event(self.create_log_event(flash_fallback_event_name, data))
        asyncio.create_task(self.flush_to_clearcut())

    def log_loop_detected_event(self, event: LoopDetectedEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_LOOP_DETECTED_TYPE,
                "value": json.dumps(event.loop_type),
            },
        ]

        self.enqueue_log_event(self.create_log_event(loop_detected_event_name, data))
        self.flush_if_needed()

    def log_next_speaker_check(self, event: NextSpeakerCheckEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_PROMPT_ID,
                "value": json.dumps(event.prompt_id),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_RESPONSE_FINISH_REASON,
                "value": json.dumps(event.finish_reason),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_NEXT_SPEAKER_CHECK_RESULT,
                "value": json.dumps(event.result),
            },
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SESSION_ID,
                "value": self.config.get_session_id() if self.config else "",
            },
        ]

        self.enqueue_log_event(
            self.create_log_event(next_speaker_check_event_name, data),
        )
        self.flush_if_needed()

    def log_slash_command_event(self, event: SlashCommandEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SLASH_COMMAND_NAME,
                "value": json.dumps(event.command),
            },
        ]

        if event.subcommand:
            data.append({
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SLASH_COMMAND_SUBCOMMAND,
                "value": json.dumps(event.subcommand),
            })

        self.enqueue_log_event(self.create_log_event(slash_command_event_name, data))
        self.flush_if_needed()

    def log_malformed_json_response_event(self, event: MalformedJsonResponseEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_MALFORMED_JSON_RESPONSE_MODEL,
                "value": json.dumps(event.model),
            },
        ]

        self.enqueue_log_event(
            self.create_log_event(malformed_json_response_event_name, data),
        )
        self.flush_if_needed()

    def log_end_session_event(self, event: EndSessionEvent) -> None:
        data = [
            {
                "gemini_cli_key": EventMetadataKey.GEMINI_CLI_SESSION_ID,
                "value": str(event.session_id) if event.session_id else "",
            },
        ]

        # 会话结束时立即刷新
        self.enqueue_log_event(self.create_log_event(end_session_event_name, data))
        asyncio.create_task(self.flush_to_clearcut())

    def get_proxy_agent(self) -> Optional[aiohttp.ClientSession]:
        proxy_url = self.config.get_proxy() if self.config else None
        if not proxy_url:
            return None
        # 支持http和https代理
        if proxy_url.startswith('http'):
            connector = ProxyConnector.from_url(proxy_url)
            return aiohttp.ClientSession(connector=connector)
        else:
            raise ValueError('Unsupported proxy type')

    def shutdown(self) -> None:
        event = EndSessionEvent(self.config)
        self.log_end_session_event(event)

