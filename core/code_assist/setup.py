import os
import time
from typing import Optional, Dict, Any
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# 假设这些类型已从types.ts转换
from .types import ClientMetadata, GeminiUserTier, LoadCodeAssistResponse, OnboardUserRequest, UserTierId
# 假设CodeAssistServer已从server.ts转换
from .server import CodeAssistServer


class ProjectIdRequiredError(Exception):
    """
    当需要设置GOOGLE_CLOUD_PROJECT环境变量但未设置时抛出的异常
    """
    def __init__(self):
        super().__init__(
            'This account requires setting the GOOGLE_CLOUD_PROJECT env var. See https://goo.gle/gemini-cli-auth-docs#workspace-gca'
        )


class UserData:
    """
    用户数据类，包含项目ID和用户层级
    """
    def __init__(self, project_id: str, user_tier: UserTierId):
        self.project_id = project_id
        self.user_tier = user_tier


async def setup_user(client: Credentials) -> UserData:
    """
    设置用户，包括加载代码助手、获取用户层级和onboard用户

    Args:
        client: Google认证客户端

    Returns:
        UserData: 包含项目ID和用户层级的用户数据

    Raises:
        ProjectIdRequiredError: 当需要项目ID但未提供时抛出
    """
    project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
    ca_server = CodeAssistServer(client, project_id, {}, '', None)

    client_metadata: ClientMetadata = {
        'ideType': 'IDE_UNSPECIFIED',
        'platform': 'PLATFORM_UNSPECIFIED',
        'pluginType': 'GEMINI',
        'duetProject': project_id,
    }

    load_res = await ca_server.load_code_assist({
        'cloudaicompanionProject': project_id,
        'metadata': client_metadata,
    })

    if not project_id and load_res.cloudaicompanionProject:
        project_id = load_res.cloudaicompanionProject

    tier = get_onboard_tier(load_res)
    if tier.userDefinedCloudaicompanionProject and not project_id:
        raise ProjectIdRequiredError()

    onboard_req: OnboardUserRequest = {
        'tierId': tier.id,
        'cloudaicompanionProject': project_id,
        'metadata': client_metadata,
    }

    # 轮询onboardUser直到长时间运行的操作完成
    lro_res = await ca_server.onboard_user(onboard_req)
    while not lro_res.done:
        await asyncio.sleep(5)
        lro_res = await ca_server.onboard_user(onboard_req)

    return UserData(
        project_id=lro_res.response.cloudaicompanionProject.id if lro_res.response and lro_res.response.cloudaicompanionProject else '',
        user_tier=tier.id
    )


def get_onboard_tier(res: LoadCodeAssistResponse) -> GeminiUserTier:
    """
    获取用户的onboard层级

    Args:
        res: 加载代码助手的响应

    Returns:
        GeminiUserTier: 用户层级
    """
    if res.currentTier:
        return res.currentTier

    for tier in res.allowedTiers or []:
        if tier.isDefault:
            return tier

    # 默认返回LEGACY层级
    return {
        'name': '',
        'description': '',
        'id': UserTierId.LEGACY,
        'userDefinedCloudaicompanionProject': True,
    }


# 注意：为了使代码完整，还需要导入asyncio
import asyncio