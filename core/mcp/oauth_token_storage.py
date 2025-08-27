import os
import json
import time
from typing import Dict, Optional, Any


class MCPOAuthToken:
    """MCP OAuth 令牌接口"""
    def __init__(self, 
                 access_token: str, 
                 token_type: str, 
                 refresh_token: Optional[str] = None, 
                 expires_at: Optional[int] = None, 
                 scope: Optional[str] = None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.token_type = token_type
        self.scope = scope

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式以便序列化"""
        result = {
            'accessToken': self.access_token,
            'tokenType': self.token_type
        }
        if self.refresh_token is not None:
            result['refreshToken'] = self.refresh_token
        if self.expires_at is not None:
            result['expiresAt'] = self.expires_at
        if self.scope is not None:
            result['scope'] = self.scope
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MCPOAuthToken':
        """从字典创建令牌对象"""
        return cls(
            access_token=data['accessToken'],
            token_type=data['tokenType'],
            refresh_token=data.get('refreshToken'),
            expires_at=data.get('expiresAt'),
            scope=data.get('scope')
        )


class MCPOAuthCredentials:
    """存储的 MCP OAuth 凭证接口"""
    def __init__(self, 
                 server_name: str, 
                 token: MCPOAuthToken, 
                 updated_at: int, 
                 client_id: Optional[str] = None,
                 token_url: Optional[str] = None,
                 mcp_server_url: Optional[str] = None):
        self.server_name = server_name
        self.token = token
        self.client_id = client_id
        self.token_url = token_url
        self.mcp_server_url = mcp_server_url
        self.updated_at = updated_at

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式以便序列化"""
        result = {
            'serverName': self.server_name,
            'token': self.token.to_dict(),
            'updatedAt': self.updated_at
        }
        if self.client_id is not None:
            result['clientId'] = self.client_id
        if self.token_url is not None:
            result['tokenUrl'] = self.token_url
        if self.mcp_server_url is not None:
            result['mcpServerUrl'] = self.mcp_server_url
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MCPOAuthCredentials':
        """从字典创建凭证对象"""
        return cls(
            server_name=data['serverName'],
            token=MCPOAuthToken.from_dict(data['token']),
            client_id=data.get('clientId'),
            token_url=data.get('tokenUrl'),
            mcp_server_url=data.get('mcpServerUrl'),
            updated_at=data['updatedAt']
        )


class MCPOAuthTokenStorage:
    """管理 MCP OAuth 令牌存储和检索的类"""
    _TOKEN_FILE = 'mcp-oauth-tokens.json'
    _CONFIG_DIR = '.gemini'

    @classmethod
    def _get_token_file_path(cls) -> str:
        """获取令牌存储文件的路径"""
        home_dir = os.path.expanduser('~')
        return os.path.join(home_dir, cls._CONFIG_DIR, cls._TOKEN_FILE)

    @classmethod
    async def _ensure_config_dir(cls) -> None:
        """确保配置目录存在"""
        config_dir = os.path.dirname(cls._get_token_file_path())
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)

    @classmethod
    async def load_tokens(cls) -> Dict[str, MCPOAuthCredentials]:
        """加载所有存储的 MCP OAuth 令牌"""
        token_map: Dict[str, MCPOAuthCredentials] = {}

        try:
            token_file = cls._get_token_file_path()
            with open(token_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                tokens = data  # 假设数据是 MCPOAuthCredentials 列表

                for credential_data in tokens:
                    credential = MCPOAuthCredentials.from_dict(credential_data)
                    token_map[credential.server_name] = credential
        except FileNotFoundError:
            # 文件不存在，返回空映射
            pass
        except Exception as e:
            # 其他错误，记录错误信息
            print(f"Failed to load MCP OAuth tokens: {str(e)}")

        return token_map

    @classmethod
    async def save_token(cls, 
                        server_name: str, 
                        token: MCPOAuthToken, 
                        client_id: Optional[str] = None, 
                        token_url: Optional[str] = None, 
                        mcp_server_url: Optional[str] = None) -> None:
        """为特定的 MCP 服务器保存令牌"""
        await cls._ensure_config_dir()

        tokens = await cls.load_tokens()

        credential = MCPOAuthCredentials(
            server_name=server_name,
            token=token,
            client_id=client_id,
            token_url=token_url,
            mcp_server_url=mcp_server_url,
            updated_at=int(time.time() * 1000)  # 使用毫秒时间戳
        )

        tokens[server_name] = credential

        token_array = list(tokens.values())
        token_file = cls._get_token_file_path()

        try:
            with open(token_file, 'w', encoding='utf-8') as f:
                json.dump([cred.to_dict() for cred in token_array], f, indent=2)
            # 设置文件权限为仅当前用户可读写
            os.chmod(token_file, 0o600)
        except Exception as e:
            print(f"Failed to save MCP OAuth token: {str(e)}")
            raise

    @classmethod
    async def get_token(cls, server_name: str) -> Optional[MCPOAuthCredentials]:
        """获取特定 MCP 服务器的令牌"""
        tokens = await cls.load_tokens()
        return tokens.get(server_name)

    @classmethod
    async def remove_token(cls, server_name: str) -> None:
        """删除特定 MCP 服务器的令牌"""
        tokens = await cls.load_tokens()

        if server_name in tokens:
            del tokens[server_name]
            token_array = list(tokens.values())
            token_file = cls._get_token_file_path()

            try:
                if len(token_array) == 0:
                    # 如果没有令牌了，删除文件
                    if os.path.exists(token_file):
                        os.remove(token_file)
                else:
                    with open(token_file, 'w', encoding='utf-8') as f:
                        json.dump([cred.to_dict() for cred in token_array], f, indent=2)
                    os.chmod(token_file, 0o600)
            except Exception as e:
                print(f"Failed to remove MCP OAuth token: {str(e)}")

    @classmethod
    def is_token_expired(cls, token: MCPOAuthToken) -> bool:
        """检查令牌是否已过期"""
        if token.expires_at is None:
            return False  # 没有过期时间，假设有效

        # 添加 5 分钟的缓冲时间以应对时钟偏差
        buffer_ms = 5 * 60 * 1000
        return int(time.time() * 1000) + buffer_ms >= token.expires_at

    @classmethod
    async def clear_all_tokens(cls) -> None:
        """清除所有存储的 MCP OAuth 令牌"""
        try:
            token_file = cls._get_token_file_path()
            if os.path.exists(token_file):
                os.remove(token_file)
        except FileNotFoundError:
            # 文件不存在，忽略错误
            pass
        except Exception as e:
            print(f"Failed to clear MCP OAuth tokens: {str(e)}")