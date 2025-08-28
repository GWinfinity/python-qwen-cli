from typing import List
from ..config.config import Config
from ..tools.mcp_client import DiscoveredMCPPrompt


def get_mcp_server_prompts(config: Config, server_name: str) -> List[DiscoveredMCPPrompt]:
    """
    从配置中获取指定服务器名称的 MCP 提示。
    
    Args:
        config: Config 对象，包含提示注册表
        server_name: 服务器名称
        
    Returns:
        指定服务器的所有提示列表，如果没有提示注册表则返回空列表
    """
    prompt_registry = config.get_prompt_registry()
    if prompt_registry is None:
        return []
    return prompt_registry.get_prompts_by_server(server_name)