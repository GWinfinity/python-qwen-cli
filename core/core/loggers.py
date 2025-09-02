import os
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from google.genai import Content
from ..utils.paths import get_project_temp_dir

LOG_FILE_NAME = 'logs.json'

class MessageSenderType:
    USER = 'user'

class LogEntry:
    def __init__(self, session_id: str, message_id: int, timestamp: str, type: str, message: str):
        self.session_id = session_id
        self.message_id = message_id
        self.timestamp = timestamp
        self.type = type
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sessionId': self.session_id,
            'messageId': self.message_id,
            'timestamp': self.timestamp,
            'type': self.type,
            'message': self.message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LogEntry':
        return cls(
            session_id=data['sessionId'],
            message_id=data['messageId'],
            timestamp=data['timestamp'],
            type=data['type'],
            message=data['message']
        )

class Logger:
    def __init__(self, session_id: str):
        self.qwen_dir: Optional[str] = None
        self.log_file_path: Optional[str] = None
        self.session_id: Optional[str] = session_id
        self.message_id = 0  
        self.initialized = False
        self.logs: List[LogEntry] = []  

    async def _read_log_file(self) -> List[LogEntry]:
        if not self.log_file_path:
            raise ValueError('Log file path not set during read attempt.')
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as file:
                file_content = file.read()
                parsed_logs = json.loads(file_content)
                if not isinstance(parsed_logs, list):
                    print(f"Log file at {self.log_file_path} is not a valid JSON array. Starting with empty logs.")
                    await self._backup_corrupted_log_file('malformed_array')
                    return []
                return [
                    LogEntry.from_dict(entry)
                    for entry in parsed_logs
                    if (
                        isinstance(entry.get('sessionId'), str) and
                        isinstance(entry.get('messageId'), int) and
                        isinstance(entry.get('timestamp'), str) and
                        isinstance(entry.get('type'), str) and
                        isinstance(entry.get('message'), str)
                    )
                ]
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in log file {self.log_file_path}. Backing up and starting fresh.", e)
            await self._backup_corrupted_log_file('invalid_json')
            return []
        except Exception as e:
            print(f"Failed to read or parse log file {self.log_file_path}:", e)
            raise

    async def _backup_corrupted_log_file(self, reason: str) -> None:
        if not self.log_file_path:
            return
        backup_path = f"{self.log_file_path}.{reason}.{int(datetime.now().timestamp())}.bak"
        try:
            if os.path.exists(self.log_file_path):
                os.rename(self.log_file_path, backup_path)
                print(f"Backed up corrupted log file to {backup_path}")
        except Exception:
            
            pass

    async def initialize(self) -> None:
        if self.initialized:
            return


        self.qwen_dir = get_project_temp_dir(os.getcwd())
        self.log_file_path = os.path.join(self.qwen_dir, LOG_FILE_NAME)

        try:
            os.makedirs(self.qwen_dir, exist_ok=True)
            file_existed = os.path.exists(self.log_file_path)
            self.logs = await self._read_log_file()
            if not file_existed and not self.logs:
                with open(self.log_file_path, 'w', encoding='utf-8') as file:
                    file.write('[]')
            session_logs = [entry for entry in self.logs if entry.session_id == self.session_id]
            self.message_id = max(entry.message_id for entry in session_logs) + 1 if session_logs else 0
            self.initialized = True
        except Exception as err:
            print('Failed to initialize logger:', err)
            self.initialized = False

    async def __update_log_file(self, entry_to_append: LogEntry) -> Optional[LogEntry]:
        if not self.log_file_path:
            print('Log file path not set. Cannot persist log entry.')
            raise ValueError('Log file path not set during update attempt.')

        try:
            current_logs_on_disk = await self._read_log_file()
        except Exception as read_error:
            print('Critical error reading log file before append:', read_error)
            raise


        session_logs_on_disk = [e for e in current_logs_on_disk if e.session_id == entry_to_append.session_id]
        next_message_id_for_session = max(e.message_id for e in session_logs_on_disk) + 1 if session_logs_on_disk else 0

        entry_to_append.message_id = next_message_id_for_session


        entry_exists = any(
            e.session_id == entry_to_append.session_id and
            e.message_id == entry_to_append.message_id and
            e.timestamp == entry_to_append.timestamp and 
            e.message == entry_to_append.message
            for e in current_logs_on_disk
        )

        if entry_exists:
            print(f"Duplicate log entry detected and skipped: session {entry_to_append.session_id}, messageId {entry_to_append.message_id}")
            self.logs = current_logs_on_disk 
            return None  

        current_logs_on_disk.append(entry_to_append)

        try:
            with open(self.log_file_path, 'w', encoding='utf-8') as file:
                json.dump([entry.to_dict() for entry in current_logs_on_disk], file, indent=2, ensure_ascii=False)
            self.logs = current_logs_on_disk
            return entry_to_append  
        except Exception as error:
            print('Error writing to log file:', error)
            raise

    async def get_previous_user_messages(self) -> List[str]:
        if not self.initialized:
            return []

        user_logs = [entry for entry in self.logs if entry.type == MessageSenderType.USER]
        user_logs.sort(key=lambda x: datetime.fromisoformat(x.timestamp), reverse=True)
        return [entry.message for entry in user_logs]

    async def log_message(self, type: str, message: str) -> None:
        if not self.initialized or self.session_id is None:
            print('Logger not initialized or session ID missing. Cannot log message.')
            return


        new_entry = LogEntry(
            session_id=self.session_id,
            message_id=self.message_id,  
            type=type,
            message=message,
            timestamp=datetime.now().isoformat()
        )

        try:
            written_entry = await self.__update_log_file(new_entry)
            if written_entry:
          
                self.message_id = written_entry.message_id + 1
        except Exception:
            # Error already logged by _updateLogFile or _readLogFile
            pass

    def checkpoint_path(self, tag: str) -> str:
        if not tag:
            raise ValueError('No checkpoint tag specified.')
        if not self.qwen_dir:
            raise ValueError('Checkpoint file path not set.')
        #Sanitize tag to prevent directory traversal attacks
        sanitized_tag = re.sub(r'[^a-zA-Z0-9-_]', '', tag)
        if not sanitized_tag:
            sanitized_tag = 'default'
        return os.path.join(self.qwen_dir, f'checkpoint-{sanitized_tag}.json')

    async def save_checkpoint(self, conversation: Content, tag: str) -> None:
        if not self.initialized:
            print('Logger not initialized or checkpoint file path not set. Cannot save a checkpoint.')
            return
        path = self.checkpoint_path(tag)
        try:
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(conversation, file, indent=2, ensure_ascii=False)
        except Exception as error:
            print('Error writing to checkpoint file:', error)

    async def load_checkpoint(self, tag: str) -> Content:
        if not self.initialized:
            print('Logger not initialized or checkpoint file path not set. Cannot load checkpoint.')
            return []

        path = self.checkpoint_path(tag)
        try:
            with open(path, 'r', encoding='utf-8') as file:
                file_content = file.read()
                parsed_content = json.loads(file_content)
                if not isinstance(parsed_content, list):
                    print(f"Checkpoint file at {path} is not a valid JSON array. Returning empty checkpoint.")
                    return []
                return parsed_content
        except Exception as error:
            print(f"Failed to read or parse checkpoint file {path}:", error)
            return []

    async def delete_checkpoint(self, tag: str) -> bool:
        if not self.initialized or not self.qwen_dir:
            print('Logger not initialized or checkpoint file path not set. Cannot delete checkpoint.')
            return False

        path = self.checkpoint_path(tag)

        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            # File doesn't exist, which is fine.
            return False
        except Exception as error:
            print(f"Failed to delete checkpoint file {path}:", error)
            raise

    def close(self) -> None:
        self.initialized = False
        self.log_file_path = None
        self.logs = []
        self.session_id = None
        self.message_id = 0