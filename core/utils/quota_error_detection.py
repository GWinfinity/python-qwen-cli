from typing import Any, Dict, List, Optional, TypeGuard, Union

# 注意：Python 3.10+ 支持TypeGuard，需要从typing_extensions导入
# 如果使用的Python版本较低，可能需要安装typing_extensions包
from typing_extensions import TypeGuard


class ApiError:
    """ApiError接口对应的Python类"""
    def __init__(self, error: Dict[str, Any]):
        self.error = error


class StructuredError:
    """StructuredError接口对应的Python类"""
    def __init__(self, message: str, status: Optional[int] = None):
        self.message = message
        self.status = status


def is_api_error(error: Any) -> TypeGuard[ApiError]:
    """
    检查错误是否符合ApiError类型
    
    参数:
        error: 要检查的错误对象
    
    返回:
        如果是ApiError类型则返回True，否则返回False
    """
    if not isinstance(error, dict):
        return False
    if 'error' not in error:
        return False
    error_obj = error['error']
    if not isinstance(error_obj, dict):
        return False
    return 'message' in error_obj


def is_structured_error(error: Any) -> TypeGuard[StructuredError]:
    """
    检查错误是否符合StructuredError类型
    
    参数:
        error: 要检查的错误对象
    
    返回:
        如果是StructuredError类型则返回True，否则返回False
    """
    if not isinstance(error, dict):
        return False
    if 'message' not in error:
        return False
    return isinstance(error['message'], str)


def is_pro_quota_exceeded_error(error: Any) -> bool:
    """
    检查是否是Pro配额超额错误
    
    参数:
        error: 要检查的错误对象
    
    返回:
        如果是Pro配额超额错误则返回True，否则返回False
    """
    def check_message(message: str) -> bool:
        return (
            "Quota exceeded for quota metric 'Gemini" in message
            and "Pro Requests'" in message
        )

    if isinstance(error, str):
        return check_message(error)

    if is_structured_error(error):
        return check_message(error['message'])

    if is_api_error(error):
        return check_message(error['error']['message'])

    # 检查是否是Gaxios错误，带有响应数据
    if isinstance(error, dict) and 'response' in error:
        response = error['response']
        if isinstance(response, dict) and 'data' in response:
            data = response['data']
            if isinstance(data, str):
                return check_message(data)
            if isinstance(data, dict) and 'error' in data:
                error_data = data['error']
                if isinstance(error_data, dict) and 'message' in error_data:
                    return check_message(error_data['message'])

    return False


def is_generic_quota_exceeded_error(error: Any) -> bool:
    """
    检查是否是通用配额超额错误
    
    参数:
        error: 要检查的错误对象
    
    返回:
        如果是通用配额超额错误则返回True，否则返回False
    """
    if isinstance(error, str):
        return 'Quota exceeded for quota metric' in error

    if is_structured_error(error):
        return 'Quota exceeded for quota metric' in error['message']

    if is_api_error(error):
        return 'Quota exceeded for quota metric' in error['error']['message']

    return False


def is_qwen_quota_exceeded_error(error: Any) -> bool:
    """
    检查是否是Qwen配额超额错误（不应该重试）
    
    参数:
        error: 要检查的错误对象
    
    返回:
        如果是Qwen配额超额错误则返回True，否则返回False
    """
    def check_message(message: str) -> bool:
        lower_message = message.lower()
        return (
            'insufficient_quota' in lower_message
            or 'free allocated quota exceeded' in lower_message
            or ('quota' in lower_message and 'exceeded' in lower_message)
        )

    if isinstance(error, str):
        return check_message(error)

    if is_structured_error(error):
        return check_message(error['message'])

    if is_api_error(error):
        return check_message(error['error']['message'])

    return False


def is_qwen_throttling_error(error: Any) -> bool:
    """
    检查是否是Qwen限流错误（应该重试）
    
    参数:
        error: 要检查的错误对象
    
    返回:
        如果是Qwen限流错误则返回True，否则返回False
    """
    def check_message(message: str) -> bool:
        lower_message = message.lower()
        return (
            'throttling' in lower_message
            or 'requests throttling triggered' in lower_message
            or 'rate limit' in lower_message
            or 'too many requests' in lower_message
        )

    def get_status_code(error_obj: Any) -> Optional[int]:
        if isinstance(error_obj, dict):
            return error_obj.get('status') or error_obj.get('code')
        return None

    status_code = get_status_code(error)

    if isinstance(error, str):
        return (
            (status_code == 429 and check_message(error))
            or 'throttling' in error
        )

    if is_structured_error(error):
        return status_code == 429 and check_message(error['message'])

    if is_api_error(error):
        return (
            error['error'].get('code') == 429
            and check_message(error['error']['message'])
        )

    return False