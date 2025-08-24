import asyncio
import os
import signal
import subprocess
from typing import Dict, List, Optional, Callable, Any, Union, Tuple
from enum import Enum
from dataclasses import dataclass
from ..utils.system_encoding import get_cached_encoding_for_buffer
from ..utils.text_utils import is_binary

SIGKILL_TIMEOUT_MS = 200


@dataclass
class ShellExecutionResult:
    """A structured result from a shell command execution."""
    raw_output: bytes
    output: str
    stdout: str
    stderr: str
    exit_code: Optional[int]
    signal: Optional[str]
    error: Optional[Exception]
    aborted: bool
    pid: Optional[int]


@dataclass
class ShellExecutionHandle:
    """A handle for an ongoing shell execution."""
    pid: Optional[int]
    result: asyncio.Future[ShellExecutionResult]


class ShellOutputEventType(Enum):
    DATA = 'data'
    BINARY_DETECTED = 'binary_detected'
    BINARY_PROGRESS = 'binary_progress'


@dataclass
class ShellOutputEvent:
    """Describes a structured event emitted during shell command execution."""
    type: ShellOutputEventType
    stream: Optional[str] = None  # 'stdout' or 'stderr' for DATA type
    chunk: Optional[str] = None   # For DATA type
    bytes_received: Optional[int] = None  # For BINARY_PROGRESS type


class ShellExecutionService:
    """
    A centralized service for executing shell commands with robust process
    management, cross-platform compatibility, and streaming output capabilities.
    """

    @staticmethod
    async def execute(
        command_to_execute: str,
        cwd: str,
        on_output_event: Callable[[ShellOutputEvent], None],
        abort_signal: asyncio.Event,
    ) -> ShellExecutionHandle:
        """
        Executes a shell command using subprocess, capturing all output and lifecycle events.

        Args:
            command_to_execute: The exact command string to run.
            cwd: The working directory to execute the command in.
            on_output_event: A callback for streaming structured events.
            abort_signal: An Event to signal termination of the process.

        Returns:
            An object containing the process ID (pid) and a future that
            resolves with the complete execution result.
        """
        is_windows = os.name == 'nt'

        # Prepare environment variables
        env = os.environ.copy()
        env['GEMINI_CLI'] = '1'

        # Determine shell to use
        shell = True
        if not is_windows:
            shell = '/bin/bash'

        # Create a future to hold the result
        result_future = asyncio.Future()

        try:
            # Start the subprocess
            process = subprocess.Popen(
                command_to_execute,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if is_windows else 0,
                text=False  # We'll handle decoding manually
            )

            # Create handle with pid and result future
            handle = ShellExecutionHandle(pid=process.pid, result=result_future)

            # Setup output handling
            stdout_buffer: List[bytes] = []
            stderr_buffer: List[bytes] = []
            output_chunks: List[bytes] = []
            stdout_str = ''
            stderr_str = ''
            error: Optional[Exception] = None
            exited = False
            is_streaming_raw_content = True
            MAX_SNIFF_SIZE = 4096
            sniffed_bytes = 0
            stdout_encoding = 'utf-8'
            stderr_encoding = 'utf-8'

            # Check for binary content in the first chunks
            def check_binary(buffer: bytes) -> None:
                nonlocal is_streaming_raw_content, sniffed_bytes
                if is_streaming_raw_content and sniffed_bytes < MAX_SNIFF_SIZE:
                    sniff_buffer = b''.join(output_chunks[:20])
                    sniffed_bytes = len(sniff_buffer)

                    if ShellExecutionService.is_binary(sniff_buffer):
                        is_streaming_raw_content = False
                        on_output_event(ShellOutputEvent(
                            type=ShellOutputEventType.BINARY_DETECTED
                        ))

            # Read stdout and stderr asynchronously
            async def read_stdout():
                nonlocal stdout_str, stdout_encoding
                while True:
                    chunk = await asyncio.to_thread(process.stdout.read1, 8192)
                    if not chunk:
                        break
                    stdout_buffer.append(chunk)
                    output_chunks.append(chunk)
                    check_binary(chunk)

                    if is_streaming_raw_content:
                        try:
                            decoded_chunk = chunk.decode(stdout_encoding)
                            stdout_str += decoded_chunk
                            on_output_event(ShellOutputEvent(
                                type=ShellOutputEventType.DATA,
                                stream='stdout',
                                chunk=decoded_chunk
                            ))
                        except UnicodeDecodeError:
                            # If decoding fails, try to detect encoding
                            stdout_encoding = ShellExecutionService.get_cached_encoding_for_buffer(chunk)
                            try:
                                decoded_chunk = chunk.decode(stdout_encoding)
                                stdout_str += decoded_chunk
                                on_output_event(ShellOutputEvent(
                                    type=ShellOutputEventType.DATA,
                                    stream='stdout',
                                    chunk=decoded_chunk
                                ))
                            except UnicodeDecodeError:
                                # If still failing, mark as binary
                                is_streaming_raw_content = False
                                on_output_event(ShellOutputEvent(
                                    type=ShellOutputEventType.BINARY_DETECTED
                                ))
                    else:
                        total_bytes = sum(len(c) for c in output_chunks)
                        on_output_event(ShellOutputEvent(
                            type=ShellOutputEventType.BINARY_PROGRESS,
                            bytes_received=total_bytes
                        ))

            async def read_stderr():
                nonlocal stderr_str, stderr_encoding
                while True:
                    chunk = await asyncio.to_thread(process.stderr.read1, 8192)
                    if not chunk:
                        break
                    stderr_buffer.append(chunk)
                    output_chunks.append(chunk)
                    check_binary(chunk)

                    if is_streaming_raw_content:
                        try:
                            decoded_chunk = chunk.decode(stderr_encoding)
                            stderr_str += decoded_chunk
                            on_output_event(ShellOutputEvent(
                                type=ShellOutputEventType.DATA,
                                stream='stderr',
                                chunk=decoded_chunk
                            ))
                        except UnicodeDecodeError:
                            # If decoding fails, try to detect encoding
                            stderr_encoding = ShellExecutionService.get_cached_encoding_for_buffer(chunk)
                            try:
                                decoded_chunk = chunk.decode(stderr_encoding)
                                stderr_str += decoded_chunk
                                on_output_event(ShellOutputEvent(
                                    type=ShellOutputEventType.DATA,
                                    stream='stderr',
                                    chunk=decoded_chunk
                                ))
                            except UnicodeDecodeError:
                                # If still failing, mark as binary
                                is_streaming_raw_content = False
                                on_output_event(ShellOutputEvent(
                                    type=ShellOutputEventType.BINARY_DETECTED
                                ))
                    else:
                        total_bytes = sum(len(c) for c in output_chunks)
                        on_output_event(ShellOutputEvent(
                            type=ShellOutputEventType.BINARY_PROGRESS,
                            bytes_received=total_bytes
                        ))

            # Setup abort handling
            async def handle_abort():
                nonlocal exited
                await abort_signal.wait()
                if process.pid and not exited:
                    if is_windows:
                        # Kill process tree on Windows
                        try:
                            subprocess.run(
                                ['taskkill', '/pid', str(process.pid), '/f', '/t'],
                                check=True
                            )
                        except subprocess.SubprocessError:
                            # Fallback to killing just the process
                            process.kill()
                    else:
                        try:
                            # Kill the entire process group
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            await asyncio.sleep(SIGKILL_TIMEOUT_MS / 1000)
                            if not exited:
                                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            # Fallback to killing just the process
                            if not exited:
                                process.kill()

            # Start reading output and abort handling
            stdout_task = asyncio.create_task(read_stdout())
            stderr_task = asyncio.create_task(read_stderr())
            abort_task = asyncio.create_task(handle_abort())

            # Wait for process to exit
            exit_code = await asyncio.to_thread(process.wait)
            exited = True

            # Cancel abort task since process has exited
            abort_task.cancel()

            # Wait for output reading to complete
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

            # Prepare final result
            raw_output = b''.join(output_chunks)
            output = stdout_str
            if stderr_str:
                output += f'\n{stderr_str}'

            result = ShellExecutionResult(
                raw_output=raw_output,
                output=output,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=exit_code,
                signal=None,  # Python doesn't provide signal that killed the process
                error=error,
                aborted=abort_signal.is_set(),
                pid=process.pid
            )

            # Resolve the future with the result
            result_future.set_result(result)

        except Exception as e:
            # Handle any errors during process creation
            result = ShellExecutionResult(
                raw_output=b'',
                output='',
                stdout='',
                stderr='',
                exit_code=None,
                signal=None,
                error=e,
                aborted=abort_signal.is_set(),
                pid=None
            )
            result_future.set_result(result)
            handle = ShellExecutionHandle(pid=None, result=result_future)

        return handle