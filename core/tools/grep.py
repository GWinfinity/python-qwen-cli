import os
import re
import subprocess
import sys
from pathlib import Path
import asyncio
import glob
from typing import Optional, List, Dict, Any
from ..tools.tools import BaseTool, ToolResult,Icon
from google.genai.types import Type
from ..utils.schema_validator import SchemaValidator
from ..utils.path import make_relative, shorten_path
from ..utils.errors import get_error_message, is_node_error
from ..utils.git_utils import is_git_repository
from ..config.config import Config


# --- 接口定义 --- 

class GrepToolParams:
    def __init__(self, pattern: str, path: Optional[str] = None, include: Optional[str] = None):
        self.pattern = pattern
        self.path = path
        self.include = include

class GrepMatch:
    def __init__(self, file_path: str, line_number: int, line: str):
        self.file_path = file_path
        self.line_number = line_number
        self.line = line

# --- GrepTool 类 --- 

class GrepTool(BaseTool):
    Name = 'search_file_content'  # 保持静态名称

    def __init__(self, config: Config):
        super().__init__(
            GrepTool.Name,
            'SearchText',
            'Searches for a regular expression pattern within the content of files in a specified directory (or current working directory). Can filter files by a glob pattern. Returns the lines containing matches, along with their file paths and line numbers.',
            Icon.Regex,
            {
                'properties': {
                    'pattern': {
                        'description':
                            "The regular expression (regex) pattern to search for within file contents (e.g., 'function\\s+myFunction', 'import\\s+\\{.*\\}\\s+from\\s+.*').",
                        'type': Type.STRING,
                    },
                    'path': {
                        'description':
                            'Optional: The absolute path to the directory to search within. If omitted, searches the current working directory.',
                        'type': Type.STRING,
                    },
                    'include': {
                        'description':
                            "Optional: A glob pattern to filter which files are searched (e.g., '*.js', '*.{ts,tsx}', 'src/**'). If omitted, searches all files (respecting potential global ignores).",
                        'type': Type.STRING,
                    },
                },
                'required': ['pattern'],
                'type': Type.OBJECT,
            },
        )
        self.config = config

    # --- 验证方法 --- 

    def resolve_and_validate_path(self, relative_path: Optional[str]) -> Optional[str]:
        # 如果未指定路径，返回 None 表示搜索所有工作区目录
        if not relative_path:
            return None

        target_path = os.path.abspath(os.path.join(self.config.getTargetDir(), relative_path))

        # 安全检查：确保解析的路径在工作区边界内
        workspace_context = self.config.getWorkspaceContext()
        if not workspace_context.isPathWithinWorkspace(target_path):
            directories = workspace_context.getDirectories()
            raise ValueError(
                f"Path validation failed: Attempted path \"{relative_path}\" resolves outside the allowed workspace directories: {', '.join(directories)}"
            )

        # 检查存在性和类型
        try:
            if not os.path.isdir(target_path):
                raise ValueError(f"Path is not a directory: {target_path}")
        except Exception as error:
            if is_node_error(error) and getattr(error, 'code') != 'ENOENT':
                raise ValueError(f"Path does not exist: {target_path}")
            raise ValueError(f"Failed to access path stats for {target_path}: {error}")

        return target_path

    def validate_tool_params(self, params: Dict[str, Any]) -> Optional[str]:
        errors = SchemaValidator.validate(self.schema['properties'], params)
        if errors:
            return errors

        try:
            re.compile(params['pattern'])
        except re.error as error:
            return f"Invalid regular expression pattern provided: {params['pattern']}. Error: {get_error_message(error)}"

        # 只有在提供了路径时才验证路径
        if 'path' in params and params['path']:
            try:
                self.resolve_and_validate_path(params['path'])
            except ValueError as error:
                return get_error_message(error)

        return None  # 参数有效

    # --- 核心执行 --- 

    async def execute(
        self,
        params: Dict[str, Any],
        signal: Optional[asyncio.Event] = None,
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: Invalid parameters provided. Reason: {validation_error}",
                return_display=f"Model provided invalid parameters. Error: {validation_error}",
            )

        try:
            workspace_context = self.config.getWorkspaceContext()
            search_dir_abs = self.resolve_and_validate_path(params.get('path'))
            search_dir_display = params.get('path') or '.'

            # 确定要搜索的目录
            search_directories: List[str]
            if search_dir_abs is None:
                # 未指定路径 - 搜索所有工作区目录
                search_directories = workspace_context.getDirectories()
            else:
                # 提供了特定路径 - 只搜索该目录
                search_directories = [search_dir_abs]

            # 收集所有搜索目录的匹配项
            all_matches: List[GrepMatch] = []
            for search_dir in search_directories:
                matches = await self.perform_grep_search({
                    'pattern': params['pattern'],
                    'path': search_dir,
                    'include': params.get('include'),
                    'signal': signal,
                })

                # 如果搜索多个目录，添加目录前缀
                if len(search_directories) > 1:
                    dir_name = os.path.basename(search_dir)
                    for match in matches:
                        match.file_path = os.path.join(dir_name, match.file_path)

                all_matches.extend(matches)

            search_location_description: str
            if search_dir_abs is None:
                num_dirs = len(workspace_context.getDirectories())
                search_location_description = \
                    f"across {num_dirs} workspace directories" if num_dirs > 1 \
                    else "in the workspace directory"
            else:
                search_location_description = f"in path \"{search_dir_display}\""

            if not all_matches:
                no_match_msg = f"No matches found for pattern \"{params['pattern']}\" {search_location_description}{f" (filter: \"{params.get('include')}\")" if params.get('include') else ''}."
                return ToolResult(llm_content=no_match_msg, return_display="No matches found")

            # 按文件分组匹配项
            matches_by_file: Dict[str, List[GrepMatch]] = {}
            for match in all_matches:
                file_key = match.file_path
                if file_key not in matches_by_file:
                    matches_by_file[file_key] = []
                matches_by_file[file_key].append(match)
                matches_by_file[file_key].sort(key=lambda m: m.line_number)

            match_count = len(all_matches)
            match_term = 'match' if match_count == 1 else 'matches'

            llm_content = f"Found {match_count} {match_term} for pattern \"{params['pattern']}\" {search_location_description}{f" (filter: \"{params.get('include')}\")" if params.get('include') else ''}:---\n"

            for file_path in matches_by_file:
                llm_content += f"File: {file_path}\n"
                for match in matches_by_file[file_path]:
                    trimmed_line = match.line.strip()
                    llm_content += f"L{match.line_number}: {trimmed_line}\n"
                llm_content += "---\n"

            return ToolResult(
                llm_content=llm_content.strip(),
                return_display=f"Found {match_count} {match_term}",
            )
        except Exception as error:
            print(f"Error during GrepLogic execution: {error}", file=sys.stderr)
            error_message = get_error_message(error)
            return ToolResult(
                llm_content=f"Error during grep search operation: {error_message}",
                return_display=f"Error: {error_message}",
            )

    # --- Grep 实现逻辑 --- 

    async def is_command_available(self, command: str) -> bool:
        try:
            # Windows 系统使用 'where' 命令，其他系统使用 'which'
            if sys.platform == 'win32':
                result = await asyncio.create_subprocess_exec(
                    'where', command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True
                )
            else:
                result = await asyncio.create_subprocess_exec(
                    'which', command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            await result.wait()
            return result.returncode == 0
        except Exception:
            return False

    def parse_grep_output(self, output: str, base_path: str) -> List[GrepMatch]:
        results: List[GrepMatch] = []
        if not output:
            return results

        lines = output.splitlines()

        for line in lines:
            if not line.strip():
                continue

            # 查找第一个冒号的索引
            first_colon_index = line.find(':')
            if first_colon_index == -1:
                continue  # 格式错误

            # 查找第二个冒号的索引，从第一个冒号之后开始搜索
            second_colon_index = line.find(':', first_colon_index + 1)
            if second_colon_index == -1:
                continue  # 格式错误

            # 基于找到的冒号索引提取部分
            file_path_raw = line[:first_colon_index]
            line_number_str = line[first_colon_index + 1:second_colon_index]
            line_content = line[second_colon_index + 1:]

            try:
                line_number = int(line_number_str)
            except ValueError:
                continue

            absolute_file_path = os.path.abspath(os.path.join(base_path, file_path_raw))
            relative_file_path = os.path.relpath(absolute_file_path, base_path)

            results.append(GrepMatch(
                file_path=relative_file_path or os.path.basename(absolute_file_path),
                line_number=line_number,
                line=line_content
            ))
        return results

    def get_description(self, params: Dict[str, Any]) -> str:
        description = f"'{params['pattern']}'"
        if params.get('include'):
            description += f" in {params['include']}"
        if params.get('path'):
            resolved_path = os.path.abspath(
                os.path.join(self.config.getTargetDir(), params['path'])
            )
            if resolved_path == self.config.getTargetDir() or params['path'] == '.':
                description += " within ./"
            else:
                relative_path = make_relative(

                    resolved_path,
                    self.config.getTargetDir()
                )
                description += f" within {shorten_path(relative_path)}"
        else:
            # 当未指定路径时，表示搜索所有工作区目录
            workspace_context = self.config.getWorkspaceContext()
            directories = workspace_context.getDirectories()
            if len(directories) > 1:
                description += " across all workspace directories"
        return description

    async def perform_grep_search(self, options: Dict[str, Any]) -> List[GrepMatch]:
        pattern = options['pattern']
        absolute_path = options['path']
        include = options.get('include')
        signal = options.get('signal')
        strategy_used = 'none'

        try:
            # --- 策略 1: git grep ---
            is_git = is_git_repository(absolute_path)
            git_available = is_git and await self.is_command_available('git')

            if git_available:
                strategy_used = 'git grep'
                git_args = [
                    'grep',
                    '--untracked',
                    '-n',
                    '-E',
                    '--ignore-case',
                    pattern,
                ]
                if include:
                    git_args.extend(['--', include])

                try:
                    proc = await asyncio.create_subprocess_exec(
                        'git', *git_args,
                        cwd=absolute_path,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    stdout, stderr = await proc.communicate()
                    output = stdout.decode('utf-8')
                    stderr_data = stderr.decode('utf-8')
                    
                    if proc.returncode == 0:
                        return self.parse_grep_output(output, absolute_path)
                    elif proc.returncode == 1:
                        return []  # 无匹配项
                    else:
                        raise RuntimeError(f"git grep exited with code {proc.returncode}: {stderr_data}")
                except Exception as git_error:
                    print(f"GrepLogic: git grep failed: {get_error_message(git_error)}. Falling back...", file=sys.stderr)

            # --- 策略 2: 系统 grep ---
            grep_available = await self.is_command_available('grep')
            if grep_available:
                strategy_used = 'system grep'
                grep_args = ['-r', '-n', '-H', '-E']
                common_excludes = ['.git', 'node_modules', 'bower_components']
                for dir_name in common_excludes:
                    grep_args.append(f'--exclude-dir={dir_name}')
                if include:
                    grep_args.append(f'--include={include}')
                grep_args.extend([pattern, '.'])

                try:
                    proc = await asyncio.create_subprocess_exec(
                        'grep', *grep_args,
                        cwd=absolute_path,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    stdout, stderr = await proc.communicate()
                    output = stdout.decode('utf-8')
                    stderr_data = stderr.decode('utf-8').strip()
                    
                    # 过滤常见的无害 stderr 消息
                    filtered_stderr = []
                    for line in stderr_data.splitlines():
                        if 'Permission denied' not in line and not re.search(r'grep:.*: Is a directory', line, re.IGNORECASE):
                            filtered_stderr.append(line)
                    filtered_stderr_data = '\n'.join(filtered_stderr)
                    
                    if proc.returncode == 0:
                        return self.parse_grep_output(output, absolute_path)
                    elif proc.returncode == 1:
                        return []  # 无匹配项
                    else:
                        if filtered_stderr_data:
                            raise RuntimeError(f"System grep exited with code {proc.returncode}: {filtered_stderr_data}")
                        else:
                            return []  # 退出代码 > 1 但无 stderr，可能只是被抑制的错误
                except Exception as grep_error:
                    print(f"GrepLogic: System grep failed: {get_error_message(grep_error)}. Falling back...", file=sys.stderr)

            # --- 策略 3: 纯 Python 回退 --- 
            print("GrepLogic: Falling back to Python grep implementation.", file=sys.stderr)
            strategy_used = 'python fallback'
            glob_pattern = include if include else '**/*'
            ignore_patterns = [
                '.git/**',
                'node_modules/**',
                'bower_components/**',
                '.svn/**',
                '.hg/**',
            ]  # 这里使用 glob 模式进行忽略

            # 使用 pathlib 的 glob 或 Python 的 glob 模块
            files = []
            if sys.version_info >= (3, 10):
                # Python 3.10+ 支持 recursive=True
                p = Path(absolute_path)
                files = list(p.glob(glob_pattern, recursive=True))
            else:
                # 对于较旧的 Python 版本
                old_cwd = os.getcwd()
                os.chdir(absolute_path)
                try:
                    files = glob.glob(glob_pattern, recursive=True)
                finally:
                    os.chdir(old_cwd)

            # 过滤掉目录和被忽略的文件
            file_paths = []
            for file_path in files:
                if isinstance(file_path, Path):
                    str_path = str(file_path)
                else:
                    str_path = file_path
                
                # 检查是否为文件
                full_path = os.path.join(absolute_path, str_path) if not isinstance(file_path, Path) else str(file_path)
                if not os.path.isfile(full_path):
                    continue
                
                # 检查是否被忽略
                ignore = False
                for ignore_pattern in ignore_patterns:
                    # 简化的忽略逻辑
                    if any(ignore_part in full_path for ignore_part in ignore_pattern.split('/')):
                        ignore = True
                        break
                
                if not ignore:
                    file_paths.append(full_path)

            regex = re.compile(pattern, re.IGNORECASE)
            all_matches: List[GrepMatch] = []

            for file_path in file_paths:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    lines = content.splitlines()
                    for index, line in enumerate(lines):
                        if regex.search(line):
                            relative_path = os.path.relpath(file_path, absolute_path)
                            all_matches.append(GrepMatch(
                                file_path=relative_path or os.path.basename(file_path),
                                line_number=index + 1,
                                line=line
                            ))
                except Exception as read_error:
                    # 忽略权限错误或读取过程中文件消失等错误
                    if not (is_node_error(read_error) and getattr(read_error, 'code') == 'ENOENT'):
                        print(f"GrepLogic: Could not read/process {file_path}: {get_error_message(read_error)}", file=sys.stderr)

            return all_matches
        except Exception as error:
            print(f"GrepLogic: Error in perform_grep_search (Strategy: {strategy_used}): {get_error_message(error)}", file=sys.stderr)
            raise

