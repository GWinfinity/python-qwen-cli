# Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0

from google.oauth2 import service_account
from google.auth import default
from google.auth.transport.requests import Request
from typing import Optional, Dict, List, Any
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata,OAuthClientInformationFull,OAuthToken
# 定义接口需要的类型
typing.OAuthClientInformation = Dict[str, Any]
typing.MCPServerConfig = Dict[str, Any]

class OAuthClientInformation(TypedDict, total=False):
    """OAuth 客户端信息结构定义
    
    属性:
        client_id: 客户端ID，必需字段
        client_secret: 客户端密钥，可选字段
        client_id_issued_at: 客户端ID颁发时间（时间戳），可选字段
        client_secret_expires_at: 客户端密钥过期时间（时间戳），可选字段
    """
    client_id: str
    client_secret: Optional[str]
    client_id_issued_at: Optional[int]
    client_secret_expires_at: Optional[int]


class GoogleCredentialProvider:
    def __init__(self, config: Optional[MCPServerConfig] = None):
        """初始化 GoogleCredentialProvider 实例
        
        Args:
            config: 可选的 MCP 服务器配置，包含 OAuth 相关设置
        
        Raises:
            ValueError: 当配置中未提供有效的 OAuth scopes 时
        """
        scopes = config.get('oauth', {}).get('scopes', []) if config else []
        if not scopes:
            raise ValueError('Scopes must be provided in the oauth config for Google Credentials provider')
        
        self.config = config
        self.scopes = scopes
        self._auth_client = None
        
        # 实现 OAuthClientProvider 接口所需的属性
        self.redirect_url = ''
        self.client_metadata: OAuthClientMetadata = {
            'client_name': 'Gemini CLI (Google ADC)',
            'redirect_uris': [],
            'grant_types': [],
            'response_types': [],
            'token_endpoint_auth_method': 'none',
        }
        self._client_information: Optional[OAuthClientInformationFull] = None
    
    def _get_auth_client(self):
        """获取或创建 Google Auth 客户端实例"""
        if self._auth_client is None:
            try:
                # 尝试使用应用默认凭据
                credentials, _ = default(scopes=self.scopes)
                self._auth_client = credentials
            except Exception as e:
                print(f"Failed to get default credentials: {e}")
                # 可以在这里添加其他凭据获取方式
                raise
        
        # 确保凭据有效
        if self._auth_client.expired and self._auth_client.refresh_token:
            self._auth_client.refresh(Request())
        
        return self._auth_client
    
    def client_information(self) -> Optional[OAuthClientInformation]:
        """获取客户端信息
        
        Returns:
            客户端信息（如果已保存），否则为 None
        """
        return self._client_information
    
    def save_client_information(self, client_information: OAuthClientInformationFull) -> None:
        """保存客户端信息
        
        Args:
            client_information: 要保存的客户端完整信息
        """
        self._client_information = client_information
    
    async def tokens(self) -> Optional[OAuthTokens]:
        """获取 OAuth 令牌
        
        Returns:
            OAuth 令牌对象（如果成功），否则为 None
        """
        try:
            client = self._get_auth_client()
            # 获取访问令牌
            access_token = client.token
            
            if not access_token:
                print('Failed to get access token from Google ADC')
                return None
            
            tokens: OAuthTokens = {
                'access_token': access_token,
                'token_type': 'Bearer',
            }
            return tokens
        except Exception as e:
            print(f"Error getting tokens: {e}")
            return None
    
    def save_tokens(self, tokens: OAuthTokens) -> None:
        """保存令牌（在 ADC 模式下为空操作）
        
        Args:
            tokens: 要保存的令牌对象
        """
        # 空操作，ADC 会管理令牌
        pass
    
    def redirect_to_authorization(self, authorization_url: str) -> None:
        """重定向到授权页面（在 ADC 模式下为空操作）
        
        Args:
            authorization_url: 授权 URL
        """
        # 空操作
        pass
    
    def save_code_verifier(self, code_verifier: str) -> None:
        """保存代码验证器（在 ADC 模式下为空操作）
        
        Args:
            code_verifier: 代码验证器字符串
        """
        # 空操作
        pass
    
    def code_verifier(self) -> str:
        """获取代码验证器（在 ADC 模式下返回空字符串）
        
        Returns:
            空字符串
        """
        return ''