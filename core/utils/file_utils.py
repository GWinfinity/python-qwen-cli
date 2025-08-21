
"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import os
import pathlib
import mimetypes
from typing import Union, Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from google.genai.types import PartUnion

# 常量定义
DEFAULT_MAX_LINES_TEXT_FILE = 2000
MAX_LINE_LENGTH_TEXT_FILE = 2000
DEFAULT_ENCODING = 'utf-8'


def get_specific_mime_type(file_path: str) -> Optional[str]:
    """
    查找文件路径的特定 MIME 类型
    :param file_path: 文件路径
    :return: 特定的 MIME 类型字符串（例如 'text/python', 'application/javascript'），如果未找到则返回 None
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type


def is_within_root(path_to_check: str, root_directory: str) -> bool:
    """
    检查路径是否在给定的根目录内
    :param path_to_check: 要检查的绝对路径
    :param root_directory: 绝对根目录
    :return: 如果路径在根目录内则返回 True，否则返回 False
    """
    normalized_path_to_check = os.path.normpath(os.path.abspath(path_to_check))
    normalized_root_directory = os.path.normpath(os.path.abspath(root_directory))

    # 确保根目录路径以分隔符结尾，以便正确进行 startsWith 比较
    # 除非它本身就是根路径（例如 '/' 或 'C:\'）
    if normalized_root_directory != os.path.sep and not normalized_root_directory.endswith(os.path.sep):
        root_with_separator = normalized_root_directory + os.path.sep
    else:
        root_with_separator = normalized_root_directory

    return (normalized_path_to_check == normalized_root_directory or
            normalized_path_to_check.startswith(root_with_separator))


async def is_binary_file(file_path: str) -> bool:
    """
    基于内容采样确定文件是否可能是二进制文件
    :param file_path: 文件路径
    :return: 如果文件看起来是二进制文件，则返回 True 的异步函数
    """
    try:
        # 以二进制模式打开文件
        with open(file_path, 'rb') as file_handle:
            # 获取文件大小
            file_size = os.fstat(file_handle.fileno()).st_size
            if file_size == 0:
                # 空文件不被视为二进制文件
                return False

            # 读取最多 4KB 或文件大小，取较小值
            buffer_size = min(4096, file_size)
            buffer = file_handle.read(buffer_size)
            bytes_read = len(buffer)

            if bytes_read == 0:
                return False

            non_printable_count = 0
            for byte in buffer:
                if byte == 0:
                    return True  # 空字节是强指示器
                if byte < 9 or (byte > 13 and byte < 32):
                    non_printable_count += 1

            # 如果 >30% 是非打印字符，则认为是二进制文件
            return non_printable_count / bytes_read > 0.3
    except Exception as e:
        # 记录错误用于调试，同时保持现有行为
        print(f"Failed to check if file is binary: {file_path}", str(e))
        # 如果发生任何错误（例如文件未找到，权限问题），
        # 在这里视为非二进制文件；让更高级别的函数处理存在/访问错误
        return False


async def detect_file_type(
    file_path: str
) -> str:
    """
    基于扩展名和内容检测文件类型
    :param file_path: 文件路径
    :return: 'text', 'image', 'pdf', 'audio', 'video', 'binary' 或 'svg'
    """
    ext = pathlib.Path(file_path).suffix.lower()

    # .ts 扩展名的 MIME 类型是 MPEG 传输流（视频格式），但我们希望将其视为 typescript 文件
    if ext == '.ts':
        return 'text'

    if ext == '.svg':
        return 'svg'

    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        if mime_type.startswith('image/'):
            return 'image'
        if mime_type.startswith('audio/'):
            return 'audio'
        if mime_type.startswith('video/'):
            return 'video'
        if mime_type == 'application/pdf':
            return 'pdf'

    # 对于常见的非文本扩展名进行更严格的二进制检查
    binary_extensions = [
        '.zip', '.tar', '.gz', '.exe', '.dll', '.so', '.class', '.jar',
        '.war', '.7z', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.odt', '.ods', '.odp', '.bin', '.dat', '.obj', '.o', '.a', '.lib',
        '.wasm', '.pyc', '.pyo'
    ]
    if ext in binary_extensions:
        return 'binary'

    # 如果 MIME 类型不能确定为图像/PDF，并且不是已知的二进制扩展名，则回退到基于内容的检查
    if await is_binary_file(file_path):
        return 'binary'

    return 'text'


@dataclass
class ProcessedFileReadResult:
    llm_content: PartUnion
    return_display: str
    error: Optional[str] = None
    is_truncated: Optional[bool] = None
    original_line_count: Optional[int] = None
    lines_shown: Optional[Tuple[int, int]] = None


async def process_single_file_content(
    file_path: str,
    root_directory: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> ProcessedFileReadResult:
    """
    读取并处理单个文件，处理文本、图像和PDF
    :param file_path: 文件的绝对路径
    :param root_directory: 项目根目录的绝对路径，用于显示相对路径
    :param offset: 文本文件的可选偏移量（基于0的行号）
    :param limit: 文本文件的可选限制（要读取的行数）
    :return: ProcessedFileReadResult 对象
    """
    try:
        if not os.path.exists(file_path):
            return ProcessedFileReadResult(
                llm_content='',
                return_display='File not found.',
                error=f'File not found: {file_path}'
            )

        stats = os.stat(file_path)
        if os.path.isdir(file_path):
            return ProcessedFileReadResult(
                llm_content='',
                return_display='Path is a directory.',
                error=f'Path is a directory, not a file: {file_path}'
            )

        file_size_in_bytes = stats.st_size
        # 20MB 限制
        max_file_size = 20 * 1024 * 1024

        if file_size_in_bytes > max_file_size:
            raise Exception(
                f'File size exceeds the 20MB limit: {file_path} ({(file_size_in_bytes / (1024 * 1024)):.2f}MB)'
            )

        file_type = await detect_file_type(file_path)
        relative_path_for_display = os.path.relpath(file_path, root_directory).replace('\\', '/')

        if file_type == 'binary':
            return ProcessedFileReadResult(
                llm_content=f'Cannot display content of binary file: {relative_path_for_display}',
                return_display=f'Skipped binary file: {relative_path_for_display}'
            )
        elif file_type == 'svg':
            SVG_MAX_SIZE_BYTES = 1 * 1024 * 1024
            if file_size_in_bytes > SVG_MAX_SIZE_BYTES:
                return ProcessedFileReadResult(
                    llm_content=f'Cannot display content of SVG file larger than 1MB: {relative_path_for_display}',
                    return_display=f'Skipped large SVG file (>1MB): {relative_path_for_display}'
                )
            with open(file_path, 'r', encoding=DEFAULT_ENCODING) as f:
                content = f.read()
            return ProcessedFileReadResult(
                llm_content=content,
                return_display=f'Read SVG as text: {relative_path_for_display}'
            )
        elif file_type == 'text':
            with open(file_path, 'r', encoding=DEFAULT_ENCODING) as f:
                content = f.read()
            lines = content.split('\n')
            original_line_count = len(lines)

            start_line = offset or 0
            effective_limit = limit if limit is not None else DEFAULT_MAX_LINES_TEXT_FILE
            # 确保 endLine 不超过 originalLineCount
            end_line = min(start_line + effective_limit, original_line_count)
            # 确保 selectedLines 不会尝试切片超出数组边界
            actual_start_line = min(start_line, original_line_count)
            selected_lines = lines[actual_start_line:end_line]

            lines_were_truncated_in_length = False
            formatted_lines = []
            for line in selected_lines:
                if len(line) > MAX_LINE_LENGTH_TEXT_FILE:
                    lines_were_truncated_in_length = True
                    formatted_lines.append(line[:MAX_LINE_LENGTH_TEXT_FILE] + '... [truncated]')
                else:
                    formatted_lines.append(line)

            content_range_truncated = end_line < original_line_count
            is_truncated = content_range_truncated or lines_were_truncated_in_length

            llm_text_content = ''
            if content_range_truncated:
                llm_text_content += f'[File content truncated: showing lines {actual_start_line + 1}-{end_line} of {original_line_count} total lines. Use offset/limit parameters to view more.]\n'
            elif lines_were_truncated_in_length:
                llm_text_content += f'[File content partially truncated: some lines exceeded maximum length of {MAX_LINE_LENGTH_TEXT_FILE} characters.]\n'
            llm_text_content += '\n'.join(formatted_lines)

            # 默认情况下，不返回任何内容以简化成功读取文件的常见情况
            return_display = ''
            if content_range_truncated:
                return_display = f'Read lines {actual_start_line + 1}-{end_line} of {original_line_count} from {relative_path_for_display}'
                if lines_were_truncated_in_length:
                    return_display += ' (some lines were shortened)'
            elif lines_were_truncated_in_length:
                return_display = f'Read all {original_line_count} lines from {relative_path_for_display} (some lines were shortened)'

            return ProcessedFileReadResult(
                llm_content=llm_text_content,
                return_display=return_display,
                is_truncated=is_truncated,
                original_line_count=original_line_count,
                lines_shown=(actual_start_line + 1, end_line)
            )
        elif file_type in ['image', 'pdf', 'audio', 'video']:
            with open(file_path, 'rb') as f:
                content_buffer = f.read()
            base64_data = content_buffer.hex()  # 在实际应用中，这里应该使用 base64 编码
            mime_type, _ = mimetypes.guess_type(file_path)
            return ProcessedFileReadResult(
                llm_content={
                    'inlineData': {
                        'data': base64_data,
                        'mimeType': mime_type or 'application/octet-stream'
                    }
                },
                return_display=f'Read {file_type} file: {relative_path_for_display}'
            )
        else:
            # 不应该发生，因为 detect_file_type 应该涵盖所有情况
            return ProcessedFileReadResult(
                llm_content=f'Unhandled file type: {file_type}',
                return_display=f'Skipped unhandled file type: {relative_path_for_display}',
                error=f'Unhandled file type for {file_path}'
            )
    except Exception as e:
        error_message = str(e)
        display_path = os.path.relpath(file_path, root_directory).replace('\\', '/')
        return ProcessedFileReadResult(
            llm_content=f'Error reading file {display_path}: {error_message}',
            return_display=f'Error reading file {display_path}: {error_message}',
            error=f'Error reading file {file_path}: {error_message}'
        )
    """
    读取并处理单个文件，处理文本、图像和PDF
    :param file_path: 文件的绝对路径
    :param root_directory: 项目根目录的绝对路径，用于显示相对路径
    :param offset: 文本文件的可选偏移量（基于0的行号）
    :param limit: 文本文件的可选限制（要读取的行数）
    :return: ProcessedFileReadResult 对象
    """
    try:
        if not os.path.exists(file_path):
            return ProcessedFileReadResult(
                llm_content='',
                return_display='File not found.',
                error=f'File not found: {file_path}'
            )

        stats = os.stat(file_path)
        if os.path.isdir(file_path):
            return ProcessedFileReadResult(
                llm_content='',
                return_display='Path is a directory.',
                error=f'Path is a directory, not a file: {file_path}'
            )

        file_size_in_bytes = stats.st_size
        # 20MB 限制
        max_file_size = 20 * 1024 * 1024

        if file_size_in_bytes > max_file_size:
            raise Exception(
                f'File size exceeds the 20MB limit: {file_path} ({(file_size_in_bytes / (1024 * 1024)):.2f}MB)'
            )

        file_type = await detect_file_type(file_path)
        relative_path_for_display = os.path.relpath(file_path, root_directory).replace('\\', '/')

        if file_type == 'binary':
            return ProcessedFileReadResult(
                llm_content=f'Cannot display content of binary file: {relative_path_for_display}',
                return_display=f'Skipped binary file: {relative_path_for_display}'
            )
        elif file_type == 'svg':
            SVG_MAX_SIZE_BYTES = 1 * 1024 * 1024
            if file_size_in_bytes > SVG_MAX_SIZE_BYTES:
                return ProcessedFileReadResult(
                    llm_content=f'Cannot display content of SVG file larger than 1MB: {relative_path_for_display}',
                    return_display=f'Skipped large SVG file (>1MB): {relative_path_for_display}'
                )
            with open(file_path, 'r', encoding=DEFAULT_ENCODING) as f:
                content = f.read()
            return ProcessedFileReadResult(
                llm_content=content,
                return_display=f'Read SVG as text: {relative_path_for_display}'
            )
        elif file_type == 'text':
            with open(file_path, 'r', encoding=DEFAULT_ENCODING) as f:
                content = f.read()
            lines = content.split('\n')
            original_line_count = len(lines)

            start_line = offset or 0
            effective_limit = limit if limit is not None else DEFAULT_MAX_LINES_TEXT_FILE
            # 确保 endLine 不超过 originalLineCount
            end_line = min(start_line + effective_limit, original_line_count)
            # 确保 selectedLines 不会尝试切片超出数组边界
            actual_start_line = min(start_line, original_line_count)
            selected_lines = lines[actual_start_line:end_line]

            lines_were_truncated_in_length = False
            formatted_lines = []
            for line in selected_lines:
                if len(line) > MAX_LINE_LENGTH_TEXT_FILE:
                    lines_were_truncated_in_length = True
                    formatted_lines.append(line[:MAX_LINE_LENGTH_TEXT_FILE] + '... [truncated]')
                else:
                    formatted_lines.append(line)

            content_range_truncated = end_line < original_line_count
            is_truncated = content_range_truncated or lines_were_truncated_in_length

            llm_text_content = ''
            if content_range_truncated:
                llm_text_content += f'[File content truncated: showing lines {actual_start_line + 1}-{end_line} of {original_line_count} total lines. Use offset/limit parameters to view more.]\n'
            elif lines_were_truncated_in_length:
                llm_text_content += f'[File content partially truncated: some lines exceeded maximum length of {MAX_LINE_LENGTH_TEXT_FILE} characters.]\n'
            llm_text_content += '\n'.join(formatted_lines)

            # 默认情况下，不返回任何内容以简化成功读取文件的常见情况
            return_display = ''
            if content_range_truncated:
                return_display = f'Read lines {actual_start_line + 1}-{end_line} of {original_line_count} from {relative_path_for_display}'
                if lines_were_truncated_in_length:
                    return_display += ' (some lines were shortened)'
            elif lines_were_truncated_in_length:
                return_display = f'Read all {original_line_count} lines from {relative_path_for_display} (some lines were shortened)'

            return ProcessedFileReadResult(
                llm_content=llm_text_content,
                return_display=return_display,
                is_truncated=is_truncated,
                original_line_count=original_line_count,
                lines_shown=(actual_start_line + 1, end_line)
            )
        elif file_type in ['image', 'pdf', 'audio', 'video']:
            with open(file_path, 'rb') as f:
                content_buffer = f.read()
            base64_data = content_buffer.hex()  # 在实际应用中，这里应该使用 base64 编码
            mime_type, _ = mimetypes.guess_type(file_path)
            return ProcessedFileReadResult(
                llm_content={
                    'inlineData': {
                        'data': base64_data,
                        'mimeType': mime_type or 'application/octet-stream'
                    }
                },
                return_display=f'Read {file_type} file: {relative_path_for_display}'
            )
        else:
            # 不应该发生，因为 detect_file_type 应该涵盖所有情况
            return ProcessedFileReadResult(
                llm_content=f'Unhandled file type: {file_type}',
                return_display=f'Skipped unhandled file type: {relative_path_for_display}',
                error=f'Unhandled file type for {file_path}'
            )
    except Exception as e:
        error_message = str(e)
        display_path = os.path.relpath(file_path, root_directory).replace('\\', '/')
        return ProcessedFileReadResult(
            llm_content=f'Error reading file {display_path}: {error_message}',
            return_display=f'Error reading file {display_path}: {error_message}',
            error=f'Error reading file {file_path}: {error_message}'
        )