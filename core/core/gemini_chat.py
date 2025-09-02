import json
import time
from typing import Optional, List, Dict, Any, AsyncGenerator, Union
from google.genai.types import GenerateContentResponse,Content,GenerateContentConfig,Part,Tool,GenerateContentResponseUsageMetadata
from turn import PartListUnion
from content_generator import ContentGenerator,AuthType
from ..utils.retry import retry_with_backoff
from ..utils.message_inspectors import is_function_response
from ..config.config import Config
from ..config.models import DEFAULT_GEMINI_FLASH_MODEL
from ..telemetry.loggers import log_api_error,log_api_request,log_api_response
from ..telemetry.types import ApiErrorEvent,ApiRequestEvent,ApiResponseEvent

def create_part_from_text(text: str) -> Part:
    return {'text': text}

def _is_part(obj: Any) -> bool:
    if isinstance(obj, dict) and obj is not None:
        # 检查对象是否包含Part类型的关键属性
        return any(key in obj for key in [
            'fileData', 'text', 'functionCall', 'functionResponse',
            'inlineData', 'videoMetadata', 'codeExecutionResult', 'executableCode'
        ])
    return False

def _to_parts(partOrString: Union[PartListUnion, str]) -> List[Part]:
    parts: List[Part] = []
    
    if isinstance(partOrString, str):
        parts.append(createPartFromText(partOrString))
    elif _is_part(partOrString):
        parts.append(partOrString)
    elif isinstance(partOrString, list):
        if len(partOrString) == 0:
            raise ValueError('partOrString cannot be an empty array')
        for part in partOrString:
            if isinstance(part, str):
                parts.append(createPartFromText(part))
            elif _is_part(part):
                parts.append(part)
            else:
                raise ValueError('element in PartUnion must be a Part object or string')
    else:
        raise ValueError('partOrString must be a Part object, string, or array')
    
    return parts

def createUserContent(parts: List[Part]) -> Content:
    return {
        'role': 'user',
        'parts': _to_parts(parts)
    }

class SendMessageParameters:
    """SendMessageParameters 接口用于定义发送消息的参数
    """
    def __init__(self, message: PartListUnion, config: Optional[GenerateContentConfig] = None):
        self.message = message
        self.config = config


"""Returns true if the response is valid, false otherwise."""
def is_valid_response(response: GenerateContentResponse) -> bool:
    if response.get("candidates") is None or len(response["candidates"]) == 0:
        return False
    content = response["candidates"][0].get("content")
    if content is None:
        return False
    return is_valid_content(content)

def is_valid_content(content: Content) -> bool:
    if content.get("parts") is None or len(content["parts"]) == 0:
        return False
    for part in content["parts"]:
        if part is None or len(part) == 0:
            return False
        if not part.get("thought") and part.get("text") is not None and part["text"] == "":
            return False
    return True

"""Validates the history contains the correct roles.

Raises:
    ValueError: If the history does not start with a user turn or contains an invalid role.
"""
def validate_history(history: List[Content]) -> None:
    for content in history:
        if content.get("role") not in ["user", "model"]:
            raise ValueError(f"Role must be user or model, but got {content.get('role')}.")

"""Extracts the curated (valid) history from a comprehensive history.

The model may sometimes generate invalid or empty contents(e.g., due to safety
filters or recitation). Extracting valid turns from the history
ensures that subsequent requests could be accepted by the model.
"""
def extract_curated_history(comprehensiveHistory: List[Content]) -> List[Content]:
    if comprehensiveHistory is None or len(comprehensiveHistory) == 0:
        return []
    curatedHistory: List[Content] = []
    length = len(comprehensiveHistory)
    i = 0
    while i < length:
        if comprehensiveHistory[i].get("role") == "user":
            curatedHistory.append(comprehensiveHistory[i])
            i += 1
        else:
            modelOutput: List[Content] = []
            isValid = True
            while i < length and comprehensiveHistory[i].get("role") == "model":
                modelOutput.append(comprehensiveHistory[i])
                if isValid and not is_valid_content(comprehensiveHistory[i]):
                    isValid = False
                i += 1
            if isValid:
                curatedHistory.extend(modelOutput)
            else:
                # Remove the last user input when model content is invalid.
                if curatedHistory:
                    curatedHistory.pop()
    return curatedHistory

"""Chat session that enables sending messages to the model with previous
conversation context.

The session maintains all the turns between user and model.
"""
class GeminiChat:
    def __init__(self, 
                 config: Config, 
                 contentGenerator: ContentGenerator, 
                 generationConfig: GenerateContentConfig = None, 
                 history: List[Content] = None):
        # A promise to represent the current state of the message being sent to the model.
        self.sendPromise = None  
        self.config = config
        self.contentGenerator = contentGenerator
        self.generationConfig = generationConfig or {}
        self.history = history or []
        validate_history(self.history)
    
    def __get_request_text_from_contents(self, contents: List[Content]) -> str:
        return json.dumps(contents)
    
    async def __log_api_request(self, 
                           contents: List[Content], 
                           model: str, 
                           prompt_id: str) -> None:
        requestText = self.__get_request_text_from_contents(contents)
        log_api_request(
            self.config,
            ApiRequestEvent(model=model, prompt_id=prompt_id, request_text=requestText)
        )
    
    async def __log_api_response(self, 
                            durationMs: int, 
                            prompt_id: str, 
                            usageMetadata: Optional[GenerateContentResponseUsageMetadata] = None, 
                            responseText: Optional[str] = None) -> None:
        log_api_response(
            self.config,
            ApiResponseEvent(
                model=self.config.get_model(),
                duration=durationMs,
                prompt_id=prompt_id,
                auth_type=self.config.getContentGeneratorConfig().get("authType"),
                usage_metadata=usageMetadata,
                response_text=responseText,))
    
    def __logApiError(self, 
                    durationMs: int, 
                    error: Exception, 
                    prompt_id: str) -> None:
        errorMessage = str(error) if isinstance(error, Exception) else str(error)
        errorType = error.__class__.__name__ if isinstance(error, Exception) else "unknown"

        log_api_error(
            self.config,
            ApiErrorEvent(
                model=self.config.get_model(),
                error_message=errorMessage,
                duration=durationMs,
                prompt_id=prompt_id,
                auth_type=self.config.getContentGeneratorConfig().get("authType"),
                error_type=errorType,
            )
        )
    
    """Handles falling back to Flash model when persistent 429 errors occur for OAuth users.
    Uses a fallback handler if provided by the config; otherwise, returns null."""
    async def __handle_flash_fallback(
            self, 
            authType: Optional[str] = None, 
            error: Optional[Exception] = None) -> Optional[str]:
        # Handle different auth types
        if authType == AuthType.QWEN_OAUTH:
            return await self.__handle_qwen_oauth_error(error)

        # Only handle fallback for OAuth users
        if authType != AuthType.LOGIN_WITH_GOOGLE:
            return None

        currentModel = self.config.get_model()
        fallbackModel = DEFAULT_GEMINI_FLASH_MODEL

        # Don't fallback if already using Flash model
        if currentModel == fallbackModel:
            return None

        # Check if config has a fallback handler (set by CLI package)
        fallbackHandler = self.config.flashFallbackHandler
        if callable(fallbackHandler):
            try:
                accepted = await fallbackHandler(
                    currentModel, 
                    fallbackModel, 
                    error
                )
                if accepted is not False and accepted is not None:
                    self.config.setModel(fallbackModel)
                    self.config.setFallbackMode(True)
                    return fallbackModel
                # Check if the model was switched manually in the handler
                if self.config.get_model() == fallbackModel:
                    return None  # Model was switched but don't continue with current prompt
            except Exception as e:
                print(f"Flash fallback handler failed: {e}")

        return None
    
    """Sends a message to the model and returns the response.

    This method will wait for the previous message to be processed before
sending the next message.

    Args:
        params: Parameters for sending messages within a chat session.
        prompt_id: Unique identifier for the prompt.

    Returns:
        The model's response.
    """
    async def send_message(
            self, 
            params: SendMessageParameters, 
            prompt_id: str) -> GenerateContentResponse:
        # Python中不需要等待Promise，异步操作由async/await处理
        userContent = createUserContent(params.get("message"))
        requestContents = self.get_history(True) + [userContent]

        await self.__log_api_request(requestContents, self.config.get_model(), prompt_id)

        startTime = int(time.time() * 1000)  # 转换为毫秒
        response = None

        try:
            async def apiCall():
                modelToUse = self.config.get_model() or DEFAULT_GEMINI_FLASH_MODEL

                # Prevent Flash model calls immediately after quota error
                if (
                    self.config.get_quota_error_occurred() and
                    modelToUse == DEFAULT_GEMINI_FLASH_MODEL
                ):
                    raise Exception(
                        'Please submit a new query to continue with the Flash model.'
                    )

                return await self.contentGenerator.generate_content(
                    {
                        "model": modelToUse,
                        "contents": requestContents,
                        "config": {**self.generationConfig, **params.get("config", {})}
                    },
                    prompt_id,
                )

            response = await retry_with_backoff(apiCall, {
                "shouldRetry": lambda error: (
                    error and hasattr(error, 'message') and (
                        '429' in str(error.message) or 
                        any(str(e) in str(error.message) for e in range(500, 600))
                    )
                ),
                "onPersistent429": lambda authType=None, error=None: self.__handle_flash_fallback(authType, error),
                "authType": self.config.getContentGeneratorConfig().get("authType"),
            })
            durationMs = int(time.time() * 1000) - startTime
            await self.__log_api_response(
                durationMs,
                prompt_id,
                response.get("usageMetadata"),
                json.dumps(response)
            )

            # 处理历史记录更新
            outputContent = response.get("candidates", [{}])[0].get("content")
            # Because the AFC input contains the entire curated chat history in
            # addition to the new user input, we need to truncate the AFC history
            # to deduplicate the existing chat history.
            fullAutomaticFunctionCallingHistory = response.get("automaticFunctionCallingHistory")
            index = len(self.get_history(True))
            automaticFunctionCallingHistory: List[Content] = []
            if fullAutomaticFunctionCallingHistory is not None:
                automaticFunctionCallingHistory = fullAutomaticFunctionCallingHistory[index:] or []
            modelOutput = [outputContent] if outputContent else []
            
            try:
                self.__record_history(
                    userContent,
                    modelOutput,
                    automaticFunctionCallingHistory,
                )
            except Exception:
                # Resets sendPromise to avoid subsequent calls failing
                pass
                
            return response
        except Exception as error:
            durationMs = int(time.time() * 1000) - startTime
            self.__logApiError(durationMs, error, prompt_id)
            raise error
    
    """Sends a message to the model and returns the response in chunks.

    This method will wait for the previous message to be processed before
sending the next message.

    Args:
        params: Parameters for sending the message.
        prompt_id: Unique identifier for the prompt.

    Returns:
        An async generator yielding the model's response chunks.
    """
    async def send_message_stream(
            self, 
            params: SendMessageParameters, 
            prompt_id: str) -> AsyncGenerator[GenerateContentResponse, None]:
        # Python中不需要等待Promise，异步操作由async/await处理
        userContent = createUserContent(params.get("message"))
        requestContents = self.get_history(True) + [userContent]
        await self._logApiRequest(requestContents, self.config.get_model(), prompt_id)

        startTime = int(time.time() * 1000)  # 转换为毫秒

        try:
            async def apiCall():
                modelToUse = self.config.get_model()

                # Prevent Flash model calls immediately after quota error
                if (
                    self.config.get_quota_error_occurred() and
                    modelToUse == DEFAULT_GEMINI_FLASH_MODEL
                ):
                    raise Exception(
                        'Please submit a new query to continue with the Flash model.'
                    )

                return await self.contentGenerator.generate_content_stream(
                    {
                        "model": modelToUse,
                        "contents": requestContents,
                        "config": {**self.generationConfig, **params.get("config", {})}
                    },
                    prompt_id,
                )

            # Note: Retrying streams can be complex. If generateContentStream itself doesn't handle retries
            # for transient issues internally before yielding the async generator, this retry will re-initiate
            # the stream. For simple 429/500 errors on initial call, this is fine.
            # If errors occur mid-stream, this setup won't resume the stream; it will restart it.
            streamResponse = await retry_with_backoff(apiCall, {
                "shouldRetry": lambda error: (
                    error and hasattr(error, 'message') and (
                        '429' in str(error.message) or 
                        any(str(e) in str(error.message) for e in range(500, 600))
                    )
                ),
                "onPersistent429": lambda authType=None, error=None: self.__handle_flash_fallback(authType, error),
                "authType": self.config.get_content_generator_config().get("authType"),
            })

            # 处理流式响应
            async for chunk in self.__process_stream_response(
                streamResponse, 
                userContent, 
                startTime, 
                prompt_id
            ):
                yield chunk
                
        except Exception as error:
            durationMs = int(time.time() * 1000) - startTime
            self.__logApiError(durationMs, error, prompt_id)
            raise error
    
    """Returns the chat history.

    The history is a list of contents alternating between user and model.

    There are two types of history:
    - The `curated history` contains only the valid turns between user and
    model, which will be included in the subsequent requests sent to the model.
    - The `comprehensive history` contains all turns, including invalid or
    empty model outputs, providing a complete record of the history.

    The history is updated after receiving the response from the model,
    for streaming response, it means receiving the last chunk of the response.

    The `comprehensive history` is returned by default. To get the `curated
    history`, set the `curated` parameter to `true`.

    Args:
        curated: Whether to return the curated history or the comprehensive history.

    Returns:
        History contents alternating between user and model for the entire chat session.
    """
    def get_history(self, curated: bool = False) -> List[Content]:
        history = extract_curated_history(self.history) if curated else self.history
        # Deep copy the history to avoid mutating the history outside of the chat session.
        # 在Python中，我们使用json序列化/反序列化来实现深拷贝
        return json.loads(json.dumps(history))
    
    """Clears the chat history."""
    def clear_history(self) -> None:
        self.history = []
    
    """Adds a new entry to the chat history.

    Args:
        content: The content to add to the history.
    """
    def add_history(self, content: Content) -> None:
        self.history.append(content)
        
    def set_history(self, history: List[Content]) -> None:
        self.history = history
    
    def set_tools(self, tools: List[Tool]) -> None:
        self.generationConfig["tools"] = tools
    
    def get_final_usage_metadata(
            self, 
            chunks: List[GenerateContentResponse]) -> Optional[GenerateContentResponseUsageMetadata]:
        # 从后往前查找带有metadata的chunk
        for chunk in reversed(chunks):
            if chunk.get("usageMetadata"):
                return chunk["usageMetadata"]
        return None
    
    async def __process_stream_response(
            self, 
            streamResponse: AsyncGenerator[GenerateContentResponse, None],
            inputContent: Content,
            startTime: int,
            prompt_id: str
    ) -> AsyncGenerator[GenerateContentResponse, None]:
        outputContent: List[Content] = []
        chunks: List[GenerateContentResponse] = []
        errorOccurred = False

        try:
            async for chunk in streamResponse:
                if is_valid_response(chunk):
                    chunks.append(chunk)
                    content = chunk.get("candidates", [{}])[0].get("content")
                    if content is not None:
                        if self.__is_thought_content(content):
                            yield chunk
                            continue
                        outputContent.append(content)
                yield chunk
        except Exception as error:
            errorOccurred = True
            durationMs = int(time.time() * 1000) - startTime
            self.__logApiError(durationMs, error, prompt_id)
            raise error

        if not errorOccurred:
            durationMs = int(time.time() * 1000) - startTime
            allParts: List[Part] = []
            for content in outputContent:
                if content.get("parts"):
                    allParts.extend(content["parts"])
            await self.__log_api_response(
                durationMs,
                prompt_id,
                self.get_final_usage_metadata(chunks),
                json.dumps(chunks)
            )
        await self.__record_history(inputContent, outputContent)
    
    async def __record_history(
            self, 
            userInput: Content,
            modelOutput: List[Content],
            automaticFunctionCallingHistory: Optional[List[Content]] = None
    ):
        nonThoughtModelOutput = [
            content for content in modelOutput if not self.__is_thought_content(content)
        ]

        outputContents: List[Content] = []
        if (
            len(nonThoughtModelOutput) > 0 and
            all(content.get("role") is not None for content in nonThoughtModelOutput)
        ):
            outputContents = nonThoughtModelOutput
        elif len(nonThoughtModelOutput) == 0 and len(modelOutput) > 0:
            # This case handles when the model returns only a thought.
            # We don't want to add an empty model response in this case.
            pass
        else:
            # When not a function response appends an empty content when model returns empty response, so that the
            # history is always alternating between user and model.
            # Workaround for: https://b.corp.google.com/issues/420354090
            if not is_function_response(userInput):
                outputContents.append({
                    "role": "model",
                    "parts": [],
                })

        if (
            automaticFunctionCallingHistory and
            len(automaticFunctionCallingHistory) > 0
        ):
            self.history.extend(
                extract_curated_history(automaticFunctionCallingHistory)
            )
        else:
            self.history.append(userInput)

        # Consolidate adjacent model roles in outputContents
        consolidatedOutputContents: List[Content] = []
        for content in outputContents:
            if self.__is_thought_content(content):
                continue
            if consolidatedOutputContents:
                lastContent = consolidatedOutputContents[-1]
                if self.__is_text_content(lastContent) and self.__is_text_content(content):
                    # If both current and last are text, combine their text into the lastContent's first part
                    # and append any other parts from the current content.
                    lastContent["parts"][0]["text"] += content["parts"][0].get("text", "")
                    if len(content["parts"]) > 1:
                        lastContent["parts"].extend(content["parts"][1:])
                    continue
            consolidatedOutputContents.append(content)

        if consolidatedOutputContents:
            lastHistoryEntry = self.history[-1] if self.history else None
            canMergeWithLastHistory = (
                not automaticFunctionCallingHistory or
                len(automaticFunctionCallingHistory) == 0
            )

            if (
                canMergeWithLastHistory and
                lastHistoryEntry and
                self.__is_text_content(lastHistoryEntry) and
                self.__is_text_content(consolidatedOutputContents[0])
            ):
                # If both current and last are text, combine their text into the lastHistoryEntry's first part
                # and append any other parts from the current content.
                lastHistoryEntry["parts"][0]["text"] += \
                    consolidatedOutputContents[0]["parts"][0].get("text", "")
                if len(consolidatedOutputContents[0]["parts"]) > 1:
                    lastHistoryEntry["parts"].extend(
                        consolidatedOutputContents[0]["parts"][1:]
                    )
                consolidatedOutputContents.pop(0)  # Remove the first element as it's merged
            
            if consolidatedOutputContents:
                self.history.extend(consolidatedOutputContents)
    
    def __is_text_content(
            self, 
            content: Optional[Content]
    ) -> bool:
        return bool(
            content and
            content.get("role") == "model" and
            content.get("parts") and
            len(content["parts"]) > 0 and
            isinstance(content["parts"][0].get("text"), str) and
            content["parts"][0]["text"] != ""
        )
    
    def __is_thought_content(
            self, 
            content: Optional[Content]
    ) -> bool:
        return bool(
            content and
            content.get("role") == "model" and
            content.get("parts") and
            len(content["parts"]) > 0 and
            isinstance(content["parts"][0].get("thought"), bool) and
            content["parts"][0]["thought"] is True
        )
    
    """Handles Qwen OAuth authentication errors and rate limiting"""
    async def __handle_qwen_oauth_error(self, error: Optional[Exception] = None) -> Optional[str]:
        if not error:
            return None

        errorMessage = str(error).lower()
        
        # 尝试获取错误代码
        errorCode = None
        if hasattr(error, 'status'):
            errorCode = error.status
        elif hasattr(error, 'code'):
            errorCode = error.code

        # Check if this is an authentication/authorization error
        isAuthError = (
            errorCode == 401 or
            errorCode == 403 or
            'unauthorized' in errorMessage or
            'forbidden' in errorMessage or
            'invalid api key' in errorMessage or
            'authentication' in errorMessage or
            'access denied' in errorMessage or
            ('token' in errorMessage and 'expired' in errorMessage)
        )

        # Check if this is a rate limiting error
        isRateLimitError = (
            errorCode == 429 or
            '429' in errorMessage or
            'rate limit' in errorMessage or
            'too many requests' in errorMessage
        )

        if isAuthError:
            print(f'Qwen OAuth authentication error detected: {errorMessage}')
            # The QwenContentGenerator should automatically handle token refresh
            # If it still fails, it likely means the refresh token is also expired
            print(
                'Note: If this persists, you may need to re-authenticate with Qwen OAuth'
            )
            return None

        if isRateLimitError:
            print(f'Qwen API rate limit encountered: {errorMessage}')
            # For rate limiting, we don't need to do anything special
            # The retry mechanism will handle the backoff
            return None

        # For other errors, don't handle them specially
        return None