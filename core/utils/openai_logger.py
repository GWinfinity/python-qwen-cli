import os
import pathlib
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List


class OpenAILogger:
    """Logger specifically for OpenAI API requests and responses"""
    def __init__(self, custom_log_dir: Optional[str] = None):
        """
        Creates a new OpenAI logger

        Args:
            custom_log_dir: Optional custom log directory path
        """
        if custom_log_dir:
            self.log_dir = custom_log_dir
        else:
            self.log_dir = os.path.join(os.getcwd(), 'logs', 'openai')
        self.initialized = False

    async def initialize(self) -> None:
        """Initialize the logger by creating the log directory if it doesn't exist"""
        if self.initialized:
            return

        try:
            os.makedirs(self.log_dir, exist_ok=True)
            self.initialized = True
        except Exception as error:
            print(f'Failed to initialize OpenAI logger: {error}')
            raise RuntimeError(f'Failed to initialize OpenAI logger: {error}') from error

    async def log_interaction(
        self,
        request: Any,
        response: Optional[Any] = None,
        error: Optional[Exception] = None
    ) -> str:
        """
        Logs an OpenAI API request and its response

        Args:
            request: The request sent to OpenAI
            response: The response received from OpenAI
            error: Optional error if the request failed

        Returns:
            The file path where the log was written
        """
        if not self.initialized:
            await self.initialize()

        timestamp = datetime.now().isoformat().replace(':', '-')
        id = str(uuid.uuid4())[:8]
        filename = f'openai-{timestamp}-{id}.json'
        file_path = os.path.join(self.log_dir, filename)

        log_data: Dict[str, Any] = {
            'timestamp': datetime.now().isoformat(),
            'request': request,
            'response': response if response is not None else None,
            'error': None,
            'system': {
                'hostname': os.uname().nodename,
                'platform': os.uname().sysname,
                'release': os.uname().release,
                'pythonVersion': f'{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}'
            }
        }

        if error:
            log_data['error'] = {
                'message': str(error),
                'stack': error.__traceback__.__str__() if error.__traceback__ else None
            }

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
            return file_path
        except Exception as write_error:
            print(f'Failed to write OpenAI log file: {write_error}')
            raise RuntimeError(f'Failed to write OpenAI log file: {write_error}') from write_error

    async def get_log_files(self, limit: Optional[int] = None) -> List[str]:
        """
        Get all logged interactions

        Args:
            limit: Optional limit on the number of log files to return (sorted by most recent first)

        Returns:
            Array of log file paths
        """
        if not self.initialized:
            await self.initialize()

        try:
            files = os.listdir(self.log_dir)
            log_files = [
                os.path.join(self.log_dir, file)
                for file in files
                if file.startswith('openai-') and file.endswith('.json')
            ]
            # Sort by filename (which includes timestamp) in reverse order (newest first)
            log_files.sort(reverse=True)

            return log_files[:limit] if limit else log_files
        except FileNotFoundError:
            return []
        except Exception as error:
            print(f'Failed to read OpenAI log directory: {error}')
            return []

    async def read_log_file(self, file_path: str) -> Any:
        """
        Read a specific log file

        Args:
            file_path: The path to the log file

        Returns:
            The log file content
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as error:
            print(f'Failed to read log file {file_path}: {error}')
            raise RuntimeError(f'Failed to read log file: {error}') from error


# Create a singleton instance for easy import
openai_logger = OpenAILogger()