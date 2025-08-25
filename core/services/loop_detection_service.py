import hashlib
import json
from typing import Dict, List, Optional, Any, Union, Set
import asyncio
from dataclasses import dataclass
from enum import Enum

# 假设以下是从其他文件导入的类和类型
def logLoopDetected(config, loop_event):
    # 实现日志记录逻辑
    pass

class GeminiEventType(Enum):
    ToolCallRequest = 1
    Content = 2
    # 其他事件类型...

class ServerGeminiStreamEvent:
    def __init__(self, type: GeminiEventType, value: Any):
        self.type = type
        self.value = value

class LoopType(Enum):
    CONSECUTIVE_IDENTICAL_TOOL_CALLS = 1
    CHANTING_IDENTICAL_SENTENCES = 2
    LLM_DETECTED_LOOP = 3

class LoopDetectedEvent:
    def __init__(self, loop_type: LoopType, prompt_id: str):
        self.loop_type = loop_type
        self.prompt_id = prompt_id

class Config:
    def __init__(self):
        # 配置初始化
        self.debug_mode = False
        # 其他配置...

    def getGeminiClient(self):
        # 返回 Gemini 客户端实例
        return GeminiClient()

    def getDebugMode(self):
        return self.debug_mode

class GeminiClient:
    def getHistory(self):
        # 返回历史记录
        return []

    async def generateJson(self, contents, schema, signal, model):
        # 实现生成 JSON 的逻辑
        return {'reasoning': 'No loop detected', 'confidence': 0.0}

# 常量定义
TOOL_CALL_LOOP_THRESHOLD = 5
CONTENT_LOOP_THRESHOLD = 10
CONTENT_CHUNK_SIZE = 50
MAX_HISTORY_LENGTH = 1000
# 当请求LLM检查循环时，要包含在历史记录中的最近对话轮次数量
LLM_LOOP_CHECK_HISTORY_COUNT = 20
# 在基于LLM的循环检查被激活之前，单个提示中必须经过的轮次数量。
LLM_CHECK_AFTER_TURNS = 30
# 执行基于LLM的循环检查的默认间隔（以轮次数量计）。此值会根据LLM的置信度动态调整。
DEFAULT_LLM_CHECK_INTERVAL = 3
# 基于LLM的循环检查的最小间隔。当循环置信度高时使用，以便更频繁地检查。
MIN_LLM_CHECK_INTERVAL = 5
# 基于LLM的循环检查的最大间隔。当循环置信度低时使用，以便减少检查频率。
MAX_LLM_CHECK_INTERVAL = 15
# 用于检测和防止AI响应中无限循环的服务。监控工具调用重复和内容句子重复。
DEFAULT_GEMINI_FLASH_MODEL = "gemini-flash"

class LoopDetectionService:
    def __init__(self, config: Config):
        self.config = config
        self.prompt_id = ''

        # 工具调用跟踪
        self.last_tool_call_key: Optional[str] = None
        self.tool_call_repetition_count: int = 0

        # 内容流跟踪
        self.stream_content_history = ''
        self.content_stats: Dict[str, List[int]] = {}  # hash -> list of indices
        self.last_content_index = 0
        self.loop_detected = False
        self.in_code_block = False

        # LLM 循环跟踪
        self.turns_in_current_prompt = 0
        self.llm_check_interval = DEFAULT_LLM_CHECK_INTERVAL
        self.last_check_turn = 0

    def get_tool_call_key(self, tool_call: Dict[str, Any]) -> str:
        name = tool_call['name']
        args = tool_call['args']
        args_string = json.dumps(args, sort_keys=True)
        key_string = f"{name}:{args_string}"
        return hashlib.sha256(key_string.encode()).hexdigest()

    def add_and_check(self, event: ServerGeminiStreamEvent) -> bool:
        if self.loop_detected:
            return True

        if event.type == GeminiEventType.ToolCallRequest:
            # 工具调用之间重置内容跟踪
            self.reset_content_tracking()
            self.loop_detected = self.check_tool_call_loop(event.value)
        elif event.type == GeminiEventType.Content:
            self.loop_detected = self.check_content_loop(event.value)

        return self.loop_detected

    async def turn_started(self, signal) -> bool:
        self.turns_in_current_prompt += 1

        if (
            self.turns_in_current_prompt >= LLM_CHECK_AFTER_TURNS
            and self.turns_in_current_prompt - self.last_check_turn >= self.llm_check_interval
        ):
            self.last_check_turn = self.turns_in_current_prompt
            return await self.check_for_loop_with_llm(signal)

        return False

    def check_tool_call_loop(self, tool_call: Dict[str, Any]) -> bool:
        key = self.get_tool_call_key(tool_call)
        if self.last_tool_call_key == key:
            self.tool_call_repetition_count += 1
        else:
            self.last_tool_call_key = key
            self.tool_call_repetition_count = 1

        if self.tool_call_repetition_count >= TOOL_CALL_LOOP_THRESHOLD:
            logLoopDetected(
                self.config,
                LoopDetectedEvent(
                    LoopType.CONSECUTIVE_IDENTICAL_TOOL_CALLS,
                    self.prompt_id
                )
            )
            return True
        return False

    def check_content_loop(self, content: str) -> bool:
        # 检测代码块中的重复内容可能导致误报，因此在代码块内暂时禁用循环检测
        num_fences = content.count('```')
        if num_fences:
            # 检测到代码围栏时重置跟踪
            self.reset_content_tracking()

        was_in_code_block = self.in_code_block
        self.in_code_block = self.in_code_block if num_fences % 2 == 0 else not self.in_code_block
        if was_in_code_block:
            return False

        self.stream_content_history += content

        self.truncate_and_update()
        return self.analyze_content_chunks_for_loop()

    def truncate_and_update(self) -> None:
        if len(self.stream_content_history) <= MAX_HISTORY_LENGTH:
            return

        # 计算需要从开头移除的内容量
        truncation_amount = len(self.stream_content_history) - MAX_HISTORY_LENGTH
        self.stream_content_history = self.stream_content_history[truncation_amount:]
        self.last_content_index = max(0, self.last_content_index - truncation_amount)

        # 更新所有存储的块索引以适应截断
        for hash_key, old_indices in list(self.content_stats.items()):
            adjusted_indices = [
                index - truncation_amount
                for index in old_indices
                if index - truncation_amount >= 0
            ]

            if adjusted_indices:
                self.content_stats[hash_key] = adjusted_indices
            else:
                del self.content_stats[hash_key]

    def analyze_content_chunks_for_loop(self) -> bool:
        while self.has_more_chunks_to_process():
            # 提取当前文本块
            current_chunk = self.stream_content_history[
                self.last_content_index : self.last_content_index + CONTENT_CHUNK_SIZE
            ]
            chunk_hash = hashlib.sha256(current_chunk.encode()).hexdigest()

            if self.is_loop_detected_for_chunk(current_chunk, chunk_hash):
                logLoopDetected(
                    self.config,
                    LoopDetectedEvent(
                        LoopType.CHANTING_IDENTICAL_SENTENCES,
                        self.prompt_id
                    )
                )
                return True

            # 移动到滑动窗口的下一个位置
            self.last_content_index += 1

        return False

    def has_more_chunks_to_process(self) -> bool:
        return self.last_content_index + CONTENT_CHUNK_SIZE <= len(self.stream_content_history)

    def is_loop_detected_for_chunk(self, chunk: str, hash_key: str) -> bool:
        existing_indices = self.content_stats.get(hash_key)

        if not existing_indices:
            self.content_stats[hash_key] = [self.last_content_index]
            return False

        if not self.is_actual_content_match(chunk, existing_indices[0]):
            return False

        existing_indices.append(self.last_content_index)

        if len(existing_indices) < CONTENT_LOOP_THRESHOLD:
            return False

        # 分析最近的出现次数，看它们是否紧密聚集
        recent_indices = existing_indices[-CONTENT_LOOP_THRESHOLD:]
        total_distance = recent_indices[-1] - recent_indices[0]
        average_distance = total_distance / (CONTENT_LOOP_THRESHOLD - 1)
        max_allowed_distance = CONTENT_CHUNK_SIZE * 1.5

        return average_distance <= max_allowed_distance

    def is_actual_content_match(self, current_chunk: str, original_index: int) -> bool:
        original_chunk = self.stream_content_history[
            original_index : original_index + CONTENT_CHUNK_SIZE
        ]
        return original_chunk == current_chunk

    async def check_for_loop_with_llm(self, signal) -> bool:
        recent_history = self.config.getGeminiClient().getHistory()[-LLM_LOOP_CHECK_HISTORY_COUNT:]

        prompt = ("You are a sophisticated AI diagnostic agent specializing in identifying when a conversational AI is stuck in an unproductive state. Your task is to analyze the provided conversation history and determine if the assistant has ceased to make meaningful progress.\n\n"
                  "An unproductive state is characterized by one or more of the following patterns over the last 5 or more assistant turns:\n\n"
                  "Repetitive Actions: The assistant repeats the same tool calls or conversational responses a decent number of times. This includes simple loops (e.g., tool_A, tool_A, tool_A) and alternating patterns (e.g., tool_A, tool_B, tool_A, tool_B, ...).\n\n"
                  "Cognitive Loop: The assistant seems unable to determine the next logical step. It might express confusion, repeatedly ask the same questions, or generate responses that don't logically follow from the previous turns, indicating it's stuck and not advancing the task.\n\n"
                  "Crucially, differentiate between a true unproductive state and legitimate, incremental progress."
                  "For example, a series of 'tool_A' or 'tool_B' tool calls that make small, distinct changes to the same file (like adding docstrings to functions one by one) is considered forward progress and is NOT a loop. A loop would be repeatedly replacing the same text with the same content, or cycling between a small set of files with no net change.\n\n"
                  "Please analyze the conversation history to determine the possibility that the conversation is stuck in a repetitive, non-productive state.")

        contents = [*recent_history, {'role': 'user', 'parts': [{'text': prompt}]}]
        schema = {
            'type': 'object',
            'properties': {
                'reasoning': {
                    'type': 'string',
                    'description': 'Your reasoning on if the conversation is looping without forward progress.'
                },
                'confidence': {
                    'type': 'number',
                    'description': 'A number between 0.0 and 1.0 representing your confidence that the conversation is in an unproductive state.'
                }
            },
            'required': ['reasoning', 'confidence']
        }

        try:
            result = await self.config.getGeminiClient().generateJson(
                contents, schema, signal, DEFAULT_GEMINI_FLASH_MODEL
            )
        except Exception as e:
            # 发生异常时，视为无循环
            if self.config.getDebugMode():
                print(f"Error in LLM loop check: {e}")
            return False

        if isinstance(result.get('confidence'), (int, float)):
            if result['confidence'] > 0.9:
                if isinstance(result.get('reasoning'), str) and result['reasoning']:
                    print(f"Warning: Possible loop detected: {result['reasoning']}")
                logLoopDetected(
                    self.config,
                    LoopDetectedEvent(LoopType.LLM_DETECTED_LOOP, self.prompt_id)
                )
                return True
            else:
                # 根据置信度动态调整检查间隔
                self.llm_check_interval = round(
                    MIN_LLM_CHECK_INTERVAL +
                    (MAX_LLM_CHECK_INTERVAL - MIN_LLM_CHECK_INTERVAL) *
                    (1 - result['confidence'])
                )
        return False

    def reset(self, prompt_id: str) -> None:
        self.prompt_id = prompt_id
        self.reset_tool_call_count()
        self.reset_content_tracking()
        self.reset_llm_check_tracking()
        self.loop_detected = False

    def reset_tool_call_count(self) -> None:
        self.last_tool_call_key = None
        self.tool_call_repetition_count = 0

    def reset_content_tracking(self, reset_history: bool = True) -> None:
        if reset_history:
            self.stream_content_history = ''
        self.content_stats.clear()
        self.last_content_index = 0

    def reset_llm_check_tracking(self) -> None:
        self.turns_in_current_prompt = 0
        self.llm_check_interval = DEFAULT_LLM_CHECK_INTERVAL
        self.last_check_turn = 0