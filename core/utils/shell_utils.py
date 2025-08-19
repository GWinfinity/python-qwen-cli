"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import re
from typing import List, Optional, Set, Dict, Any
from ..config.config import Config


def split_commands(command: str) -> List[str]:
    """
    Splits a shell command into a list of individual commands, respecting quotes.
    This is used to separate chained commands (e.g., using &&, ||, ;).

    Args:
        command: The shell command string to parse

    Returns:
        An array of individual command strings
    """
    commands: List[str] = []
    current_command = ''
    in_single_quotes = False
    in_double_quotes = False
    i = 0

    while i < len(command):
        char = command[i]
        next_char = command[i + 1] if i < len(command) - 1 else ''

        if char == '\\' and i < len(command) - 1:
            current_command += char + command[i + 1]
            i += 2
            continue

        if char == "'" and not in_double_quotes:
            in_single_quotes = not in_single_quotes
        elif char == '"' and not in_single_quotes:
            in_double_quotes = not in_double_quotes

        if not in_single_quotes and not in_double_quotes:
            if (
                (char == '&' and next_char == '&') or
                (char == '|' and next_char == '|')
            ):
                commands.append(current_command.strip())
                current_command = ''
                i += 1  # Skip the next character
            elif char in [';', '&', '|']:
                commands.append(current_command.strip())
                current_command = ''
            else:
                current_command += char
        else:
            current_command += char
        i += 1

    if current_command.strip():
        commands.append(current_command.strip())

    return [cmd for cmd in commands if cmd]  # Filter out any empty strings


def get_command_root(command: str) -> Optional[str]:
    """
    Extracts the root command from a given shell command string.
    This is used to identify the base command for permission checks.

    Args:
        command: The shell command string to parse

    Returns:
        The root command name, or None if it cannot be determined

    Examples:
        >>> get_command_root("ls -la /tmp")
        'ls'
        >>> get_command_root("git status && npm test")
        'git'
    """
    trimmed_command = command.strip()
    if not trimmed_command:
        return None

    # This regex is designed to find the first "word" of a command,
    # while respecting quotes. It looks for a sequence of non-whitespace
    # characters that are not inside quotes.
    match = re.match(r'^"([^"]+)"|^\'([^\']+)\'|^(\S+)', trimmed_command)
    if match:
        # The first element in the match array is the full match.
        # The subsequent elements are the capture groups.
        # We prefer a captured group because it will be unquoted.
        command_root = match.group(1) or match.group(2) or match.group(3)
        if command_root:
            # If the command is a path, return the last component.
            return command_root.split('\\').pop().split('/').pop()

    return None


def get_command_roots(command: str) -> List[str]:
    """
    Extracts root commands from all individual commands in a shell command string.

    Args:
        command: The shell command string to parse

    Returns:
        A list of root command names
    """
    if not command:
        return []
    return [
        cmd for cmd in (
            get_command_root(c) for c in split_commands(command)
        ) if cmd is not None
    ]


def strip_shell_wrapper(command: str) -> str:
    """
    Removes shell wrapper commands (like sh -c, bash -c) from the start of a command.

    Args:
        command: The shell command string to process

    Returns:
        The command with shell wrappers removed
    """
    pattern = r'^\s*(?:sh|bash|zsh|cmd\.exe)\s+(?:\/c|-c)\s+'
    match = re.match(pattern, command)
    if match:
        new_command = command[len(match.group(0)):].strip()
        if (
            (new_command.startswith('"') and new_command.endswith('"')) or
            (new_command.startswith("'") and new_command.endswith("'"))
        ):
            new_command = new_command[1:-1]
        return new_command
    return command.strip()


def detect_command_substitution(command: str) -> bool:
    """
    Detects command substitution patterns in a shell command, following bash quoting rules:
    - Single quotes ('): Everything literal, no substitution possible
    - Double quotes ("): Command substitution with $() and backticks unless escaped with \
    - No quotes: Command substitution with $(), <(), and backticks

    Args:
        command: The shell command string to check

    Returns:
        True if command substitution would be executed by bash
    """
    in_single_quotes = False
    in_double_quotes = False
    in_backticks = False
    i = 0

    while i < len(command):
        char = command[i]
        next_char = command[i + 1] if i < len(command) - 1 else ''

        # Handle escaping - only works outside single quotes
        if char == '\\' and not in_single_quotes:
            i += 2  # Skip the escaped character
            continue

        # Handle quote state changes
        if char == "'" and not in_double_quotes and not in_backticks:
            in_single_quotes = not in_single_quotes
        elif char == '"' and not in_single_quotes and not in_backticks:
            in_double_quotes = not in_double_quotes
        elif char == '`' and not in_single_quotes:
            # Backticks work outside single quotes (including in double quotes)
            in_backticks = not in_backticks

        # Check for command substitution patterns that would be executed
        if not in_single_quotes:
            # $(...) command substitution - works in double quotes and unquoted
            if char == '$' and next_char == '(':
                return True

            # <(...) process substitution - works unquoted only (not in double quotes)
            if char == '<' and next_char == '(' and not in_double_quotes and not in_backticks:
                return True

            # Backtick command substitution - check for opening backtick
            # (We track the state above, so this catches the start of backtick substitution)
            if char == '`' and not in_backticks:
                return True

        i += 1

    return False


def check_command_permissions(
    command: str,
    config: Config,
    session_allowlist: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Checks a shell command against security policies and allowlists.

    This function operates in one of two modes depending on the presence of
    the `session_allowlist` parameter:

    1.  **"Default Deny" Mode (session_allowlist is provided):** This is the
        strictest mode, used for user-defined scripts like custom commands.
        A command is only permitted if it is found on the global `coreTools`
        allowlist OR the provided `session_allowlist`. It must not be on the
        global `excludeTools` blocklist.

    2.  **"Default Allow" Mode (session_allowlist is NOT provided):** This mode
        is used for direct tool invocations (e.g., by the model). If a strict
        global `coreTools` allowlist exists, commands must be on it. Otherwise,
        any command is permitted as long as it is not on the `excludeTools`
        blocklist.

    Args:
        command: The shell command string to validate.
        config: The application configuration.
        session_allowlist: A session-level list of approved commands. Its
            presence activates "Default Deny" mode.

    Returns:
        An object detailing which commands are not allowed.
    """
    # Disallow command substitution for security.
    if detect_command_substitution(command):
        return {
            'allAllowed': False,
            'disallowedCommands': [command],
            'blockReason': 'Command substitution using $(), <(), or >() is not allowed for security reasons',
            'isHardDenial': True,
        }

    SHELL_TOOL_NAMES = ['run_shell_command', 'ShellTool']
    normalize = lambda cmd: cmd.strip().replace('\s+', ' ', re.DOTALL)

    def is_prefixed_by(cmd: str, prefix: str) -> bool:
        if not cmd.startswith(prefix):
            return False
        return len(cmd) == len(prefix) or cmd[len(prefix)] == ' '

    def extract_commands(tools: List[str]) -> List[str]:
        result = []
        for tool in tools:
            for tool_name in SHELL_TOOL_NAMES:
                if tool.startswith(f'{tool_name}(') and tool.endswith(')'):
                    result.append(normalize(tool[len(tool_name) + 1:-1]))
        return result

    core_tools = config.get_core_tools() or []
    exclude_tools = config.get_exclude_tools() or []
    commands_to_validate = split_commands(command)

    # 1. Blocklist Check (Highest Priority)
    if any(tool_name in exclude_tools for tool_name in SHELL_TOOL_NAMES):
        return {
            'allAllowed': False,
            'disallowedCommands': commands_to_validate,
            'blockReason': 'Shell tool is globally disabled in configuration',
            'isHardDenial': True,
        }
    blocked_commands = extract_commands(exclude_tools)
    for cmd in commands_to_validate:
        if any(is_prefixed_by(cmd, blocked) for blocked in blocked_commands):
            return {
                'allAllowed': False,
                'disallowedCommands': [cmd],
                'blockReason': f"Command '{cmd}' is blocked by configuration",
                'isHardDenial': True,
            }

    globally_allowed_commands = extract_commands(core_tools)
    is_wildcard_allowed = any(tool_name in core_tools for tool_name in SHELL_TOOL_NAMES)

    # If there's a global wildcard, all commands are allowed at this point
    # because they have already passed the blocklist check.
    if is_wildcard_allowed:
        return {'allAllowed': True, 'disallowedCommands': []}

    if session_allowlist:
        # "DEFAULT DENY" MODE: A session allowlist is provided.
        # All commands must be in either the session or global allowlist.
        disallowed_commands: List[str] = []
        for cmd in commands_to_validate:
            is_session_allowed = any(
                is_prefixed_by(cmd, normalize(allowed))
                for allowed in session_allowlist
            )
            if is_session_allowed:
                continue

            is_globally_allowed = any(
                is_prefixed_by(cmd, allowed)
                for allowed in globally_allowed_commands
            )
            if is_globally_allowed:
                continue

            disallowed_commands.append(cmd)

        if disallowed_commands:
            return {
                'allAllowed': False,
                'disallowedCommands': disallowed_commands,
                'blockReason': 'Command(s) not on the global or session allowlist.',
                'isHardDenial': False,  # This is a soft denial; confirmation is possible.
            }
    else:
        # "DEFAULT ALLOW" MODE: No session allowlist.
        has_specific_allowed_commands = bool(globally_allowed_commands)
        if has_specific_allowed_commands:
            disallowed_commands: List[str] = []
            for cmd in commands_to_validate:
                is_globally_allowed = any(
                    is_prefixed_by(cmd, allowed)
                    for allowed in globally_allowed_commands
                )
                if not is_globally_allowed:
                    disallowed_commands.append(cmd)
            if disallowed_commands:
                return {
                    'allAllowed': False,
                    'disallowedCommands': disallowed_commands,
                    'blockReason': 'Command(s) not in the allowed commands list.',
                    'isHardDenial': False,  # This is a soft denial.
                }
        # If no specific global allowlist exists, and it passed the blocklist,
        # the command is allowed by default.

    # If all checks for the current mode pass, the command is allowed.
    return {'allAllowed': True, 'disallowedCommands': []}


def is_command_allowed(
    command: str,
    config: Config,
) -> Dict[str, Any]:
    """
    Determines whether a given shell command is allowed to execute based on
    the tool's configuration including allowlists and blocklists.

    This function operates in "default allow" mode. It is a wrapper around
    `check_command_permissions`.

    Args:
        command: The shell command string to validate.
        config: The application configuration.

    Returns:
        An object with 'allowed' boolean and optional 'reason' string if not allowed.
    """
    # By not providing a session_allowlist, we invoke "default allow" behavior.
    result = check_command_permissions(command, config)
    if result['allAllowed']:
        return {'allowed': True}
    return {'allowed': False, 'reason': result.get('blockReason')}