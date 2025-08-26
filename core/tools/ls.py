"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import os
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from ..tools.tools import BaseTool, Icon, ToolResult
from ..utils.path import make_relative,shorten_path
from ..utils.schema_validator import SchemaValidator
from ..config.config import Config, DEFAULT_FILE_FILTERING_OPTIONS

class FileEntry:
    """
    文件条目类，用于表示文件或目录
    """
    def __init__(self, name: str, path: str, is_directory: bool, size: int, modified_time: datetime):
        self.name = name
        self.path = path
        self.is_directory = is_directory
        self.size = size
        self.modified_time = modified_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "isDirectory": self.is_directory,
            "size": self.size,
            "modifiedTime": self.modified_time
        }


class WorkspaceContext:
    """
    工作区上下文（模拟实现）
    """
    def __init__(self):
        self._directories = [os.getcwd()]

    def isPathWithinWorkspace(self, path: str) -> bool:
        # 简化实现，检查路径是否在工作区内
        path_obj = Path(path).resolve()
        for dir_path in self._directories:
            dir_obj = Path(dir_path).resolve()
            if dir_obj in path_obj.parents or dir_obj == path_obj:
                return True
        return False

    def getDirectories(self) -> List[str]:
        return self._directories


class FileService:
    """
    文件服务（模拟实现）
    """
    def shouldGitIgnoreFile(self, path: str) -> bool:
        # 简化实现，实际应用中应检查.gitignore文件
        return False

    def shouldGeminiIgnoreFile(self, path: str) -> bool:
        # 简化实现，实际应用中应检查.geminiignore文件
        return False


class LSTool(BaseTool):
    """
    列出目录内容的工具实现
    """
    NAME = 'list_directory'

    def __init__(self, config: Config):
        super().__init__(
            LSTool.NAME,
            'ReadFolder',
            'Lists the names of files and subdirectories directly within a specified directory path. Can optionally ignore entries matching provided glob patterns.',
            ICON_FOLDER,
            {
                "properties": {
                    "path": {
                        "description": 'The absolute path to the directory to list (must be absolute, not relative)',
                        "type": "string"
                    },
                    "ignore": {
                        "description": 'List of glob patterns to ignore',
                        "items": {
                            "type": "string"
                        },
                        "type": "array"
                    },
                    "file_filtering_options": {
                        "description": 'Optional: Whether to respect ignore patterns from .gitignore or .geminiignore',
                        "type": "object",
                        "properties": {
                            "respect_git_ignore": {
                                "description": 'Optional: Whether to respect .gitignore patterns when listing files. Only available in git repositories. Defaults to true.',
                                "type": "boolean"
                            },
                            "respect_gemini_ignore": {
                                "description": 'Optional: Whether to respect .geminiignore patterns when listing files. Defaults to true.',
                                "type": "boolean"
                            }
                        }
                    }
                },
                "required": ["path"],
                "type": "object"
            }
        )
        self.config = config

    def validateToolParams(self, params: Dict[str, Any]) -> Optional[str]:
        """
        验证工具参数
        """
        errors = SchemaValidator.validate(self.schema["parameters"], params)
        if errors:
            return errors
        
        # 检查路径是否为绝对路径
        path_value = params.get("path")
        if not path_value or not Path(path_value).is_absolute():
            return f"Path must be absolute: {path_value}"

        # 检查路径是否在工作区内
        workspace_context = self.config.getWorkspaceContext()
        if not workspace_context.isPathWithinWorkspace(path_value):
            directories = workspace_context.getDirectories()
            return f"Path must be within one of the workspace directories: {', '.join(directories)}"
        
        return None

    def shouldIgnore(self, filename: str, patterns: Optional[List[str]]) -> bool:
        """
        检查文件名是否匹配任何忽略模式
        """
        if not patterns or not patterns:
            return False
        
        for pattern in patterns:
            # 将glob模式转换为正则表达式
            regex_pattern = pattern.replace('.', '\\.').replace('*', '.*').replace('?', '.')
            regex = re.compile(f"^{regex_pattern}$")
            if regex.match(filename):
                return True
        
        return False

    def getDescription(self, params: Dict[str, Any]) -> str:
        """
        获取文件读取操作的描述
        """
        relativePath = makeRelative(params.path, self.config.getTargetDir())
        return shorten_path(relativePath)


    def _shortenPath(self, path: str) -> str:
        """
        简化路径显示（模拟实现）
        """
        # 简单实现，实际应用中可能需要更复杂的逻辑
        return path

    def errorResult(self, llm_content: str, return_display: str) -> ToolResult:
        """
        创建错误结果
        """
        return ToolResult(llm_content, f"Error: {return_display}")

    async def execute(self, params: Dict[str, Any], signal: Any = None) -> ToolResult:
        """
        执行LS操作
        """
        validation_error = self.validateToolParams(params)
        if validation_error:
            return self.errorResult(
                f"Error: Invalid parameters provided. Reason: {validation_error}",
                "Failed to execute tool."
            )

        try:
            path_value = params.get("path")
            
            # 检查路径是否存在且是目录
            if not os.path.exists(path_value):
                return self.errorResult(
                    f"Error: Directory not found or inaccessible: {path_value}",
                    "Directory not found or inaccessible."
                )
            
            if not os.path.isdir(path_value):
                return self.errorResult(
                    f"Error: Path is not a directory: {path_value}",
                    "Path is not a directory."
                )

            # 读取目录内容
            files = os.listdir(path_value)

            # 获取文件过滤选项
            default_file_ignores = self.config.getFileFilteringOptions() or DEFAULT_FILE_FILTERING_OPTIONS
            
            file_filtering_options = {
                "respectGitIgnore": (
                    params.get("file_filtering_options", {}).get("respect_git_ignore") 
                    if params.get("file_filtering_options") and "respect_git_ignore" in params.get("file_filtering_options", {})
                    else default_file_ignores["respectGitIgnore"]
                ),
                "respectGeminiIgnore": (
                    params.get("file_filtering_options", {}).get("respect_gemini_ignore")
                    if params.get("file_filtering_options") and "respect_gemini_ignore" in params.get("file_filtering_options", {})
                    else default_file_ignores["respectGeminiIgnore"]
                )
            }

            # 获取文件发现服务
            file_discovery = self.config.getFileService()

            entries: List[FileEntry] = []
            git_ignored_count = 0
            gemini_ignored_count = 0

            if not files:
                return ToolResult(
                    f"Directory {path_value} is empty.",
                    "Directory is empty."
                )

            for file in files:
                # 检查是否应被用户提供的模式忽略
                if self.shouldIgnore(file, params.get("ignore")):
                    continue

                full_path = os.path.join(path_value, file)
                relative_path = os.path.relpath(full_path, self.config.getTargetDir())

                # 检查是否应被git或gemini忽略规则忽略
                if file_filtering_options["respectGitIgnore"] and file_discovery.shouldGitIgnoreFile(relative_path):
                    git_ignored_count += 1
                    continue
                
                if file_filtering_options["respectGeminiIgnore"] and file_discovery.shouldGeminiIgnoreFile(relative_path):
                    gemini_ignored_count += 1
                    continue

                try:
                    # 获取文件状态
                    stats = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    
                    # 创建文件条目
                    entry = FileEntry(
                        name=file,
                        path=full_path,
                        is_directory=is_dir,
                        size=0 if is_dir else stats.st_size,
                        modified_time=datetime.fromtimestamp(stats.st_mtime)
                    )
                    entries.append(entry)
                except Exception as e:
                    # 内部记录错误，但不影响整个列表
                    print(f"Error accessing {full_path}: {e}")

            # 对条目进行排序（目录在前，然后按字母顺序）
            entries.sort(key=lambda x: (not x.is_directory, x.name))

            # 创建格式化的内容
            directory_content = "\n".join([f"{'[DIR] ' if entry.is_directory else ''}{entry.name}" for entry in entries])

            result_message = f"Directory listing for {path_value}:\n{directory_content}"
            ignored_messages = []
            
            if git_ignored_count > 0:
                ignored_messages.append(f"{git_ignored_count} git-ignored")
            
            if gemini_ignored_count > 0:
                ignored_messages.append(f"{gemini_ignored_count} gemini-ignored")

            if ignored_messages:
                result_message += f"\n\n({', '.join(ignored_messages)})"

            display_message = f"Listed {len(entries)} item(s)."
            if ignored_messages:
                display_message += f" ({', '.join(ignored_messages)})"

            return ToolResult(result_message, display_message)

        except Exception as e:
            error_msg = f"Error listing directory: {str(e)}"
            return self.errorResult(error_msg, "Failed to list directory.")


