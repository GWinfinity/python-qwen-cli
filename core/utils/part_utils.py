from typing import List, Dict, Union, Any, Optional
from google.genai.types import GenerateContentResponse, Part  


def part_to_string(part: Union[Part, str, List[Union[Part, str]]]) -> str:
    """
    将 Part 或 Part 列表转换为字符串表示
    Args:
        part: 要转换的 Part 或 Part 列表
    Returns:
        转换后的字符串
    """
    if isinstance(part, str):
        return part
    elif isinstance(part, list):
        return ''.join(part_to_string(p) for p in part)
    elif hasattr(part, 'text'):
        return part.text
    elif hasattr(part, 'inline_data'):
        inline_data = part.inline_data
        mime_type = inline_data.mime_type
        if mime_type.startswith('image/'):
            return f'[Image ({mime_type})]'
        else:
            return f'[Inline data ({mime_type})]'
    elif hasattr(part, 'file_data'):
        file_data = part.file_data
        return f'[File: {file_data.file_uri}]'
    elif hasattr(part, 'function_call'):
        function_call = part.function_call
        return f'[Function call: {function_call.name}({function_call.args})]'
    elif hasattr(part, 'function_response'):
        function_response = part.function_response
        return f'[Function response: {function_response.name}]'
    else:
        return '[Unsupported part type]'


def get_response_text(response: GenerateContentResponse) -> str:
    """
    从 GenerateContentResponse 中提取文本内容
    Args:
        response: GenerateContentResponse 对象
    Returns:
        提取的文本内容
    """
    if not response or not hasattr(response, 'candidates') or not response.candidates:
        return ''

    # 获取第一个候选结果
    candidate = response.candidates[0]

    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
        return part_to_string(candidate.content.parts)
    elif hasattr(candidate, 'text'):
        return candidate.text
    else:
        return ''