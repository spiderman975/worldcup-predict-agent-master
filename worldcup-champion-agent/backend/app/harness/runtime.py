"""Service-facing runtime wrapper around the packaged my-claude-code harness."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import httpx
from openai import OpenAI

from app.core.config import get_settings
from app.harness.adapters.worldcup_tools import register_worldcup_tools
from app.harness.my_claude_code.tools import get_definitions, get_handler
from app.harness.reliability import CircuitOpenError, resilient_call
from app.harness.tool_allowlist import WEB_CHAT_TOOL_NAMES


SYSTEM_PROMPT = """
你是 worldcup-predict-agent 的主 Chat Agent，运行在 my-claude-code 主系统之中。

你的职责：
1. 像正常助手一样回答用户关于项目、球队、赛程、预测结果和预测理由的问题。
2. 当用户问“你是谁 / 你能做什么 / 怎么用”时，说明你可以查赛程、查球队、查数据库、读取已保存的单场预测、触发单场预测工作流，也可以确认当前实时时间。
3. 当用户询问当前时间、今天日期、现在几点、是否已经到赛前/赛后等问题时，先调用 worldcup_get_current_time，再基于工具结果回答。
4. 当用户要求预测某场比赛的比分、胜负或理由时，优先识别比赛 ID 或双方球队；如果能识别，调用 worldcup_predict_match_workflow，并基于返回的 prediction、explanation、agent_trace 回答。
5. 当用户询问某场“已经预测过的比分、理由、为什么这么判断”时，先调用 worldcup_get_saved_match_prediction；如果没有保存，再询问用户是否现在预测，不要假装已有结果。
6. 当用户问赛程或某日比赛时，调用 worldcup_list_matches。
7. 当用户问球队实力、攻防、排名、分组时，调用 worldcup_list_teams 或 worldcup_get_team_database_report。
8. 当用户问阵容、伤病、数据库资料或需要更宽泛检索时，调用 worldcup_search_database。
9. 如果用户没有给出具体比赛，要自然追问，例如“你想看哪一场？可以说比赛 ID，或 Brazil vs Mexico。”
10. 当前网页聊天只开放 World Cup 业务工具，不要声称你能读写代码、执行 shell 或直接联网搜索；联网搜索只有在数据库工具 include_web=true 且后端配置了 BOCHA_API_KEY 时才可用。

回答要求：
- 必须使用中文。
- 先给结论，再给关键依据。
- 涉及预测时写清楚这是模型预测，不是真实赛果。
- 如果数据缺失，要说明缺失并给出下一步可问法。
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

    async def stream(self, messages: list[dict[str, str]]):
        queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce() -> None:
            try:
                for token in self._complete_sync_stream(messages):
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
                return choice.message.content or "我没有拿到可用回答。你可以换成具体比赛 ID，例如 A1。"

            self._append_tool_results(runtime_messages, choice.message.tool_calls)

        return "我已经尝试调用业务工具，但工具循环次数达到上限。请把问题缩小到具体球队、日期或比赛 ID。"

    def _complete_sync_stream(self, messages: list[dict[str, str]]):
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

            self._append_tool_results(runtime_messages, tool_calls)

        yield "我已经尝试调用业务工具，但工具循环次数达到上限。请把问题缩小到具体球队、日期或比赛 ID。"

    def _append_tool_results(self, runtime_messages: list[dict[str, Any]], tool_calls: list[Any]) -> None:
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
                    output = resilient_call(
                        f"harness_tool:{name}",
                        lambda: handler(**args),
                        max_attempts=2,
                        payload={"tool": name, "args": args},
                    )
                except Exception as exc:
                    output = f"[错误] 工具 {name} 调用失败：{exc}。失败任务已记录到 dead-letter 队列。"
            runtime_messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": str(output)})


my_claude_runtime = MyClaudeRuntime()
