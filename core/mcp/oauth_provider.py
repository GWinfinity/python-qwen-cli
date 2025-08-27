import asyncio
import base64
import hashlib
import json
import os
import random
import string
import sys
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Any, Tuple, Union

# 导入其他必要的模块（根据实际项目结构调整导入路径）
from ..utils.secure_browser_launcher import open_browser_securely
from .oauth_token_storage import MCPOAuthToken, MCPOAuthTokenStorage
from ..utils.errors import get_error_message
from .oauth_utils import OAuthUtils


class MCPOAuthConfig:
    """OAuth configuration for an MCP server."""
    def __init__(self, 
                 enabled: Optional[bool] = None, 
                 client_id: Optional[str] = None, 
                 client_secret: Optional[str] = None, 
                 authorization_url: Optional[str] = None, 
                 token_url: Optional[str] = None, 
                 scopes: Optional[List[str]] = None, 
                 redirect_uri: Optional[str] = None, 
                 token_param_name: Optional[str] = None):
        self.enabled = enabled
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorization_url = authorization_url
        self.token_url = token_url
        self.scopes = scopes or []
        self.redirect_uri = redirect_uri
        self.token_param_name = token_param_name


class OAuthAuthorizationResponse:
    """OAuth authorization response."""
    def __init__(self, code: str, state: str):
        self.code = code
        self.state = state


class OAuthTokenResponse:
    """OAuth token response from the authorization server."""
    def __init__(self, 
                 access_token: str, 
                 token_type: str, 
                 expires_in: Optional[int] = None, 
                 refresh_token: Optional[str] = None, 
                 scope: Optional[str] = None):
        self.access_token = access_token
        self.token_type = token_type
        self.expires_in = expires_in
        self.refresh_token = refresh_token
        self.scope = scope


class OAuthClientRegistrationRequest:
    """Dynamic client registration request."""
    def __init__(self, 
                 client_name: str, 
                 redirect_uris: List[str], 
                 grant_types: List[str], 
                 response_types: List[str], 
                 token_endpoint_auth_method: str, 
                 code_challenge_method: Optional[List[str]] = None, 
                 scope: Optional[str] = None):
        self.client_name = client_name
        self.redirect_uris = redirect_uris
        self.grant_types = grant_types
        self.response_types = response_types
        self.token_endpoint_auth_method = token_endpoint_auth_method
        self.code_challenge_method = code_challenge_method
        self.scope = scope


class OAuthClientRegistrationResponse:
    """Dynamic client registration response."""
    def __init__(self, 
                 client_id: str, 
                 client_secret: Optional[str] = None, 
                 client_id_issued_at: Optional[int] = None, 
                 client_secret_expires_at: Optional[int] = None, 
                 redirect_uris: Optional[List[str]] = None, 
                 grant_types: Optional[List[str]] = None, 
                 response_types: Optional[List[str]] = None, 
                 token_endpoint_auth_method: Optional[str] = None, 
                 code_challenge_method: Optional[List[str]] = None, 
                 scope: Optional[str] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.client_id_issued_at = client_id_issued_at
        self.client_secret_expires_at = client_secret_expires_at
        self.redirect_uris = redirect_uris or []
        self.grant_types = grant_types or []
        self.response_types = response_types or []
        self.token_endpoint_auth_method = token_endpoint_auth_method
        self.code_challenge_method = code_challenge_method
        self.scope = scope


class PKCEParams:
    """PKCE (Proof Key for Code Exchange) parameters."""
    def __init__(self, code_verifier: str, code_challenge: str, state: str):
        self.code_verifier = code_verifier
        self.code_challenge = code_challenge
        self.state = state


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handler for OAuth callback requests."""
    expected_state = None
    callback_result = None
    callback_event = None

    def do_GET(self):
        try:
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            path = parsed_url.path

            if path != MCPOAuthProvider.REDIRECT_PATH:
                self.send_error(404, "Not found")
                return

            code = query_params.get('code', [None])[0]
            state = query_params.get('state', [None])[0]
            error = query_params.get('error', [None])[0]
            error_description = query_params.get('error_description', [''])[0]

            if error:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                error_html = f"""
                <html>
                  <body>
                    <h1>Authentication Failed</h1>
                    <p>Error: {error}</p>
                    <p>{error_description}</p>
                    <p>You can close this window.</p>
                  </body>
                </html>
                """
                self.wfile.write(error_html.encode('utf-8'))
                if self.callback_event:
                    self.callback_result = Exception(f"OAuth error: {error}")
                    self.callback_event.set()
                return

            if not code or not state:
                self.send_error(400, "Missing code or state parameter")
                return

            if state != self.expected_state:
                self.send_error(400, "Invalid state parameter")
                if self.callback_event:
                    self.callback_result = Exception("State mismatch - possible CSRF attack")
                    self.callback_event.set()
                return

            # Send success response to browser
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            success_html = """
            <html>
              <body>
                <h1>Authentication Successful!</h1>
                <p>You can close this window and return to Gemini CLI.</p>
                <script>window.close();</script>
              </body>
            </html>
            """
            self.wfile.write(success_html.encode('utf-8'))

            if self.callback_event:
                self.callback_result = OAuthAuthorizationResponse(code, state)
                self.callback_event.set()

        except Exception as e:
            if self.callback_event:
                self.callback_result = e
                self.callback_event.set()


class MCPOAuthProvider:
    """Provider for handling OAuth authentication for MCP servers."""
    REDIRECT_PORT = 7777
    REDIRECT_PATH = '/oauth/callback'
    HTTP_OK = 200
    HTTP_REDIRECT = 302

    @staticmethod
    async def register_client(
            registration_url: str, 
            config: MCPOAuthConfig) -> OAuthClientRegistrationResponse:
        """
        Register a client dynamically with the OAuth server.

        Args:
            registration_url: The client registration endpoint URL
            config: OAuth configuration

        Returns:
            The registered client information
        """
        redirect_uri = config.redirect_uri or \
            f"http://localhost:{MCPOAuthProvider.REDIRECT_PORT}{MCPOAuthProvider.REDIRECT_PATH}"

        registration_request = OAuthClientRegistrationRequest(
            client_name='Gemini CLI (Google ADC)',
            redirect_uris=[redirect_uri],
            grant_types=['authorization_code', 'refresh_token'],
            response_types=['code'],
            token_endpoint_auth_method='none',  # Public client
            code_challenge_method=['S256'],
            scope=' '.join(config.scopes) if config.scopes else ''
        )

        # 转换为字典以便JSON序列化
        request_data = {
            'client_name': registration_request.client_name,
            'redirect_uris': registration_request.redirect_uris,
            'grant_types': registration_request.grant_types,
            'response_types': registration_request.response_types,
            'token_endpoint_auth_method': registration_request.token_endpoint_auth_method
        }
        if registration_request.code_challenge_method:
            request_data['code_challenge_method'] = registration_request.code_challenge_method
        if registration_request.scope:
            request_data['scope'] = registration_request.scope

        # 使用 aiohttp 或其他异步 HTTP 客户端发送请求
        # 这里使用模拟实现，实际项目中需要替换为真实的 HTTP 请求
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    registration_url,
                    headers={'Content-Type': 'application/json'},
                    json=request_data) as response:
                if not response.ok:
                    error_text = await response.text()
                    raise Exception(
                        f"Client registration failed: {response.status} {response.reason} - {error_text}"
                    )
                data = await response.json()
                return OAuthClientRegistrationResponse(
                    client_id=data['client_id'],
                    client_secret=data.get('client_secret'),
                    client_id_issued_at=data.get('client_id_issued_at'),
                    client_secret_expires_at=data.get('client_secret_expires_at'),
                    redirect_uris=data.get('redirect_uris'),
                    grant_types=data.get('grant_types'),
                    response_types=data.get('response_types'),
                    token_endpoint_auth_method=data.get('token_endpoint_auth_method'),
                    code_challenge_method=data.get('code_challenge_method'),
                    scope=data.get('scope')
                )

    @staticmethod
    async def discover_oauth_from_mcp_server(
            mcp_server_url: str) -> Optional[MCPOAuthConfig]:
        """
        Discover OAuth configuration from an MCP server URL.

        Args:
            mcp_server_url: The MCP server URL

        Returns:
            OAuth configuration if discovered, None otherwise
        """
        base_url = OAuthUtils.extract_base_url(mcp_server_url)
        return await OAuthUtils.discover_oauth_config(base_url)

    @staticmethod
    def generate_pkce_params() -> PKCEParams:
        """
        Generate PKCE parameters for OAuth flow.

        Returns:
            PKCE parameters including code verifier, challenge, and state
        """
        # Generate code verifier (43-128 characters)
        # 使用Python的secrets模块可能更安全，但为了兼容性这里使用random
        code_verifier = ''.join(
            random.choices(string.ascii_letters + string.digits + '-._~', k=64)
        )

        # Generate code challenge using SHA256
        code_challenge_bytes = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        # URL-safe base64 encoding without padding
        code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).rstrip(b'=').decode('utf-8')

        # Generate state for CSRF protection
        state = ''.join(
            random.choices(string.ascii_letters + string.digits + '-._~', k=32)
        )

        return PKCEParams(code_verifier, code_challenge, state)

    @staticmethod
    async def start_callback_server(
            expected_state: str) -> OAuthAuthorizationResponse:
        """
        Start a local HTTP server to handle OAuth callback.

        Args:
            expected_state: The state parameter to validate

        Returns:
            Promise that resolves with the authorization code
        """
        event = asyncio.Event()
        OAuthCallbackHandler.expected_state = expected_state
        OAuthCallbackHandler.callback_result = None
        OAuthCallbackHandler.callback_event = event

        server = HTTPServer(('localhost', MCPOAuthProvider.REDIRECT_PORT), OAuthCallbackHandler)
        server.timeout = 1  # 设置超时以便定期检查event

        print(f"OAuth callback server listening on port {MCPOAuthProvider.REDIRECT_PORT}")

        # 创建一个任务来运行服务器
        async def serve_forever():
            while not event.is_set():
                server.handle_request()
                await asyncio.sleep(0.1)  # 短暂睡眠以避免CPU占用过高
            server.server_close()

        # 创建超时任务
        async def timeout():
            await asyncio.sleep(5 * 60)  # 5分钟超时
            if not event.is_set():
                event.set()
                OAuthCallbackHandler.callback_result = Exception("OAuth callback timeout")

        # 运行服务器和超时任务
        server_task = asyncio.create_task(serve_forever())
        timeout_task = asyncio.create_task(timeout())

        # 等待事件设置或超时
        await event.wait()

        # 取消任务
        server_task.cancel()
        timeout_task.cancel()

        # 检查结果
        if isinstance(OAuthCallbackHandler.callback_result, Exception):
            raise OAuthCallbackHandler.callback_result
        elif OAuthCallbackHandler.callback_result:
            return OAuthCallbackHandler.callback_result
        else:
            raise Exception("Unknown error in OAuth callback")

    @staticmethod
    def build_authorization_url(
            config: MCPOAuthConfig, 
            pkce_params: PKCEParams, 
            mcp_server_url: Optional[str] = None) -> str:
        """
        Build the authorization URL with PKCE parameters.

        Args:
            config: OAuth configuration
            pkce_params: PKCE parameters
            mcp_server_url: The MCP server URL to use as the resource parameter

        Returns:
            The authorization URL
        """
        redirect_uri = config.redirect_uri or \
            f"http://localhost:{MCPOAuthProvider.REDIRECT_PORT}{MCPOAuthProvider.REDIRECT_PATH}"

        params = urllib.parse.urlencode({
            'client_id': config.client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'state': pkce_params.state,
            'code_challenge': pkce_params.code_challenge,
            'code_challenge_method': 'S256'
        })

        if config.scopes and len(config.scopes) > 0:
            scope_param = urllib.parse.urlencode({'scope': ' '.join(config.scopes)})
            params += '&' + scope_param

        # Add resource parameter for MCP OAuth spec compliance
        # Use the MCP server URL if provided, otherwise fall back to authorization URL
        resource_url = mcp_server_url or config.authorization_url
        try:
            resource_param = urllib.parse.urlencode({
                'resource': OAuthUtils.build_resource_parameter(resource_url)
            })
            params += '&' + resource_param
        except Exception as e:
            raise Exception(f"Invalid resource URL: \"{resource_url}\". {get_error_message(e)}")

        return f"{config.authorization_url}?{params}"

    @staticmethod
    async def exchange_code_for_token(
            config: MCPOAuthConfig, 
            code: str, 
            code_verifier: str, 
            mcp_server_url: Optional[str] = None) -> OAuthTokenResponse:
        """
        Exchange authorization code for tokens.

        Args:
            config: OAuth configuration
            code: Authorization code
            code_verifier: PKCE code verifier
            mcp_server_url: The MCP server URL to use as the resource parameter

        Returns:
            The token response
        """
        redirect_uri = config.redirect_uri or \
            f"http://localhost:{MCPOAuthProvider.REDIRECT_PORT}{MCPOAuthProvider.REDIRECT_PATH}"

        params = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'code_verifier': code_verifier,
            'client_id': config.client_id
        }

        if config.client_secret:
            params['client_secret'] = config.client_secret

        # Add resource parameter for MCP OAuth spec compliance
        # Use the MCP server URL if provided, otherwise fall back to token URL
        resource_url = mcp_server_url or config.token_url
        try:
            params['resource'] = OAuthUtils.build_resource_parameter(resource_url)
        except Exception as e:
            raise Exception(f"Invalid resource URL: \"{resource_url}\". {get_error_message(e)}")

        # 使用 aiohttp 发送请求
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    config.token_url, 
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    data=params) as response:
                if not response.ok:
                    error_text = await response.text()
                    raise Exception(f"Token exchange failed: {response.status} - {error_text}")
                data = await response.json()
                return OAuthTokenResponse(
                    access_token=data['access_token'],
                    token_type=data['token_type'],
                    expires_in=data.get('expires_in'),
                    refresh_token=data.get('refresh_token'),
                    scope=data.get('scope')
                )

    @staticmethod
    async def refresh_access_token(
            config: MCPOAuthConfig, 
            refresh_token: str, 
            token_url: str, 
            mcp_server_url: Optional[str] = None) -> OAuthTokenResponse:
        """
        Refresh an access token using a refresh token.

        Args:
            config: OAuth configuration
            refresh_token: The refresh token
            token_url: The token endpoint URL
            mcp_server_url: The MCP server URL to use as the resource parameter

        Returns:
            The new token response
        """
        params = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': config.client_id
        }

        if config.client_secret:
            params['client_secret'] = config.client_secret

        if config.scopes and len(config.scopes) > 0:
            params['scope'] = ' '.join(config.scopes)

        # Add resource parameter for MCP OAuth spec compliance
        # Use the MCP server URL if provided, otherwise fall back to token URL
        resource_url = mcp_server_url or token_url
        try:
            params['resource'] = OAuthUtils.build_resource_parameter(resource_url)
        except Exception as e:
            raise Exception(f"Invalid resource URL: \"{resource_url}\". {get_error_message(e)}")

        # 使用 aiohttp 发送请求
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    token_url, 
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    data=params) as response:
                if not response.ok:
                    error_text = await response.text()
                    raise Exception(f"Token refresh failed: {response.status} - {error_text}")
                data = await response.json()
                return OAuthTokenResponse(
                    access_token=data['access_token'],
                    token_type=data['token_type'],
                    expires_in=data.get('expires_in'),
                    refresh_token=data.get('refresh_token'),
                    scope=data.get('scope')
                )

    @staticmethod
    async def authenticate(
            server_name: str, 
            config: MCPOAuthConfig, 
            mcp_server_url: Optional[str] = None) -> MCPOAuthToken:
        """
        Perform the full OAuth authorization code flow with PKCE.

        Args:
            server_name: The name of the MCP server
            config: OAuth configuration
            mcp_server_url: Optional MCP server URL for OAuth discovery

        Returns:
            The obtained OAuth token
        """
        # If no authorization URL is provided, try to discover OAuth configuration
        if not config.authorization_url and mcp_server_url:
            print('No authorization URL provided, attempting OAuth discovery...')

            # For SSE URLs, first check if authentication is required
            if OAuthUtils.is_sse_endpoint(mcp_server_url):
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.head(
                                mcp_server_url,
                                headers={'Accept': 'text/event-stream'}) as response:
                            if response.status == 401 or response.status == 307:
                                www_authenticate = response.headers.get('www-authenticate')
                                if www_authenticate:
                                    discovered_config = \
                                        await OAuthUtils.discover_oauth_from_www_authenticate(
                                            www_authenticate
                                        )
                                    if discovered_config:
                                        config = MCPOAuthConfig(
                                            enabled=discovered_config.enabled or config.enabled,
                                            client_id=discovered_config.client_id or config.client_id,
                                            client_secret=discovered_config.client_secret or config.client_secret,
                                            authorization_url=discovered_config.authorization_url or config.authorization_url,
                                            token_url=discovered_config.token_url or config.token_url,
                                            scopes=discovered_config.scopes or config.scopes,
                                            redirect_uri=discovered_config.redirect_uri or config.redirect_uri,
                                            token_param_name=discovered_config.token_param_name or config.token_param_name
                                        )
                except Exception as e:
                    print(f"Failed to check SSE endpoint for authentication requirements: {get_error_message(e)}")

            # If we still don't have OAuth config, try the standard discovery
            if not config.authorization_url:
                discovered_config = await MCPOAuthProvider.discover_oauth_from_mcp_server(mcp_server_url)
                if discovered_config:
                    config = MCPOAuthConfig(
                        enabled=discovered_config.enabled or config.enabled,
                        client_id=discovered_config.client_id or config.client_id,
                        client_secret=discovered_config.client_secret or config.client_secret,
                        authorization_url=discovered_config.authorization_url or config.authorization_url,
                        token_url=discovered_config.token_url or config.token_url,
                        scopes=discovered_config.scopes or config.scopes,
                        redirect_uri=discovered_config.redirect_uri or config.redirect_uri,
                        token_param_name=discovered_config.token_param_name or config.token_param_name
                    )
                    print('OAuth configuration discovered successfully')
                else:
                    raise Exception('Failed to discover OAuth configuration from MCP server')

        # If no client ID is provided, try dynamic client registration
        if not config.client_id:
            # Extract server URL from authorization URL
            if not config.authorization_url:
                raise Exception('Cannot perform dynamic registration without authorization URL')

            parsed_url = urllib.parse.urlparse(config.authorization_url)
            server_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

            print('No client ID provided, attempting dynamic client registration...')

            # Get the authorization server metadata for registration
            auth_server_metadata_url = urllib.parse.urljoin(
                server_url, '/.well-known/oauth-authorization-server')

            auth_server_metadata = await OAuthUtils.fetch_authorization_server_metadata(
                auth_server_metadata_url
            )
            if not auth_server_metadata:
                raise Exception('Failed to fetch authorization server metadata for client registration')

            # Register client if registration endpoint is available
            if auth_server_metadata.get('registration_endpoint'):
                client_registration = await MCPOAuthProvider.register_client(
                    auth_server_metadata['registration_endpoint'],
                    config
                )

                config.client_id = client_registration.client_id
                if client_registration.client_secret:
                    config.client_secret = client_registration.client_secret

                print('Dynamic client registration successful')
            else:
                raise Exception('No client ID provided and dynamic registration not supported')

        # Validate configuration
        if not config.client_id or not config.authorization_url or not config.token_url:
            raise Exception('Missing required OAuth configuration after discovery and registration')

        # Generate PKCE parameters
        pkce_params = MCPOAuthProvider.generate_pkce_params()

        # Build authorization URL
        auth_url = MCPOAuthProvider.build_authorization_url(
            config, pkce_params, mcp_server_url
        )

        print('\nOpening browser for OAuth authentication...')
        print('If the browser does not open, please visit:')
        print('')

        # Get terminal width or default to 80
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            terminal_width = 80
        separator_length = min(terminal_width - 2, 80)
        separator = '━' * separator_length

        print(separator)
        print('COPY THE ENTIRE URL BELOW (select all text between the lines):')
        print(separator)
        print(auth_url)
        print(separator)
        print('')
        print('💡 TIP: Triple-click to select the entire URL, then copy and paste it into your browser.')
        print('⚠️  Make sure to copy the COMPLETE URL - it may wrap across multiple lines.')
        print('')

        # Start callback server
        callback_promise = MCPOAuthProvider.start_callback_server(pkce_params.state)

        # Open browser securely
        try:
            await open_browser_securely(auth_url)
        except Exception as e:
            print(f"Warning: {get_error_message(e)}")

        # Wait for callback
        authorization_response = await callback_promise

        print('\nAuthorization code received, exchanging for tokens...')

        # Exchange code for tokens
        token_response = await MCPOAuthProvider.exchange_code_for_token(
            config, authorization_response.code, pkce_params.code_verifier, mcp_server_url
        )

        # Convert to our token format
        token = MCPOAuthToken(
            access_token=token_response.access_token,
            token_type=token_response.token_type,
            refresh_token=token_response.refresh_token,
            scope=token_response.scope
        )

        if token_response.expires_in:
            token.expires_at = int(time.time() * 1000) + token_response.expires_in * 1000

        # Save token
        try:
            await MCPOAuthTokenStorage.save_token(
                server_name, token, config.client_id, config.token_url, mcp_server_url
            )
            print('Authentication successful! Token saved.')

            # Verify token was saved
            saved_token = await MCPOAuthTokenStorage.get_token(server_name)
            if saved_token:
                print(f'Token verification successful: {saved_token.token.access_token[:20]}...')
            else:
                print('Token verification failed: token not found after save')
        except Exception as save_error:
            print(f'Failed to save token: {get_error_message(save_error)}')
            raise save_error

        return token

    @staticmethod
    async def get_valid_token(
            server_name: str, 
            config: MCPOAuthConfig) -> Optional[str]:
        """
        Get a valid access token for an MCP server, refreshing if necessary.

        Args:
            server_name: The name of the MCP server
            config: OAuth configuration

        Returns:
            A valid access token or None if not authenticated
        """
        print(f"Debug: Getting valid token for server: {server_name}")
        credentials = await MCPOAuthTokenStorage.get_token(server_name)

        if not credentials:
            print(f"Debug: No credentials found for server: {server_name}")
            return None

        token = credentials.token
        is_expired = MCPOAuthTokenStorage.is_token_expired(token)
        print(f"Debug: Found token for server: {server_name}, expired: {is_expired}")

        # Check if token is expired
        if not is_expired:
            print(f"Debug: Returning valid token for server: {server_name}")
            return token.access_token

        # Try to refresh if we have a refresh token
        if token.refresh_token and config.client_id and credentials.token_url:
            try:
                print(f"Refreshing expired token for MCP server: {server_name}")

                new_token_response = await MCPOAuthProvider.refresh_access_token(
                    config, token.refresh_token, credentials.token_url, credentials.mcp_server_url
                )

                # Update stored token
                new_token = MCPOAuthToken(
                    access_token=new_token_response.access_token,
                    token_type=new_token_response.token_type,
                    refresh_token=new_token_response.refresh_token or token.refresh_token,
                    scope=new_token_response.scope or token.scope
                )

                if new_token_response.expires_in:
                    new_token.expires_at = int(time.time() * 1000) + new_token_response.expires_in * 1000

                await MCPOAuthTokenStorage.save_token(
                    server_name, new_token, config.client_id, credentials.token_url, credentials.mcp_server_url
                )

                return new_token.access_token
            except Exception as e:
                print(f'Failed to refresh token: {get_error_message(e)}')
                # Remove invalid token
                await MCPOAuthTokenStorage.remove_token(server_name)

        return None