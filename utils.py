"""
工具函数：重试机制、计时、异常包装等
"""

import time
import random
import functools
from typing import Callable, TypeVar, Any
from logger_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    non_retryable_exceptions: tuple = (ValueError, TypeError),
):
    """
    带指数退避的重试装饰器

    :param max_retries:    最大重试次数（不含首次执行）
    :param base_delay:     基础延迟秒数，每次重试延迟 = base * 2^attempt + jitter
    :param max_delay:      延迟上限秒数
    :param retryable_exceptions: 可重试的异常类型
    :param non_retryable_exceptions: 不应重试的异常类型（优先于 retryable）
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except non_retryable_exceptions:
                    # 不可重试异常，直接抛出
                    raise
                except retryable_exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = min(
                            base_delay * (2 ** attempt) + random.uniform(0, 0.5),
                            max_delay,
                        )
                        logger.warning(
                            "%s 第 %d/%d 次失败（%s），%.1fs 后重试...",
                            func.__name__, attempt + 1, max_retries, e, delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "%s 已重试 %d 次，全部失败: %s",
                            func.__name__, max_retries, e,
                        )
            # 所有重试耗尽
            raise last_exc  # type: ignore[misc]

        return wrapper
    return decorator


def safe_str(obj: Any, max_len: int = 200) -> str:
    """安全地将对象转为字符串，限制长度"""
    s = str(obj)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s
