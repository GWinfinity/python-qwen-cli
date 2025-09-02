from typing import Optional

# 导入所需的模块
# 注意：需要确保这些模块在Python中有对应的实现
from core.core.content_generator import AuthType, ContentGenerator
from core.code_assist.oauth2 import get_oauth_client
from core.code_assist.setup import setup_user
from core.code_assist.server import CodeAssistServer, HttpOptions
from core.config.config import Config


async def create_code_assist_content_generator(
    http_options: HttpOptions,
    auth_type: AuthType,
    config: Config,
    session_id: Optional[str] = None
) -> ContentGenerator:
    """创建代码辅助内容生成器
    
    Args:
        http_options: HTTP选项配置
        auth_type: 认证类型
        config: 配置对象
        session_id: 可选的会话ID
        
    Returns:
        ContentGenerator: 创建的内容生成器实例
        
    Raises:
        ValueError: 当提供的认证类型不支持时
    """
    if auth_type in (AuthType.LOGIN_WITH_GOOGLE, AuthType.CLOUD_SHELL):
        auth_client = await get_oauth_client(auth_type, config)
        user_data = await setup_user(auth_client)
        return CodeAssistServer(
            auth_client,
            user_data.project_id,
            http_options,
            session_id,
            user_data.user_tier
        )
    
    raise ValueError(f"Unsupported authType: {auth_type}")


# 为了与TypeScript的导出风格保持一致，可以使用__all__指定公共API
__all__ = ["create_code_assist_content_generator"]