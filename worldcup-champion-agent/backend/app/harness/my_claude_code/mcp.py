"""
MCP 插件 — 标准协议接入外部工具，命名空间避免冲突
工具定义已适配 OpenAI function calling 格式
"""

import json, subprocess, re, threading

class MCPClient:
    """通过子进程 stdin/stdout JSON-RPC 与 MCP server 通信"""

    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: subprocess.Popen | None = None
        self.tools: list[dict] = []
        self._lock = threading.Lock()
        self._rid = 0

    def connect(self):
        self.process = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        self._send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "my-claude-code", "version": "1.0"}})

    def _send(self, method: str, params: dict) -> dict:
        with self._lock:
            self._rid += 1
            req = {"jsonrpc": "2.0", "id": self._rid, "method": method, "params": params}
            self.process.stdin.write(json.dumps(req) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            return json.loads(line) if line else {}

    def list_tools(self) -> list[dict]:
        resp = self._send("tools/list", {})
        self.tools = resp.get("result", {}).get("tools", [])
        return self.tools

    def call_tool(self, name: str, args: dict) -> str:
        resp = self._send("tools/call", {"name": name, "arguments": args})
        content = resp.get("result", {}).get("content", [])
        texts = [c["text"] for c in content if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(resp.get("result", {}))

    def disconnect(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None


_clients: dict[str, MCPClient] = {}


def _norm(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]', '_', s)


def connect(server_name: str, command: list[str]) -> list[dict]:
    c = MCPClient(server_name, command)
    c.connect()
    tools = c.list_tools()
    _clients[server_name] = c
    print(f"  [MCP] Connected: {server_name} ({len(tools)} tools)")
    return tools


def disconnect(server_name: str):
    c = _clients.pop(server_name, None)
    if c:
        c.disconnect()


def assemble_pool(builtin_defs: list, builtin_handlers: dict) -> tuple:
    """组装工具池：内置 + MCP，返回 (definitions, handlers) — OpenAI 格式"""
    defs = list(builtin_defs)
    handlers = dict(builtin_handlers)
    for sname, client in _clients.items():
        ns = _norm(sname)
        for t in client.tools:
            orig = t.get("name", "")
            full = f"mcp__{ns}__{_norm(orig)}"
            defs.append({
                "type": "function",
                "function": {
                    "name": full,
                    "description": t.get("description", f"MCP: {sname}"),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            })
            def make_h(c=client, n=orig):
                return lambda **kw: c.call_tool(n, kw)
            handlers[full] = make_h()
    return defs, handlers


def get_servers() -> list[str]:
    return list(_clients.keys())


def disconnect_all():
    for name in list(_clients):
        disconnect(name)
