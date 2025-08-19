from typing import Optional


# 测试工具，用于在单元测试中模拟429错误

# 全局变量
request_counter = 0
simulate_429_enabled = False
simulate_429_after_requests = 0
simulate_429_for_auth_type: Optional[str] = None
fallback_occurred = False


def should_simulate_429(auth_type: Optional[str] = None) -> bool:
    """
    检查当前请求是否应该模拟429错误

    Args:
        auth_type: 认证类型

    Returns:
        True 如果应该模拟429错误，否则 False
    """
    global request_counter

    if not simulate_429_enabled or fallback_occurred:
        return False

    # 如果设置了认证类型过滤器，只对该类型模拟
    if simulate_429_for_auth_type and auth_type != simulate_429_for_auth_type:
        return False

    request_counter += 1

    # 如果设置了after_requests，只在超过该数量后模拟
    if simulate_429_after_requests > 0:
        return request_counter > simulate_429_after_requests

    # 否则，对每个请求都模拟
    return True


def reset_request_counter() -> None:
    """重置请求计数器（对测试有用）"""
    global request_counter
    request_counter = 0


def disable_simulation_after_fallback() -> None:
    """成功回退后禁用429模拟"""
    global fallback_occurred
    fallback_occurred = True


def create_simulated_429_error() -> Exception:
    """创建模拟的429错误响应"""
    error = Exception('Rate limit exceeded (simulated)')
    # 为异常添加status属性
    setattr(error, 'status', 429)
    return error


def reset_simulation_state() -> None:
    """切换认证方法时重置模拟状态"""
    global fallback_occurred
    fallback_occurred = False
    reset_request_counter()


def set_simulate_429(
    enabled: bool,
    after_requests: int = 0,
    for_auth_type: Optional[str] = None
) -> None:
    """
    以编程方式启用/禁用429模拟（用于测试）

    Args:
        enabled: 是否启用模拟
        after_requests: 在多少次请求后开始模拟
        for_auth_type: 针对哪个认证类型进行模拟
    """
    global simulate_429_enabled, simulate_429_after_requests
    global simulate_429_for_auth_type, fallback_occurred

    simulate_429_enabled = enabled
    simulate_429_after_requests = after_requests
    simulate_429_for_auth_type = for_auth_type
    fallback_occurred = False  # 重新启用模拟时重置回退状态
    reset_request_counter()