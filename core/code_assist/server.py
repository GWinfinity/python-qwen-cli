import os
import json
import asyncio
from typing import Any, Dict, Optional, AsyncGenerator, List, Union
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from aiohttp import ClientSession, ClientResponse
from aiohttp.client_exceptions import ClientError

# 假设这些类型已从types.ts转换
from .types import (
    CodeAssistGlobalUserSettingResponse,
    LoadCodeAssistRequest,
    LoadCodeAssistResponse,
    LongRunningOperationResponse,
    OnboardUserRequest,
    SetCodeAssistGlobalUserSettingRequest,
    UserTierId
)
# 假设这些类型已从@google/genai转换
from google.genai.types import (
    CountTokensParameters,
    CountTokensResponse,
    EmbedContentParameters,
    EmbedContentResponse,
    GenerateContentParameters,
    GenerateContentResponse
)
# 假设这些函数已从converter.ts转换
from .converter import (
    CaCountTokenResponse,
    CaGenerateContentResponse,
    from_count_token_response,
    from_generate_content_response,
    to_count_token_request,
    to_generate_content_request
)
# 假设ContentGenerator已从contentGenerator.ts转换
from ..core.content_generator import ContentGenerator


class HttpOptions:
    """
    HTTP选项类，用于配置请求参数
    """
    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.headers = headers or {}


CODE_ASSIST_ENDPOINT = 'https://localhost:0'  # 禁用Google Code Assist API请求
CODE_ASSIST_API_VERSION = 'v1internal'


class CodeAssistServer(ContentGenerator):
    """
    代码助手服务器类，实现ContentGenerator接口
    用于与代码助手服务进行交互
    """
    def __init__(
        self,
        client: Credentials,
        project_id: Optional[str] = None,
        http_options: Optional[HttpOptions] = None,
        session_id: Optional[str] = None,
        user_tier: Optional[UserTierId] = None
    ):
        self.client = client
        self.project_id = project_id
        self.http_options = http_options or HttpOptions()
        self.session_id = session_id
        self.user_tier = user_tier

    async def generate_content_stream(
        self,
        req: GenerateContentParameters,
        user_prompt_id: str
    ) -> AsyncGenerator[GenerateContentResponse, None]:
        """
        流式生成内容

        Args:
            req: 生成内容的参数
            user_prompt_id: 用户提示ID

        Yields:
            GenerateContentResponse: 生成的内容响应
        """
        resps = await self.request_streaming_post[
            CaGenerateContentResponse
        ](
            'streamGenerateContent',
            to_generate_content_request(
                req,
                user_prompt_id,
                self.project_id,
                self.session_id
            ),
            req.config.abort_signal if req.config and hasattr(req.config, 'abort_signal') else None
        )
        async for resp in resps:
            yield from_generate_content_response(resp)

    async def generate_content(
        self,
        req: GenerateContentParameters,
        user_prompt_id: str
    ) -> GenerateContentResponse:
        """
        生成内容

        Args:
            req: 生成内容的参数
            user_prompt_id: 用户提示ID

        Returns:
            GenerateContentResponse: 生成的内容响应
        """
        resp = await self.request_post[CaGenerateContentResponse](
            'generateContent',
            to_generate_content_request(
                req,
                user_prompt_id,
                self.project_id,
                self.session_id
            ),
            req.config.abort_signal if req.config and hasattr(req.config, 'abort_signal') else None
        )
        return from_generate_content_response(resp)

    async def onboard_user(
        self,
        req: OnboardUserRequest
    ) -> LongRunningOperationResponse:
        """
         onboard用户

        Args:
            req: Onboard用户的请求

        Returns:
            LongRunningOperationResponse: 长时间运行操作的响应
        """
        return await self.request_post[LongRunningOperationResponse](
            'onboardUser',
            req
        )

    async def load_code_assist(
        self,
        req: LoadCodeAssistRequest
    ) -> LoadCodeAssistResponse:
        """
        加载代码助手

        Args:
            req: 加载代码助手的请求

        Returns:
            LoadCodeAssistResponse: 加载代码助手的响应
        """
        return await self.request_post[LoadCodeAssistResponse](
            'loadCodeAssist',
            req
        )

    async def get_code_assist_global_user_setting(
        self
    ) -> CodeAssistGlobalUserSettingResponse:
        """
        获取代码助手全局用户设置

        Returns:
            CodeAssistGlobalUserSettingResponse: 代码助手全局用户设置响应
        """
        return await self.request_get[CodeAssistGlobalUserSettingResponse](
            'getCodeAssistGlobalUserSetting'
        )

    async def set_code_assist_global_user_setting(
        self,
        req: SetCodeAssistGlobalUserSettingRequest
    ) -> CodeAssistGlobalUserSettingResponse:
        """
        设置代码助手全局用户设置

        Args:
            req: 设置代码助手全局用户设置的请求

        Returns:
            CodeAssistGlobalUserSettingResponse: 代码助手全局用户设置响应
        """
        return await self.request_post[CodeAssistGlobalUserSettingResponse](
            'setCodeAssistGlobalUserSetting',
            req
        )

    async def count_tokens(
        self,
        req: CountTokensParameters
    ) -> CountTokensResponse:
        """
        计算令牌数量

        Args:
            req: 计算令牌数量的参数

        Returns:
            CountTokensResponse: 令牌数量响应
        """
        resp = await self.request_post[CaCountTokenResponse](
            'countTokens',
            to_count_token_request(req)
        )
        return from_count_token_response(resp)

    async def embed_content(
        self,
        _req: EmbedContentParameters
    ) -> EmbedContentResponse:
        """
        嵌入内容（未实现）

        Args:
            _req: 嵌入内容的参数

        Raises:
            NotImplementedError: 该方法未实现
        """
        raise NotImplementedError()

    async def request_post(
        self,
        method: string,
        req: object,
        signal: Optional[Any] = None
    ) -> T:
        """
        发送POST请求

        Args:
            method: 请求方法名
            req: 请求体
            signal: 可选的中止信号

        Returns:
            T: 响应数据

        Raises:
            ClientError: 请求失败时抛出
        """
        # 确保令牌有效
        if not self.client.valid:
            await asyncio.to_thread(self.client.refresh, GoogleRequest())

        headers = {
            'Content-Type': 'application/json',
            **self.http_options.headers
        }

        # 添加认证令牌
        headers['Authorization'] = f'Bearer {self.client.token}'

        async with ClientSession() as session:
            async with session.post(
                url=self.get_method_url(method),
                headers=headers,
                data=json.dumps(req),
                signal=signal
            ) as response:
                response.raise_for_status()
                return await response.json()

    async def request_get(
        self,
        method: string,
        signal: Optional[Any] = None
    ) -> T:
        """
        发送GET请求

        Args:
            method: 请求方法名
            signal: 可选的中止信号

        Returns:
            T: 响应数据

        Raises:
            ClientError: 请求失败时抛出
        """
        # 确保令牌有效
        if not self.client.valid:
            await asyncio.to_thread(self.client.refresh, GoogleRequest())

        headers = {
            'Content-Type': 'application/json',
            **self.http_options.headers
        }

        # 添加认证令牌
        headers['Authorization'] = f'Bearer {self.client.token}'

        async with ClientSession() as session:
            async with session.get(
                url=self.get_method_url(method),
                headers=headers,
                signal=signal
            ) as response:
                response.raise_for_status()
                return await response.json()

    async def request_streaming_post(
        self,
        method: string,
        req: object,
        signal: Optional[Any] = None
    ) -> AsyncGenerator[T, None]:
        """
        发送流式POST请求

        Args:
            method: 请求方法名
            req: 请求体
            signal: 可选的中止信号

        Yields:
            T: 流式响应数据

        Raises:
            ClientError: 请求失败时抛出
            ValueError: 响应格式错误时抛出
        """
        # 确保令牌有效
        if not self.client.valid:
            await asyncio.to_thread(self.client.refresh, GoogleRequest())

        headers = {
            'Content-Type': 'application/json',
            **self.http_options.headers
        }

        # 添加认证令牌
        headers['Authorization'] = f'Bearer {self.client.token}'

        async with ClientSession() as session:
            async with session.post(
                url=self.get_method_url(method),
                params={'alt': 'sse'},
                headers=headers,
                data=json.dumps(req),
                signal=signal
                # 设置为流式响应
                # response_type='stream'
            ) as response:
                response.raise_for_status()
                buffered_lines: List[str] = []
                # 逐行读取响应
                async for line in response.content:
                    line_str = line.decode('utf-8').strip()
                    if line_str == '':
                        if not buffered_lines:
                            continue
                        try:
                            yield json.loads('\n'.join(buffered_lines))
                        except json.JSONDecodeError as e:
                            raise ValueError(f'Invalid JSON in response: {e}')
                        buffered_lines = []
                    elif line_str.startswith('data: '):
                        buffered_lines.append(line_str[6:].strip())
                    else:
                        raise ValueError(f'Unexpected line format in response: {line_str}')

    def get_method_url(self, method: string) -> string:
        """
        获取方法的URL

        Args:
            method: 方法名

        Returns:
            string: 方法的完整URL
        """
        endpoint = os.environ.get('CODE_ASSIST_ENDPOINT', CODE_ASSIST_ENDPOINT)
        return f'{endpoint}/{CODE_ASSIST_API_VERSION}:{method}'