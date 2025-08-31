"""
@license
Copyright 2025 Qwen
SPDX-License-Identifier: Apache-2.0
"""

import os
import json
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional, Set, Any, Union, TypeVar, Protocol
from collections import defaultdict

# 导入相关类型和接口
from google.genai.types import (
    CountTokensResponse as GoogleCountTokensResponse,
    GenerateContentResponse as GoogleGenerateContentResponse,
    GenerateContentParameters,
    CountTokensParameters,
    EmbedContentResponse as GoogleEmbedContentResponse,
    EmbedContentParameters,
    FinishReason,
    Part,
    Content,
    Tool,
    ToolListUnion,
    CallableTool,
    FunctionCall,
    FunctionResponse,
)
from .content_generator import ContentGenerator
from openai import OpenAI
from ..telemetry.loggers import log_api_response
from ..telemetry.types import ApiResponseEvent
from ..config.config import Config
from ..utils.openai_logger import openai_logger

# OpenAI API 类型定义用于日志记录
typing_T = TypeVar('typing_T')

class OpenAIToolCall(Protocol):
    id: str
    type: str
    function: Dict[str, Any]

class OpenAIMessage(Protocol):
    role: str  # 'system' | 'user' | 'assistant' | 'tool'
    content: Optional[str]
    tool_calls: Optional[List[OpenAIToolCall]]
    tool_call_id: Optional[str]

class OpenAIUsage(Protocol):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: Optional[Dict[str, Any]]

class OpenAIChoice(Protocol):
    index: int
    message: OpenAIMessage
    finish_reason: str

class OpenAIRequestFormat(Protocol):
    model: str
    messages: List[OpenAIMessage]
    temperature: Optional[float]
    max_tokens: Optional[int]
    top_p: Optional[float]
    tools: Optional[List[Any]]

class OpenAIResponseFormat(Protocol):
    id: str
    object: str
    created: int
    model: str
    choices: List[OpenAIChoice]
    usage: Optional[OpenAIUsage]


class OpenAIContentGenerator(ContentGenerator):
    def __init__(self, api_key: str, model: str, config: Config):
        self.model = model
        self.config = config
        base_url = os.environ.get('OPENAI_BASE_URL', '')

        # 配置超时设置 - 使用渐进式超时
        timeout_config = {
            # 大多数请求的基本超时（2分钟）
            'timeout': 120000,
            # 失败请求的最大重试次数
            'max_retries': 3,
            # HTTP客户端选项
            'http_agent': None,  # 让客户端使用默认代理
        }

        # 允许配置覆盖超时设置
        content_generator_config = self.config.get_content_generator_config()
        if content_generator_config and content_generator_config.timeout:
            timeout_config['timeout'] = content_generator_config.timeout
        if content_generator_config and content_generator_config.max_retries is not None:
            timeout_config['max_retries'] = content_generator_config.max_retries

        # 设置User-Agent头（与contentGenerator.ts相同格式）
        version = os.environ.get('CLI_VERSION', '') or str(os.sys.version)
        user_agent = f"QwenCode/{version} ({os.sys.platform}; {os.sys.arch})".replace('\n', '')

        # 检查是否使用OpenRouter并添加所需的头
        is_open_router = 'openrouter.ai' in base_url
        default_headers = {
            'User-Agent': user_agent,
            **({
                'HTTP-Referer': 'https://github.com/QwenLM/qwen-code.git',
                'X-Title': 'Qwen Code',
            } if is_open_router else {})
        }

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_config['timeout'] / 1000,  # OpenAI Python客户端使用秒而不是毫秒
            max_retries=timeout_config['max_retries'],
            default_headers=default_headers,
        )
        self.streaming_tool_calls: Dict[int, Dict[str, Any]] = defaultdict(lambda: {'arguments': ''})

    """
    子类钩子来自定义错误处理行为
    @param error 发生的错误
    @param request 原始请求
    @returns 如果应该抑制错误日志记录则为True，否则为False
    """
    def should_suppress_error_logging(self, error: Any, request: GenerateContentParameters) -> bool:
        return False  # 默认行为：从不抑制错误日志记录

    """
    检查错误是否为超时错误
    """
    def is_timeout_error(self, error: Any) -> bool:
        if not error:
            return False

        error_message = str(error).lower() if not isinstance(error, Exception) else str(error).lower()
        error_code = getattr(error, 'code', None)
        error_type = getattr(error, 'type', None)

        # 检查常见的超时指示符
        return (
            'timeout' in error_message or
            'timed out' in error_message or
            'connection timeout' in error_message or
            'request timeout' in error_message or
            'read timeout' in error_message or
            'etimedout' in error_message or  # 在消息检查中包含ETIMEDOUT
            'esockettimedout' in error_message or  # 在消息检查中包含ESOCKETTIMEDOUT
            error_code == 'ETIMEDOUT' or
            error_code == 'ESOCKETTIMEDOUT' or
            error_type == 'timeout' or
            # OpenAI特定的超时指示符
            'request timed out' in error_message or
            'deadline exceeded' in error_message
        )

    async def generate_content(
        self, 
        request: GenerateContentParameters, 
        user_prompt_id: str
    ) -> GoogleGenerateContentResponse:
        start_time = datetime.now()
        messages = self.convert_to_openai_format(request)

        try:
            # 构建采样参数，优先级明确：
            # 1. 请求级参数（最高优先级）
            # 2. 配置级采样参数（中等优先级）
            # 3. 默认值（最低优先级）
            sampling_params = self.build_sampling_parameters(request)

            create_params: Dict[str, Any] = {
                'model': self.model,
                'messages': messages,
                **sampling_params,
                'metadata': {
                    'sessionId': self.config.get_session_id() if hasattr(self.config, 'get_session_id') else None,
                    'promptId': user_prompt_id,
                },
            }

            if request.config and request.config.tools:
                create_params['tools'] = await self.convert_gemini_tools_to_openai(
                    request.config.tools
                )

            completion = await self.client.chat.completions.create(**create_params)

            response = self.convert_to_gemini_format(completion)
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # 记录API响应事件用于UI遥测
            response_event = ApiResponseEvent(
                self.model,
                duration_ms,
                user_prompt_id,
                self.config.get_content_generator_config().auth_type if self.config.get_content_generator_config() else None,
                response.usage_metadata,
            )

            log_api_response(self.config, response_event)

            # 如果启用，则记录交互
            if self.config.get_content_generator_config() and self.config.get_content_generator_config().enable_openai_logging:
                openai_request = await self.convert_gemini_request_to_openai(request)
                openai_response = self.convert_gemini_response_to_openai(response)
                await openai_logger.log_interaction(openai_request, openai_response)

            return response

        except Exception as error:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # 特别识别超时错误
            is_timeout_error = self.is_timeout_error(error)
            error_message = f"请求在{round(duration_ms / 1000)}秒后超时。尝试减少输入长度或增加配置中的超时时间。" if is_timeout_error else str(error)

            # 即使出现错误也要估计token使用量
            # 这有助于跟踪失败请求的成本和使用情况
            estimated_usage = None
            try:
                token_count_result = await self.count_tokens({
                    'contents': request.contents,
                    'model': self.model,
                })
                estimated_usage = {
                    'promptTokenCount': token_count_result.total_tokens,
                    'candidatesTokenCount': 0,  # 由于请求失败，没有完成tokens
                    'totalTokenCount': token_count_result.total_tokens,
                }
            except Exception:
                # 如果token计数也失败，提供最小估计
                content_str = json.dumps(request.contents)
                estimated_tokens = max(1, len(content_str) // 4)  # 粗略估计：1 token ≈ 4个字符
                estimated_usage = {
                    'promptTokenCount': estimated_tokens,
                    'candidatesTokenCount': 0,
                    'totalTokenCount': estimated_tokens,
                }

            # 使用估计的使用量记录UI遥测的API错误事件
            error_event = ApiResponseEvent(
                self.model,
                duration_ms,
                user_prompt_id,
                self.config.get_content_generator_config().auth_type if self.config.get_content_generator_config() else None,
                estimated_usage,
                None,
                error_message,
            )
            log_api_response(self.config, error_event)

            # 如果启用，则记录错误交互
            if self.config.get_content_generator_config() and self.config.get_content_generator_config().enable_openai_logging:
                openai_request = await self.convert_gemini_request_to_openai(request)
                await openai_logger.log_interaction(
                    openai_request,
                    None,
                    error
                )

            # 允许子类为特定场景抑制错误日志记录
            if not self.should_suppress_error_logging(error, request):
                print(f"OpenAI API错误: {error_message}")

            # 提供有帮助的超时特定错误消息
            if is_timeout_error:
                raise ValueError(
                    f"{error_message}\n\n故障排除提示:\n" +
                    "- 减少输入长度或复杂度\n" +
                    "- 增加配置中的超时时间: contentGenerator.timeout\n" +
                    "- 检查网络连接\n" +
                    "- 对于长响应，考虑使用流式传输模式"
                )

            raise

    async def generate_content_stream(
        self, 
        request: GenerateContentParameters, 
        user_prompt_id: str
    ) -> AsyncGenerator[GoogleGenerateContentResponse, None]:
        start_time = datetime.now()
        messages = self.convert_to_openai_format(request)

        try:
            # 构建采样参数，优先级明确
            sampling_params = self.build_sampling_parameters(request)

            create_params: Dict[str, Any] = {
                'model': self.model,
                'messages': messages,
                **sampling_params,
                'stream': True,
                'stream_options': {'include_usage': True},
                'metadata': {
                    'sessionId': self.config.get_session_id() if hasattr(self.config, 'get_session_id') else None,
                    'promptId': user_prompt_id,
                },
            }

            if request.config and request.config.tools:
                create_params['tools'] = await self.convert_gemini_tools_to_openai(
                    request.config.tools
                )

            stream = await self.client.chat.completions.create(**create_params)

            original_stream = self.stream_generator(stream)

            # 收集所有响应用于最终日志记录（不要在流式传输期间记录）
            responses: List[GoogleGenerateContentResponse] = []

            # 返回一个新生成器，既产生响应又收集它们
            async def wrapped_generator():
                try:
                    async for response in original_stream:
                        responses.append(response)
                        yield response

                    duration_ms = (datetime.now() - start_time).total_seconds() * 1000

                    # 从最后一个有它的响应中获取最终使用元数据
                    final_usage_metadata = None
                    for response in reversed(responses):
                        if response.usage_metadata:
                            final_usage_metadata = response.usage_metadata
                            break

                    # 记录API响应事件用于UI遥测
                    response_event = ApiResponseEvent(
                        self.model,
                        duration_ms,
                        user_prompt_id,
                        self.config.get_content_generator_config().auth_type if self.config.get_content_generator_config() else None,
                        final_usage_metadata,
                    )

                    log_api_response(self.config, response_event)

                    # 如果启用，则记录交互（与generateContent方法相同）
                    if self.config.get_content_generator_config() and self.config.get_content_generator_config().enable_openai_logging:
                        openai_request = await self.convert_gemini_request_to_openai(request)
                        # 对于流式传输，我们将所有响应合并为一个响应进行记录
                        combined_response = self.combine_stream_responses_for_logging(responses)
                        openai_response = self.convert_gemini_response_to_openai(combined_response)
                        await openai_logger.log_interaction(openai_request, openai_response)

                except Exception as error:
                    duration_ms = (datetime.now() - start_time).total_seconds() * 1000

                    # 特别识别流式传输的超时错误
                    is_timeout_error = self.is_timeout_error(error)
                    error_message = f"流式请求在{round(duration_ms / 1000)}秒后超时。尝试减少输入长度或增加配置中的超时时间。" if is_timeout_error else str(error)

                    # 即使在流式传输中出现错误，也要估计token使用量
                    estimated_usage = None
                    try:
                        token_count_result = await self.count_tokens({
                            'contents': request.contents,
                            'model': self.model,
                        })
                        estimated_usage = {
                            'promptTokenCount': token_count_result.total_tokens,
                            'candidatesTokenCount': 0,  # 由于请求失败，没有完成tokens
                            'totalTokenCount': token_count_result.total_tokens,
                        }
                    except Exception:
                        # 如果token计数也失败，提供最小估计
                        content_str = json.dumps(request.contents)
                        estimated_tokens = max(1, len(content_str) // 4)  # 粗略估计：1 token ≈ 4个字符
                        estimated_usage = {
                            'promptTokenCount': estimated_tokens,
                            'candidatesTokenCount': 0,
                            'totalTokenCount': estimated_tokens,
                        }

                    # 使用估计的使用量记录UI遥测的API错误事件
                    error_event = ApiResponseEvent(
                        self.model,
                        duration_ms,
                        user_prompt_id,
                        self.config.get_content_generator_config().auth_type if self.config.get_content_generator_config() else None,
                        estimated_usage,
                        None,
                        error_message,
                    )
                    log_api_response(self.config, error_event)

                    # 如果启用，则记录错误交互
                    if self.config.get_content_generator_config() and self.config.get_content_generator_config().enable_openai_logging:
                        openai_request = await self.convert_gemini_request_to_openai(request)
                        await openai_logger.log_interaction(
                            openai_request,
                            None,
                            error
                        )

                    # 为流式传输提供有帮助的超时特定错误消息
                    if is_timeout_error:
                        raise ValueError(
                            f"{error_message}\n\n流式传输超时故障排除:\n" +
                            "- 减少输入长度或复杂度\n" +
                            "- 增加配置中的超时时间: contentGenerator.timeout\n" +
                            "- 检查流式连接的网络稳定性\n" +
                            "- 对于非常长的输入，考虑使用非流式传输模式"
                        )

                    raise

            # 将self绑定到生成器函数
            async for response in wrapped_generator():
                yield response

        except Exception as error:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # 特别识别流式设置的超时错误
            is_timeout_error = self.is_timeout_error(error)
            error_message = f"流式设置在{round(duration_ms / 1000)}秒后超时。尝试减少输入长度或增加配置中的超时时间。" if is_timeout_error else str(error)

            # 即使在流式设置中出现错误，也要估计token使用量
            estimated_usage = None
            try:
                token_count_result = await self.count_tokens({
                    'contents': request.contents,
                    'model': self.model,
                })
                estimated_usage = {
                    'promptTokenCount': token_count_result.total_tokens,
                    'candidatesTokenCount': 0,  # 由于请求失败，没有完成tokens
                    'totalTokenCount': token_count_result.total_tokens,
                }
            except Exception:
                # 如果token计数也失败，提供最小估计
                content_str = json.dumps(request.contents)
                estimated_tokens = max(1, len(content_str) // 4)  # 粗略估计：1 token ≈ 4个字符
                estimated_usage = {
                    'promptTokenCount': estimated_tokens,
                    'candidatesTokenCount': 0,
                    'totalTokenCount': estimated_tokens,
                }

            # 使用估计的使用量记录UI遥测的API错误事件
            error_event = ApiResponseEvent(
                self.model,
                duration_ms,
                user_prompt_id,
                self.config.get_content_generator_config().auth_type if self.config.get_content_generator_config() else None,
                estimated_usage,
                None,
                error_message,
            )
            log_api_response(self.config, error_event)

            # 允许子类为特定场景抑制错误日志记录
            if not self.should_suppress_error_logging(error, request):
                print(f"OpenAI API流式错误: {error_message}")

            # 为流式设置提供有帮助的超时特定错误消息
            if is_timeout_error:
                raise ValueError(
                    f"{error_message}\n\n流式设置超时故障排除:\n" +
                    "- 减少输入长度或复杂度\n" +
                    "- 增加配置中的超时时间: contentGenerator.timeout\n" +
                    "- 检查网络连接和防火墙设置\n" +
                    "- 对于非常长的输入，考虑使用非流式传输模式"
                )

            raise

    async def stream_generator(
        self, 
        stream: Any  # AsyncIterable[OpenAI.Chat.ChatCompletionChunk]
    ) -> AsyncGenerator[GoogleGenerateContentResponse, None]:
        # 为每个新流重置累加器
        self.streaming_tool_calls.clear()

        async for chunk in stream:
            yield self.convert_stream_chunk_to_gemini_format(chunk)

    """
    合并流式响应用于日志记录目的
    """
    def combine_stream_responses_for_logging(
        self, 
        responses: List[GoogleGenerateContentResponse]
    ) -> GoogleGenerateContentResponse:
        if not responses:
            from google.generativeai.types import GenerateContentResponse
            return GenerateContentResponse()

        last_response = responses[-1]

        # 找到最后一个有使用元数据的响应
        final_usage_metadata = None
        for response in reversed(responses):
            if response.usage_metadata:
                final_usage_metadata = response.usage_metadata
                break

        # 组合流中的所有文本内容
        combined_parts: List[Part] = []
        combined_text = ''
        function_calls: List[Part] = []

        for response in responses:
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        combined_text += part.text
                    elif hasattr(part, 'functionCall') and part.functionCall:
                        function_calls.append(part)

        # 如果有组合文本，则添加
        if combined_text:
            combined_parts.append({'text': combined_text})

        # 添加函数调用
        combined_parts.extend(function_calls)

        # 创建组合响应
        from google.generativeai.types import GenerateContentResponse
        combined_response = GenerateContentResponse()
        combined_response.candidates = [
            {
                'content': {
                    'parts': combined_parts,
                    'role': 'model',
                },
                'finishReason': (
                    responses[-1].candidates[0].finishReason if responses[-1].candidates and responses[-1].candidates[0] else 
                    FinishReason.FINISH_REASON_UNSPECIFIED
                ),
                'index': 0,
                'safetyRatings': [],
            },
        ]
        combined_response.response_id = last_response.response_id if hasattr(last_response, 'response_id') else None
        combined_response.create_time = last_response.create_time if hasattr(last_response, 'create_time') else None
        combined_response.model_version = self.model
        combined_response.prompt_feedback = {'safetyRatings': []}
        combined_response.usage_metadata = final_usage_metadata

        return combined_response

    async def count_tokens(
        self, 
        request: CountTokensParameters
    ) -> GoogleCountTokensResponse:
        # 使用tiktoken进行准确的token计数
        content = json.dumps(request.contents)
        total_tokens = 0

        try:
            # 动态导入tiktoken以避免依赖问题
            import importlib.util
            if importlib.util.find_spec('tiktoken') is not None:
                from tiktoken import get_encoding
                encoding = get_encoding('cl100k_base')  # GPT-4编码，但用于qwen估计
                total_tokens = len(encoding.encode(content))
                # 注意：Python中tiktoken没有free()方法
            else:
                raise ImportError("tiktoken not found")
        except Exception as error:
            print(f"加载tiktoken失败，回退到字符近似：{error}")
            # 回退：使用字符计数进行粗略近似
            total_tokens = max(1, len(content) // 4)  # 粗略估计：1 token ≈ 4个字符

        return GoogleCountTokensResponse(total_tokens=total_tokens)

    async def embed_content(
        self, 
        request: EmbedContentParameters
    ) -> GoogleEmbedContentResponse:
        # 从内容中提取文本
        text = ''
        if isinstance(request.contents, list):
            text = ' '.join([
                content if isinstance(content, str) else 
                ' '.join([
                    p if isinstance(p, str) else getattr(p, 'text', '')
                    for p in getattr(content, 'parts', [])
                ]) if hasattr(content, 'parts') else ''
                for content in request.contents
            ])
        elif request.contents:
            if isinstance(request.contents, str):
                text = request.contents
            elif hasattr(request.contents, 'parts'):
                text = ' '.join([
                    p if isinstance(p, str) else getattr(p, 'text', '')
                    for p in getattr(request.contents, 'parts', [])
                ])

        try:
            embedding = await self.client.embeddings.create({
                'model': 'text-embedding-ada-002',  # 默认嵌入模型
                'input': text,
            })

            return GoogleEmbedContentResponse(embeddings=[{
                'values': embedding.data[0].embedding,
            }])
        except Exception as error:
            print(f"OpenAI API嵌入错误: {error}")
            raise ValueError(f"OpenAI API错误: {str(error)}")

    def convert_gemini_parameters_to_openai(
        self, 
        parameters: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if not parameters or not isinstance(parameters, dict):
            return parameters

        # 深拷贝参数以避免修改原始数据
        converted = json.loads(json.dumps(parameters))

        def convert_types(obj: Any) -> Any:
            if not isinstance(obj, dict) or obj is None:
                if isinstance(obj, list):
                    return [convert_types(item) for item in obj]
                return obj

            result: Dict[str, Any] = {}
            for key, value in obj.items():
                if key == 'type' and isinstance(value, str):
                    # 将Gemini类型转换为OpenAI JSON Schema类型
                    lower_value = value.lower()
                    if lower_value == 'integer':
                        result[key] = 'integer'
                    elif lower_value == 'number':
                        result[key] = 'number'
                    else:
                        result[key] = lower_value
                elif key in ['minimum', 'maximum', 'multipleOf']:
                    # 确保数值约束是实际数字，而不是字符串
                    if isinstance(value, str) and value.replace('.', '', 1).isdigit():
                        result[key] = float(value)
                    else:
                        result[key] = value
                elif key in ['minLength', 'maxLength', 'minItems', 'maxItems']:
                    # 确保长度约束是整数，而不是字符串
                    if isinstance(value, str) and value.isdigit():
                        result[key] = int(value)
                    else:
                        result[key] = value
                elif isinstance(value, dict):
                    result[key] = convert_types(value)
                elif isinstance(value, list):
                    result[key] = [convert_types(item) for item in value]
                else:
                    result[key] = value
            return result

        return convert_types(converted) if converted else None

    async def convert_gemini_tools_to_openai(
        self, 
        gemini_tools: ToolListUnion
    ) -> List[Dict[str, Any]]:
        openai_tools: List[Dict[str, Any]] = []

        # 确保gemini_tools是可迭代的
        tools_iterable = gemini_tools if isinstance(gemini_tools, list) else [gemini_tools]

        for tool in tools_iterable:
            actual_tool: Tool

            # 处理CallableTool vs Tool
            if hasattr(tool, 'tool'):
                # 这是一个CallableTool
                actual_tool = await tool.tool()
            else:
                # 这已经是一个Tool
                actual_tool = tool

            if hasattr(actual_tool, 'function_declarations') and actual_tool.function_declarations:
                for func in actual_tool.function_declarations:
                    if hasattr(func, 'name') and func.name and hasattr(func, 'description') and func.description:
                        openai_tools.append({
                            'type': 'function',
                            'function': {
                                'name': func.name,
                                'description': func.description,
                                'parameters': self.convert_gemini_parameters_to_openai(
                                    getattr(func, 'parameters', {}) if hasattr(func, 'parameters') else {}
                                ),
                            },
                        })

        return openai_tools

    def convert_to_openai_format(
        self, 
        request: GenerateContentParameters
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []

        # 处理来自配置的系统指令
        if request.config and hasattr(request.config, 'system_instruction') and request.config.system_instruction:
            system_instruction = request.config.system_instruction
            system_text = ''

            if isinstance(system_instruction, list):
                system_text = '\n'.join([
                    content if isinstance(content, str) else 
                    '\n'.join([
                        p if isinstance(p, str) else getattr(p, 'text', '')
                        for p in getattr(content, 'parts', [])
                    ]) if hasattr(content, 'parts') else ''
                    for content in system_instruction
                ])
            elif isinstance(system_instruction, str):
                system_text = system_instruction
            elif isinstance(system_instruction, dict) and 'parts' in system_instruction:
                system_text = '\n'.join([
                    p if isinstance(p, str) else getattr(p, 'text', '')
                    for p in system_instruction.get('parts', [])
                ])

            if system_text:
                messages.append({
                    'role': 'system',
                    'content': system_text,
                })

        # 处理内容
        if isinstance(request.contents, list):
            for content in request.contents:
                if isinstance(content, str):
                    messages.append({'role': 'user', 'content': content})
                elif hasattr(content, 'role') and hasattr(content, 'parts'):
                    # 检查此内容是否有函数调用或响应
                    function_calls: List[FunctionCall] = []
                    function_responses: List[FunctionResponse] = []
                    text_parts: List[str] = []

                    for part in getattr(content, 'parts', []) or []:
                        if isinstance(part, str):
                            text_parts.append(part)
                        elif hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                        elif hasattr(part, 'functionCall') and part.functionCall:
                            function_calls.append(part.functionCall)
                        elif hasattr(part, 'functionResponse') and part.functionResponse:
                            function_responses.append(part.functionResponse)

                    # 处理函数响应（工具结果）
                    if function_responses:
                        for func_response in function_responses:
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': func_response.id or '',
                                'content': func_response.response if isinstance(func_response.response, str) else json.dumps(func_response.response),
                            })
                    # 处理带有函数调用的模型消息
                    elif getattr(content, 'role', '') == 'model' and function_calls:
                        tool_calls = [{
                            'id': fc.id or f'call_{index}',
                            'type': 'function',
                            'function': {
                                'name': fc.name or '',
                                'arguments': json.dumps(fc.args or {}),
                            },
                        } for index, fc in enumerate(function_calls)]

                        messages.append({
                            'role': 'assistant',
                            'content': '\n'.join(text_parts) or None,
                            'tool_calls': tool_calls,
                        })
                    # 处理常规文本消息
                    else:
                        role = 'assistant' if getattr(content, 'role', '') == 'model' else 'user'
                        text = '\n'.join(text_parts)
                        if text:
                            messages.append({'role': role, 'content': text})
        elif request.contents:
            if isinstance(request.contents, str):
                messages.append({'role': 'user', 'content': request.contents})
            elif hasattr(request.contents, 'role') and hasattr(request.contents, 'parts'):
                content = request.contents
                role = 'assistant' if getattr(content, 'role', '') == 'model' else 'user'
                text = '\n'.join([
                    p if isinstance(p, str) else getattr(p, 'text', '')
                    for p in getattr(content, 'parts', [])
                ])
                messages.append({'role': role, 'content': text})

        # 清理孤立的工具调用并合并连续的助手消息
        cleaned_messages = self.clean_orphaned_tool_calls(messages)
        return self.merge_consecutive_assistant_messages(cleaned_messages)

    """
    清理消息历史中的孤立工具调用，以防止OpenAI API错误
    """
    def clean_orphaned_tool_calls(
        self, 
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        tool_call_ids: Set[str] = set()
        tool_response_ids: Set[str] = set()

        # 第一遍：收集所有工具调用ID和工具响应ID
        for message in messages:
            if message.get('role') == 'assistant' and 'tool_calls' in message and message['tool_calls']:
                for tool_call in message['tool_calls']:
                    if tool_call.get('id'):
                        tool_call_ids.add(tool_call['id'])
            elif message.get('role') == 'tool' and 'tool_call_id' in message and message['tool_call_id']:
                tool_response_ids.add(message['tool_call_id'])

        # 第二遍：过滤掉孤立的消息
        for message in messages:
            if message.get('role') == 'assistant' and 'tool_calls' in message and message['tool_calls']:
                # 过滤掉没有相应响应的工具调用
                valid_tool_calls = [
                    tool_call for tool_call in message['tool_calls']
                    if tool_call.get('id') and tool_call['id'] in tool_response_ids
                ]

                if valid_tool_calls:
                    # 保留消息，但只保留有效的工具调用
                    cleaned_message = message.copy()
                    cleaned_message['tool_calls'] = valid_tool_calls
                    cleaned.append(cleaned_message)
                elif isinstance(message.get('content'), str) and message['content'].strip():
                    # 如果消息有文本内容，则保留消息，但移除工具调用
                    cleaned_message = message.copy()
                    del cleaned_message['tool_calls']
                    cleaned.append(cleaned_message)
                # 如果没有有效的工具调用且没有内容，则完全跳过消息
            elif message.get('role') == 'tool' and 'tool_call_id' in message and message['tool_call_id']:
                # 只保留有相应工具调用的工具响应
                if message['tool_call_id'] in tool_call_ids:
                    cleaned.append(message)
            else:
                # 保留所有其他消息不变
                cleaned.append(message)

        # 最终验证：确保每个带有tool_calls的助手消息都有相应的工具响应
        final_cleaned: List[Dict[str, Any]] = []
        final_tool_call_ids: Set[str] = set()

        # 收集所有剩余的工具调用ID
        for message in cleaned:
            if message.get('role') == 'assistant' and 'tool_calls' in message and message['tool_calls']:
                for tool_call in message['tool_calls']:
                    if tool_call.get('id'):
                        final_tool_call_ids.add(tool_call['id'])

        # 验证所有工具调用都有响应
        final_tool_response_ids: Set[str] = set()
        for message in cleaned:
            if message.get('role') == 'tool' and 'tool_call_id' in message and message['tool_call_id']:
                final_tool_response_ids.add(message['tool_call_id'])

        # 移除任何剩余的孤立工具调用
        for message in cleaned:
            if message.get('role') == 'assistant' and 'tool_calls' in message and message['tool_calls']:
                final_valid_tool_calls = [
                    tool_call for tool_call in message['tool_calls']
                    if tool_call.get('id') and tool_call['id'] in final_tool_response_ids
                ]

                if final_valid_tool_calls:
                    cleaned_message = message.copy()
                    cleaned_message['tool_calls'] = final_valid_tool_calls
                    final_cleaned.append(cleaned_message)
                elif isinstance(message.get('content'), str) and message['content'].strip():
                    cleaned_message = message.copy()
                    del cleaned_message['tool_calls']
                    final_cleaned.append(cleaned_message)
            else:
                final_cleaned.append(message)

        return final_cleaned

    """
    合并连续的助手消息以组合分割的文本和工具调用
    """
    def merge_consecutive_assistant_messages(
        self, 
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []

        for message in messages:
            if message.get('role') == 'assistant' and merged:
                last_message = merged[-1]

                # 如果最后一条消息也是助手消息，则合并它们
                if last_message.get('role') == 'assistant':
                    # 组合内容
                    combined_content = ''.join([
                        last_message.get('content', '') if isinstance(last_message.get('content'), str) else '',
                        message.get('content', '') if isinstance(message.get('content'), str) else '',
                    ])

                    # 组合工具调用
                    last_tool_calls = last_message.get('tool_calls', [])
                    current_tool_calls = message.get('tool_calls', [])
                    combined_tool_calls = [*last_tool_calls, *current_tool_calls]

                    # 更新最后一条消息的组合数据
                    if isinstance(last_message.get('content'), str) or message.get('content') is None:
                        last_message['content'] = combined_content or None
                    if combined_tool_calls:
                        last_message['tool_calls'] = combined_tool_calls
                    elif 'tool_calls' in last_message:
                        del last_message['tool_calls']

                    continue  # 跳过添加当前消息，因为它已经被合并

            # 如果不需要合并，则按原样添加消息
            merged.append(message)

        return merged

    def convert_to_gemini_format(
        self, 
        openai_response: Any  # OpenAI.Chat.ChatCompletion
    ) -> GoogleGenerateContentResponse:
        choice = openai_response.choices[0] if openai_response.choices else None
        if not choice:
            from google.generativeai.types import GenerateContentResponse
            return GenerateContentResponse()

        response = GoogleGenerateContentResponse()

        parts: List[Part] = []

        # 处理文本内容
        if hasattr(choice.message, 'content') and choice.message.content:
            parts.append({'text': choice.message.content})

        # 处理工具调用
        if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
            for tool_call in choice.message.tool_calls:
                if hasattr(tool_call, 'function') and tool_call.function:
                    args: Dict[str, Any] = {}
                    if hasattr(tool_call.function, 'arguments') and tool_call.function.arguments:
                        try:
                            args = json.loads(tool_call.function.arguments)
                        except Exception as error:
                            print(f"解析函数参数失败: {error}")
                            args = {}

                    parts.append({
                        'functionCall': {
                            'id': tool_call.id if hasattr(tool_call, 'id') else None,
                            'name': tool_call.function.name if hasattr(tool_call.function, 'name') else '',
                            'args': args,
                        },
                    })

        response.response_id = openai_response.id if hasattr(openai_response, 'id') else None
        response.create_time = str(openai_response.created) if hasattr(openai_response, 'created') else str(int(datetime.now().timestamp() * 1000))

        response.candidates = [
            {
                'content': {
                    'parts': parts,
                    'role': 'model',
                },
                'finishReason': self.map_finish_reason(choice.finish_reason or 'stop'),
                'index': 0,
                'safetyRatings': [],
            },
        ]

        response.model_version = self.model
        response.prompt_feedback = {'safetyRatings': []}

        # 如果可用，添加使用元数据
        if hasattr(openai_response, 'usage') and openai_response.usage:
            usage = openai_response.usage

            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            cached_tokens = getattr(getattr(usage, 'prompt_tokens_details', None), 'cached_tokens', 0) if hasattr(usage, 'prompt_tokens_details') else 0

            # 如果我们只有总tokens但没有细分，估计分割
            # 对于大多数对话，输入通常是~70%，输出是~30%
            final_prompt_tokens = prompt_tokens
            final_completion_tokens = completion_tokens

            if total_tokens > 0 and prompt_tokens == 0 and completion_tokens == 0:
                # 估计：假设70%输入，30%输出
                final_prompt_tokens = round(total_tokens * 0.7)
                final_completion_tokens = round(total_tokens * 0.3)

            response.usage_metadata = {
                'promptTokenCount': final_prompt_tokens,
                'candidatesTokenCount': final_completion_tokens,
                'totalTokenCount': total_tokens,
                'cachedContentTokenCount': cached_tokens,
            }

        return response

    def convert_stream_chunk_to_gemini_format(
        self, 
        chunk: Any  # OpenAI.Chat.ChatCompletionChunk
    ) -> GoogleGenerateContentResponse:
        choice = chunk.choices[0] if hasattr(chunk, 'choices') and chunk.choices else None
        response = GoogleGenerateContentResponse()

        if choice:
            parts: List[Part] = []

            # 处理文本内容
            if hasattr(choice, 'delta') and hasattr(choice.delta, 'content') and choice.delta.content:
                parts.append({'text': choice.delta.content})

            # 处理工具调用 - 仅在流式传输期间累积，在完成时发出
            if hasattr(choice.delta, 'tool_calls') and choice.delta.tool_calls:
                for tool_call in choice.delta.tool_calls:
                    index = getattr(tool_call, 'index', 0)

                    # 获取或创建此索引的工具调用累加器
                    if index not in self.streaming_tool_calls:
                        self.streaming_tool_calls[index] = {'arguments': ''}
                    accumulated_call = self.streaming_tool_calls[index]

                    # 更新累积的数据
                    if hasattr(tool_call, 'id') and tool_call.id:
                        accumulated_call['id'] = tool_call.id
                    if hasattr(tool_call, 'function') and hasattr(tool_call.function, 'name') and tool_call.function.name:
                        accumulated_call['name'] = tool_call.function.name
                    if hasattr(tool_call, 'function') and hasattr(tool_call.function, 'arguments') and tool_call.function.arguments:
                        accumulated_call['arguments'] += tool_call.function.arguments

            # 仅在流式传输完成时发出函数调用（存在finish_reason）
            if hasattr(choice, 'finish_reason') and choice.finish_reason:
                for accumulated_call in self.streaming_tool_calls.values():
                    # TODO: 一旦我们有一种从VLLM解析器生成tool_call_id的方法，就添加回id。
                    if accumulated_call.get('name'):
                        args: Dict[str, Any] = {}
                        if accumulated_call.get('arguments'):
                            try:
                                args = json.loads(accumulated_call['arguments'])
                            except Exception as error:
                                print(f"解析最终工具调用参数失败: {error}")

                        parts.append({
                            'functionCall': {
                                'id': accumulated_call.get('id'),
                                'name': accumulated_call['name'],
                                'args': args,
                            },
                        })
                # 清除所有累积的工具调用
                self.streaming_tool_calls.clear()

            response.candidates = [
                {
                    'content': {
                        'parts': parts,
                        'role': 'model',
                    },
                    'finishReason': self.map_finish_reason(choice.finish_reason) if hasattr(choice, 'finish_reason') and choice.finish_reason else FinishReason.FINISH_REASON_UNSPECIFIED,
                    'index': 0,
                    'safetyRatings': [],
                },
            ]
        else:
            response.candidates = []

        response.response_id = chunk.id if hasattr(chunk, 'id') else None
        response.create_time = str(chunk.created) if hasattr(chunk, 'created') else str(int(datetime.now().timestamp() * 1000))

        response.model_version = self.model
        response.prompt_feedback = {'safetyRatings': []}

        # 如果块中可用，添加使用元数据
        if hasattr(chunk, 'usage') and chunk.usage:
            usage = chunk.usage

            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            cached_tokens = getattr(getattr(usage, 'prompt_tokens_details', None), 'cached_tokens', 0) if hasattr(usage, 'prompt_tokens_details') else 0

            # 如果我们只有总tokens但没有细分，估计分割
            # 对于大多数对话，输入通常是~70%，输出是~30%
            final_prompt_tokens = prompt_tokens
            final_completion_tokens = completion_tokens

            if total_tokens > 0 and prompt_tokens == 0 and completion_tokens == 0:
                # 估计：假设70%输入，30%输出
                final_prompt_tokens = round(total_tokens * 0.7)
                final_completion_tokens = round(total_tokens * 0.3)

            response.usage_metadata = {
                'promptTokenCount': final_prompt_tokens,
                'candidatesTokenCount': final_completion_tokens,
                'totalTokenCount': total_tokens,
                'cachedContentTokenCount': cached_tokens,
            }

        return response

    """
    构建采样参数，优先级明确：
    1. 配置级采样参数（最高优先级）
    2. 请求级参数（中等优先级）
    3. 默认值（最低优先级）
    """
    def build_sampling_parameters(
        self, 
        request: GenerateContentParameters
    ) -> Dict[str, Any]:
        config_sampling_params = None
        if self.config.get_content_generator_config():
            config_sampling_params = self.config.get_content_generator_config().sampling_params

        params = {
            # 温度：配置 > 请求 > 默认
            'temperature': (
                config_sampling_params['temperature'] if config_sampling_params and 'temperature' in config_sampling_params else
                request.config.temperature if request.config and hasattr(request.config, 'temperature') else
                0.0
            ),

            # Top-p：配置 > 请求 > 默认
            'top_p': (
                config_sampling_params['top_p'] if config_sampling_params and 'top_p' in config_sampling_params else
                request.config.topP if request.config and hasattr(request.config, 'topP') else
                1.0
            ),
        }

        # 最大tokens：配置 > 请求 > 未定义
        if config_sampling_params and 'max_tokens' in config_sampling_params:
            params['max_tokens'] = config_sampling_params['max_tokens']
        elif request.config and hasattr(request.config, 'maxOutputTokens'):
            params['max_tokens'] = request.config.maxOutputTokens

        # Top-k：仅配置（请求中不可用）
        if config_sampling_params and 'top_k' in config_sampling_params:
            params['top_k'] = config_sampling_params['top_k']

        # 重复惩罚：仅配置
        if config_sampling_params and 'repetition_penalty' in config_sampling_params:
            params['repetition_penalty'] = config_sampling_params['repetition_penalty']

        # 存在惩罚：仅配置
        if config_sampling_params and 'presence_penalty' in config_sampling_params:
            params['presence_penalty'] = config_sampling_params['presence_penalty']

        # 频率惩罚：仅配置
        if config_sampling_params and 'frequency_penalty' in config_sampling_params:
            params['frequency_penalty'] = config_sampling_params['frequency_penalty']

        return params

    def map_finish_reason(self, openai_reason: Optional[str]) -> FinishReason:
        if not openai_reason:
            return FinishReason.FINISH_REASON_UNSPECIFIED
        mapping: Dict[str, FinishReason] = {
            'stop': FinishReason.STOP,
            'length': FinishReason.MAX_TOKENS,
            'content_filter': FinishReason.SAFETY,
            'function_call': FinishReason.STOP,
            'tool_calls': FinishReason.STOP,
        }
        return mapping.get(openai_reason, FinishReason.FINISH_REASON_UNSPECIFIED)

    """
    将Gemini请求格式转换为OpenAI聊天完成格式用于日志记录
    """
    async def convert_gemini_request_to_openai(
        self, 
        request: GenerateContentParameters
    ) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = []

        # 处理系统指令
        if request.config and hasattr(request.config, 'system_instruction') and request.config.system_instruction:
            system_instruction = request.config.system_instruction
            system_text = ''

            if isinstance(system_instruction, list):
                system_text = '\n'.join([
                    content if isinstance(content, str) else 
                    '\n'.join([
                        p if isinstance(p, str) else getattr(p, 'text', '')
                        for p in getattr(content, 'parts', [])
                    ]) if hasattr(content, 'parts') else ''
                    for content in system_instruction
                ])
            elif isinstance(system_instruction, str):
                system_text = system_instruction
            elif isinstance(system_instruction, dict) and 'parts' in system_instruction:
                system_text = '\n'.join([
                    p if isinstance(p, str) else getattr(p, 'text', '')
                    for p in system_instruction.get('parts', [])
                ])

            if system_text:
                messages.append({
                    'role': 'system',
                    'content': system_text,
                })

        # 处理内容
        if isinstance(request.contents, list):
            for content in request.contents:
                if isinstance(content, str):
                    messages.append({'role': 'user', 'content': content})
                elif hasattr(content, 'role') and hasattr(content, 'parts'):
                    function_calls: List[FunctionCall] = []
                    function_responses: List[FunctionResponse] = []
                    text_parts: List[str] = []

                    for part in getattr(content, 'parts', []) or []:
                        if isinstance(part, str):
                            text_parts.append(part)
                        elif hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                        elif hasattr(part, 'functionCall') and part.functionCall:
                            function_calls.append(part.functionCall)
                        elif hasattr(part, 'functionResponse') and part.functionResponse:
                            function_responses.append(part.functionResponse)

                    # 处理函数响应（工具结果）
                    if function_responses:
                        for func_response in function_responses:
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': func_response.id or '',
                                'content': func_response.response if isinstance(func_response.response, str) else json.dumps(func_response.response),
                            })
                    # 处理带有函数调用的模型消息
                    elif getattr(content, 'role', '') == 'model' and function_calls:
                        tool_calls = [{
                            'id': fc.id or f'call_{index}',
                            'type': 'function',
                            'function': {
                                'name': fc.name or '',
                                'arguments': json.dumps(fc.args or {}),
                            },
                        } for index, fc in enumerate(function_calls)]

                        messages.append({
                            'role': 'assistant',
                            'content': '\n'.join(text_parts) or None,
                            'tool_calls': tool_calls,
                        })
                    # 处理常规文本消息
                    else:
                        role = 'assistant' if getattr(content, 'role', '') == 'model' else 'user'
                        text = '\n'.join(text_parts)
                        if text:
                            messages.append({'role': role, 'content': text})
        elif request.contents:
            if isinstance(request.contents, str):
                messages.append({'role': 'user', 'content': request.contents})
            elif hasattr(request.contents, 'role') and hasattr(request.contents, 'parts'):
                content = request.contents
                role = 'assistant' if getattr(content, 'role', '') == 'model' else 'user'
                text = '\n'.join([
                    p if isinstance(p, str) else getattr(p, 'text', '')
                    for p in getattr(content, 'parts', [])
                ])
                messages.append({'role': role, 'content': text})

        # 清理孤立的工具调用并合并连续的助手消息
        cleaned_messages = self.clean_orphaned_tool_calls_for_logging(messages)
        merged_messages = self.merge_consecutive_assistant_messages_for_logging(cleaned_messages)

        openai_request: Dict[str, Any] = {
            'model': self.model,
            'messages': merged_messages,
        }

        # 使用与实际API调用相同的逻辑添加采样参数
        sampling_params = self.build_sampling_parameters(request)
        openai_request.update(sampling_params)

        # 如果存在，转换工具
        if request.config and hasattr(request.config, 'tools') and request.config.tools:
            openai_request['tools'] = await self.convert_gemini_tools_to_openai(
                request.config.tools
            )

        return openai_request

    """
    清理用于日志记录的孤立工具调用
    """
    def clean_orphaned_tool_calls_for_logging(
        self, 
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        tool_call_ids: Set[str] = set()
        tool_response_ids: Set[str] = set()

        # 第一遍：收集所有工具调用ID和工具响应ID
        for message in messages:
            if message.get('role') == 'assistant' and message.get('tool_calls'):
                for tool_call in message['tool_calls']:
                    if tool_call.get('id'):
                        tool_call_ids.add(tool_call['id'])
            elif message.get('role') == 'tool' and message.get('tool_call_id'):
                tool_response_ids.add(message['tool_call_id'])

        # 第二遍：过滤掉孤立的消息
        for message in messages:
            if message.get('role') == 'assistant' and message.get('tool_calls'):
                # 过滤掉没有相应响应的工具调用
                valid_tool_calls = [
                    tool_call for tool_call in message['tool_calls']
                    if tool_call.get('id') and tool_call['id'] in tool_response_ids
                ]

                if valid_tool_calls:
                    # 保留消息，但只保留有效的工具调用
                    cleaned_message = message.copy()
                    cleaned_message['tool_calls'] = valid_tool_calls
                    cleaned.append(cleaned_message)
                elif isinstance(message.get('content'), str) and message['content'].strip():
                    # 如果消息有文本内容，则保留消息，但移除工具调用
                    cleaned_message = message.copy()
                    del cleaned_message['tool_calls']
                    cleaned.append(cleaned_message)
                # 如果没有有效的工具调用且没有内容，则完全跳过消息
            elif message.get('role') == 'tool' and message.get('tool_call_id'):
                # 只保留有相应工具调用的工具响应
                if message['tool_call_id'] in tool_call_ids:
                    cleaned.append(message)
            else:
                # 保留所有其他消息不变
                cleaned.append(message)

        # 最终验证：确保每个带有tool_calls的助手消息都有相应的工具响应
        final_cleaned: List[Dict[str, Any]] = []
        final_tool_call_ids: Set[str] = set()

        # 收集所有剩余的工具调用ID
        for message in cleaned:
            if message.get('role') == 'assistant' and message.get('tool_calls'):
                for tool_call in message['tool_calls']:
                    if tool_call.get('id'):
                        final_tool_call_ids.add(tool_call['id'])

        # 验证所有工具调用都有响应
        final_tool_response_ids: Set[str] = set()
        for message in cleaned:
            if message.get('role') == 'tool' and message.get('tool_call_id'):
                final_tool_response_ids.add(message['tool_call_id'])

        # 移除任何剩余的孤立工具调用
        for message in cleaned:
            if message.get('role') == 'assistant' and message.get('tool_calls'):
                final_valid_tool_calls = [
                    tool_call for tool_call in message['tool_calls']
                    if tool_call.get('id') and tool_call['id'] in final_tool_response_ids
                ]

                if final_valid_tool_calls:
                    cleaned_message = message.copy()
                    cleaned_message['tool_calls'] = final_valid_tool_calls
                    final_cleaned.append(cleaned_message)
                elif isinstance(message.get('content'), str) and message['content'].strip():
                    cleaned_message = message.copy()
                    del cleaned_message['tool_calls']
                    final_cleaned.append(cleaned_message)
            else:
                final_cleaned.append(message)

        return final_cleaned

    """
    合并连续的助手消息以组合分割的文本和工具调用用于日志记录
    """
    def merge_consecutive_assistant_messages_for_logging(
        self, 
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []

        for message in messages:
            if message.get('role') == 'assistant' and merged:
                last_message = merged[-1]

                # 如果最后一条消息也是助手消息，则合并它们
                if last_message.get('role') == 'assistant':
                    # 组合内容
                    combined_content = ''.join([
                        last_message.get('content', '') if isinstance(last_message.get('content'), str) else '',
                        message.get('content', '') if isinstance(message.get('content'), str) else '',
                    ])

                    # 组合工具调用
                    combined_tool_calls = [
                        *last_message.get('tool_calls', []),
                        *message.get('tool_calls', []),
                    ]

                    # 更新最后一条消息的组合数据
                    last_message['content'] = combined_content or None
                    if combined_tool_calls:
                        last_message['tool_calls'] = combined_tool_calls
                    elif 'tool_calls' in last_message:
                        del last_message['tool_calls']

                    continue  # 跳过添加当前消息，因为它已经被合并

            # 如果不需要合并，则按原样添加消息
            merged.append(message)

        return merged

    """
    将Gemini响应格式转换为OpenAI聊天完成格式用于日志记录
    """
    def convert_gemini_response_to_openai(
        self, 
        response: GoogleGenerateContentResponse
    ) -> Dict[str, Any]:
        candidate = response.candidates[0] if response.candidates else None
        content = candidate.content if candidate and hasattr(candidate, 'content') else None

        message_content: Optional[str] = None
        tool_calls: List[Dict[str, Any]] = []

        if content and hasattr(content, 'parts') and content.parts:
            text_parts: List[str] = []

            for part in content.parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
                elif hasattr(part, 'functionCall') and part.functionCall:
                    tool_calls.append({
                        'id': part.functionCall.id or f'call_{len(tool_calls)}',
                        'type': 'function',
                        'function': {
                            'name': part.functionCall.name or '',
                            'arguments': json.dumps(part.functionCall.args or {}),
                        },
                    })

            message_content = ''.join(text_parts)

        choice: Dict[str, Any] = {
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': message_content,
            },
            'finish_reason': self.map_gemini_finish_reason_to_openai(
                candidate.finishReason if candidate and hasattr(candidate, 'finishReason') else None
            ),
        }

        if tool_calls:
            choice['message']['tool_calls'] = tool_calls

        openai_response: Dict[str, Any] = {
            'id': response.response_id or f'chatcmpl-{int(datetime.now().timestamp())}',
            'object': 'chat.completion',
            'created': int(response.create_time) if hasattr(response, 'create_time') and response.create_time else int(datetime.now().timestamp()),
            'model': self.model,
            'choices': [choice],
        }

        # 如果可用，添加使用元数据
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            openai_response['usage'] = {
                'prompt_tokens': response.usage_metadata.get('promptTokenCount', 0),
                'completion_tokens': response.usage_metadata.get('candidatesTokenCount', 0),
                'total_tokens': response.usage_metadata.get('totalTokenCount', 0),
            }

            if response.usage_metadata.get('cachedContentTokenCount'):
                if 'prompt_tokens_details' not in openai_response['usage']:
                    openai_response['usage']['prompt_tokens_details'] = {}
                openai_response['usage']['prompt_tokens_details']['cached_tokens'] = response.usage_metadata['cachedContentTokenCount']

        return openai_response

    """
    将Gemini完成原因映射到OpenAI完成原因
    """
    def map_gemini_finish_reason_to_openai(self, gemini_reason: Any) -> str:
        if not gemini_reason:
            return 'stop'

        # 检查Gemini完成原因的字符串表示或枚举值
        reason_str = str(gemini_reason).upper()
        reason_value = gemini_reason if isinstance(gemini_reason, int) else None

        if reason_str == 'STOP' or reason_value == 1:  # FinishReason.STOP
            return 'stop'
        elif reason_str == 'MAX_TOKENS' or reason_value == 2:  # FinishReason.MAX_TOKENS
            return 'length'
        elif reason_str == 'SAFETY' or reason_value == 3:  # FinishReason.SAFETY
            return 'content_filter'
        elif reason_str == 'RECITATION' or reason_value == 4:  # FinishReason.RECITATION
            return 'content_filter'
        elif reason_str == 'OTHER' or reason_value == 5:  # FinishReason.OTHER
            return 'stop'
        else:
            return 'stop'