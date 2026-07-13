"""
工具注册中心 — 所有工具的定义、处理器、dispatch map 统一入口
加工具 = 在这里加一行注册，循环不动
"""

import subprocess, glob as glob_mod
from pathlib import Path
from .config import WORKDIR, SKILLS_DIR


# ======================== 工具 Schema (OpenAI function calling 格式) ========================

DEFS = {}  # name → tool definition dict

def _def(name, desc, props, required=None):
    """快捷创建工具定义 — OpenAI function calling 格式"""
    DEFS[name] = {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or list(props),
            },
        },
    }

# ---------- 内置工具 ----------
_def("bash", "执行 shell 命令",
     {"command": {"type": "string", "description": "Shell 命令"},
      "cwd": {"type": "string", "description": "工作目录"}}, ["command"])

_def("read_file", "读取文件内容",
     {"path": {"type": "string", "description": "文件路径"}})

_def("write_file", "写入文件（自动创建目录）",
     {"path": {"type": "string"}, "content": {"type": "string"}})

_def("edit_file", "查找并替换文件内容",
     {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}})

_def("glob", "按模式搜索文件",
     {"pattern": {"type": "string"}, "path": {"type": "string", "description": "搜索根目录（默认当前目录）"}})

# ---------- 规划工具 ----------
_def("todo_write", "创建/更新任务计划",
     {"todos": {"type": "array", "items": {"type": "object", "properties": {
         "description": {"type": "string"},
         "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]}},
         "required": ["description", "status"]}}})

_def("create_task", "创建持久化任务",
     {"subject": {"type": "string"}, "blocked_by": {"type": "array", "items": {"type": "string"}}}, ["subject"])

_def("complete_task", "标记任务完成",
     {"task_id": {"type": "string"}})

_def("list_tasks", "列出所有任务", {})

# ---------- 子 Agent ----------
_def("task", "启动子智能体处理子任务",
     {"description": {"type": "string", "description": "子任务描述"}})

# ---------- 技能 ----------
_def("load_skill", "加载技能的完整指令",
     {"name": {"type": "string", "description": "技能名称"}})

# ---------- 上下文 ----------
_def("compact", "手动触发上下文压缩", {})


# ======================== 处理器 ========================

HANDLERS = {}  # name → callable


def register(name: str, definition: dict, handler):
    """注册工具：定义 + 处理器"""
    DEFS[name] = definition
    HANDLERS[name] = handler


def _tool_name(definition: dict) -> str:
    return str(definition.get("function", {}).get("name", ""))


def _filter_defs(definitions: list[dict], allowed_names: set[str] | None) -> list[dict]:
    if allowed_names is None:
        return definitions
    return [definition for definition in definitions if _tool_name(definition) in allowed_names]


def get_definitions(allowed_names: set[str] | None = None) -> list[dict]:
    """返回所有工具定义（内置 + MCP，OpenAI function calling 格式）"""
    try:
        from .mcp import assemble_pool
        defs, _ = assemble_pool(list(DEFS.values()), HANDLERS)
        return _filter_defs(defs, allowed_names)
    except ImportError:
        return _filter_defs(list(DEFS.values()), allowed_names)


def get_handler(name: str):
    """查找处理器（内置 + MCP）"""
    h = HANDLERS.get(name)
    if h:
        return h
    try:
        from .mcp import assemble_pool
        _, handlers = assemble_pool(list(DEFS.values()), HANDLERS)
        return handlers.get(name)
    except ImportError:
        return None


# ======================== 内置处理器实现 ========================

def _resolve_inside_workdir(path: str | None) -> Path:
    raw = Path(path) if path else WORKDIR
    resolved = raw.resolve() if raw.is_absolute() else (WORKDIR / raw).resolve()
    try:
        resolved.relative_to(WORKDIR.resolve())
    except ValueError as exc:
        raise PermissionError(f"路径超出工作区: {resolved}") from exc
    return resolved


def _bash(command: str, cwd: str = None) -> str:
    try:
        workdir = _resolve_inside_workdir(cwd)
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           timeout=120, cwd=str(workdir))
        out = r.stdout
        if r.stderr:
            out += f"\n[标准错误]\n{r.stderr}"
        if r.returncode != 0:
            out += f"\n[退出码: {r.returncode}]"
        return out.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        return "[错误] 超时 (120秒)"
    except Exception as e:
        return f"[错误] {e}"


def _read_file(path: str) -> str:
    try:
        p = _resolve_inside_workdir(path)
        if not p.is_file():
            return f"[错误] 文件不存在: {p}"
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"[错误] {e}"


def _write_file(path: str, content: str) -> str:
    try:
        p = _resolve_inside_workdir(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {len(content)} 字节到 {p}"
    except Exception as e:
        return f"[错误] {e}"


def _edit_file(path: str, old_string: str, new_string: str) -> str:
    try:
        p = _resolve_inside_workdir(path)
        content = p.read_text(encoding="utf-8")
        if old_string not in content:
            return "[错误] 未找到 old_string"
        p.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"已编辑 {p}"
    except Exception as e:
        return f"[错误] {e}"


def _glob(pattern: str, path: str = ".") -> str:
    try:
        base = _resolve_inside_workdir(path)
        matches = glob_mod.glob(str(base / pattern), recursive=True)
        return "\n".join(sorted(matches)) if matches else "(未找到匹配文件)"
    except Exception as e:
        return f"[错误] {e}"


# ======================== 技能系统 ========================

_skill_registry: dict[str, dict] = {}


def _scan_skills():
    global _skill_registry
    _skill_registry = {}
    if not SKILLS_DIR.exists():
        return
    for fp in SKILLS_DIR.glob("*.md"):
        try:
            text = fp.read_text(encoding="utf-8")
            meta = {}
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].strip().split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    text = parts[2].strip()
            name = meta.get("name", fp.stem)
            _skill_registry[name] = {"name": name, "description": meta.get("description", ""), "content": text}
        except Exception:
            pass


def get_skill_catalog() -> str:
    if not _skill_registry:
        return ""
    lines = [f"  - {n}: {s['description']}" for n, s in _skill_registry.items()]
    return "可用技能:\n" + "\n".join(lines) + "\n使用 load_skill(name) 获取完整内容。"


def _load_skill(name: str) -> str:
    if name not in _skill_registry:
        avail = ", ".join(_skill_registry) or "无"
        return f"[错误] 技能 '{name}' 未找到。可用: {avail}"
    return _skill_registry[name]["content"]


# ======================== 注册所有处理器 ========================

# 内置
HANDLERS["bash"] = _bash
HANDLERS["read_file"] = _read_file
HANDLERS["write_file"] = _write_file
HANDLERS["edit_file"] = _edit_file
HANDLERS["glob"] = _glob

# 规划
from .planner import h_todo, h_create_task, h_complete_task, h_list_tasks
HANDLERS["todo_write"] = h_todo
HANDLERS["create_task"] = h_create_task
HANDLERS["complete_task"] = h_complete_task
HANDLERS["list_tasks"] = h_list_tasks

# 子 Agent（由 agent.py 特殊处理，这里放占位）
HANDLERS["task"] = lambda description="", **kw: "[错误] 子智能体需要 client，请使用 agent.py"

# 技能
_scan_skills()
HANDLERS["load_skill"] = _load_skill

# 压缩（由 agent.py 特殊处理，这里放占位）
HANDLERS["compact"] = lambda **kw: "[已触发压缩]"
