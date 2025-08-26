import asyncio
import re
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Set, Tuple, Protocol, Union
import os
import json
from urllib.parse import urlparse

# 模拟导入，实际项目中需要替换为真实的导入
from mcp.client import Client
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import StreamableHTTPTransport
from mcp.types import Prompt, ListPromptsResult,GetPromptRequest,GetPromptRequestParams


# TODO: 定义MCP客户端的配置选项
# js-mcp 包有很多 *Transport 接口和 Options 类型需要转化适配Python，明天继续。

# 常量定义
def get_error_message(error: Exception) -> str:
    """获取异常的错误消息"""
    return str(error)

# 假设的类型定义，实际项目中需要替换为真实的类型
class Client:
    """MCP客户端类"""
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get('name')
        self.version = config.get('version')
        self._onerror = None
        self._call_tool = None
    
    @property
    def onerror(self) -> Optional[Callable[[Exception], None]]:
        return self._onerror
    
    @onerror.setter
    def onerror(self, callback: Optional[Callable[[Exception], None]]) -> None:
        self._onerror = callback
    
    async def connect(self, transport: Any, options: Dict[str, Any]) -> None:
        """连接到MCP服务器"""
        pass
    
    def close(self) -> None:
        """关闭连接"""
        pass
    
    async def request(self, params: Dict[str, Any], schema: Any = None) -> Any:
        """发送请求到MCP服务器"""
        pass

class MCPServerConfig:
    """MCP服务器配置"""
    def __init__(self, **kwargs):
        self.http_url: Optional[str] = kwargs.get('httpUrl')
        self.url: Optional[str] = kwargs.get('url')
        self.command: Optional[str] = kwargs.get('command')
        self.args: Optional[List[str]] = kwargs.get('args')
        self.env: Optional[Dict[str, str]] = kwargs.get('env')
        self.cwd: Optional[str] = kwargs.get('cwd')
        self.headers: Optional[Dict[str, str]] = kwargs.get('headers')
        self.timeout: Optional[int] = kwargs.get('timeout')
        self.trust: Optional[bool] = kwargs.get('trust')
        self.oauth: Optional[Dict[str, Any]] = kwargs.get('oauth')
        self.auth_provider_type: Optional[str] = kwargs.get('authProviderType')
        self.include_tools: Optional[List[str]] = kwargs.get('includeTools')
        self.exclude_tools: Optional[List[str]] = kwargs.get('excludeTools')

class ToolRegistry:
    """工具注册表"""
    def register_tool(self, tool: Any) -> None:
        """注册工具"""
        pass

class PromptRegistry:
    """提示注册表"""
    def register_prompt(self, prompt: Any) -> None:
        """注册提示"""
        pass

class DiscoveredMCPTool:
    """发现的MCP工具"""
    def __init__(self, callable_tool: Any, server_name: str, name: str, description: str,
                 parameters_json_schema: Dict[str, Any], timeout: int, trust: Optional[bool]):
        self.callable_tool = callable_tool
        self.server_name = server_name
        self.name = name
        self.description = description
        self.parameters_json_schema = parameters_json_schema
        self.timeout = timeout
        self.trust = trust

class FunctionDeclaration:
    """函数声明"""
    def __init__(self, **kwargs):
        self.name: Optional[str] = kwargs.get('name')
        self.description: Optional[str] = kwargs.get('description')
        self.parameters_json_schema: Optional[Dict[str, Any]] = kwargs.get('parametersJsonSchema')

# 常量
MCP_DEFAULT_TIMEOUT_MSEC = 10 * 60 * 1000  # 默认10分钟

# 类型定义
class DiscoveredMCPPrompt:
    """发现的MCP提示"""
    def __init__(self, prompt: Any, server_name: str, invoke_func: Callable[[Dict[str, Any]], Any]):
        self.prompt = prompt
        self.server_name = server_name
        self.invoke = invoke_func

# 枚举定义
class MCPServerStatus(Enum):
    """表示MCP服务器的连接状态"""
    DISCONNECTED = 'disconnected'  # 服务器已断开连接或遇到错误
    CONNECTING = 'connecting'      # 服务器正在连接过程中
    CONNECTED = 'connected'        # 服务器已连接并准备使用

class MCPDiscoveryState(Enum):
    """表示整体MCP发现状态"""
    NOT_STARTED = 'not_started'    # 发现尚未开始
    IN_PROGRESS = 'in_progress'    # 发现正在进行中
    COMPLETED = 'completed'        # 发现已完成（无论是否有错误）

# 跟踪每个MCP服务器状态的映射
server_statuses: Dict[str, MCPServerStatus] = {}

# 跟踪整体MCP发现状态
mcp_discovery_state = MCPDiscoveryState.NOT_STARTED

# 跟踪哪些MCP服务器被发现需要OAuth
def mcp_server_requires_oauth():
    _requires_oauth: Dict[str, bool] = {}
    return _requires_oauth

# 全局变量
global_mcp_server_requires_oauth = mcp_server_requires_oauth()

# MCP服务器状态变化的事件监听器
type StatusChangeListener = Callable[[str, MCPServerStatus], None]
status_change_listeners: List[StatusChangeListener] = []

# 添加MCP服务器状态变化的监听器
def add_mcp_status_change_listener(listener: StatusChangeListener) -> None:
    """添加MCP服务器状态变化的监听器"""
    status_change_listeners.append(listener)

# 移除MCP服务器状态变化的监听器
def remove_mcp_status_change_listener(listener: StatusChangeListener) -> None:
    """移除MCP服务器状态变化的监听器"""
    if listener in status_change_listeners:
        status_change_listeners.remove(listener)

# 更新MCP服务器状态
def update_mcp_server_status(server_name: str, status: MCPServerStatus) -> None:
    """更新MCP服务器状态"""
    server_statuses[server_name] = status
    # 通知所有监听器
    for listener in status_change_listeners:
        listener(server_name, status)

# 获取MCP服务器的当前状态
def get_mcp_server_status(server_name: str) -> MCPServerStatus:
    """获取MCP服务器的当前状态"""
    return server_statuses.get(server_name, MCPServerStatus.DISCONNECTED)

# 获取所有MCP服务器状态
def get_all_mcp_server_statuses() -> Dict[str, MCPServerStatus]:
    """获取所有MCP服务器状态"""
    return server_statuses.copy()

# 获取当前MCP发现状态
def get_mcp_discovery_state() -> MCPDiscoveryState:
    """获取当前MCP发现状态"""
    global mcp_discovery_state
    return mcp_discovery_state

# 从错误消息字符串中提取WWW-Authenticate头
def extract_www_authenticate_header(error_string: str) -> Optional[str]:
    """从错误消息字符串中提取WWW-Authenticate头

    这是比正则表达式匹配更健壮的方法。

    参数:
        error_string: 错误消息字符串

    返回:
        如果找到www-authenticate头值，则返回该值，否则返回None
    """
    # 尝试多种模式提取头
    patterns = [
        r'www-authenticate:\s*([^\n\r]+)',
        r'WWW-Authenticate:\s*([^\n\r]+)',
        r'"www-authenticate":\s*"([^"]+)"',
        r'\'www-authenticate\':\s*\'([^\']+)\'',
    ]

    for pattern in patterns:
        match = re.search(pattern, error_string, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None

# 处理服务器的自动OAuth发现和认证
async def handle_automatic_oauth(
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
    www_authenticate: str,
) -> bool:
    """处理服务器的自动OAuth发现和认证

    参数:
        mcp_server_name: MCP服务器的名称
        mcp_server_config: MCP服务器配置
        www_authenticate: www-authenticate头值

    返回:
        如果OAuth配置和认证成功，则返回True，否则返回False
    """
    try:
        print(f'🔐 \'{mcp_server_name}\' requires OAuth authentication')

        # 始终尝试从www-authenticate头中解析资源元数据URI
        oauth_config = None
        # 这里应该调用OAuthUtils.parse_www_authenticate_header
        resource_metadata_uri = None
        # 模拟OAuthUtils.parse_www_authenticate_header
        if 'resource-metadata' in www_authenticate.lower():
            # 简单的模拟实现，实际项目中需要替换为真实的解析逻辑
            match = re.search(r'resource-metadata=([^,\s]+)', www_authenticate)
            if match:
                resource_metadata_uri = match.group(1).strip('"')
        
        if resource_metadata_uri:
            # 这里应该调用OAuthUtils.discover_oauth_config
            # oauth_config = await OAuthUtils.discover_oauth_config(resource_metadata_uri)
            pass
        elif mcp_server_config.url:
            # 备选方案：尝试从SSE的基本URL发现OAuth配置
            sse_url = urlparse(mcp_server_config.url)
            base_url = f'{sse_url.scheme}://{sse_url.netloc}'
            # oauth_config = await OAuthUtils.discover_oauth_config(base_url)
            pass
        elif mcp_server_config.http_url:
            # 备选方案：尝试从HTTP的基本URL发现OAuth配置
            http_url = urlparse(mcp_server_config.http_url)
            base_url = f'{http_url.scheme}://{http_url.netloc}'
            # oauth_config = await OAuthUtils.discover_oauth_config(base_url)
            pass

        if not oauth_config:
            print(f'❌ Could not configure OAuth for \'{mcp_server_name}\' - please authenticate manually with /mcp auth {mcp_server_name}')
            return False

        # 发现OAuth配置 - 继续进行认证

        # 创建用于认证的OAuth配置
        oauth_auth_config = {
            'enabled': True,
            'authorizationUrl': oauth_config.get('authorizationUrl'),
            'tokenUrl': oauth_config.get('tokenUrl'),
            'scopes': oauth_config.get('scopes', []),
        }

        # 执行OAuth认证
        print(f'Starting OAuth authentication for server \'{mcp_server_name}\'...')
        # 这里应该调用MCPOAuthProvider.authenticate
        # await MCPOAuthProvider.authenticate(mcp_server_name, oauth_auth_config)

        print(f'OAuth authentication successful for server \'{mcp_server_name}\'')
        return True
    except Exception as error:
        print(f'Failed to handle automatic OAuth for server \'{mcp_server_name}\: {get_error_message(error)}')
        return False

# 为给定的服务器配置创建带有OAuth令牌的传输
async def create_transport_with_oauth(
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
    access_token: str,
) -> Optional[Any]:
    """为给定的服务器配置创建带有OAuth令牌的传输

    参数:
        mcp_server_name: MCP服务器的名称
        mcp_server_config: MCP服务器配置
        access_token: OAuth访问令牌

    返回:
        带有OAuth令牌的传输，如果创建失败则返回None
    """
    try:
        if mcp_server_config.http_url:
            # 创建带有OAuth令牌的HTTP传输
            oauth_transport_options = {
                'requestInit': {
                    'headers': {
                        **(mcp_server_config.headers or {}),
                        'Authorization': f'Bearer {access_token}',
                    },
                },
            }
            
            # 这里应该返回StreamableHTTPClientTransport的实例
            # return StreamableHTTPClientTransport(
            #     urlparse(mcp_server_config.http_url),
            #     oauth_transport_options,
            # )
            return None
        elif mcp_server_config.url:
            # 创建带有OAuth令牌的SSE传输
            # 这里应该返回SSEClientTransport的实例
            # return SSEClientTransport(urlparse(mcp_server_config.url), {
            #     'requestInit': {
            #         'headers': {
            #             **(mcp_server_config.headers or {}),
            #             'Authorization': f'Bearer {access_token}',
            #         },
            #     },
            # })
            return None

        return None
    except Exception as error:
        print(f'Failed to create OAuth transport for server \'{mcp_server_name}\: {get_error_message(error)}')
        return None

# 从所有配置的MCP服务器发现工具并在工具注册表中注册它们
async def discover_mcp_tools(
    mcp_servers: Dict[str, MCPServerConfig],
    mcp_server_command: Optional[str],
    tool_registry: ToolRegistry,
    prompt_registry: PromptRegistry,
    debug_mode: bool,
) -> None:
    """从所有配置的MCP服务器发现工具并在工具注册表中注册它们

    它协调每个在配置中定义的服务器以及通过命令行参数指定的任何服务器的连接和发现过程。

    参数:
        mcp_servers: 命名MCP服务器配置的记录
        mcp_server_command: 动态指定的MCP服务器的可选命令字符串
        tool_registry: 发现的工具将注册到的中央注册表
        prompt_registry: 发现的提示将注册到的中央注册表
        debug_mode: 是否启用调试模式
    """
    global mcp_discovery_state
    mcp_discovery_state = MCPDiscoveryState.IN_PROGRESS
    try:
        mcp_servers = populate_mcp_server_command(mcp_servers, mcp_server_command)

        discovery_tasks = [
            connect_and_discover(
                mcp_server_name,
                mcp_server_config,
                tool_registry,
                prompt_registry,
                debug_mode,
            )
            for mcp_server_name, mcp_server_config in mcp_servers.items()
        ]
        await asyncio.gather(*discovery_tasks)
    finally:
        mcp_discovery_state = MCPDiscoveryState.COMPLETED

# 用于测试
# 这个函数在Python中使用type: ignore标记为仅供测试可见
def populate_mcp_server_command(
    mcp_servers: Dict[str, MCPServerConfig],
    mcp_server_command: Optional[str],
) -> Dict[str, MCPServerConfig]:
    """填充MCP服务器命令

    用于测试"""
    if mcp_server_command:
        cmd = mcp_server_command
        # 这里应该使用shell_quote.parse来解析命令
        # 但为了简单起见，我们使用split作为模拟
        args = cmd.split()
        # 使用通用服务器名称'mcp'
        mcp_servers['mcp'] = MCPServerConfig(
            command=args[0],
            args=args[1:],
        )
    return mcp_servers

# 连接到MCP服务器并发现可用工具，在工具注册表中注册它们
async def connect_and_discover(
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
    tool_registry: ToolRegistry,
    prompt_registry: PromptRegistry,
    debug_mode: bool,
) -> None:
    """连接到MCP服务器并发现可用工具，在工具注册表中注册它们

    此函数处理连接到服务器、发现工具的完整生命周期，
    如果未找到工具，则清理资源。

    参数:
        mcp_server_name: 此MCP服务器的名称标识符
        mcp_server_config: 包含连接详细信息的配置对象
        tool_registry: 注册发现的工具的注册表
        prompt_registry: 注册发现的提示的注册表
        debug_mode: 是否启用调试模式

    返回:
        发现完成时解析的Promise
    """
    update_mcp_server_status(mcp_server_name, MCPServerStatus.CONNECTING)

    mcp_client: Optional[Client] = None
    try:
        mcp_client = await connect_to_mcp_server(
            mcp_server_name,
            mcp_server_config,
            debug_mode,
        )

        # 设置错误处理函数
        def on_error(error):
            print(f'MCP ERROR ({mcp_server_name}):', str(error))
            update_mcp_server_status(mcp_server_name, MCPServerStatus.DISCONNECTED)
        
        mcp_client.onerror = on_error

        # 尝试发现提示和工具
        prompts = await discover_prompts(
            mcp_server_name,
            mcp_client,
            prompt_registry,
        )
        tools = await discover_tools(
            mcp_server_name,
            mcp_server_config,
            mcp_client,
        )

        # 如果我们既没有提示也没有工具，那么发现失败
        if len(prompts) == 0 and len(tools) == 0:
            raise Exception('No prompts or tools found on the server.')

        # 如果我们找到了任何东西，服务器已连接
        update_mcp_server_status(mcp_server_name, MCPServerStatus.CONNECTED)

        # 注册任何发现的工具
        for tool in tools:
            tool_registry.register_tool(tool)
    except Exception as error:
        if mcp_client:
            mcp_client.close()
        print(f'Error connecting to MCP server \'{mcp_server_name}\: {get_error_message(error)}')
        update_mcp_server_status(mcp_server_name, MCPServerStatus.DISCONNECTED)

# 从连接的MCP客户端发现和清理工具
async def discover_tools(
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
    mcp_client: Client,
) -> List[DiscoveredMCPTool]:
    """从连接的MCP客户端发现和清理工具

    它从客户端检索函数声明，过滤掉禁用的工具，
    为它们生成有效的名称，并将它们包装在`DiscoveredMCPTool`实例中。

    参数:
        mcp_server_name: MCP服务器的名称
        mcp_server_config: MCP服务器的配置
        mcp_client: 活动的MCP客户端实例

    返回:
        一个解析为已发现并启用的工具数组的Promise

    抛出:
        如果未找到启用的工具或服务器提供无效的函数声明，则抛出错误
    """
    try:
        # 这里应该调用mcp_to_tool函数
        # mcp_callable_tool = mcp_to_tool(mcp_client)
        # tool = await mcp_callable_tool.tool()
        
        # 模拟工具数据
        tool = {"functionDeclarations": []}

        if not isinstance(tool.get("functionDeclarations"), list):
            # 对于仅提示的服务器，这是有效情况
            return []

        discovered_tools: List[DiscoveredMCPTool] = []
        for func_decl_dict in tool["functionDeclarations"]:
            try:
                # 将dict转换为FunctionDeclaration对象
                func_decl = FunctionDeclaration(**func_decl_dict)
                
                if not is_enabled(func_decl, mcp_server_name, mcp_server_config):
                    continue

                # 模拟mcp_callable_tool
                mcp_callable_tool = None
                
                discovered_tools.append(
                    DiscoveredMCPTool(
                        mcp_callable_tool,
                        mcp_server_name,
                        func_decl.name or '',
                        func_decl.description or '',
                        func_decl.parameters_json_schema or {"type": "object", "properties": {}},
                        mcp_server_config.timeout or MCP_DEFAULT_TIMEOUT_MSEC,
                        mcp_server_config.trust,
                    )
                )
            except Exception as error:
                print(f'Error discovering tool: \'{func_decl_dict.get("name", "unknown")}\' from MCP server \'{mcp_server_name}\: {str(error)}')
        return discovered_tools
    except Exception as error:
        if isinstance(error, Exception) and not ('Method not found' in str(error)):
            print(f'Error discovering tools from {mcp_server_name}: {get_error_message(error)}')
        return []

# 从连接的MCP客户端发现和记录提示
async def discover_prompts(
    mcp_server_name: str,
    mcp_client: Client,
    prompt_registry: PromptRegistry,
) -> List[Any]:
    """从连接的MCP客户端发现和记录提示

    它从客户端检索提示声明并记录它们的名称。

    参数:
        mcp_server_name: MCP服务器的名称
        mcp_client: 活动的MCP客户端实例
        prompt_registry: 注册发现的提示的注册表

    返回:
        提示列表
    """
    try:
        response = await mcp_client.request(
            {"method": "prompts/list", "params": {}},
        )

        for prompt in response.get("prompts", []):
            # 创建invoke函数
            def create_invoke_func(prompt_name):
                async def invoke(params: Dict[str, Any]) -> Any:
                    return await invoke_mcp_prompt(mcp_server_name, mcp_client, prompt_name, params)
                return invoke
            
            prompt_registry.register_prompt({
                **prompt,
                "serverName": mcp_server_name,
                "invoke": create_invoke_func(prompt.get("name"))
            })
        return response.get("prompts", [])
    except Exception as error:
        # 如果失败也没关系，不是所有服务器都会有提示
        # 如果方法未找到，不要记录错误，这是常见情况
        if isinstance(error, Exception) and not ('Method not found' in str(error)):
            print(f'Error discovering prompts from {mcp_server_name}: {get_error_message(error)}')
        return []

# 在连接的MCP客户端上调用提示
async def invoke_mcp_prompt(
    mcp_server_name: str,
    mcp_client: Client,
    prompt_name: str,
    prompt_params: Dict[str, Any],
) -> Any:
    """在连接的MCP客户端上调用提示

    参数:
        mcp_server_name: MCP服务器的名称
        mcp_client: 活动的MCP客户端实例
        prompt_name: 要调用的提示的名称
        prompt_params: 要传递给提示的参数

    返回:
        一个解析为提示调用结果的Promise
    """
    try:
        response = await mcp_client.request(
            {
                "method": "prompts/get",
                "params": {
                    "name": prompt_name,
                    "arguments": prompt_params,
                },
            },
            # 这里应该传递GetPromptResultSchema
        )

        return response
    except Exception as error:
        if isinstance(error, Exception) and not ('Method not found' in str(error)):
            print(f'Error invoking prompt \'{prompt_name}\' from {mcp_server_name} {prompt_params}: {get_error_message(error)}')
        raise error

# 创建并连接MCP客户端到基于提供的配置的服务器
async def connect_to_mcp_server(
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
    debug_mode: bool,
) -> Client:
    """创建并连接MCP客户端到基于提供的配置的服务器

    它确定适当的传输（Stdio、SSE或Streamable HTTP）并建立连接。
    它还应用补丁来处理请求超时。

    参数:
        mcp_server_name: MCP服务器的名称，用于日志记录和标识
        mcp_server_config: 指定如何连接到服务器的配置
        debug_mode: 是否启用调试模式

    返回:
        一个解析为已连接的MCP `Client` 实例的Promise

    抛出:
        如果连接失败或配置无效，则抛出错误
    """
    mcp_client = Client({
        "name": "qwen-code-mcp-client",
        "version": "0.0.1",
    })

    # 为客户端添加超时处理
    # 这里应该实现类似于TypeScript中的patch

    try:
        transport = await create_transport(
            mcp_server_name,
            mcp_server_config,
            debug_mode,
        )
        try:
            await mcp_client.connect(transport, {
                "timeout": mcp_server_config.timeout or MCP_DEFAULT_TIMEOUT_MSEC,
            })
            return mcp_client
        except Exception as error:
            # 这里应该调用transport.close()
            # await transport.close()
            raise error
    except Exception as error:
        # 检查这是否是可能表明需要OAuth的401错误
        error_string = str(error)
        if ('401' in error_string) and (mcp_server_config.http_url or mcp_server_config.url):
            global_mcp_server_requires_oauth[mcp_server_name] = True
            # 仅为HTTP服务器或显式配置了OAuth的服务器触发自动OAuth发现
            # 对于SSE服务器，我们不应自动触发新的OAuth流程
            should_trigger_oauth = (
                mcp_server_config.http_url or (mcp_server_config.oauth and mcp_server_config.oauth.get('enabled'))
            )

            if not should_trigger_oauth:
                # 对于没有显式OAuth配置的SSE服务器，如果找到令牌但被拒绝，准确报告
                # 这里应该调用MCPOAuthTokenStorage.get_token
                # credentials = await MCPOAuthTokenStorage.get_token(mcp_server_name)
                credentials = None
                if credentials:
                    # 这里应该调用MCPOAuthProvider.get_valid_token
                    # has_stored_tokens = await MCPOAuthProvider.get_valid_token(
                    #     mcp_server_name,
                    #     {
                    #         "clientId": credentials.get("clientId"),
                    #     },
                    # )
                    has_stored_tokens = False
                    if has_stored_tokens:
                        print(f'Stored OAuth token for SSE server \'{mcp_server_name}\' was rejected. ' +
                              f'Please re-authenticate using: /mcp auth {mcp_server_name}')
                    else:
                        print(f'401 error received for SSE server \'{mcp_server_name}\' without OAuth configuration. ' +
                              f'Please authenticate using: /mcp auth {mcp_server_name}')
                raise Exception(
                    f'401 error received for SSE server \'{mcp_server_name}\' without OAuth configuration. ' +
                    f'Please authenticate using: /mcp auth {mcp_server_name}'
                )

            # 尝试从错误中提取www-authenticate头
            www_authenticate = extract_www_authenticate_header(error_string)

            # 如果我们没有从错误字符串中获取头，尝试从服务器获取
            if not www_authenticate and mcp_server_config.url:
                print('No www-authenticate header in error, trying to fetch it from server...')
                try:
                    # 这里应该使用aiohttp或类似库进行异步HTTP请求
                    # response = await fetch(mcp_server_config.url, {
                    #     "method": "HEAD",
                    #     "headers": {
                    #         "Accept": "text/event-stream",
                    #     },
                    #     "signal": AbortSignal.timeout(5000),
                    # })
                    # 
                    # if response.status == 401:
                    #     www_authenticate = response.headers.get('www-authenticate')
                    #     if www_authenticate:
                    #         print(f'Found www-authenticate header from server: {www_authenticate}')
                    pass
                except Exception as fetch_error:
                    print(f'Failed to fetch www-authenticate header: {get_error_message(fetch_error)}')

            if www_authenticate:
                print(f'Received 401 with www-authenticate header: {www_authenticate}')

                # 尝试自动OAuth发现和认证
                oauth_success = await handle_automatic_oauth(
                    mcp_server_name,
                    mcp_server_config,
                    www_authenticate,
                )
                if oauth_success:
                    # 使用OAuth令牌重试连接
                    print(f'Retrying connection to \'{mcp_server_name}\' with OAuth token...')

                    # 获取有效令牌 - 我们需要创建适当的OAuth配置
                    # 令牌应该已经在认证过程中可用
                    # 这里应该调用MCPOAuthTokenStorage.get_token
                    # credentials = await MCPOAuthTokenStorage.get_token(mcp_server_name)
                    credentials = None
                    if credentials:
                        # 这里应该调用MCPOAuthProvider.get_valid_token
                        # access_token = await MCPOAuthProvider.get_valid_token(
                        #     mcp_server_name,
                        #     {
                        #         "clientId": credentials.get("clientId"),
                        #     },
                        # )
                        access_token = None

                        if access_token:
                            # 创建带有OAuth令牌的传输
                            oauth_transport = await create_transport_with_oauth(
                                mcp_server_name,
                                mcp_server_config,
                                access_token,
                            )
                            if oauth_transport:
                                try:
                                    await mcp_client.connect(oauth_transport, {
                                        "timeout":
                                            mcp_server_config.timeout or MCP_DEFAULT_TIMEOUT_MSEC,
                                    })
                                    # 使用OAuth连接成功
                                    return mcp_client
                                except Exception as retry_error:
                                    print(f'Failed to connect with OAuth token: {get_error_message(retry_error)}')
                                    raise retry_error
                            else:
                                print(f'Failed to create OAuth transport for server \'{mcp_server_name}\'')
                                raise Exception(
                                    f'Failed to create OAuth transport for server \'{mcp_server_name}\'')
                        else:
                            print(f'Failed to get OAuth token for server \'{mcp_server_name}\'')
                            raise Exception(
                                f'Failed to get OAuth token for server \'{mcp_server_name}\'')
                    else:
                        print(f'Failed to get credentials for server \'{mcp_server_name}\' after successful OAuth authentication')
                        raise Exception(
                            f'Failed to get credentials for server \'{mcp_server_name}\' after successful OAuth authentication')
                else:
                    print(f'Failed to handle automatic OAuth for server \'{mcp_server_name}\'')
                    raise Exception(
                        f'Failed to handle automatic OAuth for server \'{mcp_server_name}\'')
            else:
                # 没有找到www-authenticate头，但我们收到了401
                # 仅为HTTP服务器或显式配置了OAuth的服务器尝试OAuth发现
                # 对于SSE服务器，我们不应自动触发新的OAuth流程
                should_try_discovery = (
                    mcp_server_config.http_url or (mcp_server_config.oauth and mcp_server_config.oauth.get('enabled'))
                )

                if not should_try_discovery:
                    # 这里应该调用MCPOAuthTokenStorage.get_token
                    # credentials = await MCPOAuthTokenStorage.get_token(mcp_server_name)
                    credentials = None
                    if credentials:
                        # 这里应该调用MCPOAuthProvider.get_valid_token
                        # has_stored_tokens = await MCPOAuthProvider.get_valid_token(
                        #     mcp_server_name,
                        #     {
                        #         "clientId": credentials.get("clientId"),
                        #     },
                        # )
                        has_stored_tokens = False
                        if has_stored_tokens:
                            print(f'Stored OAuth token for SSE server \'{mcp_server_name}\' was rejected. ' +
                                  f'Please re-authenticate using: /mcp auth {mcp_server_name}')
                        else:
                            print(f'401 error received for SSE server \'{mcp_server_name}\' without OAuth configuration. ' +
                                  f'Please authenticate using: /mcp auth {mcp_server_name}')
                    raise Exception(
                        f'401 error received for SSE server \'{mcp_server_name}\' without OAuth configuration. ' +
                        f'Please authenticate using: /mcp auth {mcp_server_name}')

                # 对于SSE服务器，尝试从基本URL发现OAuth配置
                print(f'🔍 Attempting OAuth discovery for \'{mcp_server_name}\'...')

                if mcp_server_config.url:
                    sse_url = urlparse(mcp_server_config.url)
                    base_url = f'{sse_url.scheme}://{sse_url.netloc}'

                    try:
                        # 尝试从基本URL发现OAuth配置
                        # 这里应该调用OAuthUtils.discover_oauth_config
                        # oauth_config = await OAuthUtils.discover_oauth_config(base_url)
                        oauth_config = None
                        if oauth_config:
                            print(f'Discovered OAuth configuration from base URL for server \'{mcp_server_name}\'')

                            # 创建用于认证的OAuth配置
                            oauth_auth_config = {
                                'enabled': True,
                                'authorizationUrl': oauth_config.get('authorizationUrl'),
                                'tokenUrl': oauth_config.get('tokenUrl'),
                                'scopes': oauth_config.get('scopes', []),
                            }

                            # 执行OAuth认证
                            print(f'Starting OAuth authentication for server \'{mcp_server_name}\'...')
                            # 这里应该调用MCPOAuthProvider.authenticate
                            # await MCPOAuthProvider.authenticate(
                            #     mcp_server_name,
                            #     oauth_auth_config,
                            # )

                            # 使用OAuth令牌重试连接
                            # 这里应该调用MCPOAuthTokenStorage.get_token
                            # credentials = await MCPOAuthTokenStorage.get_token(mcp_server_name)
                            credentials = None
                            if credentials:
                                # 这里应该调用MCPOAuthProvider.get_valid_token
                                # access_token = await MCPOAuthProvider.get_valid_token(
                                #     mcp_server_name,
                                #     {
                                #         "clientId": credentials.get("clientId"),
                                #     },
                                # )
                                access_token = None
                                if access_token:
                                    # 创建带有OAuth令牌的传输
                                    oauth_transport = await create_transport_with_oauth(
                                        mcp_server_name,
                                        mcp_server_config,
                                        access_token,
                                    )
                                    if oauth_transport:
                                        try:
                                            await mcp_client.connect(oauth_transport, {
                                                "timeout":
                                                    mcp_server_config.timeout or MCP_DEFAULT_TIMEOUT_MSEC,
                                            })
                                            # 使用OAuth连接成功
                                            return mcp_client
                                        except Exception as retry_error:
                                            print(f'Failed to connect with OAuth token: {get_error_message(retry_error)}')
                                            raise retry_error
                                    else:
                                        print(f'Failed to create OAuth transport for server \'{mcp_server_name}\'')
                                        raise Exception(
                                            f'Failed to create OAuth transport for server \'{mcp_server_name}\'')
                                else:
                                    print(f'Failed to get OAuth token for server \'{mcp_server_name}\'')
                                    raise Exception(
                                        f'Failed to get OAuth token for server \'{mcp_server_name}\'')
                            else:
                                print(f'Failed to get stored credentials for server \'{mcp_server_name}\'')
                                raise Exception(
                                    f'Failed to get stored credentials for server \'{mcp_server_name}\'')
                        else:
                            print(f'❌ Could not configure OAuth for \'{mcp_server_name}\' - please authenticate manually with /mcp auth {mcp_server_name}')
                            raise Exception(
                                f'OAuth configuration failed for \'{mcp_server_name}\. Please authenticate manually with /mcp auth {mcp_server_name}')
                    except Exception as discovery_error:
                        print(f'❌ OAuth discovery failed for \'{mcp_server_name}\' - please authenticate manually with /mcp auth {mcp_server_name}')
                        raise discovery_error
                else:
                    print(f'❌ \'{mcp_server_name}\' requires authentication but no OAuth configuration found')
                    raise Exception(
                        f'MCP server \'{mcp_server_name}\' requires authentication. Please configure OAuth or check server settings.')
        else:
            # 处理其他连接错误
            # 创建简洁的错误消息
            error_message = str(error) if isinstance(error, Exception) else str(error)
            is_network_error = (
                'ENOTFOUND' in error_message or
                'ECONNREFUSED' in error_message
            )

            concise_error: str
            if is_network_error:
                concise_error = f'Cannot connect to \'{mcp_server_name}\' - server may be down or URL incorrect'
            else:
                concise_error = f'Connection failed for \'{mcp_server_name}\: {error_message}'

            if os.environ.get('SANDBOX'):
                concise_error += ' (check sandbox availability)'

            raise Exception(concise_error)

# 用于测试
# 这个函数在Python中使用type: ignore标记为仅供测试可见
async def create_transport(
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
    debug_mode: bool,
) -> Any:
    """创建传输

    用于测试"""
    # AuthProviderType应该从配置导入
    AuthProviderType = type('AuthProviderType', (), {'GOOGLE_CREDENTIALS': 'GOOGLE_CREDENTIALS'})
    
    if mcp_server_config.auth_provider_type == AuthProviderType.GOOGLE_CREDENTIALS:
        # 这里应该创建GoogleCredentialProvider实例
        # provider = GoogleCredentialProvider(mcp_server_config)
        transport_options = {
            'authProvider': None,  # 应该是provider
        }
        if mcp_server_config.http_url:
            # 这里应该返回StreamableHTTPClientTransport的实例
            # return StreamableHTTPClientTransport(
            #     urlparse(mcp_server_config.http_url),
            #     transport_options,
            # )
            return None
        elif mcp_server_config.url:
            # 这里应该返回SSEClientTransport的实例
            # return SSEClientTransport(
            #     urlparse(mcp_server_config.url),
            #     transport_options,
            # )
            return None
        raise Exception('No URL configured for Google Credentials MCP server')

    # 检查我们是否有OAuth配置或存储的令牌
    access_token: Optional[str] = None
    has_oauth_config = mcp_server_config.oauth and mcp_server_config.oauth.get('enabled')

    if has_oauth_config and mcp_server_config.oauth:
        # 这里应该调用MCPOAuthProvider.get_valid_token
        # access_token = await MCPOAuthProvider.get_valid_token(
        #     mcp_server_name,
        #     mcp_server_config.oauth,
        # )

        if not access_token:
            print(f'MCP server \'{mcp_server_name}\' requires OAuth authentication. ' +
                  'Please authenticate using the /mcp auth command.')
            raise Exception(
                f'MCP server \'{mcp_server_name}\' requires OAuth authentication. ' +
                'Please authenticate using the /mcp auth command.')
    else:
        # 检查我们是否有此服务器的存储OAuth令牌（来自先前的认证）
        # 这里应该调用MCPOAuthTokenStorage.get_token
        # credentials = await MCPOAuthTokenStorage.get_token(mcp_server_name)
        credentials = None
        if credentials:
            # 这里应该调用MCPOAuthProvider.get_valid_token
            # access_token = await MCPOAuthProvider.get_valid_token(mcp_server_name, {
            #     "clientId": credentials.get("clientId"),
            # })

            if access_token:
                has_oauth_config = True
                print(f'Found stored OAuth token for server \'{mcp_server_name}\'')

    if mcp_server_config.http_url:
        transport_options = {}

        # 如果可用，设置带有OAuth令牌的头
        if has_oauth_config and access_token:
            transport_options['requestInit'] = {
                'headers': {
                    **(mcp_server_config.headers or {}),
                    'Authorization': f'Bearer {access_token}',
                },
            }
        elif mcp_server_config.headers:
            transport_options['requestInit'] = {
                'headers': mcp_server_config.headers,
            }

        # 这里应该返回StreamableHTTPClientTransport的实例
        # return StreamableHTTPClientTransport(
        #     urlparse(mcp_server_config.http_url),
        #     transport_options,
        # )
        return None

    if mcp_server_config.url:
        transport_options = {}

        # 如果可用，设置带有OAuth令牌的头
        if has_oauth_config and access_token:
            transport_options['requestInit'] = {
                'headers': {
                    **(mcp_server_config.headers or {}),
                    'Authorization': f'Bearer {access_token}',
                },
            }
        elif mcp_server_config.headers:
            transport_options['requestInit'] = {
                'headers': mcp_server_config.headers,
            }

        # 这里应该返回SSEClientTransport的实例
        # return SSEClientTransport(
        #     urlparse(mcp_server_config.url),
        #     transport_options,
        # )
        return None

    if mcp_server_config.command:
        # 这里应该返回StdioClientTransport的实例
        # transport = StdioClientTransport({
        #     "command": mcp_server_config.command,
        #     "args": mcp_server_config.args or [],
        #     "env": {
        #         **os.environ,
        #         **(mcp_server_config.env or {}),
        #     },
        #     "cwd": mcp_server_config.cwd,
        #     "stderr": "pipe",
        # })
        # if debug_mode:
        #     # 这里应该设置stderr的事件处理器
        #     pass
        # return transport
        return None

    raise Exception(
        'Invalid configuration: missing httpUrl (for Streamable HTTP), url (for SSE), and command (for stdio).')

# 用于测试
# 这个函数在Python中使用type: ignore标记为仅供测试可见
def is_enabled(
    func_decl: FunctionDeclaration,
    mcp_server_name: str,
    mcp_server_config: MCPServerConfig,
) -> bool:
    """检查函数声明是否启用

    用于测试"""
    if not func_decl.name:
        print(f'Discovered a function declaration without a name from MCP server \'{mcp_server_name}\. Skipping.')
        return False
    include_tools = mcp_server_config.include_tools
    exclude_tools = mcp_server_config.exclude_tools

    # excludeTools优先于includeTools
    if exclude_tools and func_decl.name in exclude_tools:
        return False

    return (
        not include_tools or
        any(tool == func_decl.name or tool.startswith(f'{func_decl.name}(') for tool in include_tools)
    )