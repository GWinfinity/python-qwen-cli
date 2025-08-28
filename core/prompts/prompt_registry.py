from typing import Dict, List, Optional
from ..tools.mcp_client import DiscoveredMCPPrompt


class PromptRegistry:
    def __init__(self):
        """初始化提示注册表。"""
        self._prompts: Dict[str, DiscoveredMCPPrompt] = {}
    
    def register_prompt(self, prompt: DiscoveredMCPPrompt) -> None:
        """
        注册一个提示定义。
        
        Args:
            prompt: 包含模式和执行逻辑的提示对象
        """
        if prompt.name in self._prompts:
            new_name = f"{prompt.server_name}_{prompt.name}"
            print(f"警告: 名称为\"{prompt.name}\"的提示已注册。重命名为\"{new_name}\"。")
            # 创建新的提示对象，修改名称
            updated_prompt = prompt.__class__()
            for attr_name, attr_value in prompt.__dict__.items():
                setattr(updated_prompt, attr_name, attr_value)
            updated_prompt.name = new_name
            self._prompts[new_name] = updated_prompt
        else:
            self._prompts[prompt.name] = prompt
    
    def get_all_prompts(self) -> List[DiscoveredMCPPrompt]:
        """
        返回所有已注册和发现的提示实例数组。
        
        Returns:
            按名称排序的提示实例列表
        """
        return sorted(self._prompts.values(), key=lambda prompt: prompt.name)
    
    def get_prompt(self, name: str) -> Optional[DiscoveredMCPPrompt]:
        """
        获取特定提示的定义。
        
        Args:
            name: 提示的名称
            
        Returns:
            提示对象或 None（如果未找到）
        """
        return self._prompts.get(name)
    
    def get_prompts_by_server(self, server_name: str) -> List[DiscoveredMCPPrompt]:
        """
        返回从特定 MCP 服务器注册的提示数组。
        
        Args:
            server_name: 服务器名称
            
        Returns:
            按名称排序的指定服务器的提示列表
        """
        server_prompts: List[DiscoveredMCPPrompt] = []
        for prompt in self._prompts.values():
            if prompt.server_name == server_name:
                server_prompts.append(prompt)
        return sorted(server_prompts, key=lambda prompt: prompt.name)