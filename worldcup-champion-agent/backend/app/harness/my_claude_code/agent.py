"""
Agent 核心 — 基础循环 + 增强循环（集成全部 Harness 机制）
纯 OpenAI API，无适配层
"""

import json

from .config import MODEL, MAX_TOKENS
from .tools import get_definitions, get_handler
from .hooks import trigger_hooks
from .permission import check_permission


def _build_assistant_msg(choice) -> dict:
    """从 OpenAI choice 构建 assistant 消息 dict"""
    msg = {"role": "assistant", "content": choice.message.content or ""}
    if choice.message.tool_calls:
        msg["tool_calls"] = [tc.model_dump() for tc in choice.message.tool_calls]
    return msg


def _append_tool_results(messages: list, tool_calls, results: list):
    """追加 tool result 消息（OpenAI 格式：role='tool'）"""
    for tc, output in zip(tool_calls, results):
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": str(output),
        })


# ======================== 基础循环 (s01) ========================

def base_loop(messages: list, system: str, client) -> str:
    """最小 Agent 循环：LLM → 工具 → 循环"""
    while True:
        api_messages = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(
            model=MODEL, messages=api_messages,
            tools=get_definitions(), tool_choice="auto",
            max_tokens=MAX_TOKENS,
        )
        choice = resp.choices[0]
        messages.append(_build_assistant_msg(choice))

        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            return choice.message.content or ""

        results = []
        for tc in choice.message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            h = get_handler(name)
            output = h(**args) if h else f"[错误] 未知工具: {name}"
            results.append(output)
        _append_tool_results(messages, choice.message.tool_calls, results)


# ======================== 增强循环 (s20) ========================

def enhanced_loop(messages: list, client) -> str:
    """
    完整 Harness 循环：
    通知注入 → 压缩管线 → prompt 组装 → LLM (错误恢复) → 工具分发
    """
    from .recovery import RecoveryState, with_retry, handle_truncation, handle_too_long, is_prompt_too_long
    from .context import run_compaction
    from .prompt import get_prompt, build_context
    from .planner import tick, consume_cron, collect_bg
    from .memory import extract_memories, consolidate, select_relevant
    from .team import spawn_subagent

    state = RecoveryState()
    max_tokens = MAX_TOKENS

    while True:
        # === 1. 注入通知 ===
        for p in consume_cron():
            messages.append({"role": "user", "content": p})
        for n in collect_bg():
            messages.append({"role": "user", "content": n})

        # === 2. 压缩管线 ===
        messages = run_compaction(messages, client)

        # === 3. TodoWrite 提醒 ===
        reminder = tick()
        if reminder:
            messages.append({"role": "user", "content": reminder})

        # === 4. 组装 prompt（含记忆注入）===
        ctx = build_context()
        relevant = select_relevant(messages, client)
        if relevant:
            ctx["memories"] = "\n\n".join(relevant)
        system = get_prompt(ctx)
        api_messages = [{"role": "system", "content": system}] + messages

        # === 5. LLM 调用（错误恢复）===
        trigger_hooks("UserPromptSubmit", messages)
        try:
            resp = with_retry(
                lambda: client.chat.completions.create(
                    model=state.current_model, messages=api_messages,
                    tools=get_definitions(), tool_choice="auto",
                    max_tokens=max_tokens,
                ), state,
            )
        except Exception as e:
            if is_prompt_too_long(e):
                messages, retry = handle_too_long(messages, state, client)
                if retry:
                    continue
            print(f"\n[错误] {e}")
            return ""

        choice = resp.choices[0]

        # === 6. 截断检查 ===
        if choice.finish_reason == "length":
            messages, max_tokens, go = handle_truncation(choice, messages, state, max_tokens)
            if go:
                continue
            return choice.message.content or ""

        # === 7. 追加响应 ===
        messages.append(_build_assistant_msg(choice))

        # === 8. 不再调工具 → 结束 ===
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            try:
                extract_memories(messages, client)
                consolidate(client)
            except Exception:
                pass
            trigger_hooks("Stop", messages)
            return choice.message.content or ""

        # === 9. 执行工具 ===
        results = []
        for tc in choice.message.tool_calls:
            func_name = tc.function.name
            try:
                func_args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                func_args = {}
            tc_dict = tc.model_dump()

            # Hook: PreToolUse
            blocked = trigger_hooks("PreToolUse", func_name, func_args)
            if blocked is not None:
                results.append(f"[已拦截] {blocked}")
                continue

            # 权限
            if not check_permission(func_name, func_args):
                results.append("[权限拒绝]")
                continue

            # 手动压缩
            if func_name == "compact":
                messages[:] = run_compaction(messages, client)
                results.append("[已压缩]")
                continue

            # 子 Agent（需要 client）
            if func_name == "task":
                output = spawn_subagent(func_args.get("description", ""), client)
                trigger_hooks("PostToolUse", func_name, func_args, output)
                results.append(output)
                continue

            # 后台任务判断
            from .planner import should_background, start_bg
            if should_background(func_name, func_args):
                h = get_handler(func_name)
                if h:
                    bg_id = start_bg(func_name, func_args, h)
                    results.append(f"[后台任务 {bg_id} 已启动]")
                    continue

            # 常规工具
            h = get_handler(func_name)
            output = h(**func_args) if h else f"[错误] 未知工具: {func_name}"
            trigger_hooks("PostToolUse", func_name, func_args, output)
            results.append(output)

        _append_tool_results(messages, choice.message.tool_calls, results)
