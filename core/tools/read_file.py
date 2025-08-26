import os
import pathlib
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field
from ..utils.schema_validator import SchemaValidator
from ..utils.path import make_relative,shorten_path
from .tool import Tool, ToolResult, BaseTool, Icon
from google.genai.types import Type
from ..utils.file_utils import get_specific_mime_type,process_single_file_content


# 工具参数模型
class ReadFileToolParams(BaseModel):
    """Parameters for the ReadFile tool"""
    absolute_path: str = Field(
        description="The absolute path to the file to read"
    )
    offset: Optional[int] = Field(
        default=None,
        description="The line number to start reading from (optional)"
    )
    limit: Optional[int] = Field(
        default=None,
        description="The number of lines to read (optional)"
    )

# 文件操作类型枚举
class FileOperation:
    READ = "read"

# 工具实现
class ReadFileTool(BaseTool):
    Name: str = 'read_file'

    def __init__(self, config: Config):
        schema = {
            "properties": {
                "absolute_path": {
                    "description": "The absolute path to the file to read (e.g., '/home/user/project/file.txt'). Relative paths are not supported. You must provide an absolute path.",
                    "type": Type.STRING,
                },
                "offset": {
                    "description": "Optional: For text files, the 0-based line number to start reading from. Requires 'limit' to be set. Use for paginating through large files.",
                    "type": Type.NUMBER,
                },
                "limit": {
                    "description": "Optional: For text files, maximum number of lines to read. Use with 'offset' to paginate through large files. If omitted, reads the entire file (if feasible, up to a default limit).",
                    "type": Type.NUMBER,
                },
            },
            "required": ["absolute_path"],
            "type": Type.OBJECT,
        }
        
        super().__init__(
            ReadFileTool.Name,
            'ReadFile',
            'Reads and returns the content of a specified file from the local filesystem. Handles text, images (PNG, JPG, GIF, WEBP, SVG, BMP), and PDF files. For text files, it can read specific line ranges.',
            Icon.FileSearch,
            schema
        )
        self.config = config

    def validate_tool_params(self, params: ReadFileToolParams) -> Optional[str]:
        errors = SchemaValidator.validate(self.schema.parameter, params)
        if errors:
            return f"Invalid parameters: {errors}"

        if not os.path.isabs(params.absolute_path):
            return f"File path must be absolute, but was relative: {params.absolute_path}. You must provide an absolute path."

        # 检查路径是否在工作区内
        workspace_context = self.config.getWorkspaceContext()
        if workspace_context and not workspace_context.isPathWithinWorkspace(params.absolute_path):
            directories = workspace_context.getDirectories()
            return f"File path must be within one of the workspace directories: {', '.join(directories)}"
        
        if params.offset is not None and params.offset < 0:
            return 'Offset must be a non-negative number'
        
        if params.limit is not None and params.limit <= 0:
            return 'Limit must be a positive number'

        # 检查文件是否被忽略
        file_service = self.config.getFileService()
        if file_service and file_service.shouldGeminiIgnoreFile(params.absolute_path):
            return f"File path '{params.absolute_path}' is ignored by .geminiignore pattern(s)."

        return None

    def get_description(self, params: ReadFileToolParams) -> str:
        if not params or not hasattr(params, 'absolute_path') or not params.absolute_path.strip():
            return "Path unavailable"
        
        # 简化实现，实际应使用makeRelative和shortenPath函数
        relativePath = make_relative(params.absolute_path,self.config.getTargetDir())
        return shorten_path(relativePath)


    def tool_locations(self, params: ReadFileToolParams) -> List[ToolLocation]:
        return [ToolLocation(path=params.absolute_path, line=params.offset)]

    async def execute(self, params: ReadFileToolParams, _signal=None) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llmContent=f"Error: Invalid parameters provided. Reason: {validation_error}",
                returnDisplay=validation_error
            )

        # 简化实现processSingleFileContent的调用
        result = await process_single_file_content(
            params.absolute_path,
            self.config.getTargetDir(),
            params.offset,
            params.limit
        )

        if result.get('error'):
            return ToolResult(
                llmContent=result['error'],
                returnDisplay=result.get('returnDisplay', 'Error reading file')
            )

        # 记录文件操作指标
        lines = None
        if isinstance(result.get('llmContent'), str):
            lines = len(result['llmContent'].split('\n'))
        
        mimetype = get_specific_mime_type(params.absolute_path)
        ext = pathlib.Path(params.absolute_path).suffix
        
        # 简化实现recordFileOperationMetric的调用
        self._record_file_operation_metric(
            self.config,
            FileOperation.READ,
            lines,
            mimetype,
            ext
        )

        return ToolResult(
            llmContent=result.get('llmContent', ''),
            returnDisplay=result.get('returnDisplay', '')
        )

    # 模拟工具函数，实际实现应从相应模块导入
    async def _process_single_file_content(self, absolute_path, target_dir, offset=None, limit=None):
        # 这里仅为占位实现，实际应使用真实的文件处理逻辑
        try:
            with open(absolute_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if offset is not None and limit is not None:
                    lines = content.split('\n')
                    content = '\n'.join(lines[offset:offset + limit])
            return {
                'llmContent': content,
                'returnDisplay': f"Content of {os.path.basename(absolute_path)}"
            }
        except Exception as e:
            return {
                'error': str(e),
                'returnDisplay': f"Failed to read file: {str(e)}"
            }


    def _record_file_operation_metric(self, config, operation, lines, mimetype, extension):
        # 简化的指标记录实现
        pass