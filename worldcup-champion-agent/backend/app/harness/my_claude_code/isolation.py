"""
Git Worktree 隔离 — 各干各的目录，互不干扰
"""

import json, re, subprocess
from datetime import datetime
from pathlib import Path
from .config import WORKTREES_DIR, WORKDIR, DATA_DIR

WORKTREE_FILE = DATA_DIR / "worktrees.json"
_worktrees: dict[str, dict] = {}


def validate_name(name: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9._-]{1,64}$', name))


def create(name: str, task_id: str = None) -> dict:
    if not validate_name(name):
        raise ValueError(f"Invalid worktree name: {name}")
    wt_path = WORKTREES_DIR / name
    branch = f"wt/{name}"
    subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch, "HEAD"],
        capture_output=True, text=True, cwd=str(WORKDIR), check=True,
    )
    record = {"name": name, "path": str(wt_path), "branch": branch,
              "task_id": task_id or "", "created_at": datetime.now().isoformat()}
    _worktrees[name] = record
    _save()
    if task_id:
        bind(task_id, name)
    return record


def remove(name: str, force: bool = False):
    rec = _worktrees.get(name)
    if not rec:
        return
    wt_path = Path(rec["path"])
    if not force and wt_path.exists():
        r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=str(wt_path))
        if r.stdout.strip():
            raise RuntimeError(f"Worktree {name} has uncommitted changes.")
    subprocess.run(["git", "worktree", "remove", str(wt_path)],
                   capture_output=True, cwd=str(WORKDIR))
    _worktrees.pop(name, None)
    _save()


def list_all() -> list[dict]:
    return list(_worktrees.values())


def bind(task_id: str, wt_name: str):
    from .planner import load_task, save_task
    task = load_task(task_id)
    if task:
        task["worktree"] = wt_name
        save_task(task)


def get_path(task_id: str) -> str | None:
    for r in _worktrees.values():
        if r.get("task_id") == task_id:
            return r["path"]
    return None


def _save():
    WORKTREE_FILE.write_text(json.dumps(_worktrees, ensure_ascii=False, indent=2), encoding="utf-8")

def _load():
    global _worktrees
    if WORKTREE_FILE.exists():
        try:
            _worktrees = json.loads(WORKTREE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _worktrees = {}

_load()


# ==================== 工具处理函数 ====================

def h_create(name: str, task_id: str = None) -> str:
    try:
        r = create(name, task_id)
        return f"Created worktree '{name}' at {r['path']}"
    except Exception as e:
        return f"[Error] {e}"

def h_list() -> str:
    wts = list_all()
    if not wts:
        return "(no worktrees)"
    return "\n".join(f"  {w['name']}: {w['path']}" + (f" (task: {w['task_id']})" if w.get("task_id") else "") for w in wts)
