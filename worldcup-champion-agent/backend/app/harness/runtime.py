"""Service-facing runtime wrapper around the packaged my-claude-code harness."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable

import httpx
from openai import OpenAI

from app.core.config import get_settings
from app.harness.adapters.worldcup_tools import register_worldcup_tools
from app.harness.my_claude_code.tools import get_definitions, get_handler
from app.harness.reliability import CircuitOpenError, resilient_call
from app.harness.tool_allowlist import WEB_CHAT_TOOL_NAMES


SYSTEM_PROMPT = """
你是 worldcup-predict-agent 的主 Chat Agent，运行在 my-claude-code harness 系统中。

你的目标不是让用户记比赛 ID，而是主动把自然语言问题转换成可靠的工具调用，再用中文给出清晰结论。

通用回答流程：
1. 先判断用户意图：赛程查询、球队查询、比赛解析、比分预测、真实赛果查询、已保存预测查询、实时新闻/伤病/阵容查询、普通问答。
2. 涉及“今天、现在、已经开始、已经结束、赛前、赛后、实时”时，必须先调用 worldcup_get_current_time。
3. 涉及单场比赛时，必须先调用 worldcup_resolve_match。用户可能会说“法西大战”“法国西班牙”“France vs Spain”“今天法国那场”，不要直接要求用户提供 ID。
4. 如果 worldcup_resolve_match 返回多个候选，列出候选并追问；如果只有一个高置信候选，继续执行。
5. 在预测单场比赛前，必须调用 worldcup_get_match_context。
6. 如果比赛已完赛，不要直接做赛前预测；先说明数据库/时间判断显示已完赛，并询问用户想看真实比分、赛前预测回放，还是强行重新预测。
7. 如果比赛未开赛或正在进行，才调用 worldcup_predict_match_workflow，并说明这是模型预测，不是真实赛果。
8. 用户问“最新、刚刚、伤病、首发、阵容、新闻、赔率、真实比分、赛果”时，优先调用 worldcup_web_search 或 worldcup_search_match_result；如果数据库已足够且问题不需要实时信息，可以只查数据库。
9. 用户问数据库、球队资料、历史预测、赛程时，优先使用本地工具，不要无意义联网。
10. 如果上层系统提示“用户已开启实时搜索模式”，必须优先使用实时搜索预检结果，并按需继续调用 worldcup_web_search / worldcup_search_match_result / worldcup_search_database(include_web=true) 核验，不要直接跳到离线回答。
11. 如果数据库状态和北京时间推算不一致，必须把 data_quality.warnings 里的问题告诉用户，不能假装确定。

可用核心工具：
- worldcup_get_current_time：获取北京时间。
- worldcup_resolve_match：把自然语言解析为比赛。
- worldcup_get_match_context：读取比赛、球队、预测、比分和状态一致性。
- worldcup_list_matches：查询赛程。
- worldcup_list_teams / worldcup_get_team_database_report：查询球队。
- worldcup_search_database：查本地数据库，可选 include_web。
- worldcup_web_search：明确联网搜索。
- worldcup_search_match_result：联网搜索某场真实比分/赛果。
- worldcup_get_saved_match_prediction：查已保存预测。
- worldcup_predict_match_workflow：运行单场预测工作流。

回答要求：
- 必须使用中文。
- 先给结论，再给关键依据。
- 不要把完整内部推理过程写进最终回答；实时流程由系统单独推送。最终回答保持精炼。
- 涉及单场预测时，按“预测比分 / 胜负倾向 / 关键依据 / 风险提示”组织，每部分 1-3 句即可。
- 最终回答不要使用 Markdown 标题、粗体星号、反引号或项目符号；用自然中文、短段落和编号即可。
- 不要在最终回答里写“我先确认日期”“我正在识别比赛”“我调用了工具”等过程句，这些只放在实时流程中。
- 涉及预测时写清楚“这是模型预测，不是真实赛果”。
- 如果信息缺失或工具返回冲突，要明确说明缺失/冲突点，并给出下一步建议。
- 不要声称自己能读写代码、执行 shell 或使用未开放的工具；网页搜索只能通过 World Cup 业务工具完成。
""".strip()


class MyClaudeRuntime:
    @property
    def enabled(self) -> bool:
        settings = get_settings()
        return bool(settings.my_claude_runtime_enabled and settings.llm_api_key)

    def _client(self) -> OpenAI:
        settings = get_settings()
        if not settings.llm_api_key:
            raise RuntimeError("LLM API key is not configured")
        http_client = httpx.Client(timeout=settings.llm_timeout_seconds, trust_env=False)
        return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, http_client=http_client)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return await asyncio.to_thread(self._complete_sync, messages)

    async def complete_direct(self, *, system_prompt: str, user_prompt: str) -> str:
        """Run one harness-managed LLM call without business tool recursion."""

        return await asyncio.to_thread(self._complete_direct_sync, system_prompt, user_prompt)

    async def stream(self, messages: list[dict[str, str]], progress_callback: Callable[[dict[str, Any]], None] | None = None):
        queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce() -> None:
            try:
                for token in self._complete_sync_stream(messages, progress_callback=progress_callback):
                    loop.call_soon_threadsafe(queue.put_nowait, token)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)

        threading.Thread(target=produce, daemon=True, name="my-claude-stream").start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    def _complete_sync(self, messages: list[dict[str, str]]) -> str:
        register_worldcup_tools()
        settings = get_settings()
        client = self._client()
        runtime_messages: list[dict[str, Any]] = [dict(item) for item in messages]
        tool_defs = get_definitions(WEB_CHAT_TOOL_NAMES)

        for _ in range(8):
            try:
                response = resilient_call(
                    "llm_chat_completion",
                    lambda: client.chat.completions.create(
                        model=settings.llm_model,
                        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + runtime_messages,
                        tools=tool_defs,
                        tool_choice="auto",
                        temperature=settings.llm_temperature,
                        max_tokens=settings.llm_max_tokens,
                    ),
                    max_attempts=3,
                    payload={"message_count": len(runtime_messages), "stream": False},
                )
            except CircuitOpenError as exc:
                return f"大模型服务暂时熔断：{exc}。你可以稍后重试，或先查询赛程、球队、数据库等本地信息。"
            except Exception as exc:
                return f"大模型调用失败：{exc}。失败任务已记录到 dead-letter 队列。"
            choice = response.choices[0]
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": choice.message.content or ""}
            if choice.message.tool_calls:
                assistant_msg["tool_calls"] = [tool_call.model_dump() for tool_call in choice.message.tool_calls]
            runtime_messages.append(assistant_msg)

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                return choice.message.content or "我没有拿到可用回答。你可以换成具体比赛、球队或日期再问。"

            self._append_tool_results(runtime_messages, choice.message.tool_calls)

        return "我已经尝试调用业务工具，但工具循环次数达到上限。请把问题缩小到具体球队、日期或比赛。"

    def _complete_direct_sync(self, system_prompt: str, user_prompt: str) -> str:
        settings = get_settings()
        client = self._client()
        try:
            response = resilient_call(
                "llm_direct_completion",
                lambda: client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                ),
                max_attempts=3,
                payload={"message_count": 2, "stream": False, "direct": True},
            )
        except CircuitOpenError as exc:
            raise RuntimeError(f"大模型服务暂时熔断：{exc}") from exc
        return response.choices[0].message.content or ""

    def _complete_sync_stream(self, messages: list[dict[str, str]], progress_callback: Callable[[dict[str, Any]], None] | None = None):
        register_worldcup_tools()
        settings = get_settings()
        client = self._client()
        runtime_messages: list[dict[str, Any]] = [dict(item) for item in messages]
        tool_defs = get_definitions(WEB_CHAT_TOOL_NAMES)

        for _ in range(8):
            try:
                chunks = resilient_call(
                    "llm_chat_completion",
                    lambda: client.chat.completions.create(
                        model=settings.llm_model,
                        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + runtime_messages,
                        tools=tool_defs,
                        tool_choice="auto",
                        temperature=settings.llm_temperature,
                        max_tokens=settings.llm_max_tokens,
                        stream=True,
                    ),
                    max_attempts=3,
                    payload={"message_count": len(runtime_messages), "stream": True},
                )
            except CircuitOpenError as exc:
                yield f"大模型服务暂时熔断：{exc}。你可以稍后重试，或先查询赛程、球队、数据库等本地信息。"
                return
            except Exception as exc:
                yield f"大模型调用失败：{exc}。失败任务已记录到 dead-letter 队列。"
                return

            content_parts: list[str] = []
            tool_call_parts: dict[int, dict[str, Any]] = {}
            finish_reason = None

            for chunk in chunks:
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta
                token = getattr(delta, "content", None)
                if token:
                    content_parts.append(token)
                    yield token

                for tool_delta in getattr(delta, "tool_calls", None) or []:
                    index = tool_delta.index
                    current = tool_call_parts.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if getattr(tool_delta, "id", None):
                        current["id"] = tool_delta.id
                    if getattr(tool_delta, "type", None):
                        current["type"] = tool_delta.type
                    function_delta = getattr(tool_delta, "function", None)
                    if function_delta:
                        if getattr(function_delta, "name", None):
                            current["function"]["name"] += function_delta.name
                        if getattr(function_delta, "arguments", None):
                            current["function"]["arguments"] += function_delta.arguments

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
            tool_calls = [tool_call_parts[index] for index in sorted(tool_call_parts)]
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            runtime_messages.append(assistant_msg)

            if finish_reason != "tool_calls" or not tool_calls:
                return

            self._append_tool_results(runtime_messages, tool_calls, progress_callback=progress_callback)

        yield "我已经尝试调用业务工具，但工具循环次数达到上限。请把问题缩小到具体球队、日期或比赛。"

    def _append_tool_results(
        self,
        runtime_messages: list[dict[str, Any]],
        tool_calls: list[Any],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                tool_call_id = tool_call.get("id", "")
                name = tool_call["function"]["name"]
                raw_args = tool_call["function"].get("arguments") or "{}"
            else:
                tool_call_id = tool_call.id
                name = tool_call.function.name
                raw_args = tool_call.function.arguments or "{}"

            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}

            handler = get_handler(name)
            if not handler:
                output = f"[错误] 未知工具: {name}"
            else:
                try:
                    self._emit_tool_progress(progress_callback, name, "running", args)
                    output = resilient_call(
                        f"harness_tool:{name}",
                        lambda: handler(**args),
                        max_attempts=2,
                        payload={"tool": name, "args": args},
                    )
                    self._emit_tool_progress(progress_callback, name, "completed", args)
                except Exception as exc:
                    self._emit_tool_progress(progress_callback, name, "failed", args, error=str(exc))
                    output = f"[错误] 工具 {name} 调用失败：{exc}。失败任务已记录到 dead-letter 队列。"
            runtime_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": str(output)})

    @staticmethod
    def _emit_tool_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        tool_name: str,
        status: str,
        args: dict[str, Any],
        *,
        error: str | None = None,
    ) -> None:
        if not progress_callback:
            return
        labels = {
            "worldcup_get_current_time": "确认北京时间",
            "worldcup_resolve_match": "识别比赛",
            "worldcup_get_match_context": "读取比赛上下文",
            "worldcup_list_teams": "读取球队数据",
            "worldcup_list_matches": "读取赛程数据",
            "worldcup_get_saved_match_prediction": "查询已保存预测",
            "worldcup_predict_match_workflow": "运行多 Agent 单场预测工作流",
            "worldcup_search_database": "检索本地数据库",
            "worldcup_web_search": "联网搜索实时信息",
            "worldcup_search_match_result": "联网搜索真实比分",
            "worldcup_get_team_database_report": "读取球队数据库报告",
        }
        status_text = {"running": "正在", "completed": "已完成", "failed": "失败"}.get(status, status)
        title = labels.get(tool_name, tool_name)
        message = f"{status_text}{title}"
        if error:
            message = f"{message}：{error}"
        progress_callback(
            {
                "stage": tool_name,
                "status": status,
                "message": message,
                "args": args,
            }
        )


my_claude_runtime = MyClaudeRuntime()
