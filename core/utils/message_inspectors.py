from typing import Dict, Any, List
from google.genai.types import Content


def is_function_response(content: Content) -> bool:
    """
    检查内容是否是函数响应

    :param content: 要检查的内容对象
    :return: 如果是函数响应则返回 True，否则返回 False
    """
    return (
        content.get("role") == "user"
        and content.get("parts") is not None
        and all(part.get("functionResponse") is not None for part in content["parts"])
    )


def is_function_call(content: Content) -> bool:
    """
    检查内容是否是函数调用

    :param content: 要检查的内容对象
    :return: 如果是函数调用则返回 True，否则返回 False
    """
    return (
        content.get("role") == "model"
        and content.get("parts") is not None
        and all(part.get("functionCall") is not None for part in content["parts"])
    )