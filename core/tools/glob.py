import os
import re
import glob
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
import sys
from datetime import datetime
from ..utils.schema_validator import SchemaValidator
from ..utils.path import make_relative,shorten_path
from ..config.config import Config
from ..tools.tools import BaseTool, ToolResult, Icon
from google.genai.types import Type

# --- 接口定义 --- 

class GlobPath:
    def __init__(self, full_path: str, mtime_ms: Optional[float] = None):
        self._full_path = full_path
        self.mtime_ms = mtime_ms
    
    def fullpath(self) -> str:
        return self._full_path

# --- 工具函数 --- 

def sortFileEntries(
    entries: List[GlobPath],
    now_timestamp: float,
    recency_threshold_ms: float,
) -> List[GlobPath]:
    sorted_entries = entries.copy()
    sorted_entries.sort(key=lambda a: (
        # 先按是否在最近时间段内排序
        # 然后按修改时间排序（最新的在前）
        # 最后按路径字母顺序排序
        -(now_timestamp - (a.mtime_ms or 0) < recency_threshold_ms),
        -(a.mtime_ms or 0),
        a.fullpath()
    ))
    return sorted_entries

# --- GlobTool 类 --- 

class GlobTool(BaseTool):
    Name = 'glob'

    def __init__(self, config: Config):
        super().__init__(
            GlobTool.Name,
            'FindFiles',
            'Efficiently finds files matching specific glob patterns (e.g., `src/**/*.ts`, `**/*.md`), returning absolute paths sorted by modification time (newest first). Ideal for quickly locating files based on their name or path structure, especially in large codebases.',
            Icon.FileSearch,
            {
                'properties': {
                    'pattern': {
                        'description':
                            "The glob pattern to match against (e.g., '**/*.py', 'docs/*.md').",
                        'type': Type.STRING,
                    },
                    'path': {
                        'description':
                            'Optional: The absolute path to the directory to search within. If omitted, searches the root directory.',
                        'type': Type.STRING,
                    },
                    'case_sensitive': {
                        'description':
                            'Optional: Whether the search should be case-sensitive. Defaults to false.',
                        'type': Type.BOOLEAN,
                    },
                    'respect_git_ignore': {
                        'description':
                            'Optional: Whether to respect .gitignore patterns when finding files. Only available in git repositories. Defaults to true.',
                        'type': Type.BOOLEAN,
                    },
                },
                'required': ['pattern'],
                'type': Type.OBJECT,
            },
        )
        self.config = config

    def validate_tool_params(self, params: Dict[str, Any]) -> Optional[str]:
        errors = SchemaValidator.validate(self.schema['properties'], params)
        if errors:
            return errors

        search_dir_absolute = os.path.abspath(
            os.path.join(self.config.getTargetDir(), params.get('path', '.'))
        )

        workspace_context = self.config.getWorkspaceContext()
        if not workspace_context.isPathWithinWorkspace(search_dir_absolute):
            directories = workspace_context.getDirectories()
            return f"Search path (\"{search_dir_absolute}\") resolves outside the allowed workspace directories: {', '.join(directories)}"

        target_dir = search_dir_absolute or self.config.getTargetDir()
        try:
            if not os.path.exists(target_dir):
                return f"Search path does not exist {target_dir}"
            if not os.path.isdir(target_dir):
                return f"Search path is not a directory: {target_dir}"
        except Exception as e:
            return f"Error accessing search path: {str(e)}"

        if not params.get('pattern') or not isinstance(params.get('pattern'), str) or params.get('pattern').strip() == '':
            return "The 'pattern' parameter cannot be empty."

        return None

    def get_description(self, params: Dict[str, Any]) -> str:
        description = f"'{params['pattern']}'"
        if params.get('path'):
            search_dir = os.path.abspath(
                os.path.join(self.config.getTargetDir(), params.get('path', '.'))
            )
            relative_path = make_relative(search_dir, self.config.getTargetDir())
            description += f" within {shorten_path(relative_path)}"
        return description

    async def execute(
        self,
        params: Dict[str, Any],
        signal: Optional[asyncio.Event] = None,
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: Invalid parameters provided. Reason: {validation_error}",
                return_display=validation_error,
            )

        try:
            workspace_context = self.config.getWorkspaceContext()
            workspace_directories = workspace_context.getDirectories()

            # 如果提供了特定路径，解析它并检查是否在工作区内
            search_directories: List[str]
            if params.get('path'):
                search_dir_absolute = os.path.abspath(
                    os.path.join(self.config.getTargetDir(), params.get('path'))
                )
                if not workspace_context.isPathWithinWorkspace(search_dir_absolute):
                    return ToolResult(
                        llm_content=f"Error: Path \"{params.get('path')}\" is not within any workspace directory",
                        return_display="Path is not within workspace",
                    )
                search_directories = [search_dir_absolute]
            else:
                # 搜索所有工作区目录
                search_directories = workspace_directories

            # 获取集中式文件发现服务
            respect_git_ignore = params.get('respect_git_ignore') if params.get('respect_git_ignore') is not None else self.config.getFileFilteringRespectGitIgnore()
            file_discovery = self.config.getFileService()

            # 收集所有搜索目录的条目
            all_entries: List[GlobPath] = []

            for search_dir in search_directories:
                # Python 的 glob 模块不直接支持 withFileTypes 和 stat 选项
                # 所以我们需要手动实现这些功能
                try:
                    # 构建 glob 模式
                    pattern = os.path.join(search_dir, params['pattern'])
                    
                    # 执行 glob 搜索
                    file_paths = glob.glob(pattern, recursive=True)
                    
                    # 过滤掉目录，只保留文件
                    file_paths = [p for p in file_paths if os.path.isfile(p)]
                    
                    # 如果不区分大小写，我们需要手动处理
                    if not params.get('case_sensitive', False) and os.name == 'nt':  # Windows 平台
                        # Windows 系统上 glob 默认不区分大小写，但为了完整性，我们这里保留这个逻辑
                        pass
                    elif not params.get('case_sensitive', False):  # 非 Windows 平台
                        # 在非 Windows 平台上实现不区分大小写的搜索
                        # 这是一个简化的实现，可能不完全准确
                        pattern_lower = params['pattern'].lower()
                        all_files = []
                        for root, dirs, files in os.walk(search_dir):
                            # 过滤掉 node_modules 和 .git 目录
                            dirs[:] = [d for d in dirs if d not in ['node_modules', '.git']]
                            for file in files:
                                full_path = os.path.join(root, file)
                                # 检查文件路径是否匹配模式（不区分大小写）
                                rel_path = os.path.relpath(full_path, search_dir)
                                if self._match_glob_case_insensitive(rel_path, pattern_lower):
                                    all_files.append(full_path)
                        file_paths = all_files
                    
                    # 创建 GlobPath 对象并添加 mtime_ms 属性
                    for file_path in file_paths:
                        try:
                            # 获取文件修改时间
                            mtime = os.path.getmtime(file_path)
                            mtime_ms = mtime * 1000  # 转换为毫秒
                            all_entries.append(GlobPath(file_path, mtime_ms))
                        except OSError:
                            # 忽略无法访问的文件
                            continue
                except Exception as e:
                    print(f"Error searching in {search_dir}: {str(e)}", file=sys.stderr)

            entries = all_entries

            # 如果启用了 git-aware 过滤并且在 git 仓库中，应用过滤
            filtered_entries = entries
            git_ignored_count = 0

            if respect_git_ignore:
                relative_paths = [
                    make_relative(entry.fullpath(), self.config.getTargetDir())
                    for entry in entries
                ]
                filtered_relative_paths = file_discovery.filterFiles(relative_paths, {
                    'respectGitIgnore': respect_git_ignore,
                })
                filtered_absolute_paths = set(
                    os.path.abspath(os.path.join(self.config.getTargetDir(), p))
                    for p in filtered_relative_paths
                )

                filtered_entries = [
                    entry for entry in entries
                    if os.path.abspath(entry.fullpath()) in filtered_absolute_paths
                ]
                git_ignored_count = len(entries) - len(filtered_entries)

            if not filtered_entries:
                message = f"No files found matching pattern \"{params['pattern']}\""
                if len(search_directories) == 1:
                    message += f" within {search_directories[0]}"
                else:
                    message += f" within {len(search_directories)} workspace directories"
                if git_ignored_count > 0:
                    message += f" ({git_ignored_count} files were git-ignored)"
                return ToolResult(
                    llmContent=message,
                    returnDisplay="No files found",
                )

            # 设置过滤，首先显示最近的文件
            one_day_in_ms = 24 * 60 * 60 * 1000
            now_timestamp = datetime.now().timestamp() * 1000  # 转换为毫秒

            # 使用辅助函数对过滤后的条目进行排序
            sorted_entries = sortFileEntries(
                filtered_entries,
                now_timestamp,
                one_day_in_ms,
            )

            sorted_absolute_paths = [entry.fullpath() for entry in sorted_entries]
            file_list_description = '\n'.join(sorted_absolute_paths)
            file_count = len(sorted_absolute_paths)

            result_message = f"Found {file_count} file(s) matching \"{params['pattern']}\""
            if len(search_directories) == 1:
                result_message += f" within {search_directories[0]}"
            else:
                result_message += f" across {len(search_directories)} workspace directories"
            if git_ignored_count > 0:
                result_message += f" ({git_ignored_count} additional files were git-ignored)"
            result_message += f", sorted by modification time (newest first):\n{file_list_description}"

            return ToolResult(
                llmContent=result_message,
                returnDisplay=f"Found {file_count} matching file(s)",
            )
        except Exception as error:
            error_message = str(error)
            print(f"GlobLogic execute Error: {error_message}", file=sys.stderr)
            return ToolResult(
                llmContent=f"Error during glob search operation: {error_message}",
                returnDisplay="Error: An unexpected error occurred.",
            )
    
    def _match_glob_case_insensitive(self, path: str, pattern: str) -> bool:
        # 简化的不区分大小写的 glob 匹配实现
        # 实际应用中可能需要更复杂的逻辑
        path_lower = path.lower()
        # 基本的通配符替换
        # 将 glob 模式转换为正则表达式
        regex_pattern = pattern.replace('.', '\\.').replace('*', '.*').replace('?', '.')
        try:
            return bool(re.match(f"^{regex_pattern}$", path_lower))
        except re.error:
            # 如果正则表达式无效，则使用简单的包含检查
            return pattern in path_lower

# 示例用法
if __name__ == '__main__':
    # 创建一个简单的配置对象
    config = Config(os.getcwd())
    
    # 创建 GlobTool 实例
    glob_tool = GlobTool(config)
    
    # 测试搜索
    async def test_glob():
        result = await glob_tool.execute({
            'pattern': '*.py',
            'path': '.',
            'case_sensitive': False,
            'respect_git_ignore': True
        })
        print(result.llmContent)
    
    # 运行测试
    asyncio.run(test_glob())