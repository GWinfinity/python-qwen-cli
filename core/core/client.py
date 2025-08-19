import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Union, Callable, TypeVar, Generic

# 假设的导入，需要根据实际Python库调整
# 注意：这些导入可能需要替换为实际可用的Python库
from google.generativeai import (EmbedContentParameters, GenerateContentConfig,
                                Part, SchemaUnion, PartListUnion, Content, Tool,
                                GenerateContentResponse, FunctionDeclaration, Schema)
from .utils.get_folder_structure import get_folder_structure
from .core.turn import Turn, ServerGeminiStreamEvent, GeminiEventType, ChatCompressionInfo
from .config.config import Config
from .code_assist.types import UserTierId
from .core.prompts import get_core_system_prompt, get_compression_prompt
from .tools.read_many_files import ReadManyFilesTool
from .utils.generate_content_response_utilities import get_function_calls
from .utils.next_speaker_checker import check_next_speaker
from .utils.error_reporting import report_error
from .core.gemini_chat import GeminiChat
from .utils.retry import retry_with_backoff
from .utils.errors import get_error_message
from .utils.message_inspectors import is_function_response
from .core.token_limits import token_limit
from .core.content_generator import (
    AuthType, ContentGenerator, ContentGeneratorConfig, create_content_generator
)
from .services.loop_detection_service import LoopDetectionService
from .ide.ide_context import ide_context
from .telemetry.loggers import log_next_speaker_check
from .telemetry.types import NextSpeakerCheckEvent
from .config.models import DEFAULT_GEMINI_FLASH_MODEL

# 用于设置代理的库，根据实际情况调整
# 这里使用requests的代理设置方式作为示例
import requests


def is_thinking_supported(model: str) -> bool:
    if model.startswith('gemini-2.5'):
        return True
    return False


def find_index_after_fraction(history: List[Content], fraction: float) -> int:
    """
    Returns the index of the content after the fraction of the total characters in the history.
    Exported for testing purposes.
    """
    if fraction <= 0 or fraction >= 1:
        raise ValueError('Fraction must be between 0 and 1')

    content_lengths = [len(json.dumps(content)) for content in history]
    total_characters = sum(content_lengths)
    target_characters = total_characters * fraction

    characters_so_far = 0
    for i, length in enumerate(content_lengths):
        characters_so_far += length
        if characters_so_far >= target_characters:
            return i
    return len(content_lengths)


class GeminiClient:
    def __init__(self, config: Config):
        self.config = config
        self.chat: Optional[GeminiChat] = None
        self.content_generator: Optional[ContentGenerator] = None
        self.embedding_model: str = config.get_embedding_model()
        self.generate_content_config: GenerateContentConfig = {
            'temperature': 0,
            'top_p': 1,
        }
        self.session_turn_count = 0
        self.MAX_TURNS = 100
        self.COMPRESSION_TOKEN_THRESHOLD = 0.7
        self.COMPRESSION_PRESERVE_THRESHOLD = 0.3
        self.loop_detector = LoopDetectionService(config)
        self.last_prompt_id = config.get_session_id()

        # 设置代理
        proxy = config.get_proxy()
        if proxy:
            # 根据实际Python库调整代理设置
            # 这里以requests为例
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy
            # 如果使用其他HTTP客户端，如aiohttp，需要单独设置

    async def initialize(self, content_generator_config: ContentGeneratorConfig) -> None:
        self.content_generator = await create_content_generator(
            content_generator_config, self.config, self.config.get_session_id()
        )
        self.chat = await self.start_chat()

    def get_content_generator(self) -> ContentGenerator:
        if not self.content_generator:
            raise ValueError('Content generator not initialized')
        return self.content_generator

    def get_user_tier(self) -> Optional[UserTierId]:
        return self.content_generator.user_tier if self.content_generator else None

    async def add_history(self, content: Content) -> None:
        self.get_chat().add_history(content)

    def get_chat(self) -> GeminiChat:
        if not self.chat:
            raise ValueError('Chat not initialized')
        return self.chat

    def is_initialized(self) -> bool:
        return self.chat is not None and self.content_generator is not None

    def get_history(self) -> List[Content]:
        return self.get_chat().get_history()

    def set_history(self, history: List[Content]) -> None:
        self.get_chat().set_history(history)

    async def set_tools(self) -> None:
        tool_registry = await self.config.get_tool_registry()
        tool_declarations = tool_registry.get_function_declarations()
        tools: List[Tool] = [{'function_declarations': tool_declarations}]
        self.get_chat().set_tools(tools)

    async def reset_chat(self) -> None:
        self.chat = await self.start_chat()

    async def add_directory_context(self) -> None:
        if not self.chat:
            return

        self.get_chat().add_history({
            'role': 'user',
            'parts': [{'text': await self.get_directory_context()}]
        })

    async def get_directory_context(self) -> str:
        workspace_context = self.config.get_workspace_context()
        workspace_directories = workspace_context.get_directories()

        folder_structures = []
        for dir_path in workspace_directories:
            folder_structures.append(
                await get_folder_structure(dir_path, {
                    'file_service': self.config.get_file_service()
                })
            )

        folder_structure = '\n'.join(folder_structures)
        dir_list = '\n'.join([f'  - {dir_path}' for dir_path in workspace_directories])
        working_dir_preamble = f"I'm currently working in the following directories:\n{dir_list}\n Folder structures are as follows:\n{folder_structure}"
        return working_dir_preamble

    async def get_environment(self) -> List[Part]:
        today = datetime.now().strftime('%A, %B %d, %Y')
        platform = os.name

        workspace_context = self.config.get_workspace_context()
        workspace_directories = workspace_context.get_directories()

        folder_structures = []
        for dir_path in workspace_directories:
            folder_structures.append(
                await get_folder_structure(dir_path, {
                    'file_service': self.config.get_file_service()
                })
            )

        folder_structure = '\n'.join(folder_structures)

        if len(workspace_directories) == 1:
            working_dir_preamble = f"I'm currently working in the directory: {workspace_directories[0]}"
        else:
            dir_list = '\n'.join([f'  - {dir_path}' for dir_path in workspace_directories])
            working_dir_preamble = f"I'm currently working in the following directories:\n{dir_list}"

        context = f'''
  This is the Qwen Code. We are setting up the context for our chat.
  Today's date is {today}.
  My operating system is: {platform}
  {working_dir_preamble}
  Here is the folder structure of the current working directories:

  {folder_structure}
        '''.strip()

        initial_parts: List[Part] = [{'text': context}]
        tool_registry = await self.config.get_tool_registry()

        # Add full file context if the flag is set
        if self.config.get_full_context():
            try:
                read_many_files_tool = tool_registry.get_tool('read_many_files')
                if read_many_files_tool and isinstance(read_many_files_tool, ReadManyFilesTool):
                    # Read all files in the target directory
                    result = await read_many_files_tool.execute(
                        {
                            'paths': ['**/*'],  # Read everything recursively
                            'use_default_excludes': True  # Use default excludes
                        },
                        asyncio.TimeoutError(30000)  # 30 seconds timeout
                    )
                    if result.llm_content:
                        initial_parts.append({
                            'text': f'\n--- Full File Context ---{result.llm_content}'
                        })
                    else:
                        print('Full context requested, but read_many_files returned no content.')
                else:
                    print('Full context requested, but read_many_files tool not found.')
            except Exception as error:
                # Not using report_error here as it's a startup/config phase error
                print(f'Error reading full file context: {error}')
                initial_parts.append({
                    'text': '\n--- Error reading full file context ---'
                })

        return initial_parts

    async def start_chat(self, extra_history: Optional[List[Content]] = None) -> GeminiChat:
        env_parts = await self.get_environment()
        tool_registry = await self.config.get_tool_registry()
        tool_declarations = tool_registry.get_function_declarations()
        tools: List[Tool] = [{'function_declarations': tool_declarations}]
        history: List[Content] = [
            {
                'role': 'user',
                'parts': env_parts
            },
            {
                'role': 'model',
                'parts': [{'text': 'Got it. Thanks for the context!'}]
            },
            *(extra_history or [])
        ]
        try:
            user_memory = self.config.get_user_memory()
            system_instruction = get_core_system_prompt(user_memory)
            generate_content_config_with_thinking = (
                {
                    **self.generate_content_config,
                    'thinking_config': {
                        'include_thoughts': True
                    },
                } if is_thinking_supported(self.config.get_model())
                else self.generate_content_config
            )
            return GeminiChat(
                self.config,
                self.get_content_generator(),
                {
                    'system_instruction': system_instruction,
                    **generate_content_config_with_thinking,
                    'tools': tools
                },
                history
            )
        except Exception as error:
            await report_error(
                error,
                'Error initializing Gemini chat session.',
                history,
                'start_chat'
            )
            raise ValueError(f'Failed to initialize chat: {get_error_message(error)}')

    async def send_message_stream(
        self,
        request: PartListUnion,
        signal: asyncio.Future,
        prompt_id: str,
        turns: int = None,
        original_model: Optional[str] = None
    ) -> AsyncGenerator[ServerGeminiStreamEvent, Turn]:
        if turns is None:
            turns = self.MAX_TURNS

        if self.last_prompt_id != prompt_id:
            self.loop_detector.reset(prompt_id)
            self.last_prompt_id = prompt_id

        self.session_turn_count += 1
        max_session_turns = self.config.get_max_session_turns()
        if max_session_turns > 0 and self.session_turn_count > max_session_turns:
            yield {'type': GeminiEventType.MaxSessionTurns}
            return Turn(self.get_chat(), prompt_id)

        # Ensure turns never exceeds MAX_TURNS to prevent infinite loops
        bounded_turns = min(turns, self.MAX_TURNS)
        if not bounded_turns:
            return Turn(self.get_chat(), prompt_id)

        # Track the original model from the first call to detect model switching
        initial_model = original_model or self.config.get_model()

        compressed = await self.try_compress_chat(prompt_id)
        if compressed:
            yield {'type': GeminiEventType.ChatCompressed, 'value': compressed}

        # Check session token limit after compression using accurate token counting
        session_token_limit = self.config.get_session_token_limit()
        if session_token_limit > 0:
            # Get all the content that would be sent in an API call
            current_history = self.get_chat().get_history(true)
            user_memory = self.config.get_user_memory()
            system_prompt = get_core_system_prompt(user_memory)
            environment = await self.get_environment()

            # Create a mock request content to count total tokens
            mock_request_content = [
                {
                    'role': 'system',
                    'parts': [{'text': system_prompt}, *environment]
                },
                *current_history
            ]

            # Use the improved count_tokens method for accurate counting
            count_result = await self.get_content_generator().count_tokens({
                'model': self.config.get_model(),
                'contents': mock_request_content
            })
            total_request_tokens = count_result.get('total_tokens')

            if total_request_tokens is not None and total_request_tokens > session_token_limit:
                yield {
                    'type': GeminiEventType.SessionTokenLimitExceeded,
                    'value': {
                        'current_tokens': total_request_tokens,
                        'limit': session_token_limit,
                        'message': (
                            f'Session token limit exceeded: {total_request_tokens} tokens > {session_token_limit} limit. '
                            'Please start a new session or increase the sessionTokenLimit in your settings.json.'
                        )
                    }
                }
                return Turn(self.get_chat(), prompt_id)

        if self.config.get_ide_mode_feature() and self.config.get_ide_mode():
            ide_context_state = ide_context.get_ide_context()
            open_files = ide_context_state.get('workspace_state', {}).get('open_files', [])

            if open_files:
                context_parts: List[str] = []
                first_file = open_files[0]
                active_file = first_file if first_file.get('is_active') else None

                if active_file:
                    context_parts.append(
                        f'This is the file that the user is looking at:\n- Path: {active_file.get("path")}'
                    )
                    cursor = active_file.get('cursor')
                    if cursor:
                        context_parts.append(
                            f'This is the cursor position in the file:\n- Cursor Position: Line {cursor.get("line")}, Character {cursor.get("character")}'
                        )
                    selected_text = active_file.get('selected_text')
                    if selected_text:
                        context_parts.append(
                            f'This is the selected text in the file:\n- {selected_text}'
                        )

                other_open_files = open_files[1:] if active_file else open_files

                if other_open_files:
                    recent_files = '\n'.join([f'- {file.get("path")}' for file in other_open_files])
                    heading = (
                        'Here are some other files the user has open, with the most recent at the top:'
                        if active_file
                        else 'Here are some files the user has open, with the most recent at the top:'
                    )
                    context_parts.append(f'{heading}\n{recent_files}')

                if context_parts:
                    request = [
                        {'text': '\n'.join(context_parts)},
                        *(request if isinstance(request, list) else [request])
                    ]

        turn = Turn(self.get_chat(), prompt_id)

        loop_detected = await self.loop_detector.turn_started(signal)
        if loop_detected:
            yield {'type': GeminiEventType.LoopDetected}
            return turn

        result_stream = turn.run(request, signal)
        async for event in result_stream:
            if self.loop_detector.add_and_check(event):
                yield {'type': GeminiEventType.LoopDetected}
                return turn
            yield event

        if not turn.pending_tool_calls and signal and not signal.done():
            # Check if model was switched during the call (likely due to quota error)
            current_model = self.config.get_model()
            if current_model != initial_model:
                # Model was switched (likely due to quota error fallback)
                # Don't continue with recursive call to prevent unwanted Flash execution
                return turn

            next_speaker_check = await check_next_speaker(
                self.get_chat(), self, signal
            )
            log_next_speaker_check(
                self.config,
                NextSpeakerCheckEvent(
                    prompt_id,
                    str(turn.finish_reason) if turn.finish_reason else '',
                    next_speaker_check.get('next_speaker', '') if next_speaker_check else ''
                )
            )
            if next_speaker_check and next_speaker_check.get('next_speaker') == 'model':
                next_request = [{'text': 'Please continue.'}]
                # This recursive call's events will be yielded out, but the final
                # turn object will be from the top-level call.
                async for event in self.send_message_stream(
                    next_request,
                    signal,
                    prompt_id,
                    bounded_turns - 1,
                    initial_model
                ):
                    yield event

        return turn

    async def generate_json(
        self,
        contents: List[Content],
        schema: SchemaUnion,
        abort_signal: asyncio.Future,
        model: Optional[str] = None,
        config: GenerateContentConfig = None
    ) -> Dict[str, Any]:
        if config is None:
            config = {}

        # Use current model from config instead of hardcoded Flash model
        model_to_use = model or self.config.get_model() or DEFAULT_GEMINI_FLASH_MODEL
        try:
            user_memory = self.config.get_user_memory()
            system_prompt_mappings = self.config.get_system_prompt_mappings()
            system_instruction = get_core_system_prompt(user_memory, {
                'system_prompt_mappings': system_prompt_mappings
            })
            request_config = {
                'abort_signal': abort_signal,
                **self.generate_content_config,
                **config
            }

            # Convert schema to function declaration
            function_declaration: FunctionDeclaration = {
                'name': 'respond_in_schema',
                'description': 'Provide the response in provided schema',
                'parameters': schema 
            }

            tools: List[Tool] = [{
                'function_declarations': [function_declaration]
            }]

            async def api_call():
                return await self.get_content_generator().generate_content(
                    {
                        'model': model_to_use,
                        'config': {
                            **request_config,
                            'system_instruction': system_instruction,
                            'tools': tools
                        },
                        'contents': contents
                    },
                    self.last_prompt_id
                )

            result = await retry_with_backoff(api_call, {
                'on_persistent_429': lambda auth_type=None, error=None: self.handle_flash_fallback(auth_type, error),
                'auth_type': self.config.get_content_generator_config().get('auth_type') if self.config.get_content_generator_config() else None
            })
            function_calls = get_function_calls(result)
            if function_calls and len(function_calls) > 0:
                function_call = next((call for call in function_calls if call.get('name') == 'respond_in_schema'), None)
                if function_call and 'args' in function_call:
                    return function_call['args']
            return {}
        except Exception as error:
            if abort_signal.done() and abort_signal.exception() is not None:
                raise error

            # Avoid double reporting for the empty response case handled above
            if isinstance(error, Exception) and str(error) == 'API returned an empty response for generateJson.':
                raise error

            await report_error(
                error,
                'Error generating JSON content via API.',
                contents,
                'generateJson-api'
            )
            raise ValueError(f'Failed to generate JSON content: {get_error_message(error)}')

    async def generate_content(
        self,
        contents: List[Content],
        generation_config: GenerateContentConfig,
        abort_signal: asyncio.Future,
        model: Optional[str] = None
    ) -> GenerateContentResponse:
        model_to_use = model or self.config.get_model()
        config_to_use: GenerateContentConfig = {
            **self.generate_content_config,
            **generation_config
        }

        try:
            user_memory = self.config.get_user_memory()
            system_prompt_mappings = self.config.get_system_prompt_mappings()
            system_instruction = get_core_system_prompt(user_memory, {
                'system_prompt_mappings': system_prompt_mappings
            })

            request_config = {
                'abort_signal': abort_signal,
                **config_to_use,
                'system_instruction': system_instruction
            }

            async def api_call():
                return await self.get_content_generator().generate_content(
                    {
                        'model': model_to_use,
                        'config': request_config,
                        'contents': contents
                    },
                    self.last_prompt_id
                )

            result = await retry_with_backoff(api_call, {
                'on_persistent_429': lambda auth_type=None, error=None: self.handle_flash_fallback(auth_type, error),
                'auth_type': self.config.get_content_generator_config().get('auth_type') if self.config.get_content_generator_config() else None
            })
            return result
        except Exception as error:
            if abort_signal.done() and abort_signal.exception() is not None:
                raise error

            await report_error(
                error,
                f'Error generating content via API with model {model_to_use}.',
                {
                    'request_contents': contents,
                    'request_config': config_to_use
                },
                'generateContent-api'
            )
            raise ValueError(f'Failed to generate content with model {model_to_use}: {get_error_message(error)}')

    async def generate_embedding(self, texts: List[str]) -> List[List[float]]:
        if not texts or len(texts) == 0:
            return []
        embed_model_params: EmbedContentParameters = {
            'model': self.embedding_model,
            'contents': texts
        }

        embed_content_response = await self.get_content_generator().embed_content(embed_model_params)
        if not embed_content_response.get('embeddings') or len(embed_content_response['embeddings']) == 0:
            raise ValueError('No embeddings found in API response.')

        if len(embed_content_response['embeddings']) != len(texts):
            raise ValueError(
                f'API returned a mismatched number of embeddings. Expected {len(texts)}, got {len(embed_content_response["embeddings"])}.')

        embeddings = []
        for i, embedding in enumerate(embed_content_response['embeddings']):
            values = embedding.get('values')
            if not values or len(values) == 0:
                raise ValueError(f'API returned an empty embedding for input text at index {i}: 