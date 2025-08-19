"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional

"""
检查默认的 "pro" 模型是否受到速率限制，并在必要时返回备用的 "flash" 模型。
此函数设计为静默运行。

参数:
    api_key: 用于检查的 API 密钥
    current_configured_model: 当前在设置中配置的模型
    proxy: 代理服务器地址（可选）

返回:
    指示要使用的模型的字符串
"""
async def get_effective_model(
    api_key: str,
    current_configured_model: str,
    proxy: Optional[str] = None,
) -> str:
    # 禁用 Google API 模型检查
    return current_configured_model