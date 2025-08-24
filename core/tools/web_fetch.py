import os
import re
import json
import asyncio
import aiohttp
import ipaddress
from typing import Dict, List, Optional, Any, Tuple, Union
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# 假设这些是已存在的模块，根据实际情况调整导入
from ..utils.config import Config
from ..utils.logger import Logger
from ..utils.gemini_client import GeminiClient
from ..utils.private_ip_detector import PrivateIPDetector
from ..utils.schema_validator import SchemaValidator
from .tool import BaseTool, ToolResult,ToolCallConfirmationDetails,ToolConfirmationOutcome,Icon

URL_FETCH_TIMEOUT_MS = 10000
MAX_CONTENT_LENGTH = 100000

# Helper function to extract URLs from a string
def extract_urls(text: str) -> List[str]:
    url_regex = r"(https?:\\/\\/[^\\s]+)"
    return re.findall(url_regex, text) or []

# Interfaces for grounding metadata (similar to web-search.ts)
class GroundingChunkWeb(TypedDict, total=False):
    uri: str
    title: str

class GroundingChunkItem(TypedDict, total=False):
    web: GroundingChunkWeb

class GroundingSupportSegment(TypedDict):
    startIndex: int
    endIndex: int
    text: Optional[str]

class GroundingSupportItem(TypedDict, total=False):
    segment: GroundingSupportSegment
    groundingChunkIndices: List[int]

class WebFetchToolParams:
    url:str
    prompt:str

class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetches content from provided URLs and processes it"
    params_schema = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5
            },
            "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 30000},
            "include_raw_content": {"type": "boolean"},
            "include_html_content": {"type": "boolean"},
            "extract_images": {"type": "boolean"}
        },
        "required": ["urls"]
    }

    def __init__(self, config: Config):
        super().__init__(config)
        self.validator = SchemaValidator()
        self.gemini_client = GeminiClient(config)
        self.timeout_ms = config.web_fetch_timeout_ms or 15000

    async def call(self, params: WebFetchToolParams) -> WebFetchResult:
        # Validate parameters
        self.validator.validate(params, self.params_schema)

        urls = params["urls"]
        timeout_ms = params.get("timeout_ms", self.timeout_ms)
        include_raw_content = params.get("include_raw_content", False)
        include_html_content = params.get("include_html_content", False)
        extract_images = params.get("extract_images", False)

        contents: List[WebFetchContent] = []
        grounding_chunks: List[Dict[str, Any]] = []
        grounding_support: List[Dict[str, Any]] = []

        for url in urls:
            try:
                # Extract domain and check for private IP
                match = re.search(r"https?://([^/]+)", url)
                if not match:
                    contents.append({
                        "url": url,
                        "error": "Invalid URL format"
                    })
                    continue

                domain = match.group(1)
                # In a real implementation, you would resolve the domain to IP
                # For simplicity, we'll skip that step here

                # Fetch content with timeout
                timeout = timeout_ms / 1000
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status != 200:
                            contents.append({
                                "url": url,
                                "error": f"HTTP error: {response.status}"
                            })
                            continue

                        content_type = response.headers.get("Content-Type", "")
                        raw_content = await response.text()

                        # Process based on content type
                        text_content = ""
                        html_content = ""
                        images = []

                        if "text/html" in content_type:
                            html_content = raw_content
                            soup = BeautifulSoup(raw_content, "html.parser")
                            text_content = soup.get_text(separator="\n", strip=True)

                            if extract_images:
                                for img in soup.find_all("img"):
                                    img_url = img.get("src")
                                    if img_url:
                                        # Convert relative URLs to absolute
                                        if not img_url.startswith("http"):
                                            from urllib.parse import urljoin
                                            img_url = urljoin(url, img_url)
                                        images.append(img_url)
                        else:
                            text_content = raw_content

                        # Prepare result
                        result: WebFetchContent = {
                            "url": url,
                            "text": text_content
                        }

                        if include_raw_content:
                            result["raw_content"] = raw_content

                        if include_html_content and html_content:
                            result["html_content"] = html_content

                        if extract_images and images:
                            result["images"] = images

                        contents.append(result)

                        # Add grounding chunks
                        chunk_index = len(grounding_chunks)
                        grounding_chunks.append({
                            "web": {
                                "uri": url,
                                "title": ""  # In a real implementation, extract title from HTML
                            }
                        })

                        # Add grounding support
                        if text_content:
                            grounding_support.append({
                                "segment": {
                                    "startIndex": 0,
                                    "endIndex": len(text_content),
                                    "text": text_content[:100] + ("..." if len(text_content) > 100 else "")
                                },
                                "groundingChunkIndices": [chunk_index]
                            })

            except asyncio.TimeoutError:
                contents.append({
                    "url": url,
                    "error": f"Request timed out after {timeout_ms}ms"
                })
            except Exception as e:
                contents.append({
                    "url": url,
                    "error": f"Error fetching content: {str(e)}"
                })

        return {
            "contents": contents,
            "grounding_chunks": grounding_chunks,
            "grounding_support": grounding_support
        }