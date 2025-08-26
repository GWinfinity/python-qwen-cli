import os
import pathlib
import difflib
from typing import Optional, List, Dict, Any, Union, Tuple
from abc import ABC, abstractmethod
from google.genai.types import Type
from tools import (BaseTool,
  Icon,
  ToolCallConfirmationDetails,
  ToolConfirmationOutcome,
  ToolEditConfirmationDetails,
  ToolLocation,
  ToolResult,
  ToolResultDisplay)
from tool_error import ToolErrorType
from read_file import ReadFileTool
from diff_options import DEFAULT_DIFF_OPTIONS
from modifiable_tool import ModifiableTool, ModifyContext
from ..config.config import Config, ApprovalMode
from ..utils.schema_validator import SchemaValidator
from ..utils.path import make_relative, shorten_path
from ..utils.error import is_node_error
from ..utils.edit_corrector import ensure_correct_edit


class EditTool(BaseTool, ModifiableTool):
    Name = 'replace'
    
    def __init__(self, config):
        schema = {
            'properties': {
                'file_path': {
                    'description': "The absolute path to the file to modify. Must start with '/'.",
                    'type': Type.STRING,
                },
                'old_string': {
                    'description': 'The exact literal text to replace, preferably unescaped. For single replacements (default), include at least 3 lines of context BEFORE and AFTER the target text, matching whitespace and indentation precisely. For multiple replacements, specify expected_replacements parameter. If this string is not the exact literal text (i.e. you escaped it) or does not match exactly, the tool will fail.',
                    'type': Type.STRING,
                },
                'new_string': {
                    'description': 'The exact literal text to replace `old_string` with, preferably unescaped. Provide the EXACT text. Ensure the resulting code is correct and idiomatic.',
                    'type': Type.STRING,
                },
                'expected_replacements': {
                    'type': Type.NUMBER,
                    'description': 'Number of replacements expected. Defaults to 1 if not specified. Use when you want to replace multiple occurrences.',
                    'minimum': 1,
                },
            },
            'required': ['file_path', 'old_string', 'new_string'],
            'type': Type.OBJECT,
        }
        
        super().__init__(
            EditTool.Name,
            'Edit',
            "Replaces text within a file. By default, replaces a single occurrence, but can replace multiple occurrences when `expected_replacements` is specified. This tool requires providing significant context around the change to ensure precise targeting. Always use the read_file tool to examine the file's current content before attempting a text replacement.\n\nThe user has the ability to modify the `new_string` content. If modified, this will be stated in the response.\n\nExpectation for required parameters:\n1. `file_path` MUST be an absolute path; otherwise an error will be thrown.\n2. `old_string` MUST be the exact literal text to replace (including all whitespace, indentation, newlines, and surrounding code etc.).\n3. `new_string` MUST be the exact literal text to replace `old_string` with (also including all whitespace, indentation, newlines, and surrounding code etc.). Ensure the resulting code is correct and idiomatic.\n4. NEVER escape `old_string` or `new_string`, that would break the exact literal text requirement.\n**Important:** If ANY of the above are not satisfied, the tool will fail. CRITICAL for `old_string`: Must uniquely identify the single instance to change. Include at least 3 lines of context BEFORE and AFTER the target text, matching whitespace and indentation precisely. If this string matches multiple locations, or does not match exactly, the tool will fail.\n**Multiple replacements:** Set `expected_replacements` to the number of occurrences you want to replace. The tool will replace ALL occurrences that match `old_string` exactly. Ensure the number of replacements matches your expectation.",
            Icon.Pencil,
            schema,
        )
        self.config = config
        
    def validateToolParams(self, params: Dict[str, Any]) -> Optional[str]:
        errors = SchemaValidator.validate(self.schema['parameters'], params)
        if errors:
            return errors
        
        if not os.path.isabs(params['file_path']):
            return f"File path must be absolute: {params['file_path']}"
        
        workspace_context = self.config.getWorkspaceContext()
        if hasattr(workspace_context, 'isPathWithinWorkspace') and not workspace_context.isPathWithinWorkspace(params['file_path']):
            directories = workspace_context.getDirectories()
            return f"File path must be within one of the workspace directories: {', '.join(directories)}"
        
        return None
        
    def toolLocations(self, params: Dict[str, Any]) -> List[ToolLocation]:
        return [{'path': params['file_path']}]
        
    def _applyReplacement(self, current_content: Optional[str], old_string: str, new_string: str, is_new_file: bool) -> str:
        if is_new_file:
            return new_string
        if current_content is None:
            # 如果不是新文件但内容为None，防御性地返回空或new_string
            return new_string if old_string == '' else ''
        # 如果old_string为空且不是新文件，不修改内容
        if old_string == '' and not is_new_file:
            return current_content
        return current_content.replace(old_string, new_string)
        
    async def calculateEdit(self, params: Dict[str, Any], abort_signal) -> Dict[str, Any]:
        expected_replacements = params.get('expected_replacements', 1)
        current_content: Optional[str] = None
        file_exists = False
        is_new_file = False
        final_new_string = params['new_string']
        final_old_string = params['old_string']
        occurrences = 0
        error: Optional[Dict[str, str]] = None
        
        try:
            with open(params['file_path'], 'r', encoding='utf-8') as f:
                current_content = f.read()
                # 规范化行结尾为LF以便一致处理
                current_content = current_content.replace('\r\n', '\n')
                file_exists = True
        except FileNotFoundError:
            file_exists = False
        except Exception as err:
            # 重新抛出意外的文件系统错误（权限等）
            raise err
        
        if params['old_string'] == '' and not file_exists:
            # 创建新文件
            is_new_file = True
        elif not file_exists:
            # 尝试编辑不存在的文件（且old_string不为空）
            error = {
                'display': "File not found. Cannot apply edit. Use an empty old_string to create a new file.",
                'raw': f"File not found: {params['file_path']}",
                'type': ToolErrorType.FILE_NOT_FOUND,
            }
        elif current_content is not None:
            # 编辑现有文件
            corrected_edit = ensure_correct_edit(
                params.file_path,
                current_content,
                params,
                self.config.getGeminiClient(),
                abortSignal,)

            final_old_string = corrected_edit['params']['old_string']
            final_new_string = corrected_edit['params']['new_string']
            occurrences = corrected_edit['occurrences']
            
            if params['old_string'] == '':
                # 错误：尝试创建已存在的文件
                error = {
                    'display': "Failed to edit. Attempted to create a file that already exists.",
                    'raw': f"File already exists, cannot create: {params['file_path']}",
                    'type': ToolErrorType.ATTEMPT_TO_CREATE_EXISTING_FILE,
                }
            elif occurrences == 0:
                error = {
                    'display': "Failed to edit, could not find the string to replace.",
                    'raw': f"Failed to edit, 0 occurrences found for old_string in {params['file_path']}. No edits made. The exact text in old_string was not found. Ensure you're not escaping content incorrectly and check whitespace, indentation, and context. Use read_file tool to verify.",
                    'type': ToolErrorType.EDIT_NO_OCCURRENCE_FOUND,
                }
            elif occurrences != expected_replacements:
                occurrence_term = 'occurrence' if expected_replacements == 1 else 'occurrences'
                
                error = {
                    'display': f"Failed to edit, expected {expected_replacements} {occurrence_term} but found {occurrences}.",
                    'raw': f"Failed to edit, Expected {expected_replacements} {occurrence_term} but found {occurrences} for old_string in file: {params['file_path']}",
                    'type': ToolErrorType.EDIT_EXPECTED_OCCURRENCE_MISMATCH,
                }
            elif final_old_string == final_new_string:
                error = {
                    'display': "No changes to apply. The old_string and new_string are identical.",
                    'raw': f"No changes to apply. The old_string and new_string are identical in file: {params['file_path']}",
                    'type': ToolErrorType.EDIT_NO_CHANGE,
                }
        else:
            # 如果文件存在且没有抛出异常，这不应该发生，但防御性地处理：
            error = {
                'display': "Failed to read content of file.",
                'raw': f"Failed to read content of existing file: {params['file_path']}",
                'type': ToolErrorType.READ_CONTENT_FAILURE,
            }
        
        new_content = self._applyReplacement(
            current_content,
            final_old_string,
            final_new_string,
            is_new_file,
        )
        
        return {
            'currentContent': current_content,
            'newContent': new_content,
            'occurrences': occurrences,
            'error': error,
            'isNewFile': is_new_file,
        }
        
    async def shouldConfirmExecute(self, params: Dict[str, Any], abort_signal) -> Union[ToolCallConfirmationDetails, bool]:
        if hasattr(self.config, 'getApprovalMode') and self.config.getApprovalMode() == ApprovalMode.AUTO_EDIT:
            return False
        
        validation_error = self.validateToolParams(params)
        if validation_error:
            print(f"[EditTool Wrapper] Attempted confirmation with invalid parameters: {validation_error}")
            return False
        
        try:
            edit_data = await self.calculateEdit(params, abort_signal)
        except Exception as error:
            error_msg = str(error)
            print(f"Error preparing edit: {error_msg}")
            return False
        
        if edit_data['error']:
            print(f"Error: {edit_data['error']['display']}")
            return False
        
        file_name = os.path.basename(params['file_path'])
        
        # 创建差异补丁
        current_lines = (edit_data['currentContent'] or '').split('\n')
        new_lines = edit_data['newContent'].split('\n')
        
        differ = difflib.unified_diff(
            current_lines,
            new_lines,
            fromfile='Current',
            tofile='Proposed',
            lineterm='',
            n=DEFAULT_DIFF_OPTIONS.get('context', 3)
        )
        
        file_diff = '\n'.join(differ)
        
        async def on_confirm(outcome: ToolConfirmationOutcome):
            if outcome == 'ProceedAlways' and hasattr(self.config, 'setApprovalMode'):
                self.config.setApprovalMode(ApprovalMode.AUTO_EDIT)
        
        confirmation_details = {
            'type': 'edit',
            'title': f"Confirm Edit: {shorten_path(make_relative(params['file_path'], self.config.getTargetDir()))}",
            'fileName': file_name,
            'fileDiff': file_diff,
            'originalContent': edit_data['currentContent'],
            'newContent': edit_data['newContent'],
            'onConfirm': on_confirm,
        }
        
        return confirmation_details
        
    def getDescription(self, params: Dict[str, Any]) -> str:
        if not params.get('file_path') or not params.get('old_string') or not params.get('new_string'):
            return "Model did not provide valid parameters for edit tool"
        
        target_dir = self.config.getTargetDir() if hasattr(self.config, 'getTargetDir') else os.getcwd()
        relative_path = make_relative(params['file_path'], target_dir)
        
        if params['old_string'] == '':
            return f"Create {shorten_path(relative_path)}"
        
        old_string_snippet = params['old_string'].split('\n')[0][:30]
        if len(params['old_string']) > 30:
            old_string_snippet += '...'
            
        new_string_snippet = params['new_string'].split('\n')[0][:30]
        if len(params['new_string']) > 30:
            new_string_snippet += '...'
        
        if params['old_string'] == params['new_string']:
            return f"No file changes to {shorten_path(relative_path)}"
        
        return f"{shorten_path(relative_path)}: {old_string_snippet} => {new_string_snippet}"
        
    async def execute(self, params: Dict[str, Any], signal) -> ToolResult:
        validation_error = self.validateToolParams(params)
        if validation_error:
            return {
                'llmContent': f"Error: Invalid parameters provided. Reason: {validation_error}",
                'returnDisplay': f"Error: {validation_error}",
                'error': {
                    'message': validation_error,
                    'type': ToolErrorType.INVALID_TOOL_PARAMS,
                },
            }
        
        try:
            edit_data = await self.calculateEdit(params, signal)
        except Exception as error:
            error_msg = str(error)
            return {
                'llmContent': f"Error preparing edit: {error_msg}",
                'returnDisplay': f"Error preparing edit: {error_msg}",
                'error': {
                    'message': error_msg,
                    'type': ToolErrorType.EDIT_PREPARATION_FAILURE,
                },
            }
        
        if edit_data['error']:
            return {
                'llmContent': edit_data['error']['raw'],
                'returnDisplay': f"Error: {edit_data['error']['display']}",
                'error': {
                    'message': edit_data['error']['raw'],
                    'type': edit_data['error']['type'],
                },
            }
        
        try:
            self.ensureParentDirectoriesExist(params['file_path'])
            with open(params['file_path'], 'w', encoding='utf-8') as f:
                f.write(edit_data['newContent'])
                
            display_result: Union[str, Dict[str, Any]]
            target_dir = self.config.getTargetDir() if hasattr(self.config, 'getTargetDir') else os.getcwd()
            
            if edit_data['isNewFile']:
                display_result = f"Created {shorten_path(make_relative(params['file_path'], target_dir))}"
            else:
                # 生成用于显示的差异，即使核心逻辑在技术上不需要它
                file_name = os.path.basename(params['file_path'])
                current_lines = (edit_data['currentContent'] or '').split('\n')
                new_lines = edit_data['newContent'].split('\n')
                
                differ = difflib.unified_diff(
                    current_lines,
                    new_lines,
                    fromfile='Current',
                    tofile='Proposed',
                    lineterm='',
                    n=DEFAULT_DIFF_OPTIONS.get('context', 3)
                )
                
                file_diff = '\n'.join(differ)
                
                display_result = {
                    'fileDiff': file_diff,
                    'fileName': file_name,
                    'originalContent': edit_data['currentContent'],
                    'newContent': edit_data['newContent'],
                }
            
            llm_success_message_parts = []
            if edit_data['isNewFile']:
                llm_success_message_parts.append(f"Created new file: {params['file_path']} with provided content.")
            else:
                llm_success_message_parts.append(f"Successfully modified file: {params['file_path']} ({edit_data['occurrences']} replacements).")
                
            if params.get('modified_by_user'):
                llm_success_message_parts.append(f"User modified the `new_string` content to be: {params['new_string']}.")
                
            return {
                'llmContent': ' '.join(llm_success_message_parts),
                'returnDisplay': display_result,
            }
        except Exception as error:
            error_msg = str(error)
            return {
                'llmContent': f"Error executing edit: {error_msg}",
                'returnDisplay': f"Error writing file: {error_msg}",
                'error': {
                    'message': error_msg,
                    'type': ToolErrorType.FILE_WRITE_FAILURE,
                },
            }
        
    def ensureParentDirectoriesExist(self, file_path: str) -> None:
        dir_name = os.path.dirname(file_path)
        if not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        
    def getModifyContext(self, _):
        async def get_file_path(params: Dict[str, Any]) -> str:
            return params['file_path']
            
        async def get_current_content(params: Dict[str, Any]) -> str:
            try:
                with open(params['file_path'], 'r', encoding='utf-8') as f:
                    return f.read()
            except FileNotFoundError:
                return ''
            except Exception as err:
                if not is_node_error(err):
                    raise err
                return ''
                
        async def get_proposed_content(params: Dict[str, Any]) -> str:
            try:
                with open(params['file_path'], 'r', encoding='utf-8') as f:
                    current_content = f.read()
                    return self._applyReplacement(
                        current_content,
                        params['old_string'],
                        params['new_string'],
                        params['old_string'] == '' and current_content == '',
                    )
            except FileNotFoundError:
                return ''
            except Exception as err:
                if not is_node_error(err):
                    raise err
                return ''
                
        def create_updated_params(old_content: str, modified_proposed_content: str, original_params: Dict[str, Any]) -> Dict[str, Any]:
            updated_params = dict(original_params)
            updated_params['old_string'] = old_content
            updated_params['new_string'] = modified_proposed_content
            updated_params['modified_by_user'] = True
            return updated_params
            
        return {
            'getFilePath': get_file_path,
            'getCurrentContent': get_current_content,
            'getProposedContent': get_proposed_content,
            'createUpdatedParams': create_updated_params,
        }