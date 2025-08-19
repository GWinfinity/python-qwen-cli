import json
from typing import Any, Dict, Optional, Union


class GaxiosErrorDict(Dict[str, Any]):
    """表示 Gaxios 错误对象的类型提示"""
    response: Optional[Dict[str, Any]]


class ResponseDataDict(Dict[str, Any]):
    """表示响应数据的类型提示"""
    error: Optional[Dict[str, Any]]


class ForbiddenError(Exception):
    """表示权限不足错误"""
    pass


class UnauthorizedError(Exception):
    """表示未授权错误"""
    pass


class BadRequestError(Exception):
    """表示请求错误"""
    pass


def is_node_error(error: Any) -> bool:
    """检查一个错误是否是 Node.js 风格的错误

    Args:
        error: 要检查的错误对象

    Returns:
        bool: 如果是 Node.js 风格的错误则返回 True
    """
    return isinstance(error, Exception) and hasattr(error, 'code')


def get_error_message(error: Any) -> str:
    """获取错误的消息文本

    Args:
        error: 错误对象

    Returns:
        str: 错误消息
    """
    if isinstance(error, Exception):
        return str(error)
    try:
        return str(error)
    except:
        return 'Failed to get error details'


def parse_response_data(error: GaxiosErrorDict) -> ResponseDataDict:
    """解析响应数据

    Args:
        error: Gaxios 错误对象

    Returns:
        ResponseDataDict: 解析后的响应数据
    """
    # 处理响应数据可能是字符串的情况
    if error.get('response') and isinstance(error['response'].get('data'), str):
        try:
            return json.loads(error['response']['data'])  # type: ignore
        except json.JSONDecodeError:
            pass
    return error.get('response', {}).get('data', {})  # type: ignore


def to_friendly_error(error: Any) -> Any:
    """将原始错误转换为更友好的错误类型

    Args:
        error: 原始错误

    Returns:
        Any: 转换后的错误或原始错误
    """
    if error and isinstance(error, dict) and 'response' in error:
        gaxios_error = error  # 类型提示为 GaxiosErrorDict
        data = parse_response_data(gaxios_error)
        error_data = data.get('error', {})
        error_message = error_data.get('message')
        error_code = error_data.get('code')

        if error_message and error_code:
            if error_code == 400:
                return BadRequestError(error_message)
            elif error_code == 401:
                return UnauthorizedError(error_message)
            elif error_code == 403:
                # 传递消息很重要，因为它可能解释原因，如"您使用的云项目没有启用代码辅助"
                return ForbiddenError(error_message)
    return error