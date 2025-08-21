#!/usr/bin/env python3

"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import re
import socket
import urllib.parse
import asyncio
import aiohttp
from typing import Optional
from .error import get_error_message, is_node_error


# 私有 IP 地址范围正则表达式
PRIVATE_IP_RANGES = [
    re.compile(r'^10\.'),
    re.compile(r'^127\.'),
    re.compile(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.'),
    re.compile(r'^192\.168\.'),
    re.compile(r'^::1$'),
    re.compile(r'^fc00:'),
    re.compile(r'^fe80:'),
]


class FetchError(Exception):
    """
    表示获取数据时的错误
    """
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.name = 'FetchError'
        self.code = code



def is_private_ip(url: str) -> bool:
    """
    检查 URL 是否指向私有 IP 地址
    :param url: URL 字符串
    :return: 如果是私有 IP 地址则返回 True，否则返回 False
    """
    try:
        parsed_url = urllib.parse.urlparse(url)
        hostname = parsed_url.hostname
        if not hostname:
            return False

        # 检查是否为 IPv6 地址
        if ':' in hostname:
            return any(range_.match(hostname) for range_ in PRIVATE_IP_RANGES)

        # 解析主机名为 IP 地址
        ip_address = socket.gethostbyname(hostname)

        # 检查是否在私有 IP 范围内
        return any(range_.match(ip_address) for range_ in PRIVATE_IP_RANGES)
    except (socket.gaierror, ValueError):
        return False


async def fetch_with_timeout(url: str, timeout: int) -> aiohttp.ClientResponse:
    """
    带超时的异步获取数据
    :param url: URL 字符串
    :param timeout: 超时时间（毫秒）
    :return: 响应对象
    :raises: FetchError 如果请求失败或超时
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout/1000) as response:
                return response
    except asyncio.TimeoutError:
        raise FetchError(f"Request timed out after {timeout}ms", "ETIMEDOUT")
    except aiohttp.ClientError as e:
        if is_node_error(e) and hasattr(e, 'code'):
            raise FetchError(get_error_message(e), e.code)
        raise FetchError(get_error_message(e))
    except Exception as e:
        raise FetchError(get_error_message(e))