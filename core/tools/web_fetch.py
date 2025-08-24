import os
import re
import json
import asyncio
import aiohttp
from typing import Dict, List, Optional, Any, Tuple, Union
from urllib.parse import urlparse
import socket
from pathlib import Path
from difflib import SequenceMatcher

# 假设这些是已存在的模块，根据实际情况调整导入
from ..utils.config import Config
from ..utils.logger import Logger
from ..utils.gemini_client import GeminiClient
from ..utils.private_ip_detector import PrivateIPDetector
from ..utils.schema_validator import SchemaValidator
from .tool import BaseTool, ToolResult,ToolCallConfirmationDetails,ToolConfirmationOutcome,Icon


class WebFetchToolParams:
    def __init__(self,
                 url: str,
                 timeout_ms: Optional[int] = None,
                 disable_cache: Optional[bool] = None,
                 html_to_text: Optional[bool] = None,
                 max_tokens: Optional[int] = None,
                 extract_metadata: Optional[bool] = None,
                 cache_ttl_ms: Optional[int] = None,
                 grounding_mode: Optional[str] = None):
        self.url = url
        self.timeout_ms = timeout_ms
        self.disable_cache = disable_cache
        self.html_to_text = html_to_text
        self.max_tokens = max_tokens
        self.extract_metadata = extract_metadata
        self.cache_ttl_ms = cache_ttl_ms
        self.grounding_mode = grounding_mode

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WebFetchToolParams':
        return cls(
            url=data.get('url'),
            timeout_ms=data.get('timeout_ms'),
            disable_cache=data.get('disable_cache'),
            html_to_text=data.get('html_to_text'),
            max_tokens=data.get('max_tokens'),
            extract_metadata=data.get('extract_metadata'),
            cache_ttl_ms=data.get('cache_ttl_ms'),
            grounding_mode=data.get('grounding_mode')
        )

class WebFetchTool(BaseTool):
    def __init__(
        self,
        config: Config,
        logger: Logger,
        gemini_client: GeminiClient,
        private_ip_detector: PrivateIPDetector,
        schema_validator: SchemaValidator,
    ):
        super().__init__(config, logger)
        self.gemini_client = gemini_client
        self.private_ip_detector = private_ip_detector
        self.schema_validator = schema_validator

        # 初始化缓存
        self.cache = {}
        self.cache_ttl_ms = config.get('web_fetch.cache_ttl_ms', 3600000)  # 默认1小时

    @property
    def name(self) -> str:
        return 'web_fetch'

    @property
    def display_name(self) -> str:
        return 'Web Fetch'

    @property
    def description(self) -> str:
        return 'Fetches content from a URL and returns the raw content or processed text.'

    @property
    def schema(self) -> Dict[str, Any]:
        return {
            'type': 'object',
            'properties': {
                'url': {
                    'type': 'string',
                    'description': 'The URL to fetch content from.',
                    'format': 'uri',
                },
                'timeout_ms': {
                    'type': 'integer',
                    'description': 'Timeout in milliseconds for the request.',
                    'minimum': 1000,
                    'maximum': 30000,
                },
                'disable_cache': {
                    'type': 'boolean',
                    'description': 'Whether to disable caching of the response.',
                },
                'html_to_text': {
                    'type': 'boolean',
                    'description': 'Whether to convert HTML content to plain text.',
                },
                'max_tokens': {
                    'type': 'integer',
                    'description': 'Maximum number of tokens to return.',
                    'minimum': 1,
                },
                'extract_metadata': {
                    'type': 'boolean',
                    'description': 'Whether to extract metadata from the content.',
                },
                'cache_ttl_ms': {
                    'type': 'integer',
                    'description': 'Cache TTL in milliseconds.',
                    'minimum': 1000,
                },
                'grounding_mode': {
                    'type': 'string',
                    'description': 'Grounding mode for content extraction.',
                    'enum': ['none', 'basic', 'advanced'],
                },
            },
            'required': ['url'],
        }

    async def _execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # 验证参数
        validation_result = self.schema_validator.validate(params, self.schema)
        if not validation_result.is_valid:
            return {
                'error': f'Invalid parameters: {validation_result.errors}',
                'status': 'error'
            }

        # 解析参数
        web_fetch_params = WebFetchToolParams.from_dict(params)
        url = web_fetch_params.url
        timeout_ms = web_fetch_params.timeout_ms or 10000
        disable_cache = web_fetch_params.disable_cache or False
        html_to_text = web_fetch_params.html_to_text or False
        max_tokens = web_fetch_params.max_tokens
        extract_metadata = web_fetch_params.extract_metadata or False
        cache_ttl_ms = web_fetch_params.cache_ttl_ms or self.cache_ttl_ms
        grounding_mode = web_fetch_params.grounding_mode or 'none'

        # 检查URL是否有效
        if not self._is_valid_url(url):
            return {
                'error': f'Invalid URL: {url}',
                'status': 'error'
            }

        # 检查是否为私有IP
        if self._is_private_ip(url):
            return {
                'error': f'Private IP addresses are not allowed: {url}',
                'status': 'error'
            }

        # 检查缓存
        cache_key = self._generate_cache_key(url, html_to_text, max_tokens)
        if not disable_cache and cache_key in self.cache:
            cached_result = self.cache[cache_key]
            if self._is_cache_valid(cached_result, cache_ttl_ms):
                self.logger.info(f'Cache hit for URL: {url}')
                result = cached_result['data']
                result.cache_hit = True
                return result.to_dict()

        try:
            # 执行fetch
            result = await self._fetch_url(
                url,
                timeout_ms,
                html_to_text,
                max_tokens,
                extract_metadata,
                grounding_mode
            )

            # 更新缓存
            if not disable_cache:
                self.cache[cache_key] = {
                    'timestamp': asyncio.get_event_loop().time() * 1000,
                    'data': result
                }

            return result.to_dict()

        except Exception as e:
            self.logger.error(f'Error fetching URL {url}: {str(e)}')
            return {
                'error': f'Failed to fetch URL: {str(e)}',
                'status': 'error'
            }

    async def _fetch_url(
        self,
        url: str,
        timeout_ms: int,
        html_to_text: bool,
        max_tokens: Optional[int],
        extract_metadata: bool,
        grounding_mode: str
    ) -> WebFetchResult:
        timeout = timeout_ms / 1000.0  # 转换为秒

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=timeout) as response:
                status_code = response.status
                content_type = response.headers.get('Content-Type', 'application/octet-stream')
                headers = dict(response.headers)

                # 读取内容
                content = await response.text()

                # 如果是HTML且需要转换为文本
                if 'text/html' in content_type and html_to_text:
                    content = self._convert_html_to_text(content)

                # 提取元数据
                metadata = None
                if extract_metadata:
                    metadata = self._extract_metadata(content, url)

                # 截断内容
                truncated = False
                if max_tokens and self._count_tokens(content) > max_tokens:
                    content = self._truncate_to_tokens(content, max_tokens)
                    truncated = True

                # 计算字数和token数
                word_count = len(content.split())
                token_count = self._count_tokens(content)

                return WebFetchResult(
                    url=url,
                    content=content,
                    content_type=content_type,
                    status_code=status_code,
                    headers=headers,
                    metadata=metadata,
                    cache_hit=False,
                    truncated=truncated,
                    word_count=word_count,
                    token_count=token_count
                )

    def _is_valid_url(self, url: str) -> bool:
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    def _is_private_ip(self, url: str) -> bool:
        try:
            hostname = urlparse(url).netloc
            ip = socket.gethostbyname(hostname)
            return self.private_ip_detector.is_private(ip)
        except:
            return False

    def _generate_cache_key(self, url: str, html_to_text: bool, max_tokens: Optional[int]) -> str:
        return f'{url}::{html_to_text}::{max_tokens or "none"}'

    def _is_cache_valid(self, cached_entry: Dict[str, Any], ttl_ms: int) -> bool:
        current_time = asyncio.get_event_loop().time() * 1000
        return (current_time - cached_entry['timestamp']) < ttl_ms

    def _convert_html_to_text(self, html: str) -> str:
        # 简化的HTML转文本实现，实际项目中可能需要使用html2text等库
        # 这里只是一个示例
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _extract_metadata(self, content: str, url: str) -> Dict[str, Any]:
        # 提取基本元数据
        return {
            'url': url,
            'content_length': len(content),
            'word_count': len(content.split()),
            'token_count': self._count_tokens(content)
        }

    def _count_tokens(self, text: str) -> int:
        # 简单的token计数实现，实际项目中可能需要使用tiktoken等库
        return len(text.split())

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        # 按token截断文本
        tokens = text.split()
        if len(tokens) <= max_tokens:
            return text
        return ' '.join(tokens[:max_tokens]) + '... (truncated due to max_tokens limit)'