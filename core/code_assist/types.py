"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, List, Dict, Any, Union


class ClientMetadata:
    """客户端元数据接口"""
    def __init__(
        self,
        ide_type: Optional[ClientMetadataIdeType] = None,
        ide_version: Optional[str] = None,
        plugin_version: Optional[str] = None,
        platform: Optional[ClientMetadataPlatform] = None,
        update_channel: Optional[str] = None,
        duet_project: Optional[str] = None,
        plugin_type: Optional[ClientMetadataPluginType] = None,
        ide_name: Optional[str] = None,
    ):
        self.ide_type = ide_type
        self.ide_version = ide_version
        self.plugin_version = plugin_version
        self.platform = platform
        self.update_channel = update_channel
        self.duet_project = duet_project
        self.plugin_type = plugin_type
        self.ide_name = ide_name



class ClientMetadataIdeType(str, Enum):
    """IDE类型枚举"""
    IDE_UNSPECIFIED = 'IDE_UNSPECIFIED'
    VSCODE = 'VSCODE'
    INTELLIJ = 'INTELLIJ'
    VSCODE_CLOUD_WORKSTATION = 'VSCODE_CLOUD_WORKSTATION'
    INTELLIJ_CLOUD_WORKSTATION = 'INTELLIJ_CLOUD_WORKSTATION'
    CLOUD_SHELL = 'CLOUD_SHELL'


class ClientMetadataPlatform(str, Enum):
    """平台类型枚举"""
    PLATFORM_UNSPECIFIED = 'PLATFORM_UNSPECIFIED'
    DARWIN_AMD64 = 'DARWIN_AMD64'
    DARWIN_ARM64 = 'DARWIN_ARM64'
    LINUX_AMD64 = 'LINUX_AMD64'
    LINUX_ARM64 = 'LINUX_ARM64'
    WINDOWS_AMD64 = 'WINDOWS_AMD64'


class ClientMetadataPluginType(str, Enum):
    """插件类型枚举"""
    PLUGIN_UNSPECIFIED = 'PLUGIN_UNSPECIFIED'
    CLOUD_CODE = 'CLOUD_CODE'
    GEMINI = 'GEMINI'
    AIPLUGIN_INTELLIJ = 'AIPLUGIN_INTELLIJ'
    AIPLUGIN_STUDIO = 'AIPLUGIN_STUDIO'


class LoadCodeAssistRequest:
    """加载代码助手请求接口"""
    def __init__(
        self,
        cloudaicompanion_project: Optional[str] = None,
        metadata: Optional[ClientMetadata] = None,
    ):
        self.cloudaicompanion_project = cloudaicompanion_project
        self.metadata = metadata


class LoadCodeAssistResponse:
    """加载代码助手响应接口"""
    def __init__(
        self,
        current_tier: Optional[GeminiUserTier] = None,
        allowed_tiers: Optional[List[GeminiUserTier]] = None,
        ineligible_tiers: Optional[List[IneligibleTier]] = None,
        cloudaicompanion_project: Optional[str] = None,
    ):
        self.current_tier = current_tier
        self.allowed_tiers = allowed_tiers
        self.ineligible_tiers = ineligible_tiers
        self.cloudaicompanion_project = cloudaicompanion_project


class GeminiUserTier:
    """Gemini用户层级接口"""
    def __init__(
        self,
        id: UserTierId,
        name: string,
        description: string,
        user_defined_cloudaicompanion_project: Optional[bool] = None,
        is_default: Optional[bool] = None,
        privacy_notice: Optional[PrivacyNotice] = None,
        has_accepted_tos: Optional[bool] = None,
        has_onboarded_previously: Optional[bool] = None,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.user_defined_cloudaicompanion_project = user_defined_cloudaicompanion_project
        self.is_default = is_default
        self.privacy_notice = privacy_notice
        self.has_accepted_tos = has_accepted_tos
        self.has_onboarded_previously = has_onboarded_previously


class IneligibleTier:
    """不合格层级接口"""
    def __init__(
        self,
        reason_code: IneligibleTierReasonCode,
        reason_message: string,
        tier_id: UserTierId,
        tier_name: string,
    ):
        self.reason_code = reason_code
        self.reason_message = reason_message
        self.tier_id = tier_id
        self.tier_name = tier_name


class IneligibleTierReasonCode(str, Enum):
    """不合格层级原因代码枚举"""
    DASHER_USER = 'DASHER_USER'
    INELIGIBLE_ACCOUNT = 'INELIGIBLE_ACCOUNT'
    NON_USER_ACCOUNT = 'NON_USER_ACCOUNT'
    RESTRICTED_AGE = 'RESTRICTED_AGE'
    RESTRICTED_NETWORK = 'RESTRICTED_NETWORK'
    UNKNOWN = 'UNKNOWN'
    UNKNOWN_LOCATION = 'UNKNOWN_LOCATION'
    UNSUPPORTED_LOCATION = 'UNSUPPORTED_LOCATION'


class UserTierId(str, Enum):
    """用户层级ID枚举"""
    FREE = 'free-tier'
    LEGACY = 'legacy-tier'
    STANDARD = 'standard-tier'


class PrivacyNotice:
    """隐私通知接口"""
    def __init__(
        self,
        show_notice: bool,
        notice_text: Optional[str] = None,
    ):
        self.show_notice = show_notice
        self.notice_text = notice_text


class OnboardUserRequest:
    """用户入职请求接口"""
    def __init__(
        self,
        tier_id: Optional[str] = None,
        cloudaicompanion_project: Optional[str] = None,
        metadata: Optional[ClientMetadata] = None,
    ):
        self.tier_id = tier_id
        self.cloudaicompanion_project = cloudaicompanion_project
        self.metadata = metadata


class LongRunningOperationResponse:
    """长期运行操作响应接口"""
    def __init__(
        self,
        name: string,
        done: Optional[bool] = None,
        response: Optional[OnboardUserResponse] = None,
    ):
        self.name = name
        self.done = done
        self.response = response


class OnboardUserResponse:
    """用户入职响应接口"""
    def __init__(
        self,
        cloudaicompanion_project: Optional[Dict[str, str]] = None,
    ):
        self.cloudaicompanion_project = cloudaicompanion_project


class OnboardUserStatusCode(str, Enum):
    """用户入职状态码枚举"""
    DEFAULT = 'DEFAULT'
    NOTICE = 'NOTICE'
    WARNING = 'WARNING'
    ERROR = 'ERROR'


class OnboardUserStatus:
    """用户入职状态接口"""
    def __init__(
        self,
        status_code: OnboardUserStatusCode,
        display_message: string,
        help_link: Optional[HelpLinkUrl] = None,
    ):
        self.status_code = status_code
        self.display_message = display_message
        self.help_link = help_link


class HelpLinkUrl:
    """帮助链接URL接口"""
    def __init__(
        self,
        description: string,
        url: string,
    ):
        self.description = description
        self.url = url


class SetCodeAssistGlobalUserSettingRequest:
    """设置代码助手全局用户设置请求接口"""
    def __init__(
        self,
        cloudaicompanion_project: Optional[str] = None,
        free_tier_data_collection_optin: bool = False,

    ):
        self.cloudaicompanion_project = cloudaicompanion_project
        self.free_tier_data_collection_optin = free_tier_data_collection_optin


class CodeAssistGlobalUserSettingResponse:
    """代码助手全局用户设置响应接口"""
    def __init__(
        self,
        cloudaicompanion_project: Optional[str] = None,
        free_tier_data_collection_optin: bool = False,
    ):
        self.cloudaicompanion_project = cloudaicompanion_project
        self.free_tier_data_collection_optin = free_tier_data_collection_optin