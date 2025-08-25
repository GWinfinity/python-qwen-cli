import os
import pathlib
import asyncio
import glob
from typing import List, Dict, Any, Optional, Set, Union, Tuple
from pydantic import BaseModel, Field, validator
from enum import Enum

from .tools import BaseTool, Icon, ToolResult
from ..utils.schema_validator import SchemaValidator
from ..utils.errors import get_error_message
from ..utils.file_utils import detect_file_type, process_single_file_content, DEFAULT_ENCODING, get_specific_mime_type
from ..config.config import Config, DEFAULT_FILE_FILTERING_OPTIONS
from ..telemetry.metrics import record_file_operation_metric, FileOperation
from ..tools.memory_tool import get_current_gemini_md_filename


class FileFilteringOptions(BaseModel):
    respect_git_ignore: Optional[bool] = Field(None, description="Whether to respect .gitignore patterns")
    respect_gemini_ignore: Optional[bool] = Field(None, description="Whether to respect .geminiignore patterns")


class ReadManyFilesParams(BaseModel):
    paths: List[str] = Field(..., min_items=1, description="An array of file paths or directory paths to search within")
    include: Optional[List[str]] = Field([], description="Glob patterns for files to include")
    exclude: Optional[List[str]] = Field([], description="Glob patterns for files/directories to exclude")
    recursive: Optional[bool] = Field(True, description="Search directories recursively")
    use_default_excludes: Optional[bool] = Field(True, description="Apply default exclusion patterns")
    file_filtering_options: Optional[FileFilteringOptions] = Field(None, description="File filtering options")

    @validator('paths')
    def validate_paths(cls, v):
        if not v or len(v) == 0:
            raise ValueError("At least one path must be provided")
        return v


# Default exclusion patterns
DEFAULT_EXCLUDES: List[str] = [
    '**/node_modules/**',
    '**/.git/**',
    '**/.vscode/**',
    '**/.idea/**',
    '**/dist/**',
    '**/build/**',
    '**/coverage/**',
    '**/__pycache__/**',
    '**/*.pyc',
    '**/*.pyo',
    '**/*.bin',
    '**/*.exe',
    '**/*.dll',
    '**/*.so',
    '**/*.dylib',
    '**/*.class',
    '**/*.jar',
    '**/*.war',
    '**/*.zip',
    '**/*.tar',
    '**/*.gz',
    '**/*.bz2',
    '**/*.rar',
    '**/*.7z',
    '**/*.doc',
    '**/*.docx',
    '**/*.xls',
    '**/*.xlsx',
    '**/*.ppt',
    '**/*.pptx',
    '**/*.odt',
    '**/*.ods',
    '**/*.odp',
    '**/*.DS_Store',
    '**/.env',
    f'**/{get_current_gemini_md_filename()}',
]

DEFAULT_OUTPUT_SEPARATOR_FORMAT = '--- {filePath} ---'


class ReadManyFilesTool(BaseTool):
    Name: str = 'read_many_files'

    def __init__(self, config: Config):
        # 定义参数schema（在Python中使用pydantic替代）
        super().__init__(
            ReadManyFilesTool.Name,
            'ReadManyFiles',
            "Reads content from multiple files specified by paths or glob patterns within a configured target directory.",
            Icon.FileSearch,
            # 在Python中schema由pydantic模型处理
        )
        self.config = config

    def validate_params(self, params: Dict[str, Any]) -> Optional[str]:
        try:
            # 使用pydantic验证参数
            ReadManyFilesParams(**params)
            return None
        except Exception as e:
            return str(e)

    def get_description(self, params:ReadManyFilesParams ) -> str:
        try:
            all_patterns = params.paths + (params.include or [])
            path_desc = f"using patterns: `{', '.join(all_patterns)}` (within target directory: `{self.config.get_target_dir()}`)"

            param_excludes = params.exclude or []
            param_use_default_excludes = params.use_default_excludes
            gemini_ignore_patterns = self.config.get_file_service().get_gemini_ignore_patterns()
            final_exclusion_patterns_for_description: List[str] =DEFAULT_EXCLUDES + param_excludes + gemini_ignore_patterns \
                if param_use_default_excludes \
                else param_excludes + gemini_ignore_patterns

            exclude_desc = f"Excluding: {', '.join(final_exclusion_patterns[:2])}{'...' if len(final_exclusion_patterns) > 2 else ''}"

            if gemini_ignore_patterns:
                gemini_patterns_in_effect = len([p for p in gemini_ignore_patterns if p in final_exclusion_patterns])
                if gemini_patterns_in_effect > 0:
                    exclude_desc += f" (includes {gemini_patterns_in_effect} from .geminiignore)"

            return f"Will attempt to read and concatenate files {path_desc}. {exclude_desc}. File encoding: {DEFAULT_ENCODING}."
        except Exception as e:
            return f"Error generating description: {str(e)}"

    async def execute(
        self, params: ReadManyFilesParams, signal: asyncio.AbstractEventLoop
    ) -> ToolResult:
        validation_error = self.validate_params(params)
        if validation_error:
            return {
                'llmContent': f"Error: Invalid parameters for {self.display_name}. Reason: {validation_error}",
                'returnDisplay': f"## Parameter Error\n\n{validation_error}",
            }

        try:
            paths = params.paths
            include = params.include or []
            exclude = params.exclude or []
            use_default_excludes = params.use_default_excludes

            default_file_ignores = self.config.get_file_filtering_options() or DEFAULT_FILE_FILTERING_OPTIONS
            file_filtering_options = {
                'respectGitIgnore': (
                    params.file_filtering_options.respect_git_ignore
                    if params.file_filtering_options and params.file_filtering_options.respect_git_ignore is not None
                    else default_file_ignores.respectGitIgnore
                ),
                'respectGeminiIgnore': (
                    params.file_filtering_options.respect_gemini_ignore
                    if params.file_filtering_options and params.file_filtering_options.respect_gemini_ignore is not None
                    else default_file_ignores.respectGeminiIgnore
                ),
            }

            file_discovery = self.config.get_file_service()
            files_to_consider: Set[str] = set()
            skipped_files: List[Dict[str, str]] = []
            processed_files_relative_paths: List[str] = []
            content_parts: List[Union[str, Dict[str, Any]]] = []

            effective_excludes = DEFAULT_EXCLUDES+exclude if use_default_excludes else exclude.copy()
            search_patterns = paths+include

            if not search_patterns:
                return {
                    'llmContent': 'No search paths or include patterns provided.',
                    'returnDisplay': "## Information\n\nNo search paths or include patterns were specified. Nothing to read or concatenate.",
                }

            # 搜索文件
            all_entries: Set[str] = set()
            workspace_dirs = self.config.get_workspace_context().get_directories()

            for dir_path in workspace_dirs:
                # 转换Windows路径分隔符
                normalized_patterns = [p.replace('\\', '/') for p in search_patterns]
                entries_in_dir = glob.glob(
                    normalized_patterns,
                    root_dir=dir_path,
                    recursive=True,
                    include_hidden=True
                )
                for entry in entries_in_dir:
                    absolute_path = os.path.abspath(os.path.join(dir_path, entry))
                    all_entries.add(absolute_path)

            entries = list(all_entries)

            # 应用gitignore过滤
            git_filtered_entries = (
                [
                    os.path.resolve(self.config.get_target_dir(), p)
                    for p in file_discovery.filter_files(
                        [os.path.relpath(p, self.config.get_target_dir()) for p in entries],
                        {'respectGitIgnore': True, 'respectGeminiIgnore': False}
                    )
                ]
                if file_filtering_options['respectGitIgnore']
                else entries
            )

            # 应用geminiignore过滤
            final_filtered_entries = (
                [
                    os.path.resolve(self.config.get_target_dir(), p)
                    for p in file_discovery.filter_files(
                        [os.path.relpath(p, self.config.get_target_dir()) for p in git_filtered_entries],
                        {'respectGitIgnore': False, 'respectGeminiIgnore': True}
                    )
                ]
                if file_filtering_options['respectGeminiIgnore']
                else git_filtered_entries
            )

            # 统计被忽略的文件
            git_ignored_count = len(entries) - len(git_filtered_entries)
            gemini_ignored_count = len(git_filtered_entries) - len(final_filtered_entries)

            for absolute_file_path in entries:
                # 安全检查：确保路径在工作区内
                if not self.config.get_workspace_context().is_path_within_workspace(absolute_file_path):
                    skipped_files.append({
                        'path': absolute_file_path,
                        'reason': f'Security: Path outside workspace'
                    })
                    continue

                # 检查是否被gitignore过滤
                if file_filtering_options['respectGitIgnore'] and absolute_file_path not in git_filtered_entries:
                    continue

                # 检查是否被geminiignore过滤
                if file_filtering_options['respectGeminiIgnore'] and absolute_file_path not in final_filtered_entries:
                    continue

                files_to_consider.add(absolute_file_path)

            # 添加被忽略文件的信息
            if git_ignored_count > 0:
                skipped_files.append({'path': f'{git_ignored_count} file(s)', 'reason': 'git ignored'})

            if gemini_ignored_count > 0:
                skipped_files.append({'path': f'{gemini_ignored_count} file(s)', 'reason': 'gemini ignored'})

        except Exception as e:
            return {
                'llmContent': f"Error during file search: {get_error_message(e)}",
                'returnDisplay': f"## File Search Error\n\nAn error occurred while searching for files:\n\`\`\`\n{get_error_message(e)}\n\`\`\`",
            }

        # 处理找到的文件
        sorted_files = sorted(files_to_consider)

        for file_path in sorted_files:
            relative_path_for_display = os.path.relpath(file_path, self.config.get_target_dir()).replace('\\', '/')

            # 检测文件类型
            file_type = await detect_file_type(file_path)

            # 处理图像和PDF文件
            if file_type in ['image', 'pdf']:
                file_extension = pathlib.Path(file_path).suffix.lower()
                file_name_without_extension = pathlib.Path(file_path).stem
                requested_explicitly = any(
                    (file_extension in pattern.lower() or file_name_without_extension in pattern)
                    for pattern in paths
                )

                if not requested_explicitly:
                    skipped_files.append({
                        'path': relative_path_for_display,
                        'reason': 'asset file (image/pdf) was not explicitly requested'
                    })
                    continue

            # 处理文件内容
            file_read_result = await process_single_file_content(
                file_path, self.config.get_target_dir()
            )

            if file_read_result.get('error'):
                skipped_files.append({
                    'path': relative_path_for_display,
                    'reason': f'Read error: {file_read_result["error"]}'
                })
            else:
                if isinstance(file_read_result.get('llmContent'), str):
                    separator = DEFAULT_OUTPUT_SEPARATOR_FORMAT.replace('{filePath}', file_path)
                    content_parts.append(f"{separator}\n\n{file_read_result['llmContent']}\n\n")
                else:
                    content_parts.append(file_read_result.get('llmContent', {}))

                processed_files_relative_paths.append(relative_path_for_display)

                # 记录文件操作指标
                lines = len(file_read_result.get('llmContent', '').split('\n')) if isinstance(file_read_result.get('llmContent'), str) else None
                mime_type = get_specific_mime_type(file_path)
                record_file_operation_metric(
                    self.config,
                    FileOperation.READ,
                    lines,
                    mime_type,
                    pathlib.Path(file_path).suffix
                )

        # 构建显示消息
        display_message = f"### ReadManyFiles Result (Target Dir: `{self.config.get_target_dir()}`)\n\n"

        if processed_files_relative_paths:
            display_message += f"Successfully read and concatenated content from **{len(processed_files_relative_paths)} file(s)**.\n"
            if len(processed_files_relative_paths) <= 10:
                display_message += "\n**Processed Files:**\n"
                for p in processed_files_relative_paths:
                    display_message += f"- `{p}`\n"
            else:
                display_message += "\n**Processed Files (first 10 shown):**\n"
                for p in processed_files_relative_paths[:10]:
                    display_message += f"- `{p}`\n"
                display_message += f"- ...and {len(processed_files_relative_paths) - 10} more.\n"

        if skipped_files:
            if not processed_files_relative_paths:
                display_message += "No files were read and concatenated based on the criteria.\n"
            if len(skipped_files) <= 5:
                display_message += f"\n**Skipped {len(skipped_files)} item(s):**\n"
            else:
                display_message += f"\n**Skipped {len(skipped_files)} item(s) (first 5 shown):**\n"
            for f in skipped_files[:5]:
                display_message += f"- `{f['path']}` (Reason: {f['reason']})\n"
            if len(skipped_files) > 5:
                display_message += f"- ...and {len(skipped_files) - 5} more.\n"
        elif not processed_files_relative_paths:
            display_message += "No files were read and concatenated based on the criteria.\n"

        if not content_parts:
            content_parts.append("No files matching the criteria were found or all were skipped.")

        return {
            'llmContent': content_parts,
            'returnDisplay': display_message.strip(),
        }