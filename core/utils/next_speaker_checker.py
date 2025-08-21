import asyncio
from typing import List, Dict, Any, Optional, Union
from google.genai.types import Content, SchemaDict, Type

# 假设存在相应的配置和核心模块
from ..config.models import DEFAULT_GEMINI_FLASH_LITE_MODEL
from ..core.client import GeminiClient
from ..core.gemini_chat import GeminiChat
from .message_inspectors import is_function_response


CHECK_PROMPT = """Analyze *only* the content and structure of your immediately preceding response (your last turn in the conversation history). Based *strictly* on that response, determine who should logically speak next: the 'user' or the 'model' (you).
**Decision Rules (apply in order):**
1.  **Model Continues:** If your last response explicitly states an immediate next action *you* intend to take (e.g., "Next, I will...", "Now I'll process...", "Moving on to analyze...", indicates an intended tool call that didn't execute), OR if the response seems clearly incomplete (cut off mid-thought without a natural conclusion), then the **'model'** should speak next.
2.  **Question to User:** If your last response ends with a direct question specifically addressed *to the user*, then the **'user'** should speak next.
3.  **Waiting for User:** If your last response completed a thought, statement, or task *and* does not meet the criteria for Rule 1 (Model Continues) or Rule 2 (Question to User), it implies a pause expecting user input or reaction. In this case, the **'user'** should speak next."""

RESPONSE_SCHEMA: SchemaDict = {
    "type": Type.OBJECT,
    "properties": {
        "reasoning": {
            "type": Type.STRING,
            "description": "Brief explanation justifying the 'next_speaker' choice based *strictly* on the applicable rule and the content/structure of the preceding turn."
        },
        "next_speaker": {
            "type": Type.STRING,
            "enum": ["user", "model"],
            "description": "Who should speak next based *only* on the preceding turn and the decision rules"
        }
    },
    "required": ["reasoning", "next_speaker"]
}

class NextSpeakerResponse:
    """
    下一个发言者响应类
    """
    def __init__(self, reasoning: str, next_speaker: str):
        self.reasoning = reasoning
        self.next_speaker = next_speaker


async def check_next_speaker(
    chat: GeminiChat,
    gemini_client: GeminiClient,
    abort_signal: asyncio.Future
) -> Optional[NextSpeakerResponse]:
    """
    检查下一个应该发言的对象
    :param chat: GeminiChat对象
    :param gemini_client: GeminiClient对象
    :param abort_signal: 用于取消操作的信号
    :return: NextSpeakerResponse对象或None
    """
    # 获取经过整理的历史记录
    curated_history = chat.get_history(curated=True)

    # 确保有模型响应可供分析
    if not curated_history:
        # 如果历史记录为空，无法确定下一个发言者
        return None

    comprehensive_history = chat.get_history()
    # 作为额外的安全检查
    if not comprehensive_history:
        return None

    last_comprehensive_message = comprehensive_history[-1]

    # 如果最后一条消息是包含函数响应的用户消息，则模型应该接下来发言
    if last_comprehensive_message and is_function_response(last_comprehensive_message):
        return NextSpeakerResponse(
            reasoning="The last message was a function response, so the model should speak next.",
            next_speaker="model"
        )

    if (
        last_comprehensive_message
        and last_comprehensive_message.get("role") == "model"
        and last_comprehensive_message.get("parts")
        and len(last_comprehensive_message["parts"]) == 0
    ):
        last_comprehensive_message["parts"].append({"text": ""})
        return NextSpeakerResponse(
            reasoning="The last message was a filler model message with no content (nothing for user to act on), model should speak next.",
            next_speaker="model"
        )

    # 检查通过，继续进行LLM请求
    last_message = curated_history[-1]
    if not last_message or last_message.get("role") != "model":
        # 如果最后一轮不是来自模型或者历史记录为空，无法确定下一个发言者
        return None

    contents: List[Content] = [
        *curated_history,
        {"role": "user", "parts": [{"text": CHECK_PROMPT}]}
    ]

    try:
        parsed_response = await gemini_client.generate_json(
            contents,
            RESPONSE_SCHEMA,
            abort_signal,
            DEFAULT_GEMINI_FLASH_LITE_MODEL
        )

        if (
            parsed_response
            and "next_speaker" in parsed_response
            and parsed_response["next_speaker"] in ["user", "model"]
        ):
            return NextSpeakerResponse(
                reasoning=parsed_response.get("reasoning", ""),
                next_speaker=parsed_response["next_speaker"]
            )
        return None
    except Exception as e:
        print(f"Failed to talk to Gemini endpoint when seeing if conversation should continue. {e}")
        return None