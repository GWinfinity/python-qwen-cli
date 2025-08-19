"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import os
import re
import hashlib
from pathlib import Path
from typing import List, Optional

GEMINI_DIR = '.qwen'
GOOGLE_ACCOUNTS_FILENAME = 'google_accounts.json'
TMP_DIR_NAME = 'tmp'
COMMANDS_DIR_NAME = 'commands'

"""
Special characters that need to be escaped in file paths for shell compatibility.
Includes: spaces, parentheses, brackets, braces, semicolons, ampersands, pipes,
asterisks, question marks, dollar signs, backticks, quotes, hash, and other shell metacharacters.
"""
SHELL_SPECIAL_CHARS = re.compile(r'[ 	()\[\]{};|*?$`\'"#&<>!~]')


def tildeify_path(path: str) -> str:
    """
    Replaces the home directory with a tilde.

    Args:
        path: The path to tildeify.

    Returns:
        The tildeified path.
    """
    home_dir = os.path.expanduser('~')
    if path.startswith(home_dir):
        return path.replace(home_dir, '~')
    return path


def shorten_path(file_path: str, max_len: int = 35) -> str:
    """
    Shortens a path string if it exceeds max_len, prioritizing the start and end segments.
    Example: /path/to/a/very/long/file.txt -> /path/.../long/file.txt
    """
    if len(file_path) <= max_len:
        return file_path

    parsed_path = Path(file_path)
    root = parsed_path.root
    separator = os.path.sep

    # Get segments of the path *after* the root
    relative_path = file_path[len(root):]
    segments = [s for s in relative_path.split(separator) if s != '']  # Filter out empty segments

    # Handle cases with no segments after root (e.g., "/", "C:\") or only one segment
    if len(segments) <= 1:
        # Fall back to simple start/end truncation for very short paths or single segments
        keep_len = max_len - 3 // 2
        # Ensure keep_len is not negative if max_len is very small
        if keep_len <= 0:
            return file_path[:max_len - 3] + '...'
        start = file_path[:keep_len]
        end = file_path[-keep_len:]
        return f"{start}...{end}"

    first_dir = segments[0]
    last_segment = segments[-1]
    start_component = root + first_dir

    end_part_segments: List[str] = []
    # Base length: separator + "..." + lastDir
    current_length = len(separator) + len(last_segment)

    # Iterate backwards through segments (excluding the first one)
    for i in range(len(segments) - 2, -1, -1):
        segment = segments[i]
        # Length needed if we add this segment: current + separator + segment
        length_with_segment = current_length + len(separator) + len(segment)

        if length_with_segment <= max_len:
            end_part_segments.insert(0, segment)  # Add to the beginning of the end part
            current_length = length_with_segment
        else:
            break

    result = separator.join(end_part_segments) + separator + last_segment

    if current_length > max_len:
        return result

    # Construct the final path
    result = start_component + separator + result

    # As a final check, if the result is somehow still too long
    # truncate the result string from the beginning, prefixing with "...".
    if len(result) > max_len:
        return '...' + result[-(max_len - 3):]

    return result


def make_relative(target_path: str, root_directory: str) -> str:
    """
    Calculates the relative path from a root directory to a target path.
    Ensures both paths are resolved before calculating.
    Returns '.' if the target path is the same as the root directory.

    Args:
        target_path: The absolute or relative path to make relative.
        root_directory: The absolute path of the directory to make the target path relative to.

    Returns:
        The relative path from root_directory to target_path.
    """
    resolved_target_path = os.path.resolve(target_path)
    resolved_root_directory = os.path.resolve(root_directory)

    relative_path = os.path.relpath(resolved_target_path, resolved_root_directory)

    # If the paths are the same, os.path.relpath returns '.', which is correct
    return relative_path


def escape_path(file_path: str) -> str:
    """
    Escapes special characters in a file path like macOS terminal does.
    Escapes: spaces, parentheses, brackets, braces, semicolons, ampersands, pipes,
    asterisks, question marks, dollar signs, backticks, quotes, hash, and other shell metacharacters.
    """
    result = []
    for i, char in enumerate(file_path):
        # Count consecutive backslashes before this character
        backslash_count = 0
        j = i - 1
        while j >= 0 and file_path[j] == '\\':
            backslash_count += 1
            j -= 1

        # Character is already escaped if there's an odd number of backslashes before it
        is_already_escaped = backslash_count % 2 == 1

        # Only escape if not already escaped
        if not is_already_escaped and SHELL_SPECIAL_CHARS.search(char):
            result.append('\\')
            result.append(char)
        else:
            result.append(char)
    return ''.join(result)


def unescape_path(file_path: str) -> str:
    """
    Unescapes special characters in a file path.
    Removes backslash escaping from shell metacharacters.
    """
    # Create a pattern that matches a backslash followed by any special character
    special_chars_pattern = SHELL_SPECIAL_CHARS.pattern[1:-1]  # Remove the []
    escaped_pattern = re.compile(f'\\\\([{special_chars_pattern}])')
    return escaped_pattern.sub(r'\1', file_path)


def get_project_hash(project_root: str) -> str:
    """
    Generates a unique hash for a project based on its root path.

    Args:
        project_root: The absolute path to the project's root directory.

    Returns:
        A SHA256 hash of the project root path.
    """
    return hashlib.sha256(project_root.encode()).hexdigest()


def get_project_temp_dir(project_root: str) -> str:
    """
    Generates a unique temporary directory path for a project.

    Args:
        project_root: The absolute path to the project's root directory.

    Returns:
        The path to the project's temporary directory.
    """
    hash_value = get_project_hash(project_root)
    return os.path.join(os.path.expanduser('~'), GEMINI_DIR, TMP_DIR_NAME, hash_value)


def get_user_commands_dir() -> str:
    """
    Returns the absolute path to the user-level commands directory.

    Returns:
        The path to the user's commands directory.
    """
    return os.path.join(os.path.expanduser('~'), GEMINI_DIR, COMMANDS_DIR_NAME)


def get_project_commands_dir(project_root: str) -> str:
    """
    Returns the absolute path to the project-level commands directory.

    Args:
        project_root: The absolute path to the project's root directory.

    Returns:
        The path to the project's commands directory.
    """
    return os.path.join(project_root, GEMINI_DIR, COMMANDS_DIR_NAME)