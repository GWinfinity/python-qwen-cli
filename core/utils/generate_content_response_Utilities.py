import json
from typing import Optional, List
from dataclasses import dataclass
from google.genai.types import FunctionCall,Part,GenerateContentResponse

def get_response_text(response: GenerateContentResponse) -> Optional[str]:
    """从响应中提取文本内容"""
    if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
        return None

    parts = response.candidates[0].content.parts
    text_segments = [part.text for part in parts if part.text is not None]

    if not text_segments:
        return None

    return ''.join(text_segments)


def get_response_text_from_parts(parts: List[Part]) -> Optional[str]:
    """从 parts 数组中提取文本内容"""
    if not parts:
        return None

    text_segments = [part.text for part in parts if part.text is not None]

    if not text_segments:
        return None

    return ''.join(text_segments)


def get_function_calls(response: GenerateContentResponse) -> Optional[List[FunctionCall]]:
    """从响应中提取函数调用"""
    if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
        return None

    parts = response.candidates[0].content.parts
    function_call_parts = [part.function_call for part in parts if part.function_call is not None]

    return function_call_parts if function_call_parts else None


def get_function_calls_from_parts(parts: List[Part]) -> Optional[List[FunctionCall]]:
    """从 parts 数组中提取函数调用"""
    if not parts:
        return None

    function_call_parts = [part.function_call for part in parts if part.function_call is not None]

    return function_call_parts if function_call_parts else None


def get_function_calls_as_json(response: GenerateContentResponse) -> Optional[str]:
    """将函数调用转换为 JSON 字符串"""
    function_calls = get_function_calls(response)
    if not function_calls:
        return None

    # 转换 FunctionCall 对象为可序列化的字典
    serializable_calls = []
    for call in function_calls:
        serializable_calls.append({
            'name': call.name,
            'args': call.args
        })

    return json.dumps(serializable_calls, indent=2, ensure_ascii=False)


def get_function_calls_from_parts_as_json(parts: List[Part]) -> Optional[str]:
    """从 parts 数组中提取函数调用并转换为 JSON 字符串"""
    function_calls = get_function_calls_from_parts(parts)
    if not function_calls:
        return None

    # 转换 FunctionCall 对象为可序列化的字典
    serializable_calls = []
    for call in function_calls:
        serializable_calls.append({
            'name': call.name,
            'args': call.args
        })

    return json.dumps(serializable_calls, indent=2, ensure_ascii=False)


def get_structured_response(response: GenerateContentResponse) -> Optional[str]:
    """从响应中获取结构化响应（文本 + 函数调用）"""
    text_content = get_response_text(response)
    function_calls_json = get_function_calls_as_json(response)

    if text_content and function_calls_json:
        return f"{text_content}\n{function_calls_json}"
    if text_content:
        return text_content
    if function_calls_json:
        return function_calls_json
    return None


def get_structured_response_from_parts(parts: List[Part]) -> Optional[str]:
    """从 parts 数组中获取结构化响应"""
    text_content = get_response_text_from_parts(parts)
    function_calls_json = get_function_calls_from_parts_as_json(parts)

    if text_content and function_calls_json:
        return f"{text_content}\n{function_calls_json}"
    if text_content:
        return text_content
    if function_calls_json:
        return function_calls_json
    return None