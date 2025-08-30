from typing import Dict, Literal, Union, cast

# 类型定义
Model = str
TokenCount = int

# 默认token限制常量
default_token_limit = 1_048_576


def token_limit(model: Model) -> TokenCount:
    """
    获取指定模型的token限制
    基于 https://ai.google.dev/gemini-api/docs/models
    
    Args:
        model: 模型名称字符串
        
    Returns:
        该模型的token限制数量
    """
    # 根据模型名称返回对应的token限制
    # 可以根据需要添加更多模型或通过配置指定
    if model == 'gemini-1.5-pro':
        return 2_097_152
    elif model in (
        'gemini-1.5-flash',
        'gemini-2.5-pro-preview-05-06',
        'gemini-2.5-pro-preview-06-05',
        'gemini-2.5-pro',
        'gemini-2.5-flash-preview-05-20',
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite',
        'gemini-2.0-flash'
    ):
        return 1_048_576
    elif model == 'gemini-2.0-flash-preview-image-generation':
        return 32_000
    else:
        return default_token_limit

# 如果需要以模块方式导出，可以使用以下方式
__all__ = [
    'default_token_limit',
    'token_limit'
]