import os
import re
import json
import shlex
import asyncio
import subprocess
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

from ..config import Config,BaseTool, ToolResult, Icon
from ..utils.logger import Logger
from ..utils.shell_quote import shell_quote
from .schema_validator import SchemaValidator
from google.genai.types import FunctionDeclaration,Schema,Type



class DiscoveredTool:
    def __init__(self,
                 config:Config,
                 name: str,
                 description: str,
                 params_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.params_schema = params_schema
        description += f'''This tool was discovered from the project by executing the command `{discovery_cmd}` on project root.
When called, this tool will execute the command `{call_command} {name}` on project root.
Tool discovery and call commands can be configured in project or user settings.

When called, the tool call command is executed as a subprocess.
On success, tool output is returned as a json string.
Otherwise, the following information is returned:

Stdout: Output on stdout stream. Can be `(empty)` or partial.
Stderr: Output on stderr stream. Can be `(empty)` or partial.
Error: Error or `(none)` if no error was reported for the subprocess.
Exit Code: Exit code or `(none)` if terminated by signal.
Signal: Signal number or `(none)` if no signal was received."
'''
        discovery_cmd = config.get_tool_discovery_command()
        call_command = config.get_tool_call_command()

        super().__init__(
            name,
            name,
            description,
            Icon.HAMMER,
            parameter_schema,
            False,  # is_output_markdown
            False,  # can_update_output
        )
        self.config = config

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        call_command = self.config.get_tool_call_command()
        cmd_parts = shlex.split(f"{call_command} {self.name}")

        try:
            process = await asyncio.create_subprocess_exec(
                cmd_parts[0],
                *cmd_parts[1:],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Write parameters to stdin
            stdin_data = json.dumps(params).encode()
            stdout, stderr = await process.communicate(stdin_data)

            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""
            error = None
            code = process.returncode
            signal = None  # Python doesn't provide signal information directly

            # Check for errors
            if code != 0 or stderr_str:
                llm_content = [
                    f"Stdout: {stdout_str or '(empty)'}",
                    f"Stderr: {stderr_str or '(empty)'}",
                    f"Error: {error or '(none)'}",
                    f"Exit Code: {code or '(none)'}",
                    f"Signal: {signal or '(none)'}",
                ]
                return {
                    "llmContent": "\n".join(llm_content),
                    "returnDisplay": "\n".join(llm_content),
                }

            return {
                "llmContent": stdout_str,
                "returnDisplay": stdout_str,
            }
        except Exception as e:
            llm_content = [
                f"Stdout: (empty)",
                f"Stderr: (empty)",
                f"Error: {str(e)}",
                f"Exit Code: (none)",
                f"Signal: (none)",
            ]
            return {
                "llmContent": "\n".join(llm_content),
                "returnDisplay": "\n".join(llm_content),
            }


class ToolRegistry:
    def __init__(self, config: Config):
        self.tools: Dict[str, Tool] = {}
        self.config = config

    def register_tool(self, tool: Tool) -> None:
        if tool.name in self.tools:
            if isinstance(tool, DiscoveredMCPTool):
                tool = tool.as_fully_qualified_tool()
            else:
                print(f"Warning: Tool with name '{tool.name}' is already registered. Overwriting.")
        self.tools[tool.name] = tool

    async def discover_all_tools(self) -> None:
        # Remove previously discovered tools
        for tool_name in list(self.tools.keys()):
            tool = self.tools[tool_name]
            if isinstance(tool, (DiscoveredTool, DiscoveredMCPTool)):
                del self.tools[tool_name]

        await self.discover_and_register_tools_from_command()

        # Discover tools from MCP servers
        await discover_mcp_tools(
            self.config.get_mcp_servers() or {},
            self.config.get_mcp_server_command(),
            self,
            self.config.get_prompt_registry(),
            self.config.get_debug_mode(),
        )

    async def discover_mcp_tools(self) -> None:
        # Remove previously discovered MCP tools
        for tool_name in list(self.tools.keys()):
            tool = self.tools[tool_name]
            if isinstance(tool, DiscoveredMCPTool):
                del self.tools[tool_name]

        # Discover tools from MCP servers
        await discover_mcp_tools(
            self.config.get_mcp_servers() or {},
            self.config.get_mcp_server_command(),
            self,
            self.config.get_prompt_registry(),
            self.config.get_debug_mode(),
        )

    async def discover_tools_for_server(self, server_name: str) -> None:
        # Remove previously discovered tools from this server
        for tool_name in list(self.tools.keys()):
            tool = self.tools[tool_name]
            if isinstance(tool, DiscoveredMCPTool) and tool.server_name == server_name:
                del self.tools[tool_name]

        mcp_servers = self.config.get_mcp_servers() or {}
        server_config = mcp_servers.get(server_name)
        if server_config:
            await discover_mcp_tools(
                {server_name: server_config},
                None,
                self,
                self.config.get_prompt_registry(),
                self.config.get_debug_mode(),
            )

    async def discover_and_register_tools_from_command(self) -> None:
        discovery_cmd = self.config.get_tool_discovery_command()
        if not discovery_cmd:
            return

        try:
            cmd_parts = shlex.split(discovery_cmd)
            if not cmd_parts:
                raise ValueError("Tool discovery command is empty or contains only whitespace.")

            process = await asyncio.create_subprocess_exec(
                cmd_parts[0],
                *cmd_parts[1:],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = await process.communicate()
            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            if process.returncode != 0:
                print(f"Command failed with code {process.returncode}")
                print(stderr_str)
                raise ValueError(f"Tool discovery command failed with exit code {process.returncode}")

            # Parse the output
            discovered_items = json.loads(stdout_str.strip())

            if not discovered_items or not isinstance(discovered_items, list):
                raise ValueError("Tool discovery command did not return a JSON array of tools.")

            functions = []
            for tool in discovered_items:
                if tool and isinstance(tool, dict):
                    if 'function_declarations' in tool and isinstance(tool['function_declarations'], list):
                        functions.extend(tool['function_declarations'])
                    elif 'functionDeclarations' in tool and isinstance(tool['functionDeclarations'], list):
                        functions.extend(tool['functionDeclarations'])
                    elif 'name' in tool:
                        functions.append(tool)

            # Register each function as a tool
            for func in functions:
                if not func.get('name'):
                    print("Warning: Discovered a tool with no name. Skipping.")
                    continue

                # Sanitize parameters
                parameters = func.get('parameters', {})
                if not isinstance(parameters, dict):
                    parameters = {}
                sanitize_parameters(parameters)

                self.register_tool(
                    DiscoveredTool(
                        self.config,
                        func['name'],
                        func.get('description', ''),
                        parameters,
                    )
                )

        except Exception as e:
            print(f"Tool discovery command '{discovery_cmd}' failed: {e}")
            raise

    def get_function_declarations(self) -> List[Dict[str, Any]]:
        declarations = []
        for tool in self.tools.values():
            declarations.append(tool.schema)
        return declarations

    def get_all_tools(self) -> List[Tool]:
        return sorted(self.tools.values(), key=lambda tool: tool.display_name)

    def get_tools_by_server(self, server_name: str) -> List[Tool]:
        server_tools = []
        for tool in self.tools.values():
            if isinstance(tool, DiscoveredMCPTool) and tool.server_name == server_name:
                server_tools.append(tool)
        return sorted(server_tools, key=lambda tool: tool.name)

    def get_tool(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)


def sanitize_parameters(schema: Optional[Dict[str, Any]] = None) -> None:
    """
    Sanitizes a schema object in-place to ensure compatibility with the Gemini API.

    NOTE: This function mutates the passed schema object.
    """
    visited = set()
    _sanitize_parameters(schema, visited)


def _sanitize_parameters(schema: Optional[Dict[str, Any]], visited: Set[Dict[str, Any]]) -> None:
    if not schema or schema in visited:
        return
    visited.add(schema)

    # Handle anyOf
    if 'anyOf' in schema:
        # Remove default if anyOf is present
        schema.pop('default', None)
        for item in schema['anyOf']:
            if isinstance(item, dict):
                _sanitize_parameters(item, visited)

    # Handle items
    if 'items' in schema and isinstance(schema['items'], dict):
        _sanitize_parameters(schema['items'], visited)

    # Handle properties
    if 'properties' in schema and isinstance(schema['properties'], dict):
        for item in schema['properties'].values():
            if isinstance(item, dict):
                _sanitize_parameters(item, visited)

    # Handle enum values
    if 'enum' in schema and isinstance(schema['enum'], list):
        # Ensure type is string for enum
        schema['type'] = 'string'
        # Filter out null and undefined, convert to strings
        schema['enum'] = [str(value) for value in schema['enum'] if value is not None]

    # Handle string formats
    if schema.get('type') == 'string':
        if 'format' in schema and schema['format'] not in ['enum', 'date-time']:
            schema.pop('format')