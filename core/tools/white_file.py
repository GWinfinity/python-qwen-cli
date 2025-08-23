import os
import pathlib
import difflib
from typing import Optional, Dict, Any, Tuple, Union, List
from ..config.config import Config, ApprovalMode
from .tools import BaseTool, ToolResult, FileDiff, ToolEditConfirmationDetails, ToolConfirmationOutcome, ToolCallConfirmationDetails, Icon
from ..utils.schemaValidator import SchemaValidator
from ..utils.paths import make_relative, shorten_path
from ..utils.errors import get_error_message, is_node_error
from ..utils.editCorrector import ensure_correct_edit, ensure_correct_file_content
from .diffOptions import DEFAULT_DIFF_OPTIONS
from .modifiable_tool import ModifiableTool, ModifyContext
from ..utils.fileUtils import get_specific_mime_type
from ..telemetry.metrics import record_file_operation_metric, FileOperation


class WriteFileToolParams:
    def __init__(self, file_path: str, content: str, modified_by_user: bool = False):
        self.file_path = file_path
        self.content = content
        self.modified_by_user = modified_by_user


class GetCorrectedFileContentResult:
    def __init__(self, original_content: str, corrected_content: str, file_exists: bool, error: Optional[Dict[str, Any]] = None):
        self.original_content = original_content
        self.corrected_content = corrected_content
        self.file_exists = file_exists
        self.error = error


class WriteFileTool(BaseTool[WriteFileToolParams, ToolResult], ModifiableTool[WriteFileToolParams]):
    Name: str = 'write_file'

    def __init__(self, config: Config):
        super().__init__(
            WriteFileTool.Name,
            'WriteFile',
            "Writes content to a specified file in the local filesystem.\n\n" \
            "The user has the ability to modify `content`. If modified, this will be stated in the response.",
            Icon.Pencil,
            {
                'properties': {
                    'file_path': {
                        'description': "The absolute path to the file to write to (e.g., '/home/user/project/file.txt'). Relative paths are not supported.",
                        'type': 'string'
                    },
                    'content': {
                        'description': 'The content to write to the file.',
                        'type': 'string'
                    }
                },
                'required': ['file_path', 'content'],
                'type': 'object'
            }
        )
        self.config = config

    def validate_tool_params(self, params: WriteFileToolParams) -> Optional[str]:
        errors = SchemaValidator.validate(self.schema['parameters'], params.__dict__)
        if errors:
            return errors

        file_path = params.file_path
        if not pathlib.Path(file_path).is_absolute():
            return f'File path must be absolute: {file_path}'

        workspace_context = self.config.get_workspace_context()
        if not workspace_context.is_path_within_workspace(file_path):
            directories = workspace_context.get_directories()
            return f'File path must be within one of the workspace directories: {', '.join(directories)}'

        try:
            if os.path.exists(file_path):
                if os.path.isdir(file_path):
                    return f'Path is a directory, not a file: {file_path}'
        except Exception as stat_error:
            return f'Error accessing path properties for validation: {file_path}. Reason: {str(stat_error)}'

        return None

    def get_description(self, params: WriteFileToolParams) -> str:
        if not params.file_path:
            return 'Model did not provide valid parameters for write file tool, missing or empty "file_path"'
        relative_path = make_relative(
            params.file_path,
            self.config.get_target_dir()
        )
        return f'Writing to {shorten_path(relative_path)}'

    async def should_confirm_execute(
        self, params: WriteFileToolParams, abort_signal
    ) -> Union[ToolCallConfirmationDetails, bool]:
        if self.config.get_approval_mode() == ApprovalMode.AUTO_EDIT:
            return False

        validation_error = self.validate_tool_params(params)
        if validation_error:
            return False

        corrected_content_result = await self._get_corrected_file_content(
            params.file_path,
            params.content,
            abort_signal
        )

        if corrected_content_result.error:
            return False

        original_content = corrected_content_result.original_content
        corrected_content = corrected_content_result.corrected_content
        relative_path = make_relative(
            params.file_path,
            self.config.get_target_dir()
        )
        file_name = pathlib.Path(params.file_path).name

        # Create diff
        diff = difflib.unified_diff(
            original_content.splitlines(keepends=True),
            corrected_content.splitlines(keepends=True),
            fromfile='Current',
            tofile='Proposed',
            **DEFAULT_DIFF_OPTIONS
        )
        file_diff = ''.join(diff)

        confirmation_details: ToolEditConfirmationDetails = {
            'type': 'edit',
            'title': f'Confirm Write: {shorten_path(relative_path)}',
            'fileName': file_name,
            'fileDiff': file_diff,
            'originalContent': original_content,
            'newContent': corrected_content,
            'onConfirm': lambda outcome: self.config.set_approval_mode(ApprovalMode.AUTO_EDIT) if outcome == ToolConfirmationOutcome.ProceedAlways else self._execute_tool_with_params(params)
        }
        return confirmation_details

    async def execute(
        self, params: WriteFileToolParams, abort_signal
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return {
                'llmContent': f'Error: Invalid parameters provided. Reason: {validation_error}',
                'returnDisplay': f'Error: {validation_error}'
            }

        corrected_content_result = await self._get_corrected_file_content(
            params.file_path,
            params.content,
            abort_signal
        )

        if corrected_content_result.error:
            err_details = corrected_content_result.error
            error_msg = f'Error checking existing file: {err_details["message"]}'
            return {
                'llmContent': f'Error checking existing file {params.file_path}: {err_details["message"]}',
                'returnDisplay': error_msg
            }

        original_content = corrected_content_result.original_content
        file_content = corrected_content_result.corrected_content
        file_exists = corrected_content_result.file_exists
        is_new_file = not file_exists or (corrected_content_result.error is not None and not corrected_content_result.file_exists)

        try:
            dir_name = pathlib.Path(params.file_path).parent
            if not dir_name.exists():
                dir_name.mkdir(parents=True, exist_ok=True)

            with open(params.file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)

            # Generate diff for display result
            file_name = pathlib.Path(params.file_path).name
            current_content_for_diff = '' if corrected_content_result.error else original_content

            diff = difflib.unified_diff(
                current_content_for_diff.splitlines(keepends=True),
                file_content.splitlines(keepends=True),
                fromfile='Original',
                tofile='Written',
                **DEFAULT_DIFF_OPTIONS
            )
            file_diff = ''.join(diff)

            llm_success_message_parts = [
                f'Successfully created and wrote to new file: {params.file_path}.' if is_new_file else f'Successfully overwrote file: {params.file_path}.'
            ]
            if params.modified_by_user:
                llm_success_message_parts.append(
                    f'User modified the `content` to be: {params.content}'
                )

            display_result: FileDiff = {
                'fileDiff': file_diff,
                'fileName': file_name,
                'originalContent': original_content,
                'newContent': file_content
            }

            lines = len(file_content.split('\n'))
            mimetype = get_specific_mime_type(params.file_path)
            extension = pathlib.Path(params.file_path).suffix
            if is_new_file:
                record_file_operation_metric(
                    self.config,
                    FileOperation.CREATE,
                    lines,
                    mimetype,
                    extension
                )
            else:
                record_file_operation_metric(
                    self.config,
                    FileOperation.UPDATE,
                    lines,
                    mimetype,
                    extension
                )

            return {
                'llmContent': ' '.join(llm_success_message_parts),
                'returnDisplay': display_result
            }
        except Exception as error:
            error_msg = f'Error writing to file: {str(error)}'
            return {
                'llmContent': f'Error writing to file {params.file_path}: {error_msg}',
                'returnDisplay': f'Error: {error_msg}'
            }

    async def _get_corrected_file_content(
        self, file_path: str, proposed_content: str, abort_signal
    ) -> GetCorrectedFileContentResult:
        original_content = ''
        file_exists = False
        corrected_content = proposed_content

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            file_exists = True
        except Exception as err:
            if is_node_error(err) and err.code == 'ENOENT':
                file_exists = False
                original_content = ''
            else:
                file_exists = True
                original_content = ''
                error = {
                    'message': get_error_message(err),
                    'code': err.code if is_node_error(err) else None
                }
                return GetCorrectedFileContentResult(original_content, corrected_content, file_exists, error)

        if file_exists:
            corrected_params = await ensure_correct_edit(
                file_path,
                original_content,
                {
                    'old_string': original_content,
                    'new_string': proposed_content,
                    'file_path': file_path
                },
                self.config.get_gemini_client(),
                abort_signal
            )
            corrected_content = corrected_params['new_string']
        else:
            corrected_content = await ensure_correct_file_content(
                proposed_content,
                self.config.get_gemini_client(),
                abort_signal
            )

        return GetCorrectedFileContentResult(original_content, corrected_content, file_exists)

    def get_modify_context(
        self, abort_signal
    ) -> ModifyContext[WriteFileToolParams]:
        async def get_current_content(params: WriteFileToolParams) -> str:
            corrected_content_result = await self._get_corrected_file_content(
                params.file_path,
                params.content,
                abort_signal
            )
            return corrected_content_result.original_content

        async def get_proposed_content(params: WriteFileToolParams) -> str:
            corrected_content_result = await self._get_corrected_file_content(
                params.file_path,
                params.content,
                abort_signal
            )
            return corrected_content_result.corrected_content

        def create_updated_params(old_content: str, modified_proposed_content: str, original_params: WriteFileToolParams) -> WriteFileToolParams:
            return WriteFileToolParams(
                file_path=original_params.file_path,
                content=modified_proposed_content,
                modified_by_user=True
            )

        return {
            'getFilePath': lambda params: params.file_path,
            'getCurrentContent': get_current_content,
            'getProposedContent': get_proposed_content,
            'createUpdatedParams': create_updated_params
        }