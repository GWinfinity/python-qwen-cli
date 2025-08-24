import os
import sys
import pathlib
import tempfile
import asyncio
import time
from typing import Optional, Dict, Any, List, Set, TypedDict, Callable, Tuple
from google.genai.types import Type
from ..config.config import Config
from .tools import BaseTool, ToolResult, ToolCallConfirmationDetails, ToolExecuteConfirmationDetails, ToolConfirmationOutcome, Icon
from ..utils.schema_validator import SchemaValidator
from ..utils.errors import get_error_message
from ..utils.summarizer import summarize_tool_output
from ..services.shell_execution_service import ShellExecutionService, ShellOutputEvent
from ..utils.formatters import format_memory_usage
from ..utils.shell_utils import get_command_roots, is_command_allowed, strip_shell_wrapper

OUTPUT_UPDATE_INTERVAL_MS = 1000

class ShellToolParams(TypedDict):
    command: str
    description: Optional[str] = None
    directory: Optional[str] = None

class ShellTool(BaseTool):
    Name: str = 'run_shell_command'

    def __init__(self, config: Config):
        self.config = config
        self.allowlist: Set[str] = set()
        super().__init__(
            name=ShellTool.Name,
            display_name='Shell',
            description=
                "This tool executes a given shell command as `bash -c <command>`. Command can start background processes using `&`. "
                "Command is executed as a subprocess that leads its own process group. "
                "Command process group can be terminated as `kill -- -PGID` or signaled as `kill -s SIGNAL -- -PGID`."

                "The following information is returned:"

                "Command: Executed command.\n" +
                "Directory: Directory (relative to project root) where command was executed, or `(root)`.\n" +
                "Stdout: Output on stdout stream. Can be `(empty)` or partial on error and for any unwaited background processes.\n" +
                "Stderr: Output on stderr stream. Can be `(empty)` or partial on error and for any unwaited background processes.\n" +
                "Error: Error or `(none)` if no error was reported for the subprocess.\n" +
                "Exit Code: Exit code or `(none)` if terminated by signal.\n" +
                "Signal: Signal number or `(none)` if no signal was received.\n" +
                "Background PIDs: List of background processes started or `(none)`.\n" +
                "Process Group PGID: Process group started or `(none)`",
            icon=Icon.Terminal,
            parameters_schema={
                'type': Type.OBJECT,

                'properties': {
                    'command': {
                        'type': Type.STRING,
                        'description': 'Exact bash command to execute as `bash -c <command>`',
                    },
                    'description': {
                        'type': Type.STRING,
                        'description':
                            'Brief description of the command for the user. Be specific and concise. Ideally a single sentence. '+
                            'Can be up to 3 sentences for clarity. No line breaks.',
                    },
                    'directory': {
                        'type': Type.STRING,
                        'description':
                            '(OPTIONAL) Directory to run the command in, if not the project root directory. '+
                            'Must be relative to the project root directory and must already exist.',
                    },
                },
                'required': ['command'],
            },
            output_is_markdown=False,
            output_can_be_updated=True,
        )

    def get_description(self, params: ShellToolParams) -> str:
        description = f"{params['command']}"
        # append optional [in directory]
        if 'directory' in params and params['directory']:
            description += f" [in {params['directory']}]"
        # append optional (description), replacing any line breaks with spaces
        if 'description' in params and params['description']:
            description += f" ({params['description'].replace('\n', ' ')})"
        return description

    def validate_tool_params(self, params: ShellToolParams) -> Optional[str]:
        command_check = is_command_allowed(params['command'], self.config)
        if not command_check['allowed']:
            if not command_check['reason']:
                print('Unexpected: is_command_allowed returned false without a reason', file=sys.stderr)
                return f"Command is not allowed: {params['command']}"
            return command_check['reason']
        errors = SchemaValidator.validate(self.schema['parameters'], params)
        if errors:
            return errors
        if not params['command'].strip():
            return 'Command cannot be empty.'
        if len(get_command_roots(params['command'])) == 0:
            return 'Could not identify command root to obtain permission from user.'
        if 'directory' in params and params['directory']:
            if pathlib.Path(params['directory']).is_absolute():
                return 'Directory cannot be absolute. Please refer to workspace directories by their name.'
            workspace_dirs = self.config.get_workspace_context().get_directories()
            matching_dirs = [
                dir for dir in workspace_dirs
                if pathlib.Path(dir).name == params['directory']
            ]
            if len(matching_dirs) == 0:
                return f"Directory '{params['directory']}' is not a registered workspace directory."
            if len(matching_dirs) > 1:
                return f"Directory name '{params['directory']}' is ambiguous as it matches multiple workspace directories."
        return None

    async def should_confirm_execute(
        self, params: ShellToolParams, abort_signal
    ) -> Optional[ToolCallConfirmationDetails]:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return False  # skip confirmation, execute call will fail immediately

        command = strip_shell_wrapper(params['command'])
        root_commands = list(set(get_command_roots(command)))
        commands_to_confirm = [
            cmd for cmd in root_commands if cmd not in self.allowlist
        ]

        if len(commands_to_confirm) == 0:
            return False  # already approved and whitelisted

        async def on_confirm(outcome: ToolConfirmationOutcome) -> None:
            if outcome == ToolConfirmationOutcome.ProceedAlways:
                for cmd in commands_to_confirm:
                    self.allowlist.add(cmd)

        confirmation_details: ToolExecuteConfirmationDetails = {
            'type': 'exec',
            'title': 'Confirm Shell Command',
            'command': params['command'],
            'rootCommand': ', '.join(commands_to_confirm),
            'onConfirm': on_confirm,
        }
        return confirmation_details

    async def execute(
        self, params: ShellToolParams,
        signal: asyncio.AbstractEventLoop,
        update_output: Optional[Callable[[str], None]] = None
    ) -> ToolResult:
        stripped_command = strip_shell_wrapper(params['command'])
        validation_error = self.validate_tool_params({
            **params,
            'command': stripped_command
        })
        if validation_error:
            return {
                'llmContent': validation_error,
                'returnDisplay': validation_error,
            }

        if signal.is_set():
            return {
                'llmContent': 'Command was cancelled by user before it could start.',
                'returnDisplay': 'Command cancelled by user.',
            }

        is_windows = sys.platform == 'win32'
        temp_file = tempfile.NamedTemporaryFile(
            prefix='shell_pgrep_', suffix='.tmp', delete=False
        )
        temp_file_path = temp_file.name
        temp_file.close()

        try:
            # Add co-author to git commit commands
            processed_command = self.add_co_author_to_git_commit(stripped_command)

            # Prepare command to execute
            if is_windows:
                command_to_execute = processed_command
            else:
                # wrap command to append subprocess pids (via pgrep) to temporary file
                command = processed_command.strip()
                if not command.endswith('&'):
                    command += ';'
                command_to_execute = f"{{ {command} }}; __code=$?; pgrep -g 0 >{temp_file_path} 2>&1; exit $__code;"

            # Determine working directory
            target_dir = pathlib.Path(self.config.get_target_dir())
            cwd = target_dir / (params.get('directory') or '')
            cwd = cwd.resolve()

            cumulative_stdout = ''
            cumulative_stderr = ''
            last_update_time = time.time() * 1000
            is_binary_stream = False

            # Execute command
            result_promise = ShellExecutionService.execute(
                command_to_execute,
                str(cwd),
                lambda event: self._handle_output_event(
                    event, update_output, cumulative_stdout, cumulative_stderr,
                    last_update_time, is_binary_stream
                ),
                signal
            )

            result = await result_promise

            # Get background PIDs
            background_pids: List[int] = []
            if sys.platform != 'win32':
                if os.path.exists(temp_file_path):
                    with open(temp_file_path, 'r') as f:
                        pgrep_lines = f.read().split('\n')
                        for line in pgrep_lines:
                            line = line.strip()
                            if not line:
                                continue
                            if not line.isdigit():
                                print(f"pgrep: {line}", file=sys.stderr)
                                continue
                            pid = int(line)
                            if pid != result['pid']:
                                background_pids.append(pid)
                else:
                    if not signal.is_set():
                        print('missing pgrep output', file=sys.stderr)

            # Prepare LLM content
            llm_content = ''
            if result['aborted']:
                llm_content = 'Command was cancelled by user before it could complete.'
                if result['output'].strip():
                    llm_content += f" Below is the output (on stdout and stderr) before it was cancelled:\n{result['output']}"
                else:
                    llm_content += ' There was no output before it was cancelled.'
            else:
                # Clean error message
                final_error = '(none)'
                if result['error']:
                    final_error = str(result['error']).replace(command_to_execute, params['command'])

                llm_content = '\n'.join([
                    f"Command: {params['command']}",
                    f"Directory: {params.get('directory') or '(root)'}",
                    f"Stdout: {result['stdout'] or '(empty)'}",
                    f"Stderr: {result['stderr'] or '(empty)'}",
                    f"Error: {final_error}",
                    f"Exit Code: {result['exitCode'] if result['exitCode'] is not None else '(none)'}",
                    f"Signal: {result['signal'] if result['signal'] is not None else '(none)'}",
                    f"Background PIDs: {', '.join(map(str, background_pids)) if background_pids else '(none)'}",
                    f"Process Group PGID: {result['pid'] if result['pid'] is not None else '(none)'}",
                ])

            # Prepare return display message
            return_display_message = ''
            if self.config.get_debug_mode():
                return_display_message = llm_content
            else:
                if result['output'].strip():
                    return_display_message = result['output']
                else:
                    if result['aborted']:
                        return_display_message = 'Command cancelled by user.'
                    elif result['signal']:
                        return_display_message = f"Command terminated by signal: {result['signal']}"
                    elif result['error']:
                        return_display_message = f"Command failed: {get_error_message(result['error'])}"
                    elif result['exitCode'] is not None and result['exitCode'] != 0:
                        return_display_message = f"Command exited with code: {result['exitCode']}"
                    # If output is empty and command succeeded, leave it empty

            # Summarize output if configured
            summarize_config = self.config.get_summarize_tool_output_config()
            if summarize_config and self.name in summarize_config:
                summary = await summarize_tool_output(
                    llm_content,
                    self.config.get_gemini_client(),
                    signal,
                    summarize_config[self.name]['tokenBudget'],
                )
                return {
                    'llmContent': summary,
                    'returnDisplay': return_display_message,
                }

            return {
                'llmContent': llm_content,
                'returnDisplay': return_display_message,
            }

        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    print(f"Failed to delete temporary file {temp_file_path}: {e}", file=sys.stderr)

    def _handle_output_event(
        self, event: ShellOutputEvent, update_output: Optional[Callable[[str], None]],
        cumulative_stdout: str, cumulative_stderr: str, last_update_time: float,
        is_binary_stream: bool
    ) -> Tuple[str, str, float, bool]:
        if not update_output:
            return cumulative_stdout, cumulative_stderr, last_update_time, is_binary_stream

        current_display_output = ''
        should_update = False

        if event['type'] == 'data':
            if is_binary_stream:
                return cumulative_stdout, cumulative_stderr, last_update_time, is_binary_stream

            if event['stream'] == 'stdout':
                cumulative_stdout += event['chunk']
            else:
                cumulative_stderr += event['chunk']

            current_display_output = cumulative_stdout
            if cumulative_stderr:
                current_display_output += f"\n{cumulative_stderr}"

            current_time = time.time() * 1000
            if current_time - last_update_time > OUTPUT_UPDATE_INTERVAL_MS:
                should_update = True
                last_update_time = current_time

        elif event['type'] == 'binary_detected':
            is_binary_stream = True
            current_display_output = '[Binary output detected. Halting stream...]'
            should_update = True

        elif event['type'] == 'binary_progress':
            is_binary_stream = True
            current_display_output = f"[Receiving binary output... {format_memory_usage(event['bytesReceived'])} received]"
            current_time = time.time() * 1000
            if current_time - last_update_time > OUTPUT_UPDATE_INTERVAL_MS:
                should_update = True
                last_update_time = current_time

        else:
            raise ValueError(f"An unhandled ShellOutputEvent was found: {event['type']}")

        if should_update:
            update_output(current_display_output)

        return cumulative_stdout, cumulative_stderr, last_update_time, is_binary_stream

    def add_co_author_to_git_commit(self, command: str) -> str:
        # Check if co-author feature is enabled
        git_co_author_settings = self.config.get_git_co_author()
        if not git_co_author_settings or not git_co_author_settings.get('enabled', False):
            return command

        # Check if this is a git commit command
        import re
        git_commit_pattern = re.compile(r'^git\s+commit')
        if not git_commit_pattern.match(command.strip()):
            return command

        # Define the co-author line using configuration
        name = git_co_author_settings.get('name', '')
        email = git_co_author_settings.get('email', '')
        if not name or not email:
            return command

        co_author = f"\n\nCo-authored-by: {name} <{email}>"

        # Handle different git commit patterns
        # Match -m "message" or -m 'message'
        message_pattern = re.compile(r'(-m\s+)([\'"])((?:\\.|[^\\])*?)(\2)')
        match = message_pattern.search(command)

        if match:
            full_match, prefix, quote, existing_message, closing_quote = match.groups()
            new_message = existing_message + co_author
            replacement = f"{prefix}{quote}{new_message}{closing_quote}"
            return command.replace(full_match, replacement)

        # If no -m flag found, return as-is
        return command