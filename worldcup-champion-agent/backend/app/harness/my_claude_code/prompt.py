"""
System Prompt — 运行时组装，不硬编码
分段定义 + 按需拼接 + 缓存
"""

import json
from .config import WORKDIR

SECTIONS = {
    "identity": (
        "你是一个强大的编程助手。果断行动，善用工具完成任务。"
        "先思考再行动。请用中文回复。"
    ),
    "tools": (
        "可用工具：bash（执行命令）、read_file（读文件）、write_file（写文件）、"
        "edit_file（查找替换）、glob（搜索文件）、"
        "todo_write（任务计划）、task（子智能体）、load_skill（加载技能）、"
        "compact（压缩上下文）、"
        "create_task（创建任务）、complete_task（完成任务）、list_tasks（列出任务）。"
    ),
    "worldcup": (
        "世界杯业务工具：worldcup_list_teams（球队与评分）、worldcup_list_matches（赛程）、"
        "worldcup_predict_match_workflow（单场六 Agent 预测工作流）、"
        "worldcup_run_full_prediction（本地完整预测工作流）。"
        "当用户询问具体球队、赛程或单场比赛时，优先调用世界杯业务工具，"
        "不要用通用文件/命令工具绕开业务服务。"
    ),
    "workspace": f"工作目录：{WORKDIR}",
}

_cache_key: str | None = None
_cache_prompt: str | None = None


def assemble(context: dict) -> str:
    parts = [SECTIONS["identity"], SECTIONS["tools"], SECTIONS["worldcup"], SECTIONS["workspace"]]
    if context.get("memories"):
        parts.append(f"## 记忆\n{context['memories']}")
    if context.get("skills"):
        parts.append(f"## 技能\n{context['skills']}")
    if context.get("todos"):
        parts.append(f"## 当前任务\n{context['todos']}")
    return "\n\n".join(parts)


def get_prompt(context: dict) -> str:
    """带缓存的 prompt 获取"""
    global _cache_key, _cache_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _cache_key and _cache_prompt:
        return _cache_prompt
    _cache_key = key
    _cache_prompt = assemble(context)
    return _cache_prompt


def build_context() -> dict:
    """根据真实状态构建 context 字典"""
    ctx = {"workspace": str(WORKDIR)}
    try:
        from .memory import load_index
        ctx["memories"] = load_index()
    except Exception:
        ctx["memories"] = ""
    try:
        from .tools import get_skill_catalog
        ctx["skills"] = get_skill_catalog()
    except Exception:
        ctx["skills"] = ""
    try:
        from .planner import format_todos, get_todos
        ctx["todos"] = format_todos() if get_todos() else ""
    except Exception:
        ctx["todos"] = ""
    return ctx
