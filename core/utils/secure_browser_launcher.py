"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import subprocess
import sys
import os
import re
from urllib.parse import urlparse
from typing import Dict, List, Any


def validate_url(url: str) -> None:
    """
    验证URL是否安全打开。仅允许HTTP和HTTPS URL以防止命令注入。

    参数:
        url: 要验证的URL

    异常:
        ValueError: 如果URL无效或使用不安全的协议
    """
    try:
        parsed_url = urlparse(url)
    except Exception:
        raise ValueError(f"无效的URL: {url}")

    # 只允许HTTP和HTTPS协议
    if parsed_url.scheme not in ('http', 'https'):
        raise ValueError(
            f"不安全的协议: {parsed_url.scheme}。仅允许HTTP和HTTPS。"
        )

    # 额外验证: 确保没有换行符或控制字符
    if re.search(r'[\r\n\x00-\x1f]', url):
        raise ValueError("URL包含无效字符")


async def open_browser_securely(url: str) -> None:
    """
    使用平台特定命令在默认浏览器中打开URL。
    此实现通过以下方式避免shell注入漏洞:
    1. 验证URL确保仅为HTTP/HTTPS
    2. 使用subprocess避免shell解释
    3. 将URL作为参数传递而不是构造命令字符串

    参数:
        url: 要打开的URL

    异常:
        ValueError: 如果URL无效
        RuntimeError: 如果打开浏览器失败
    """
    # 先验证URL
    validate_url(url)

    platform_name = sys.platform
    command: str
    args: List[str]

    if platform_name == 'darwin':
        # macOS
        command = 'open'
        args = [url]
    elif platform_name == 'win32':
        # Windows - 使用PowerShell
        command = 'powershell.exe'
        # 转义单引号
        escaped_url = url.replace("'", "''")
        args = [
            '-NoProfile',
            '-NonInteractive',
            '-WindowStyle',
            'Hidden',
            '-Command',
            f"Start-Process '{escaped_url}'"
        ]
    elif platform_name in ('linux', 'freebsd', 'openbsd'):
        # Linux和BSD变体
        # 首先尝试xdg-open
        command = 'xdg-open'
        args = [url]
    else:
        raise RuntimeError(f"不支持的平台: {platform_name}")

    options: Dict[str, Any] = {
        # 不要继承父环境以避免潜在问题
        'env': {
            **os.environ,
            # 确保不在可能解释特殊字符的shell中
            'SHELL': None,
        },
        # 分离浏览器进程使其不阻塞
        'detached': True,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
    }

    try:
        # 注意: Python中没有直接的execFileAsync等价物，但subprocess.run可以达到相同目的
        # 对于异步支持，我们可以使用asyncio.create_subprocess_exec
        import asyncio
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            env=options['env'],
            detached=options['detached'],
            stdout=options['stdout'],
            stderr=options['stderr']
        )
        # 不等待进程完成，让它在后台运行
    except Exception as e:
        # 对于Linux，如果xdg-open失败，尝试备用命令
        if (
            platform_name in ('linux', 'freebsd', 'openbsd')
            and command == 'xdg-open'
        ):
            fallback_commands = [
                'gnome-open',
                'kde-open',
                'firefox',
                'chromium',
                'google-chrome',
            ]

            for fallback_command in fallback_commands:
                try:
                    process = await asyncio.create_subprocess_exec(
                        fallback_command,
                        url,
                        env=options['env'],
                        detached=options['detached'],
                        stdout=options['stdout'],
                        stderr=options['stderr']
                    )
                    return  # 成功!
                except Exception:
                    # 尝试下一个命令
                    continue

        # 如果所有尝试都失败，则重新抛出错误
        raise RuntimeError(f"无法打开浏览器: {str(e)}")


def should_launch_browser() -> bool:
    """
    检查当前环境是否应该尝试启动浏览器。
    这与browser.ts中的逻辑相同以保持一致性。

    返回:
        bool: 如果工具应该尝试启动浏览器，则为True
    """
    # 指示不应尝试为用户打开Web浏览器的浏览器名称列表
    browser_blocklist = ['www-browser']
    browser_env = os.environ.get('BROWSER')
    if browser_env and browser_env in browser_blocklist:
        return False

    # CI/CD或其他非交互式shell中使用的常见环境变量
    if os.environ.get('CI') or os.environ.get('DEBIAN_FRONTEND') == 'noninteractive':
        return False

    # SSH_CONNECTION的存在表示远程会话
    # 除非显式提供显示(在Linux下检查)
    is_ssh = bool(os.environ.get('SSH_CONNECTION'))

    # 在Linux上，显示服务器的存在是GUI的强烈指示器
    if sys.platform == 'linux':
        # 这些是可指示Linux上运行的合成器的环境变量
        display_variables = ['DISPLAY', 'WAYLAND_DISPLAY', 'MIR_SOCKET']
        has_display = any(os.environ.get(v) for v in display_variables)
        if not has_display:
            return False

    # 如果在非Linux操作系统(如macOS)的SSH会话中，不要启动浏览器
    # Linux情况在上面处理(如果设置了DISPLAY，则允许)
    if is_ssh and sys.platform != 'linux':
        return False

    # 对于非Linux操作系统，我们通常假设GUI可用
    # 除非其他信号(如SSH)表明否则
    return True