from enum import Enum
from typing import Optional


class EventMetadataKey(Enum):
    """
    定义 Clearcut 日志记录的有效事件元数据键。

    @license
    Copyright 2025 Google LLC
    SPDX-License-Identifier: Apache-2.0
    """
    GEMINI_CLI_KEY_UNKNOWN = 0

    # ==========================================================================
    # 开始会话事件键
    # ===========================================================================

    # 记录会话中使用的模型 ID
    GEMINI_CLI_START_SESSION_MODEL = 1

    # 记录会话中使用的嵌入模型 ID
    GEMINI_CLI_START_SESSION_EMBEDDING_MODEL = 2

    # 记录会话中使用的沙箱
    GEMINI_CLI_START_SESSION_SANDBOX = 3

    # 记录会话中启用的核心工具
    GEMINI_CLI_START_SESSION_CORE_TOOLS = 4

    # 记录会话中使用的审批模式
    GEMINI_CLI_START_SESSION_APPROVAL_MODE = 5

    # 记录会话中是否使用 API 密钥
    GEMINI_CLI_START_SESSION_API_KEY_ENABLED = 6

    # 记录会话中是否使用 Vertex API
    GEMINI_CLI_START_SESSION_VERTEX_API_ENABLED = 7

    # 记录会话中是否启用调试模式
    GEMINI_CLI_START_SESSION_DEBUG_MODE_ENABLED = 8

    # 记录会话中启用的 MCP 服务器
    GEMINI_CLI_START_SESSION_MCP_SERVERS = 9

    # 记录会话中是否启用用户收集的遥测
    GEMINI_CLI_START_SESSION_TELEMETRY_ENABLED = 10

    # 记录用户收集的遥测是否启用提示收集
    GEMINI_CLI_START_SESSION_TELEMETRY_LOG_USER_PROMPTS_ENABLED = 11

    # 记录会话是否配置为尊重 gitignore 文件
    GEMINI_CLI_START_SESSION_RESPECT_GITIGNORE = 12

    # ==========================================================================
    # 用户提示事件键
    # ===========================================================================

    # 记录提示的长度
    GEMINI_CLI_USER_PROMPT_LENGTH = 13

    # ==========================================================================
    # 工具调用事件键
    # ===========================================================================

    # 记录函数名称
    GEMINI_CLI_TOOL_CALL_NAME = 14

    # 记录用户关于如何处理工具调用的决定
    GEMINI_CLI_TOOL_CALL_DECISION = 15

    # 记录工具调用是否成功
    GEMINI_CLI_TOOL_CALL_SUCCESS = 16

    # 记录工具调用持续时间（毫秒）
    GEMINI_CLI_TOOL_CALL_DURATION_MS = 17

    # 记录工具调用错误消息（如果有）
    GEMINI_CLI_TOOL_ERROR_MESSAGE = 18

    # 记录工具调用错误类型（如果有）
    GEMINI_CLI_TOOL_CALL_ERROR_TYPE = 19

    # ==========================================================================
    # GenAI API 请求事件键
    # ===========================================================================

    # 记录请求的模型 ID
    GEMINI_CLI_API_REQUEST_MODEL = 20

    # ==========================================================================
    # GenAI API 响应事件键
    # ===========================================================================

    # 记录 API 调用的模型 ID
    GEMINI_CLI_API_RESPONSE_MODEL = 21

    # 记录响应的状态码
    GEMINI_CLI_API_RESPONSE_STATUS_CODE = 22

    # 记录 API 调用的持续时间（毫秒）
    GEMINI_CLI_API_RESPONSE_DURATION_MS = 23

    # 记录 API 调用的错误消息（如果有）
    GEMINI_CLI_API_ERROR_MESSAGE = 24

    # 记录 API 调用的输入令牌计数
    GEMINI_CLI_API_RESPONSE_INPUT_TOKEN_COUNT = 25

    # 记录 API 调用的输出令牌计数
    GEMINI_CLI_API_RESPONSE_OUTPUT_TOKEN_COUNT = 26

    # 记录 API 调用的缓存令牌计数
    GEMINI_CLI_API_RESPONSE_CACHED_TOKEN_COUNT = 27

    # 记录 API 调用的思考令牌计数
    GEMINI_CLI_API_RESPONSE_THINKING_TOKEN_COUNT = 28

    # 记录 API 调用的工具使用令牌计数
    GEMINI_CLI_API_RESPONSE_TOOL_TOKEN_COUNT = 29

    # ==========================================================================
    # GenAI API 错误事件键
    # ===========================================================================

    # 记录 API 调用的模型 ID
    GEMINI_CLI_API_ERROR_MODEL = 30

    # 记录错误类型
    GEMINI_CLI_API_ERROR_TYPE = 31

    # 记录错误响应的状态码
    GEMINI_CLI_API_ERROR_STATUS_CODE = 32

    # 记录 API 调用的持续时间（毫秒）
    GEMINI_CLI_API_ERROR_DURATION_MS = 33

    # ==========================================================================
    # 结束会话事件键
    # ===========================================================================

    # 记录会话结束
    GEMINI_CLI_END_SESSION_ID = 34

    # ==========================================================================
    # 共享键
    # ===========================================================================

    # 记录提示 ID
    GEMINI_CLI_PROMPT_ID = 35

    # 记录提示、API 响应和错误的认证类型
    GEMINI_CLI_AUTH_TYPE = 36

    # 记录曾经使用的 Google 账户总数
    GEMINI_CLI_GOOGLE_ACCOUNTS_COUNT = 37

    # 记录调用 Gemini CLI 的界面，例如：VSCode
    GEMINI_CLI_SURFACE = 39

    # 记录会话 ID
    GEMINI_CLI_SESSION_ID = 40

    # ==========================================================================
    # 检测到循环事件键
    # ===========================================================================

    # 记录检测到的循环类型
    GEMINI_CLI_LOOP_DETECTED_TYPE = 38

    # ==========================================================================
    # 斜杠命令事件键
    # ===========================================================================

    # 记录斜杠命令的名称
    GEMINI_CLI_SLASH_COMMAND_NAME = 41

    # 记录斜杠命令的子命令
    GEMINI_CLI_SLASH_COMMAND_SUBCOMMAND = 42

    # ==========================================================================
    # 下一个发言人检查事件键
    # ===========================================================================

    # 记录前一个 streamGenerateContent 响应的完成原因
    GEMINI_CLI_RESPONSE_FINISH_REASON = 43

    # 记录下一个发言人检查的结果
    GEMINI_CLI_NEXT_SPEAKER_CHECK_RESULT = 44

    # ==========================================================================
    # 格式错误的 JSON 响应事件键
    # ==========================================================================

    # 记录产生格式错误的 JSON 响应的模型
    GEMINI_CLI_MALFORMED_JSON_RESPONSE_MODEL = 45


def get_event_metadata_key(key_name: str) -> Optional[EventMetadataKey]:
    """
    根据键名获取对应的事件元数据键枚举值。

    Args:
        key_name: 要查找的键名

    Returns:
        对应的事件元数据键枚举值，如果不存在则返回 None
    """
    try:
        return EventMetadataKey[key_name]
    except KeyError:
        return None