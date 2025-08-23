from typing import List, Optional, Dict, Any, Union
import asyncio
import json
from dataclasses import dataclass
from ..base_tool import BaseTool
from ..schema_validator import SchemaValidator
from ..config import Config
from google.genai.types import GroundingMetadata


@dataclass
class GroundingChunkWeb:
    url: str
    title: str
    snippet: str
    chunk_html: Optional[str] = None


@dataclass
class GroundingChunkItem:
    web: Optional[GroundingChunkWeb] = None


@dataclass
class WebSearchToolParams:
    query: str
    num_results: Optional[int] = 5
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None
    search_country: Optional[str] = None
    time_range: Optional[str] = None


@dataclass
class WebSearchToolResult:
    query: str
    results: List[Dict[str, Any]]
    grounding_metadata: Optional[Dict[str, Any]] = None


class WebSearchTool(BaseTool):
    def __init__(self, config: Config):
        super().__init__(config)
        self._schema_validator = SchemaValidator()
        # 注意：Python中没有private成员的概念，使用下划线表示私有
        self._gemini_client = None
        self._initialized = False

    async def _initialize(self):
        if self._initialized:
            return

        try:
            # 延迟导入以避免循环依赖
            from ...utils.gemini import get_gemini_client
            self._gemini_client = await get_gemini_client(self._config)
            self._initialized = True
        except ImportError as e:
            raise ImportError("Failed to import Gemini client. Please install the required dependencies.") from e
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Gemini client: {str(e)}") from e

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def display_name(self) -> str:
        return "Web Search"

    @property
    def description(self) -> str:
        return "Search the web for information using the Gemini API."

    @property
    def is_deprecated(self) -> bool:
        return False

    @property
    def is_unsafe(self) -> bool:
        return False

    async def _run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        await self._initialize()

        # 验证参数
        validated_params = self._schema_validator.validate(
            params,
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "num_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    "include_domains": {"type": "array", "items": {"type": "string"}},
                    "exclude_domains": {"type": "array", "items": {"type": "string"}},
                    "search_country": {"type": "string"},
                    "time_range": {"type": "string"}
                },
                "required": ["query"]
            }
        )

        query = validated_params["query"]
        num_results = validated_params.get("num_results", 5)
        include_domains = validated_params.get("include_domains")
        exclude_domains = validated_params.get("exclude_domains")
        search_country = validated_params.get("search_country")
        time_range = validated_params.get("time_range")

        try:
            search_args = {
                "query": query,
                "num_results": num_results
            }

            if include_domains:
                search_args["include_domains"] = include_domains
            if exclude_domains:
                search_args["exclude_domains"] = exclude_domains
            if search_country:
                search_args["search_country"] = search_country
            if time_range:
                search_args["time_range"] = time_range

            # 执行搜索
            search_result = await self._gemini_client.search(**search_args)

            # 处理结果
            results = []
            grounding_metadata = None

            if hasattr(search_result, "grounding_metadata"):
                grounding_metadata = self._convert_grounding_metadata(search_result.grounding_metadata)

            if hasattr(search_result, "results"):
                for item in search_result.results:
                    result_item = {
                        "title": item.title,
                        "url": item.url,
                        "snippet": item.snippet,
                        "metadata": item.metadata
                    }
                    results.append(result_item)

            return WebSearchToolResult(
                query=query,
                results=results,
                grounding_metadata=grounding_metadata
            ).__dict__

        except Exception as e:
            self._logger.error(f"Web search failed: {str(e)}")
            raise RuntimeError(f"Web search failed: {str(e)}") from e

    def _convert_grounding_metadata(self, metadata: GroundingMetadata) -> Dict[str, Any]:
        if not metadata or not hasattr(metadata, "chunks"):
            return None

        result = {"chunks": []}

        for chunk in metadata.chunks:
            chunk_item = {}
            if hasattr(chunk, "web") and chunk.web:
                web_chunk = chunk.web
                chunk_item["web"] = {
                    "url": web_chunk.url,
                    "title": web_chunk.title,
                    "snippet": web_chunk.snippet,
                    "chunkHtml": web_chunk.chunk_html
                }
            result["chunks"].append(chunk_item)

        return result

    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._run(params)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "is_deprecated": self.is_deprecated,
            "is_unsafe": self.is_unsafe
        }