"""
上下文管理 — 压缩管线 + transcript 持久化
四层压缩：budget → snip → micro → auto（便宜的先跑贵的后跑）
适配 OpenAI API 消息格式
"""

import json
from datetime import datetime
from pathlib import Path
from .config import (
    MODEL, MAX_MESSAGES, KEEP_RECENT_TOOL_RESULTS,
    TOOL_RESULT_BUDGET, CONTEXT_TOKEN_THRESHOLD,
    TRANSCRIPTS_DIR, TOOL_OUTPUTS_DIR,
)


def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, ensure_ascii=False)) // 4


# ==================== 辅助函数 ====================

def _has_tool_calls(msg):
    """检查 assistant 消息是否包含 tool_calls"""
    if msg.get("role") != "assistant":
        return False
    return bool(msg.get("tool_calls"))


def _is_tool_result(msg):
    """检查消息是否为 tool result"""
    return msg.get("role") == "tool"


# ==================== L1: snip — 裁中间旧对话 ====================

def snip_compact(messages: list, max_messages: int = MAX_MESSAGES) -> list:
    """消息数超阈值时裁掉中间，保留头 3 + 尾 N"""
    if len(messages) <= max_messages:
        return messages
    head_end, tail_start = 3, len(messages) - (max_messages - 3)
    # 保护 tool_calls + tool result 配对
    if head_end > 0 and _has_tool_calls(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result(messages[head_end]):
            head_end += 1
    if (tail_start > 0 and _is_tool_result(messages[tail_start])
            and tail_start > 0 and _has_tool_calls(messages[tail_start - 1])):
        tail_start -= 1
    n = tail_start - head_end
    placeholder = {"role": "user", "content": f"[已裁剪 {n} 条旧消息]"}
    return messages[:head_end] + [placeholder] + messages[tail_start:]


# ==================== L2: micro — 旧结果占位 ====================

def micro_compact(messages: list) -> list:
    """只保留最近 N 条 tool result 完整内容，旧的换占位符"""
    results = []
    for mi, msg in enumerate(messages):
        if msg.get("role") == "tool":
            results.append((mi, msg))
    if len(results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for _, msg in results[:-KEEP_RECENT_TOOL_RESULTS]:
        if len(str(msg.get("content", ""))) > 120:
            msg["content"] = "[旧工具结果已压缩，需要时重新执行。]"
    return messages


# ==================== L3: budget — 大结果落盘 ====================

def tool_result_budget(messages: list, max_bytes: int = TOOL_RESULT_BUDGET) -> list:
    """最近一批 tool result 超预算时，大的落盘只留预览"""
    if not messages:
        return messages
    # 找最后一组连续的 tool result 消息
    end = len(messages) - 1
    while end >= 0 and messages[end].get("role") != "tool":
        end -= 1
    if end < 0:
        return messages
    start = end
    while start >= 0 and messages[start].get("role") == "tool":
        start -= 1
    start += 1

    tool_msgs = [(i, messages[i]) for i in range(start, end + 1)]
    total = sum(len(str(m.get("content", ""))) for _, m in tool_msgs)
    if total <= max_bytes:
        return messages

    ranked = sorted(tool_msgs, key=lambda p: len(str(p[1].get("content", ""))), reverse=True)
    for idx, m in ranked:
        if total <= max_bytes:
            break
        raw = str(m.get("content", ""))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = TOOL_OUTPUTS_DIR / f"{ts}_{m.get('tool_call_id', 'x')[:8]}.txt"
        fp.write_text(raw, encoding="utf-8")
        m["content"] = f"[持久化输出: {fp}]\n{raw[:2000]}"
        total = sum(len(str(msg.get("content", ""))) for _, msg in tool_msgs)
    return messages


# ==================== L4: auto — LLM 摘要 ====================

def _save_transcript(messages: list) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = TRANSCRIPTS_DIR / f"transcript_{ts}.jsonl"
    with open(fp, "w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return fp


def compact_history(messages: list, client) -> list:
    """保存 transcript → LLM 摘要 → 替换旧消息"""
    _save_transcript(messages)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content":
                 "简洁摘要：当前目标、关键发现、已修改文件、"
                 "剩余工作、用户约束。只输出摘要，不要多余内容。"},
                *messages,
            ],
            max_tokens=4000,
        )
        summary = resp.choices[0].message.content or "[压缩失败]"
    except Exception as e:
        summary = f"[压缩失败: {e}]"
    return [{"role": "user", "content": f"[已压缩]\n\n{summary}"}]


def reactive_compact(messages: list, client) -> list:
    """应急裁剪：只留最后 5 条，其余摘要"""
    _save_transcript(messages)
    tail = max(0, len(messages) - 5)
    if tail > 0 and _is_tool_result(messages[tail]) and _has_tool_calls(messages[tail - 1]):
        tail -= 1
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "简要摘要，聚焦当前任务。"},
                *messages[:tail],
            ],
            max_tokens=2000,
        )
        summary = resp.choices[0].message.content or "[已压缩]"
    except Exception:
        summary = "[早期对话已压缩]"
    return [{"role": "user", "content": f"[应急压缩]\n\n{summary}"}] + messages[tail:]


# ==================== 管线 ====================

def run_compaction(messages: list, client) -> list:
    """四层压缩管线：budget → snip → micro → auto"""
    messages = tool_result_budget(messages)
    messages = snip_compact(messages)
    messages = micro_compact(messages)
    if estimate_tokens(messages) > CONTEXT_TOKEN_THRESHOLD:
        messages = compact_history(messages, client)
    return messages
