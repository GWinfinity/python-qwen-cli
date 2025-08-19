"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import os
import pathlib
import sys
from enum import Enum
from typing import Any, Dict, List, Optional, Record, Set, Tuple, Type, Union, cast
from dataclasses import dataclass

# 假设以下模块已在 Python 中实现
from core.contentGenerator import AuthType, ContentGeneratorConfig, create_content_generator_config
from prompts.prompt_registry import PromptRegistry
from tools.tool_registry import ToolRegistry
from tools.ls import LSTool
from tools.read_file import ReadFileTool
from tools.grep import GrepTool
from tools.glob import GlobTool
from tools.edit import EditTool
from tools.shell import ShellTool
from tools.write_file import WriteFileTool
from tools.web_fetch import WebFetchTool
from tools.read_many_files import ReadManyFilesTool
from tools.memory_tool import MemoryTool, set_gemini_md_filename, GEMINI_DIR
from tools.web_search import WebSearchTool
from core.client import GeminiClient
from services.file_discovery_service import FileDiscoveryService
from services.git_service import GitService
from utils.paths import get_project_temp_dir
from telemetry.index import (
    initialize_telemetry,
    DEFAULT_TELEMETRY_TARGET,
    DEFAULT_OTLP_ENDPOINT,
    TelemetryTarget,
    StartSessionEvent,
)
from models import DEFAULT_GEMINI_EMBEDDING_MODEL, DEFAULT_GEMINI_FLASH_MODEL
from telemetry.clearcut_logger.clearcut_logger import ClearcutLogger
from utils.browser import should_attempt_browser_launch
from mcp.oauth_provider import MCPOAuthConfig
from ide.ide_client import IdeClient
from google.genai import Content
from utils.workspace_context import WorkspaceContext

class ApprovalMode(Enum):
    DEFAULT = 'default'
    AUTO_EDIT = 'autoEdit'
    YOLO = 'yolo'


class AuthProviderType(Enum):
    DYNAMIC_DISCOVERY = 'dynamic_discovery'
    GOOGLE_CREDENTIALS = 'google_credentials'


@dataclass
class AccessibilitySettings:
    disable_loading_phrases: Optional[bool] = None


@dataclass
class BugCommandSettings:
    url_template: str


@dataclass
class SummarizeToolOutputSettings:
    token_budget: Optional[int] = None


@dataclass
class TelemetrySettings:
    enabled: Optional[bool] = None
    target: Optional[TelemetryTarget] = None
    otlp_endpoint: Optional[str] = None
    log_prompts: Optional[bool] = None
    outfile: Optional[str] = None


@dataclass
class GitCoAuthorSettings:
    enabled: Optional[bool] = None
    name: Optional[str] = None
    email: Optional[str] = None


@dataclass
class GeminiCLIExtension:
    name: str
    version: str
    is_active: bool
    path: str


@dataclass
class FileFilteringOptions:
    respect_git_ignore: bool
    respect_gemini_ignore: bool


# For memory files
DEFAULT_MEMORY_FILE_FILTERING_OPTIONS = FileFilteringOptions(
    respect_git_ignore=False,
    respect_gemini_ignore=True
)

# For all other files
DEFAULT_FILE_FILTERING_OPTIONS = FileFilteringOptions(
    respect_git_ignore=True,
    respect_gemini_ignore=True
)


class MCPServerConfig:
    def __init__(
        self,
        # For stdio transport
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        # For sse transport
        url: Optional[str] = None,
        # For streamable http transport
        http_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        # For websocket transport
        tcp: Optional[str] = None,
        # Common
        timeout: Optional[int] = None,
        trust: Optional[bool] = None,
        # Metadata
        description: Optional[str] = None,
        include_tools: Optional[List[str]] = None,
        exclude_tools: Optional[List[str]] = None,
        extension_name: Optional[str] = None,
        # OAuth configuration
        oauth: Optional[MCPOAuthConfig] = None,
        auth_provider_type: Optional[AuthProviderType] = None,
    ):
        self.command = command
        self.args = args
        self.env = env
        self.cwd = cwd
        self.url = url
        self.http_url = http_url
        self.headers = headers
        self.tcp = tcp
        self.timeout = timeout
        self.trust = trust
        self.description = description
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.extension_name = extension_name
        self.oauth = oauth
        self.auth_provider_type = auth_provider_type


class Config:
    def __init__(self, params: Dict[str, Any]):
        self.session_id = params['sessionId']
        self.embedding_model = params.get('embeddingModel', DEFAULT_GEMINI_EMBEDDING_MODEL)
        self.sandbox = params.get('sandbox')
        self.target_dir = os.path.resolve(params['targetDir'])
        self.workspace_context = WorkspaceContext(
            self.target_dir,
            params.get('includeDirectories', [])
        )
        self.debug_mode = params['debugMode']
        self.question = params.get('question')
        self.full_context = params.get('fullContext', False)
        self.core_tools = params.get('coreTools')
        self.exclude_tools = params.get('excludeTools')
        self.tool_discovery_command = params.get('toolDiscoveryCommand')
        self.tool_call_command = params.get('toolCallCommand')
        self.mcp_server_command = params.get('mcpServerCommand')
        self.mcp_servers = params.get('mcpServers')
        self.user_memory = params.get('userMemory', '')
        self.gemini_md_file_count = params.get('geminiMdFileCount', 0)
        self.approval_mode = params.get('approvalMode', ApprovalMode.DEFAULT)
        self.show_memory_usage = params.get('showMemoryUsage', False)
        self.accessibility = params.get('accessibility', {})
        
        # Telemetry settings
        telemetry_params = params.get('telemetry', {})
        self.telemetry_settings = TelemetrySettings(
            enabled=telemetry_params.get('enabled', False),
            target=telemetry_params.get('target', DEFAULT_TELEMETRY_TARGET),
            otlp_endpoint=telemetry_params.get('otlpEndpoint', DEFAULT_OTLP_ENDPOINT),
            log_prompts=telemetry_params.get('logPrompts', True),
            outfile=telemetry_params.get('outfile')
        )
        
        # Git co-author settings
        git_co_author_params = params.get('gitCoAuthor', {})
        self.git_co_author = GitCoAuthorSettings(
            enabled=git_co_author_params.get('enabled', True),
            name=git_co_author_params.get('name', 'Qwen-Coder'),
            email=git_co_author_params.get('email', 'qwen-coder@alibabacloud.com')
        )
        
        self.usage_statistics_enabled = params.get('usageStatisticsEnabled', True)
        
        # File filtering settings
        file_filtering_params = params.get('fileFiltering', {})
        self.file_filtering = {
            'respectGitIgnore': file_filtering_params.get('respectGitIgnore', True),
            'respectGeminiIgnore': file_filtering_params.get('respectGeminiIgnore', True),
            'enableRecursiveFileSearch': file_filtering_params.get('enableRecursiveFileSearch', True)
        }
        
        self.checkpointing = params.get('checkpointing', False)
        self.proxy = params.get('proxy')
        self.cwd = params.get('cwd', os.getcwd())
        self.file_discovery_service = params.get('fileDiscoveryService')
        self.bug_command = params.get('bugCommand')
        self.model = params['model']
        self.extension_context_file_paths = params.get('extensionContextFilePaths', [])
        self.max_session_turns = params.get('maxSessionTurns', -1)
        self.session_token_limit = params.get('sessionTokenLimit', -1)
        self.max_folder_items = params.get('maxFolderItems', 20)
        self.experimental_acp = params.get('experimentalAcp', False)
        self.list_extensions = params.get('listExtensions', False)
        self._extensions = params.get('extensions', [])
        self._blocked_mcp_servers = params.get('blockedMcpServers', [])
        self.no_browser = params.get('noBrowser', False)
        self.summarize_tool_output = params.get('summarizeToolOutput')
        self.ide_mode_feature = params.get('ideModeFeature', False)
        self.ide_mode = params.get('ideMode', False)
        self.ide_client = params.get('ideClient') or IdeClient.get_instance(
            self.ide_mode and self.ide_mode_feature
        )
        self.system_prompt_mappings = params.get('systemPromptMappings')
        self.enable_openai_logging = params.get('enableOpenAILogging', False)
        self.sampling_params = params.get('sampling_params')
        self.content_generator = params.get('content_generator')
        
        # Initialize other properties
        self.tool_registry: Optional[ToolRegistry] = None
        self.prompt_registry: Optional[PromptRegistry] = None
        self.content_generator_config: Optional[ContentGeneratorConfig] = None
        self.gemini_client: Optional[GeminiClient] = None
        self.git_service: Optional[GitService] = None
        self.in_fallback_mode = False
        self.flash_fallback_handler: Optional[Any] = None
        self.quota_error_occurred = False
        
        # Set gemini md filename if provided
        if 'contextFileName' in params:
            set_gemini_md_filename(params['contextFileName'])
        
        # Initialize telemetry if enabled
        if self.telemetry_settings.enabled:
            initialize_telemetry(self)
        
        # Log start session event if usage statistics are enabled
        if self.get_usage_statistics_enabled():
            ClearcutLogger.get_instance(self).log_start_session_event(StartSessionEvent(self))
        else:
            print('Data collection is disabled.')

    async def initialize(self) -> None:
        # Initialize centralized FileDiscoveryService
        self.get_file_service()
        if self.get_checkpointing_enabled():
            await self.get_git_service()
        self.prompt_registry = PromptRegistry()
        self.tool_registry = await self.create_tool_registry()

    async def refresh_auth(self, auth_method: AuthType) -> None:
        # Save the current conversation history before creating a new client
        existing_history: List[Content] = []
        if self.gemini_client and self.gemini_client.is_initialized():
            existing_history = self.gemini_client.get_history()
        
        # Create new content generator config
        new_content_generator_config = create_content_generator_config(
            self, auth_method
        )
        
        # Create and initialize new client in local variable first
        new_gemini_client = GeminiClient(self)
        await new_gemini_client.initialize(new_content_generator_config)
        
        # Only assign to instance properties after successful initialization
        self.content_generator_config = new_content_generator_config
        self.gemini_client = new_gemini_client
        
        # Restore the conversation history to the new client
        if existing_history:
            self.gemini_client.set_history(existing_history)
        
        # Reset the session flag since we're explicitly changing auth and using default model
        self.in_fallback_mode = False

    def get_session_id(self) -> str:
        return self.session_id

    def get_content_generator_config(self) -> ContentGeneratorConfig:
        return self.content_generator_config

    def get_model(self) -> str:
        return self.content_generator_config.model if self.content_generator_config else self.model

    def set_model(self, new_model: str) -> None:
        if self.content_generator_config:
            self.content_generator_config.model = new_model

    def is_in_fallback_mode(self) -> boolean:
        return self.in_fallback_mode

    def set_fallback_mode(self, active: boolean) -> None:
        self.in_fallback_mode = active

    def set_flash_fallback_handler(self, handler: Any) -> None:
        self.flash_fallback_handler = handler

    def get_max_session_turns(self) -> int:
        return self.max_session_turns

    def get_session_token_limit(self) -> int:
        return self.session_token_limit

    def get_max_folder_items(self) -> int:
        return self.max_folder_items

    def set_quota_error_occurred(self, value: boolean) -> None:
        self.quota_error_occurred = value

    def get_quota_error_occurred(self) -> boolean:
        return self.quota_error_occurred

    def get_embedding_model(self) -> str:
        return self.embedding_model

    def get_sandbox(self) -> Optional[Any]:
        return self.sandbox

    def is_restrictive_sandbox(self) -> boolean:
        sandbox_config = self.get_sandbox()
        seatbelt_profile = os.environ.get('SEATBELT_PROFILE')
        return (
            sandbox_config is not None and
            sandbox_config.command == 'sandbox-exec' and
            seatbelt_profile is not None and
            seatbelt_profile.startswith('restrictive-')
        )

    def get_target_dir(self) -> str:
        return self.target_dir

    def get_project_root(self) -> str:
        return self.target_dir

    def get_workspace_context(self) -> WorkspaceContext:
        return self.workspace_context

    def get_tool_registry(self) -> ToolRegistry:
        return self.tool_registry

    def get_prompt_registry(self) -> PromptRegistry:
        return self.prompt_registry

    def get_debug_mode(self) -> boolean:
        return self.debug_mode

    def get_question(self) -> Optional[str]:
        return self.question

    def get_full_context(self) -> boolean:
        return self.full_context

    def get_core_tools(self) -> Optional[List[str]]:
        return self.core_tools

    def get_exclude_tools(self) -> Optional[List[str]]:
        return self.exclude_tools

    def get_tool_discovery_command(self) -> Optional[str]:
        return self.tool_discovery_command

    def get_tool_call_command(self) -> Optional[str]:
        return self.tool_call_command

    def get_mcp_server_command(self) -> Optional[str]:
        return self.mcp_server_command

    def get_mcp_servers(self) -> Optional[Dict[str, MCPServerConfig]]:
        return self.mcp_servers

    def get_user_memory(self) -> str:
        return self.user_memory

    def set_user_memory(self, new_user_memory: str) -> None:
        self.user_memory = new_user_memory

    def get_gemini_md_file_count(self) -> int:
        return self.gemini_md_file_count

    def set_gemini_md_file_count(self, count: int) -> None:
        self.gemini_md_file_count = count

    def get_approval_mode(self) -> ApprovalMode:
        return self.approval_mode

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        self.approval_mode = mode

    def get_show_memory_usage(self) -> boolean:
        return self.show_memory_usage

    def get_accessibility(self) -> Dict[str, Any]:
        return self.accessibility

    def get_telemetry_enabled(self) -> boolean:
        return self.telemetry_settings.enabled if self.telemetry_settings.enabled is not None else False

    def get_telemetry_log_prompts_enabled(self) -> boolean:
        return self.telemetry_settings.log_prompts if self.telemetry_settings.log_prompts is not None else True

    def get_telemetry_otlp_endpoint(self) -> str:
        return self.telemetry_settings.otlp_endpoint if self.telemetry_settings.otlp_endpoint is not None else DEFAULT_OTLP_ENDPOINT

    def get_telemetry_target(self) -> TelemetryTarget:
        return self.telemetry_settings.target if self.telemetry_settings.target is not None else DEFAULT_TELEMETRY_TARGET

    def get_telemetry_outfile(self) -> Optional[str]:
        return self.telemetry_settings.outfile

    def get_git_co_author(self) -> GitCoAuthorSettings:
        return self.git_co_author

    def get_gemini_client(self) -> GeminiClient:
        return self.gemini_client

    def get_gemini_dir(self) -> str:
        return os.path.join(self.target_dir, GEMINI_DIR)

    def get_project_temp_dir(self) -> str:
        return get_project_temp_dir(self.get_project_root())

    def get_enable_recursive_file_search(self) -> boolean:
        return self.file_filtering['enableRecursiveFileSearch']

    def get_file_filtering_respect_git_ignore(self) -> boolean:
        return self.file_filtering['respectGitIgnore']

    def get_file_filtering_respect_gemini_ignore(self) -> boolean:
        return self.file_filtering['respectGeminiIgnore']

    def get_file_filtering_options(self) -> FileFilteringOptions:
        return FileFilteringOptions(
            respect_git_ignore=self.file_filtering['respectGitIgnore'],
            respect_gemini_ignore=self.file_filtering['respectGeminiIgnore']
        )

    def get_checkpointing_enabled(self) -> boolean:
        return self.checkpointing

    def get_proxy(self) -> Optional[str]:
        return self.proxy

    def get_working_dir(self) -> str:
        return self.cwd

    def get_bug_command(self) -> Optional[BugCommandSettings]:
        return self.bug_command

    def get_file_service(self) -> FileDiscoveryService:
        if not self.file_discovery_service:
            self.file_discovery_service = FileDiscoveryService(self.target_dir)
        return self.file_discovery_service

    def get_usage_statistics_enabled(self) -> boolean:
        return self.usage_statistics_enabled

    def get_extension_context_file_paths(self) -> List[str]:
        return self.extension_context_file_paths

    def get_experimental_acp(self) -> boolean:
        return self.experimental_acp

    def get_list_extensions(self) -> boolean:
        return self.list_extensions

    def get_extensions(self) -> List[GeminiCLIExtension]:
        return self._extensions

    def get_blocked_mcp_servers(self) -> List[Dict[str, str]]:
        return self._blocked_mcp_servers

    def get_no_browser(self) -> boolean:
        return self.no_browser

    def is_browser_launch_suppressed(self) -> boolean:
        return self.get_no_browser() or not should_attempt_browser_launch()

    def get_summarize_tool_output_config(self) -> Optional[Dict[str, SummarizeToolOutputSettings]]:
        return self.summarize_tool_output

    def get_ide_mode_feature(self) -> boolean:
        return self.ide_mode_feature

    def get_ide_client(self) -> IdeClient:
        return self.ide_client

    def get_ide_mode(self) -> boolean:
        return self.ide_mode

    def set_ide_mode(self, value: boolean) -> None:
        self.ide_mode = value

    def set_ide_client_disconnected(self) -> None:
        self.ide_client.set_disconnected()

    def set_ide_client_connected(self) -> None:
        self.ide_client.reconnect(self.ide_mode and self.ide_mode_feature)

    def get_enable_openai_logging(self) -> boolean:
        return self.enable_openai_logging

    def get_sampling_params(self) -> Optional[Dict[str, Any]]:
        return self.sampling_params

    def get_content_generator_timeout(self) -> Optional[int]:
        return self.content_generator['timeout'] if self.content_generator else None

    def get_content_generator_max_retries(self) -> Optional[int]:
        return self.content_generator['maxRetries'] if self.content_generator else None

    def get_system_prompt_mappings(self) -> Optional[List[Dict[str, Any]]]:
        return self.system_prompt_mappings

    async def get_git_service(self) -> GitService:
        if not self.git_service:
            self.git_service = GitService(self.target_dir)
            await self.git_service.initialize()
        return self.git_service

    async def create_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry(self)

        # helper to create & register core tools that are enabled
        def register_core_tool(tool_class: Type[Any], *args: Any) -> None:
            class_name = tool_class.__name__
            tool_name = getattr(tool_class, 'Name', class_name)
            core_tools = self.get_core_tools()
            exclude_tools = self.get_exclude_tools()

            is_enabled = False
            if core_tools is None:
                is_enabled = True
            else:
                is_enabled = any(
                    tool == class_name or
                    tool == tool_name or
                    tool.startswith(f'{class_name}(') or
                    tool.startswith(f'{tool_name}(')
                    for tool in core_tools
                )

            if (
                exclude_tools and (class_name in exclude_tools or tool_name in exclude_tools)
            ):
                is_enabled = False

            if is_enabled:
                registry.register_tool(tool_class(*args))

        register_core_tool(LSTool, self)
        register_core_tool(ReadFileTool, self)
        register_core_tool(GrepTool, self)
        register_core_tool(GlobTool, self)
        register_core_tool(EditTool, self)
        register_core_tool(WriteFileTool, self)
        register_core_tool(WebFetchTool, self)
        register_core_tool(ReadManyFilesTool, self)
        register_core_tool(ShellTool, self)
        register_core_tool(MemoryTool)
        register_core_tool(WebSearchTool, self)

        await registry.discover_all_tools()
        return registry


# Export model constants for use in CLI
export_default_gemini_flash_model = DEFAULT_GEMINI_FLASH_MODEL