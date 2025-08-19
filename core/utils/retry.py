import asyncio
import random
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar, Union

# 假设AuthType枚举在core模块中定义
class AuthType(Enum):
    LOGIN_WITH_GOOGLE = "LOGIN_WITH_GOOGLE"
    QWEN_OAUTH = "QWEN_OAUTH"

# 从quota_error_detection模块导入函数
# 注意：这里假设这些函数已经在相应的Python模块中实现
from .quota_error_detection import (
    is_pro_quota_exceeded_error,
    is_generic_quota_exceeded_error,
    is_qwen_quota_exceeded_error,
    is_qwen_throttling_error,
)


class HttpError(Exception):
    """HTTP错误异常类，包含状态码属性"""
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


T = TypeVar('T')


class RetryOptions:
    """重试配置选项类"""
    def __init__(
        self,
        max_attempts: int = 5,
        initial_delay_ms: int = 5000,
        max_delay_ms: int = 30000,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        on_persistent_429: Optional[Callable[[Optional[str], Optional[Any]],
                                            asyncio.Future[Union[str, bool, None]]]] = None,
        auth_type: Optional[str] = None,
    ):
        self.max_attempts = max_attempts
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        self.should_retry = should_retry or default_should_retry
        self.on_persistent_429 = on_persistent_429
        self.auth_type = auth_type


DEFAULT_RETRY_OPTIONS = RetryOptions()


def default_should_retry(error: Union[Exception, Any]) -> bool:
    """
    默认的重试判断函数。
    对429（请求过多）和5xx（服务器错误）错误进行重试。
    
    参数:
        error: 错误对象
    
    返回:
        如果是暂时性错误则返回True，否则返回False
    """
    # 检查常见的暂时性错误状态码
    if hasattr(error, 'status') and isinstance(error.status, int):
        status = error.status
        if status == 429 or (status >= 500 and status < 600):
            return True
    if isinstance(error, Exception) and error.args:
        error_message = str(error.args[0])
        if '429' in error_message:
            return True
        if any(f'5{i}' in error_message for i in range(10)):
            return True
    return False


async def delay(ms: int) -> None:
    """
    延迟执行指定的毫秒数
    
    参数:
        ms: 延迟的毫秒数
    """
    await asyncio.sleep(ms / 1000.0)


async def retry_with_backoff(
    fn: Callable[[], asyncio.Future[T]],
    options: Optional[Dict[str, Any]] = None,
) -> T:
    """
    使用指数退避和抖动策略重试异步函数
    
    参数:
        fn: 要重试的异步函数
        options: 可选的重试配置
    
    返回:
        函数成功执行的结果
    
    抛出:
        如果所有尝试都失败，则抛出最后遇到的错误
    """
    # 合并默认选项和用户提供的选项
    option_dict = {**vars(DEFAULT_RETRY_OPTIONS), **(options or {})}
    retry_options = RetryOptions(**option_dict)

    attempt = 0
    current_delay = retry_options.initial_delay_ms
    consecutive_429_count = 0

    while attempt < retry_options.max_attempts:
        attempt += 1
        try:
            return await fn()
        except Exception as error:
            error_status = get_error_status(error)

            # 首先检查Pro配额超额错误 - 对于OAuth用户立即回退
            if (
                error_status == 429
                and retry_options.auth_type == AuthType.LOGIN_WITH_GOOGLE.value
                and is_pro_quota_exceeded_error(error)
                and retry_options.on_persistent_429
            ):
                try:
                    fallback_model = await retry_options.on_persistent_429(
                        retry_options.auth_type, error
                    )
                    if fallback_model is not False and fallback_model is not None:
                        # 重置尝试计数器并使用新模型
                        attempt = 0
                        consecutive_429_count = 0
                        current_delay = retry_options.initial_delay_ms
                        continue
                    else:
                        # 回退处理程序返回null/false，表示不继续 - 停止重试过程
                        raise error
                except Exception as fallback_error:
                    # 如果回退失败，继续处理原始错误
                    print(f"回退到Flash模型失败: {fallback_error}")

            # 检查通用配额超额错误（但不是Pro，已在上面处理）- 对于OAuth用户立即回退
            if (
                error_status == 429
                and retry_options.auth_type == AuthType.LOGIN_WITH_GOOGLE.value
                and not is_pro_quota_exceeded_error(error)
                and is_generic_quota_exceeded_error(error)
                and retry_options.on_persistent_429
            ):
                try:
                    fallback_model = await retry_options.on_persistent_429(
                        retry_options.auth_type, error
                    )
                    if fallback_model is not False and fallback_model is not None:
                        # 重置尝试计数器并使用新模型
                        attempt = 0
                        consecutive_429_count = 0
                        current_delay = retry_options.initial_delay_ms
                        continue
                    else:
                        # 回退处理程序返回null/false，表示不继续 - 停止重试过程
                        raise error
                except Exception as fallback_error:
                    # 如果回退失败，继续处理原始错误
                    print(f"回退到Flash模型失败: {fallback_error}")

            # 检查Qwen OAuth配额超额错误 - 立即抛出不重试
            if (
                retry_options.auth_type == AuthType.QWEN_OAUTH.value
                and is_qwen_quota_exceeded_error(error)
            ):
                raise Exception(
                    "Qwen API配额已用完: 您的Qwen API配额已耗尽。请等待配额重置。"
                )

            # 跟踪连续的429错误，但对Qwen节流错误进行不同处理
            if error_status == 429:
                # 对于Qwen节流错误，我们仍然要跟踪它们以进行指数退避
                # 但不用于配额回退逻辑（因为Qwen没有模型回退）
                if (
                    retry_options.auth_type == AuthType.QWEN_OAUTH.value
                    and is_qwen_throttling_error(error)
                ):
                    # 跟踪429但重置连续计数以避免回退逻辑
                    consecutive_429_count = 0
                else:
                    consecutive_429_count += 1
            else:
                consecutive_429_count = 0

            # 如果我们有持续的429且有OAuth的回退回调
            if (
                consecutive_429_count >= 2
                and retry_options.on_persistent_429
                and retry_options.auth_type == AuthType.LOGIN_WITH_GOOGLE.value
            ):
                try:
                    fallback_model = await retry_options.on_persistent_429(
                        retry_options.auth_type, error
                    )
                    if fallback_model is not False and fallback_model is not None:
                        # 重置尝试计数器并使用新模型
                        attempt = 0
                        consecutive_429_count = 0
                        current_delay = retry_options.initial_delay_ms
                        continue
                    else:
                        # 回退处理程序返回null/false，表示不继续 - 停止重试过程
                        raise error
                except Exception as fallback_error:
                    # 如果回退失败，继续处理原始错误
                    print(f"回退到Flash模型失败: {fallback_error}")

            # 检查是否已用尽重试次数或不应重试
            if attempt >= retry_options.max_attempts or not retry_options.should_retry(error):
                raise error

            delay_duration_ms, delay_error_status = get_delay_duration_and_status(error)

            if delay_duration_ms > 0:
                # 尊重Retry-After头（如果存在且已解析）
                print(
                    f"尝试 {attempt} 失败，状态码 {delay_error_status or '未知'}。\ "
                    f"在显式延迟 {delay_duration_ms}ms 后重试...",
                    error
                )
                await delay(delay_duration_ms)
                # 为下一个潜在的非429错误或下次没有Retry-After时重置currentDelay
                current_delay = retry_options.initial_delay_ms
            else:
                # 回退到带抖动的指数退避
                log_retry_attempt(attempt, error, error_status)
                # 添加抖动：currentDelay的+/-30%
                jitter = current_delay * 0.3 * (random.random() * 2 - 1)
                delay_with_jitter = max(0, current_delay + jitter)
                await delay(delay_with_jitter)
                current_delay = min(retry_options.max_delay_ms, current_delay * 2)

    # 理论上由于catch块中的throw，这行代码应该无法到达
    # 为了类型安全和满足编译器要求而添加
    raise Exception("重试尝试已用尽")


def get_error_status(error: Union[Exception, Any]) -> Optional[int]:
    """
    从错误对象中提取HTTP状态码
    
    参数:
        error: 错误对象
    
    返回:
        HTTP状态码，如果未找到则返回None
    """
    if hasattr(error, 'status') and isinstance(error.status, int):
        return error.status
    # 检查error.response.status（在axios错误中常见）
    if hasattr(error, 'response') and error.response is not None:
        response = error.response
        if hasattr(response, 'status') and isinstance(response.status, int):
            return response.status
    return None


def get_retry_after_delay_ms(error: Union[Exception, Any]) -> int:
    """
    从错误对象的头中提取Retry-After延迟
    
    参数:
        error: 错误对象
    
    返回:
        延迟毫秒数，如果未找到或无效则返回0
    """
    if hasattr(error, 'response') and error.response is not None:
        response = error.response
        if hasattr(response, 'headers') and response.headers is not None:
            headers = response.headers
            retry_after_header = headers.get('retry-after')
            if retry_after_header:
                # 尝试解析为秒数
                try:
                    retry_after_seconds = int(retry_after_header)
                    return retry_after_seconds * 1000
                except ValueError:
                    # 尝试解析为HTTP日期
                    try:
                        retry_after_date = time.mktime(
                            time.strptime(retry_after_header, '%a, %d %b %Y %H:%M:%S %Z')
                        )
                        current_time = time.time()
                        return max(0, int((retry_after_date - current_time) * 1000))
                    except ValueError:
                        pass
    return 0


def get_delay_duration_and_status(error: Union[Exception, Any]) -> Dict[str, Any]:
    """
    根据错误确定延迟持续时间，优先考虑Retry-After头
    
    参数:
        error: 错误对象
    
    返回:
        包含延迟持续时间（毫秒）和错误状态的字典
    """
    error_status = get_error_status(error)
    delay_duration_ms = 0

    if error_status == 429:
        delay_duration_ms = get_retry_after_delay_ms(error)
    return {
        'delay_duration_ms': delay_duration_ms,
        'error_status': error_status
    }


def log_retry_attempt(
    attempt: int,
    error: Union[Exception, Any],
    error_status: Optional[int] = None,
) -> None:
    """
    当使用指数退避时记录重试尝试的消息
    
    参数:
        attempt: 当前尝试次数
        error: 导致重试的错误
        error_status: 错误的HTTP状态码（如果有）
    """
    if error_status:
        message = f"尝试 {attempt} 失败，状态码 {error_status}。使用退避策略重试..."
    else:
        message = f"尝试 {attempt} 失败。使用退避策略重试..."

    if error_status == 429:
        print(message, error)
    elif error_status and 500 <= error_status < 600:
        print(message, error)
    elif isinstance(error, Exception):
        # 处理可能没有状态但有消息的错误
        error_message = str(error.args[0])
        if '429' in error_message:
            print(
                f"尝试 {attempt} 失败，出现429错误（无Retry-After头）。使用退避策略重试...",
                error
            )
        elif any(f'5{i}' in error_message for i in range(10)):
            print(
                f"尝试 {attempt} 失败，出现5xx错误。使用退避策略重试...",
                error
            )
        else:
            print(message, error)  # 其他错误默认为warn
    else:
        print(message, error)  # 如果错误类型未知，默认为warn