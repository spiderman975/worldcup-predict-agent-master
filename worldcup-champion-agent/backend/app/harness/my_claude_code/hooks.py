"""
Hook 事件系统
4 个扩展点：UserPromptSubmit / PreToolUse / PostToolUse / Stop
挂在循环上，不写进循环里
"""

from typing import Callable, Any

EVENTS = ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
_hooks: dict[str, list[Callable]] = {e: [] for e in EVENTS}


def register_hook(event: str, callback: Callable) -> None:
    """注册 Hook 回调"""
    if event not in EVENTS:
        raise ValueError(f"未知事件: {event}，可选: {EVENTS}")
    _hooks[event].append(callback)


def trigger_hooks(event: str, *args, **kwargs) -> Any:
    """触发事件，返回第一个非 None 结果（拦截），否则 None"""
    for cb in _hooks.get(event, []):
        result = cb(*args, **kwargs)
        if result is not None:
            return result
    return None


def clear_hooks(event: str = None) -> None:
    """清除指定或全部 Hook"""
    if event:
        _hooks.setdefault(event, []).clear()
    else:
        for e in EVENTS:
            _hooks[e].clear()


def list_hooks() -> dict[str, int]:
    return {e: len(cbs) for e, cbs in _hooks.items()}
