"""
多 Agent 协作 — 子 Agent + 邮箱通信 + 协议握手 + 自主认领
适配 OpenAI API
"""

import json, threading, time
from datetime import datetime
from .config import MODEL, MAX_TOKENS, MAILBOX_DIR, SUBAGENT_MAX_TURNS, IDLE_POLL_INTERVAL, IDLE_TIMEOUT


# ======================== MessageBus ========================

class MessageBus:
    """JSONL 文件邮箱：追加写入，消费式读取"""

    def send(self, from_a: str, to_a: str, content: str, msg_type: str = "message"):
        fp = MAILBOX_DIR / f"{to_a}.jsonl"
        msg = {"from": from_a, "type": msg_type, "content": content,
               "timestamp": datetime.now().isoformat()}
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def read_inbox(self, agent: str) -> list[dict]:
        fp = MAILBOX_DIR / f"{agent}.jsonl"
        if not fp.exists():
            return []
        msgs = []
        try:
            for line in fp.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    msgs.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            pass
        fp.unlink(missing_ok=True)
        return msgs

    def has_messages(self, agent: str) -> bool:
        fp = MAILBOX_DIR / f"{agent}.jsonl"
        return fp.exists() and fp.stat().st_size > 0


# ======================== 工具定义 (OpenAI 格式) ========================

_SUB_TOOLS = [
    {"type": "function", "function": {"name": "bash", "description": "执行命令",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "读取文件",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "写入文件",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                   "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "查找替换",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}},
         "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "glob", "description": "搜索文件",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
]

_TEAM_TOOLS = _SUB_TOOLS[:4]


# ======================== 辅助函数 ========================

def _build_msg(choice) -> dict:
    msg = {"role": "assistant", "content": choice.message.content or ""}
    if choice.message.tool_calls:
        msg["tool_calls"] = [tc.model_dump() for tc in choice.message.tool_calls]
    return msg


def _execute_tools(choice) -> list:
    outputs = []
    for tc in choice.message.tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, TypeError):
            args = {}
        from .tools import get_handler
        h = get_handler(name)
        output = h(**args) if h else f"[错误] 未知工具: {name}"
        outputs.append((tc, output))
    return outputs


def _append_results(messages, results):
    for tc, output in results:
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": str(output),
        })


# ======================== 子 Agent ========================

def spawn_subagent(description: str, client, max_turns: int = SUBAGENT_MAX_TURNS) -> str:
    print(f"  [子智能体] 启动: {description[:80]}...")
    messages = [{"role": "user", "content": description}]
    system = "你是一个专注的子智能体。完成任务后汇报结果。请用中文回复。"

    for turn in range(max_turns):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system}] + messages,
                tools=_SUB_TOOLS, tool_choice="auto",
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            return f"[子智能体错误] {e}"

        choice = resp.choices[0]
        messages.append(_build_msg(choice))

        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            print(f"  [子智能体] 完成 ({turn + 1} 轮)")
            return choice.message.content or "(无输出)"

        results = _execute_tools(choice)
        _append_results(messages, results)

    return "[子智能体] 达到最大轮次"


# ======================== 队友线程 ========================

def teammate_loop(name: str, role: str, prompt: str, client, bus: MessageBus):
    messages = [{"role": "user", "content": f"你是 {name}（{role}）。\n\n任务: {prompt}"}]
    system = f"你是 {name}。完成你的任务。请用中文回复。"

    for _ in range(10):
        inbox = bus.read_inbox(name)
        for msg in inbox:
            if msg.get("type") == "shutdown_request":
                bus.send(name, msg["from"], "正在关闭。", "shutdown_response")
                return
            messages.append({"role": "user", "content": f"[来自 {msg.get('from', '')}]: {msg.get('content', '')}"})

        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system}] + messages,
                tools=_TEAM_TOOLS, tool_choice="auto",
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            bus.send(name, "lead", f"错误: {e}", "result")
            return

        choice = resp.choices[0]
        messages.append(_build_msg(choice))

        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            bus.send(name, "lead", choice.message.content or "", "result")
            return

        results = _execute_tools(choice)
        _append_results(messages, results)

    bus.send(name, "lead", "达到最大轮次", "result")


_teammates: dict[str, threading.Thread] = {}


def spawn_teammate(name: str, role: str, prompt: str, client, bus: MessageBus):
    t = threading.Thread(target=teammate_loop, args=(name, role, prompt, client, bus),
                         daemon=True, name=f"teammate-{name}")
    _teammates[name] = t
    t.start()


def get_teammates() -> list[str]:
    return [n for n, t in _teammates.items() if t.is_alive()]


# ======================== 协议握手 ========================

_req_counter = 0

def send_request(from_a: str, to_a: str, req_type: str, content: str, bus: MessageBus) -> str:
    global _req_counter
    _req_counter += 1
    rid = f"req_{_req_counter:03d}"
    bus.send(from_a, to_a, content, msg_type=req_type)
    return rid


def handle_shutdown(agent: str, bus: MessageBus, lead: str = "lead"):
    bus.send(agent, lead, json.dumps({"approve": True}), msg_type="shutdown_response")


# ======================== 自主认领 ========================

def idle_poll(name: str, bus: MessageBus) -> str:
    elapsed = 0.0
    while elapsed < IDLE_TIMEOUT:
        for msg in bus.read_inbox(name):
            if msg.get("type") == "shutdown_request":
                bus.send(name, msg["from"], "确认关闭", "shutdown_response")
                return "shutdown"
        from .planner import scan_unclaimed, claim_task
        for task in scan_unclaimed():
            if claim_task(task["id"], name):
                print(f"  [自动] {name} 认领了 {task['id']}: {task['subject']}")
                return "work"
        time.sleep(IDLE_POLL_INTERVAL)
        elapsed += IDLE_POLL_INTERVAL
    return "timeout"


def autonomous_loop(name: str, role: str, client, bus: MessageBus):
    from .planner import load_task, complete_task, scan_unclaimed, claim_task

    current_task = None
    while True:
        if current_task is None:
            unclaimed = scan_unclaimed()
            if unclaimed and claim_task(unclaimed[0]["id"], name):
                current_task = unclaimed[0]
            else:
                result = idle_poll(name, bus)
                if result in ("shutdown", "timeout"):
                    break
                continue

        td = load_task(current_task["id"])
        if not td or td["status"] != "in_progress":
            current_task = None
            continue

        messages = [{"role": "user", "content": f"你是 {name}（{role}）。任务: {td['subject']}"}]
        for _ in range(10):
            for msg in bus.read_inbox(name):
                if msg.get("type") == "shutdown_request":
                    bus.send(name, msg["from"], "正在关闭", "shutdown_response")
                    return
            try:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": f"你是 {name}。请用中文回复。"}] + messages,
                    tools=_TEAM_TOOLS, tool_choice="auto",
                    max_tokens=MAX_TOKENS,
                )
            except Exception:
                break
            choice = resp.choices[0]
            messages.append(_build_msg(choice))
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                break
            results = _execute_tools(choice)
            _append_results(messages, results)

        complete_task(current_task["id"])
        bus.send(name, "lead", f"完成: {current_task['id']}", "result")
        current_task = None


def start_autonomous(name: str, role: str, client, bus: MessageBus) -> threading.Thread:
    t = threading.Thread(target=autonomous_loop, args=(name, role, client, bus),
                         daemon=True, name=f"auto-{name}")
    t.start()
    return t
