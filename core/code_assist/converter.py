"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Union, TypeVar, Generic

# 模拟 Google GenAI 类型
from google.genai import (
    Content,
    ContentListUnion,
    ContentUnion,
    GenerateContentConfig,
    GenerateContentParameters,
    CountTokensParameters,
    CountTokensResponse,
    GenerateContentResponse,
    GenerationConfigRoutingConfig,
    MediaResolution,
    Candidate,
    ModelSelectionConfig,
    GenerateContentResponsePromptFeedback,
    GenerateContentResponseUsageMetadata,
    Part,
    SafetySetting,
    PartUnion,
    SchemaUnion,
    SpeechConfigUnion,
    ThinkingConfig,
    ToolListUnion,
    ToolConfig,
)


class CAGenerateContentRequest:
    """CA 生成内容请求接口"""
    def __init__(
        self,
        model: str,
        project: Optional[str] = None,
        user_prompt_id: Optional[str] = None,
        request: Optional[VertexGenerateContentRequest] = None,
    ):
        self.model = model
        self.project = project
        self.user_prompt_id = user_prompt_id
        self.request = request


class VertexGenerateContentRequest:
    """Vertex 生成内容请求接口"""
    def __init__(
        self,
        contents: List[Content],
        systemInstruction: Optional[Content] = None,
        cachedContent: Optional[str] = None,
        tools: Optional[ToolListUnion] = None,
        toolConfig: Optional[ToolConfig] = None,
        labels: Optional[Dict[str, str]] = None,
        safetySettings: Optional[List[SafetySetting]] = None,
        generationConfig: Optional[VertexGenerationConfig] = None,
        session_id: Optional[str] = None,
    ):
        self.contents = contents
        self.systemInstruction = systemInstruction
        self.cachedContent = cachedContent
        self.tools = tools
        self.toolConfig = toolConfig
        self.labels = labels
        self.safetySettings = safetySettings
        self.generationConfig = generationConfig
        self.session_id = session_id


class VertexGenerationConfig:
    """Vertex 生成配置接口"""
    def __init__(
        self,
        temperature: Optional[float] = None,
        topP: Optional[float] = None,
        topK: Optional[int] = None,
        candidateCount: Optional[int] = None,
        maxOutputTokens: Optional[int] = None,
        stopSequences: Optional[List[str]] = None,
        responseLogprobs: Optional[bool] = None,
        logprobs: Optional[int] = None,
        presencePenalty: Optional[float] = None,
        frequencyPenalty: Optional[float] = None,
        seed: Optional[int] = None,
        responseMimeType: Optional[str] = None,
        responseSchema: Optional[SchemaUnion] = None,
        routingConfig: Optional[GenerationConfigRoutingConfig] = None,
        modelSelectionConfig: Optional[ModelSelectionConfig] = None,
        responseModalities: Optional[List[str]] = None,
        mediaResolution: Optional[MediaResolution] = None,
        speechConfig: Optional[SpeechConfigUnion] = None,
        audioTimestamp: Optional[bool] = None,
        thinkingConfig: Optional[ThinkingConfig] = None,
    ):
        self.temperature = temperature
        self.topP = topP
        self.topK = topK
        self.candidateCount = candidateCount
        self.maxOutputTokens = maxOutputTokens
        self.stopSequences = stopSequences
        self.responseLogprobs = responseLogprobs
        self.logprobs = logprobs
        self.presencePenalty = presencePenalty
        self.frequencyPenalty = frequencyPenalty
        self.seed = seed
        self.responseMimeType = responseMimeType
        self.responseSchema = responseSchema
        self.routingConfig = routingConfig
        self.modelSelectionConfig = modelSelectionConfig
        self.responseModalities = responseModalities
        self.mediaResolution = mediaResolution
        self.speechConfig = speechConfig
        self.audioTimestamp = audioTimestamp
        self.thinkingConfig = thinkingConfig


class CaGenerateContentResponse:
    """CA 生成内容响应接口"""
    def __init__(self, response: VertexGenerateContentResponse):
        self.response = response


class VertexGenerateContentResponse:
    """Vertex 生成内容响应接口"""
    def __init__(
        self,
        candidates: List[Candidate],
        automaticFunctionCallingHistory: Optional[List[Content]] = None,
        promptFeedback: Optional[GenerateContentResponsePromptFeedback] = None,
        usageMetadata: Optional[GenerateContentResponseUsageMetadata] = None,
    ):
        self.candidates = candidates
        self.automaticFunctionCallingHistory = automaticFunctionCallingHistory
        self.promptFeedback = promptFeedback
        self.usageMetadata = usageMetadata


class CaCountTokenRequest:
    """CA 计数令牌请求接口"""
    def __init__(self, request: VertexCountTokenRequest):
        self.request = request


class VertexCountTokenRequest:
    """Vertex 计数令牌请求接口"""
    def __init__(self, model: str, contents: List[Content]):
        self.model = model
        self.contents = contents


class CaCountTokenResponse:
    """CA 计数令牌响应接口"""
    def __init__(self, totalTokens: int):
        self.totalTokens = totalTokens


def to_count_token_request(req: CountTokensParameters) -> CaCountTokenRequest:
    """将 CountTokensParameters 转换为 CaCountTokenRequest"""
    return CaCountTokenRequest(
        request=VertexCountTokenRequest(
            model='models/' + req.model,
            contents=to_contents(req.contents),
        )
    )


def from_count_token_response(res: CaCountTokenResponse) -> CountTokensResponse:
    """将 CaCountTokenResponse 转换为 CountTokensResponse"""
    return CountTokensResponse(totalTokens=res.totalTokens)


def to_generate_content_request(
    req: GenerateContentParameters,
    user_prompt_id: str,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> CAGenerateContentRequest:
    """将 GenerateContentParameters 转换为 CAGenerateContentRequest"""
    return CAGenerateContentRequest(
        model=req.model,
        project=project,
        user_prompt_id=user_prompt_id,
        request=to_vertex_generate_content_request(req, session_id),
    )


def from_generate_content_response(res: CaGenerateContentResponse) -> GenerateContentResponse:
    """将 CaGenerateContentResponse 转换为 GenerateContentResponse"""
    inres = res.response
    out = GenerateContentResponse()
    out.candidates = inres.candidates
    out.automaticFunctionCallingHistory = inres.automaticFunctionCallingHistory
    out.promptFeedback = inres.promptFeedback
    out.usageMetadata = inres.usageMetadata
    return out


def to_vertex_generate_content_request(
    req: GenerateContentParameters,
    session_id: Optional[str] = None,
) -> VertexGenerateContentRequest:
    """将 GenerateContentParameters 转换为 VertexGenerateContentRequest"""
    return VertexGenerateContentRequest(
        contents=to_contents(req.contents),
        systemInstruction=maybe_to_content(req.config.systemInstruction),
        cachedContent=req.config.cachedContent,
        tools=req.config.tools,
        toolConfig=req.config.toolConfig,
        labels=req.config.labels,
        safetySettings=req.config.safetySettings,
        generationConfig=to_vertex_generation_config(req.config),
        session_id=session_id,
    )


def to_contents(contents: ContentListUnion) -> List[Content]:
    """将 ContentListUnion 转换为 Content 列表"""
    if isinstance(contents, list):
        # 处理 Content[] 或 PartsUnion[]
        return [to_content(content) for content in contents]
    # 处理单个 Content 或 PartsUnion
    return [to_content(contents)]


def maybe_to_content(content: Optional[ContentUnion]) -> Optional[Content]:
    """将可选的 ContentUnion 转换为可选的 Content"""
    if content is None:
        return None
    return to_content(content)


def to_content(content: ContentUnion) -> Content:
    """将 ContentUnion 转换为 Content"""
    if isinstance(content, list):
        # 处理 PartsUnion[]
        return {
            'role': 'user',
            'parts': to_parts(content),
        }
    if isinstance(content, str):
        # 处理字符串
        return {
            'role': 'user',
            'parts': [{'text': content}]
        }
    if 'parts' in content:
        # 已经是 Content 类型
        return content
    # 处理单个 Part
    return {
        'role': 'user',
        'parts': [content]
    }


def to_parts(parts: List[PartUnion]) -> List[Part]:
    """将 PartUnion 列表转换为 Part 列表"""
    return [to_part(part) for part in parts]


def to_part(part: PartUnion) -> Part:
    """将 PartUnion 转换为 Part"""
    if isinstance(part, str):
        # 处理字符串
        return {'text': part}
    return part


def to_vertex_generation_config(
    config: Optional[GenerateContentConfig]
) -> Optional[VertexGenerationConfig]:
    """将 GenerateContentConfig 转换为 VertexGenerationConfig"""
    if config is None:
        return None
    return VertexGenerationConfig(
        temperature=config.temperature,
        topP=config.topP,
        topK=config.topK,
        candidateCount=config.candidateCount,
        maxOutputTokens=config.maxOutputTokens,
        stopSequences=config.stopSequences,
        responseLogprobs=config.responseLogprobs,
        logprobs=config.logprobs,
        presencePenalty=config.presencePenalty,
        frequencyPenalty=config.frequencyPenalty,
        seed=config.seed,
        responseMimeType=config.responseMimeType,
        responseSchema=config.responseSchema,
        routingConfig=config.routingConfig,
        modelSelectionConfig=config.modelSelectionConfig,
        responseModalities=config.responseModalities,
        mediaResolution=config.mediaResolution,
        speechConfig=config.speechConfig,
        audioTimestamp=config.audioTimestamp,
        thinkingConfig=config.thinkingConfig,)