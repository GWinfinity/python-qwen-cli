import json
from typing import Dict, Any, Optional, Callable, Union
from google.genai import Content, GenerateContentConfig,GenerateContentResponse
import asyncio
from .core.client import GeminiClient

# 假设这些类型和类在 Python 中有对应的实现
# 这里我们定义一些模拟的类型和类以确保代码结构完整


# 假设的常量
DEFAULT_GEMINI_FLASH_LITE_MODEL = "gemini-flash-lite"


def part_to_string(part: Any) -> str:
    """
    将部分内容转换为字符串
    """
    # 实际实现需要根据 part 的类型进行转换
    if hasattr(part, 'text'):
        return part.text
    elif isinstance(part, dict):
        return json.dumps(part)
    return str(part)


def get_response_text(response: GenerateContentResponse) -> Optional[str]:
    """
    从响应中获取文本
    """
    if hasattr(response, 'text'):
        return response.text
    return None


# 定义 Summarizer 类型
Summarizer = Callable[[ToolResult, GeminiClient, Any], asyncio.Future[str]]


async def default_summarizer(
    result: ToolResult,
    gemini_client: GeminiClient,
    abort_signal: Any
) -> str:
    """
    默认的工具结果总结器

    参数:
        result: 工具执行的结果
        gemini_client: Gemini 客户端
        abort_signal: 中止信号

    返回:
        结果的总结
    """
    return json.dumps(result.llm_content)


SUMMARIZE_TOOL_OUTPUT_PROMPT = """
Summarize the following tool output to be a maximum of {max_output_tokens} tokens. The summary should be concise and capture the main points of the tool output.

The summarization should be done based on the content that is provided. Here are the basic rules to follow:
1. If the text is a directory listing or any output that is structural, use the history of the conversation to understand the context. Using this context try to understand what information we need from the tool output and return that as a response.
2. If the text is text content and there is nothing structural that we need, summarize the text.
3. If the text is the output of a shell command, use the history of the conversation to understand the context. Using this context try to understand what information we need from the tool output and return a summarization along with the stack trace of any error within the <error></error> tags. The stack trace should be complete and not truncated. If there are warnings, you should include them in the summary within <warning></warning> tags.


Text to summarize:
"{text_to_summarize}"

Return the summary string which should first contain an overall summarization of text followed by the full stack trace of errors and warnings in the tool output.
"""


async def llm_summarizer(
    result: ToolResult,
    gemini_client: GeminiClient,
    abort_signal: Any
) -> str:
    """
    使用 LLM 进行工具结果总结的总结器

    参数:
        result: 工具执行的结果
        gemini_client: Gemini 客户端
        abort_signal: 中止信号

    返回:
        结果的总结
    """
    return await summarize_tool_output(
        part_to_string(result.llm_content),
        gemini_client,
        abort_signal
    )


async def summarize_tool_output(
    text_to_summarize: str,
    gemini_client: GeminiClient,
    abort_signal: Any,
    max_output_tokens: int = 2000
) -> str:
    """
    总结工具输出

    参数:
        text_to_summarize: 要总结的文本
        gemini_client: Gemini 客户端
        abort_signal: 中止信号
        max_output_tokens: 最大输出标记数

    返回:
        总结后的文本
    """
    # 这里只是一个粗略的估计，实际应用中可能需要更精确的标记计数
    if not text_to_summarize or len(text_to_summarize) < max_output_tokens:
        return text_to_summarize

    prompt = SUMMARIZE_TOOL_OUTPUT_PROMPT.format(
        max_output_tokens=max_output_tokens,
        text_to_summarize=text_to_summarize
    )

    contents = [Content(role="user", parts=[{"text": prompt}])]
    tool_output_summarizer_config = GenerateContentConfig(max_output_tokens=max_output_tokens)

    try:
        parsed_response = await gemini_client.generate_content(
            contents,
            tool_output_summarizer_config,
            abort_signal,
            DEFAULT_GEMINI_FLASH_LITE_MODEL
        )
        return get_response_text(parsed_response) or text_to_summarize
    except Exception as e:
        print(f"Failed to summarize tool output: {str(e)}")
        return text_to_summarize