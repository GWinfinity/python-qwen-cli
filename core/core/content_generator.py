"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Optional, Any, AsyncGenerator, TypeVar, Generic
from google.genai import   CountTokensResponse,GenerateContentResponse,GenerateContentParameters,CountTokensParameters,EmbedContentResponse,EmbedContentParameters,GoogleGenAI
from ..config.config import Config
from ..config.models import DEFAULT_GEMINI_MODEL
from .model_check import get_effective_model
from ..code_assist.code_assist import createCodeAssistContentGenerator
from ..code_assist.types import UserTierId


"""
Interface abstracting the core functionalities for generating content and counting tokens.
"""
class ContentGenerator(ABC):
    @abstractmethod
    async def generate_content(
        self, request: GenerateContentParameters, userPromptId: str
    ) -> GenerateContentResponse:
        pass

    @abstractmethod
    async def generate_content_stream(
        self, request: GenerateContentParameters, userPromptId: str
    ) -> AsyncGenerator[GenerateContentResponse, None]:
        pass

    @abstractmethod
    async def count_tokens(self, request: CountTokensParameters) -> CountTokensResponse:
        pass

    @abstractmethod
    async def embed_content(self, request: EmbedContentParameters) -> EmbedContentResponse:
        pass

    @property
    def user_tier(self) -> Optional[UserTierId]:
        return None

class AuthType(Enum):
    LOGIN_WITH_GOOGLE = 'oauth-personal'
    USE_GEMINI = 'gemini-api-key'
    USE_VERTEX_AI = 'vertex-ai'
    CLOUD_SHELL = 'cloud-shell'
    USE_OPENAI = 'openai'
    QWEN_OAUTH = 'qwen-oauth'

class ContentGeneratorConfig:
    def __init__(
        self,
        model: str,
        apiKey: Optional[str] = None,
        vertexai: bool = False,
        authType: Optional[AuthType] = None,
        enableOpenAILogging: bool = False,
        timeout: Optional[int] = None,
        maxRetries: Optional[int] = None,
        samplingParams: Optional[Dict[str, Any]] = None,
        proxy: Optional[str] = None,
    ):
        self.model = model
        self.apiKey = apiKey
        self.vertexai = vertexai
        self.authType = authType
        self.enableOpenAILogging = enableOpenAILogging
        self.timeout = timeout
        self.maxRetries = maxRetries
        self.samplingParams = samplingParams
        self.proxy = proxy

async def create_code_assist_content_generator(
    httpOptions: Dict[str, Any],
    authType: AuthType,
    gcConfig: Config,
    sessionId: Optional[str] = None,
) -> ContentGenerator:
    # 实现代码助手内容生成器
    # 这是一个模拟实现，实际实现需要根据原始 TypeScript 代码
    class CodeAssistContentGenerator(ContentGenerator):
        async def generate_content(self, request: GenerateContentParameters, userPromptId: str) -> GenerateContentResponse:
            # 实现生成内容的逻辑
            return GenerateContentResponse()

        async def generate_content_stream(self, request: GenerateContentParameters, userPromptId: str) -> AsyncGenerator[GenerateContentResponse, None]:
            # 实现流式生成内容的逻辑
            yield GenerateContentResponse()

        async def count_tokens(self, request: CountTokensParameters) -> CountTokensResponse:
            # 实现计数 tokens 的逻辑
            return CountTokensResponse()

        async def embed_content(self, request: EmbedContentParameters) -> EmbedContentResponse:
            # 实现嵌入内容的逻辑
            return EmbedContentResponse()

    return CodeAssistContentGenerator()


def create_content_generator_config(
    config: Config,
    authType: Optional[AuthType] = None,
) -> ContentGeneratorConfig:
    geminiApiKey = os.environ.get('GEMINI_API_KEY')
    googleApiKey = os.environ.get('GOOGLE_API_KEY')
    googleCloudProject = os.environ.get('GOOGLE_CLOUD_PROJECT')
    googleCloudLocation = os.environ.get('GOOGLE_CLOUD_LOCATION')
    openaiApiKey = os.environ.get('OPENAI_API_KEY')

    # 使用配置中的模型，如果没有则使用默认模型
    effectiveModel = config.getModel() or DEFAULT_GEMINI_MODEL

    contentGeneratorConfig = ContentGeneratorConfig(
        model=effectiveModel,
        authType=authType,
        proxy=config.getProxy(),
        enableOpenAILogging=config.getEnableOpenAILogging(),
        timeout=config.getContentGeneratorTimeout(),
        maxRetries=config.getContentGeneratorMaxRetries(),
        samplingParams=config.getSamplingParams(),
    )

    # 如果使用 Google 认证或 Cloud Shell，直接返回配置
    if authType in (AuthType.LOGIN_WITH_GOOGLE, AuthType.CLOUD_SHELL):
        return contentGeneratorConfig

    if authType == AuthType.USE_GEMINI and geminiApiKey:
        contentGeneratorConfig.apiKey = geminiApiKey
        contentGeneratorConfig.vertexai = False
        # 注意：在 Python 中，我们不能直接调用异步函数，需要在异步上下文中调用
        # 这里简化处理，实际实现可能需要调整
        effectiveModel = asyncio.run(get_effective_model(
            contentGeneratorConfig.apiKey,
            contentGeneratorConfig.model,
            contentGeneratorConfig.proxy,
        ))
        contentGeneratorConfig.model = effectiveModel
        return contentGeneratorConfig

    if authType == AuthType.USE_VERTEX_AI and (googleApiKey or (googleCloudProject and googleCloudLocation)):
        contentGeneratorConfig.apiKey = googleApiKey
        contentGeneratorConfig.vertexai = True
        return contentGeneratorConfig

    if authType == AuthType.USE_OPENAI and openaiApiKey:
        contentGeneratorConfig.apiKey = openaiApiKey
        contentGeneratorConfig.model = os.environ.get('OPENAI_MODEL') or DEFAULT_GEMINI_MODEL
        return contentGeneratorConfig

    if authType == AuthType.QWEN_OAUTH:
        # 对于 Qwen OAuth，我们将在 createContentGenerator 中动态处理 API 密钥
        # 设置一个特殊标记表示这是 Qwen OAuth
        contentGeneratorConfig.apiKey = 'QWEN_OAUTH_DYNAMIC_TOKEN'
        contentGeneratorConfig.model = config.get_model() or DEFAULT_GEMINI_MODEL
        return contentGeneratorConfig

    return contentGeneratorConfig

async def create_content_generator(
    config: ContentGeneratorConfig,
    gcConfig: Config,
    sessionId: Optional[str] = None,
) -> ContentGenerator:
    version = os.environ.get('CLI_VERSION') or str(os.getpid())
    httpOptions = {
        'headers': {
            'User-Agent': f'GeminiCLI/{version} ({os.name}; {os.uname().machine})',
        }
    }

    if config.authType in (AuthType.LOGIN_WITH_GOOGLE, AuthType.CLOUD_SHELL):
        return await create_code_assist_content_generator(
            httpOptions,
            config.authType,
            gcConfig,
            sessionId,
        )

    if config.authType in (AuthType.USE_GEMINI, AuthType.USE_VERTEX_AI):
        googleGenAI = GoogleGenAI(
            apiKey=config.apiKey if config.apiKey != '' else None,
            vertexai=config.vertexai,
            httpOptions=httpOptions,
        )
        # 假设 models 属性返回一个 ContentGenerator 实例
        return googleGenAI.models

    if config.authType == AuthType.USE_OPENAI:
        if not config.apiKey:
            raise ValueError('OpenAI API key is required')

        # 动态导入 OpenAIContentGenerator 以避免循环依赖
        from .openaiContentGenerator import OpenAIContentGenerator

        # 始终使用 OpenAIContentGenerator，日志记录由 enableOpenAILogging 标志控制
        return OpenAIContentGenerator(config.apiKey, config.model, gcConfig)

    if config.authType == AuthType.QWEN_OAUTH:
        if config.apiKey != 'QWEN_OAUTH_DYNAMIC_TOKEN':
            raise ValueError('Invalid Qwen OAuth configuration')

        # 动态导入所需类
        from ..qwen.qwenOAuth2 import getQwenOAuthClient
        from ..qwen.qwenContentGenerator import QwenContentGenerator

        try:
            # 获取 Qwen OAuth 客户端（现在包含集成的令牌管理）
            qwenClient = await getQwenOAuthClient(gcConfig)

            # 创建带有动态令牌管理的内容生成器
            return QwenContentGenerator(qwenClient, config.model, gcConfig)
        except Exception as error:
            raise ValueError(f'Failed to initialize Qwen: {str(error)}')

    raise ValueError(f'Error creating contentGenerator: Unsupported authType: {config.authType}')