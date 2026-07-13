"""
错误恢复 — 三种路径：截断升级 / 压缩重试 / 退避换模型
适配 OpenAI API 的 finish_reason 和 choice 结构
"""

import time, random
from dataclasses import dataclass
from .config import MODEL, FALLBACK_MODEL, ESCALATED_MAX_TOKENS, MAX_RECOVERY_RETRIES, MAX_RETRIES, BASE_DELAY_MS


@dataclass
class RecoveryState:
    has_escalated: bool = False
    recovery_count: int = 0
    has_compacted: bool = False
    consecutive_529: int = 0
    current_model: str = MODEL


def retry_delay(attempt: int, retry_after: float = None) -> float:
    """指数退避 + 抖动"""
    if retry_after and retry_after > 0:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000.0
    return base + random.uniform(0, base * 0.25)


def classify_error(error: Exception) -> str:
    s = str(error).lower()
    if "prompt_too_long" in s or "context_length" in s or "maximum context" in s:
        return "prompt_too_long"
    if "rate_limit" in s or "429" in s:
        return "rate_limit"
    if "overloaded" in s or "529" in s or "server_error" in s or "500" in s:
        return "overloaded"
    return "unknown"


def is_prompt_too_long(error: Exception) -> bool:
    return classify_error(error) == "prompt_too_long"


def handle_truncation(choice, messages: list, state: RecoveryState, max_tokens: int) -> tuple:
    """路径 1: 截断恢复 (finish_reason == 'length') → (messages, max_tokens, should_continue)"""
    if not state.has_escalated:
        state.has_escalated = True
        return messages, ESCALATED_MAX_TOKENS, True
    msg = {"role": "assistant", "content": choice.message.content or ""}
    if choice.message.tool_calls:
        msg["tool_calls"] = [tc.model_dump() for tc in choice.message.tool_calls]
    messages.append(msg)
    if state.recovery_count < MAX_RECOVERY_RETRIES:
        messages.append({"role": "user", "content":
            "输出长度已达上限。直接继续，不要道歉，不要重复。"})
        state.recovery_count += 1
        return messages, max_tokens, True
    return messages, max_tokens, False


def handle_too_long(messages: list, state: RecoveryState, client) -> tuple:
    """路径 2: 上下文超限 → (messages, should_retry)"""
    if not state.has_compacted:
        from .context import reactive_compact
        messages = reactive_compact(messages, client)
        state.has_compacted = True
        return messages, True
    return messages, False


def with_retry(fn, state: RecoveryState):
    """路径 3: 限流/过载退避重试"""
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            et = classify_error(e)
            if et == "rate_limit":
                delay = retry_delay(attempt)
                print(f"  [重试] 限流，等待 {delay:.1f}s ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)
            elif et == "overloaded":
                state.consecutive_529 += 1
                if state.consecutive_529 >= 3 and FALLBACK_MODEL:
                    print(f"  [重试] 切换到 {FALLBACK_MODEL}")
                    state.current_model = FALLBACK_MODEL
                    state.consecutive_529 = 0
                delay = retry_delay(attempt)
                print(f"  [重试] 服务过载，等待 {delay:.1f}s ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(f"重试次数已达上限 ({MAX_RETRIES})")
