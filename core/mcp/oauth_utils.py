import re
import json
from typing import Dict, List, Optional, Any, Tuple
import urllib.parse
import aiohttp

from ..utils.error import get_error_message
from oauth_provider import MCPOAuthConfig

class OAuthAuthorizationServerMetadata():
    """OAuth 授权服务器元数据（符合 RFC 8414 标准）"""
    # 必需字段
    def __init__(self,
    issuer: str,  # 颁发者标识符
    authorization_endpoint: str,  # 授权端点 URL
    token_endpoint: str,  # 令牌端点 URL
    
    # 可选字段
    token_endpoint_auth_methods_supported: List[str],  # 支持的令牌端点认证方法
    revocation_endpoint: str,  # 撤销端点 URL
    revocation_endpoint_auth_methods_supported: List[str],  # 支持的撤销端点认证方法
    registration_endpoint: str,  # 客户端注册端点 URL
    response_types_supported: List[str],  # 支持的响应类型
    grant_types_supported: List[str],  # 支持的授权类型
    code_challenge_methods_supported: List[str],  # 支持的代码挑战方法
    scopes_supported: List[str]):
        self.issuer = issuer
        self.authorization_endpoint = authorization_endpoint
        self.token_endpoint = token_endpoint
        self.token_endpoint_auth_methods_supported = token_endpoint_auth_methods_supported
        self.revocation_endpoint = revocation_endpoint
        self.revocation_endpoint_auth_methods_supported = revocation_endpoint_auth_methods_supported
        self.registration_endpoint = registration_endpoint
        self.response_types_supported = response_types_supported
        self.grant_types_supported = grant_types_supported
        self.code_challenge_methods_supported = code_challenge_methods_supported
        self.scopes_supported = scopes_supported



class OAuthProtectedResourceMetadata():
    """OAuth 受保护资源元数据（符合 RFC 9728 标准）"""

    def __init__(self,
    # 必需字段
    resource: str,  # 资源标识符
    
    # 可选字段
    authorization_servers: List[str],  # 授权服务器列表
    bearer_methods_supported: List[str],  # 支持的持有者令牌使用方法
    resource_documentation: str,  # 资源文档 URL
    resource_signing_alg_values_supported: List[str],  # 支持的资源签名算法
    resource_encryption_alg_values_supported: List[str],  # 支持的资源加密算法
    resource_encryption_enc_values_supported: List[str]):
        self.resource = resource
        self.authorization_servers = authorization_servers
        self.bearer_methods_supported = bearer_methods_supported
        self.resource_documentation = resource_documentation
        self.resource_signing_alg_values_supported = resource_signing_alg_values_supported
        self.resource_encryption_alg_values_supported = resource_encryption_alg_values_supported
        self.resource_encryption_enc_values_supported = resource_encryption_enc_values_supported



class OAuthUtils:
    """OAuth 操作的实用工具类"""
    
    @classmethod
    def build_well_known_urls(cls, base_url: str) -> Dict[str, str]:
        """构建 well-known OAuth 端点 URL"""
        parsed_url = urllib.parse.urlparse(base_url)
        base = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        return {
            'protectedResource': urllib.parse.urljoin(base, '/.well-known/oauth-protected-resource'),
            'authorizationServer': urllib.parse.urljoin(base, '/.well-known/oauth-authorization-server')
        }
    
    @classmethod
    async def fetch_protected_resource_metadata(
        cls, resource_metadata_url: str
    ) -> Optional[OAuthProtectedResourceMetadata]:
        """获取 OAuth 受保护资源元数据"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(resource_metadata_url) as response:
                    if not response.ok:
                        return None
                    return await response.json()
        except Exception as e:
            print(f"Failed to fetch protected resource metadata from {resource_metadata_url}: {str(get_error_message(e))}")
            return None
    
    @classmethod
    async def fetch_authorization_server_metadata(
        cls, auth_server_metadata_url: str
    ) -> Optional[OAuthAuthorizationServerMetadata]:
        """获取 OAuth 授权服务器元数据"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(auth_server_metadata_url) as response:
                    if not response.ok:
                        return None
                    return await response.json()
        except Exception as e:
            print(f"Failed to fetch authorization server metadata from {auth_server_metadata_url}: {str(get_error_message(e))}")
            return None
    
    @classmethod
    def metadata_to_oauth_config(
        cls, metadata: OAuthAuthorizationServerMetadata
    ) -> MCPOAuthConfig:
        """将授权服务器元数据转换为 OAuth 配置"""
        return {
            'authorizationUrl': metadata['authorization_endpoint'],
            'tokenUrl': metadata['token_endpoint'],
            'scopes': metadata.get('scopes_supported', [])
        }
    
    @classmethod
    async def discover_oauth_config(
        cls, server_url: str
    ) -> Optional[MCPOAuthConfig]:
        """使用标准 well-known 端点发现 OAuth 配置"""
        try:
            well_known_urls = cls.build_well_known_urls(server_url)
            
            # 首先尝试获取受保护资源元数据
            resource_metadata = await cls.fetch_protected_resource_metadata(
                well_known_urls['protectedResource']
            )
            
            if resource_metadata and 'authorization_servers' in resource_metadata and resource_metadata['authorization_servers']:
                # 使用第一个授权服务器
                auth_server_url = resource_metadata['authorization_servers'][0]
                auth_server_metadata_url = urllib.parse.urljoin(
                    auth_server_url, '/.well-known/oauth-authorization-server'
                )
                
                auth_server_metadata = await cls.fetch_authorization_server_metadata(
                    auth_server_metadata_url
                )
                
                if auth_server_metadata:
                    config = cls.metadata_to_oauth_config(auth_server_metadata)
                    if 'registration_endpoint' in auth_server_metadata:
                        print(
                            'Dynamic client registration is supported at:',
                            auth_server_metadata['registration_endpoint']
                        )
                    return config
            
            # 回退：尝试在基础 URL 上使用 /.well-known/oauth-authorization-server
            print(
                f"Trying OAuth discovery fallback at {well_known_urls['authorizationServer']}"
            )
            auth_server_metadata = await cls.fetch_authorization_server_metadata(
                well_known_urls['authorizationServer']
            )
            
            if auth_server_metadata:
                config = cls.metadata_to_oauth_config(auth_server_metadata)
                if 'registration_endpoint' in auth_server_metadata:
                    print(
                        'Dynamic client registration is supported at:',
                        auth_server_metadata['registration_endpoint']
                    )
                return config
            
            return None
        except Exception as e:
            print(f"Failed to discover OAuth configuration: {str(get_error_message(e))}")

            return None
    
    @classmethod
    def parse_www_authenticate_header(cls, header: str) -> Optional[str]:
        """解析 WWW-Authenticate 头部以提取 OAuth 信息"""
        match = re.search(r'resource_metadata="([^"]+)"', header)
        if match:
            return match.group(1)
        return None
    
    @classmethod
    async def discover_oauth_from_www_authenticate(
        cls, www_authenticate: str
    ) -> Optional[MCPOAuthConfig]:
        """从 WWW-Authenticate 头部发现 OAuth 配置"""
        resource_metadata_uri = cls.parse_www_authenticate_header(www_authenticate)
        if not resource_metadata_uri:
            return None
        
        print(
            f"Found resource metadata URI from www-authenticate header: {resource_metadata_uri}"
        )
        
        resource_metadata = await cls.fetch_protected_resource_metadata(resource_metadata_uri)
        if not resource_metadata or not resource_metadata.get('authorization_servers'):
            return None
        
        auth_server_url = resource_metadata['authorization_servers'][0]
        auth_server_metadata_url = urllib.parse.urljoin(
            auth_server_url, '/.well-known/oauth-authorization-server'
        )
        
        auth_server_metadata = await cls.fetch_authorization_server_metadata(
            auth_server_metadata_url
        )
        
        if auth_server_metadata:
            print(
                'OAuth configuration discovered successfully from www-authenticate header'
            )
            return cls.metadata_to_oauth_config(auth_server_metadata)
        
        return None
    
    @classmethod
    def extract_base_url(cls, mcp_server_url: str) -> str:
        """从 MCP 服务器 URL 中提取基础 URL"""
        parsed_url = urllib.parse.urlparse(mcp_server_url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    @classmethod
    def is_sse_endpoint(cls, url: str) -> bool:
        """检查 URL 是否为 SSE 端点"""
        return '/sse' in url or '/mcp' not in url
    
    @classmethod
    def build_resource_parameter(cls, endpoint_url: str) -> str:
        """为 OAuth 请求构建资源参数"""
        parsed_url = urllib.parse.urlparse(endpoint_url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}"