"""
任务管理 — TodoWrite + 任务 DAG + 后台执行 + Cron 调度
统一管"做什么"和"什么时候做"
"""

import json, uuid, queue, threading, time
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from .config import (
    MODEL, MAX_TOKENS, TASKS_DIR, DATA_DIR,
    CRON_POLL_INTERVAL, MAX_BACKGROUND_THREADS,
)

SCHEDULE_FILE = DATA_DIR / "scheduled_tasks.json"


# ======================== TodoWrite ========================

_todos: list[dict] = []
_tick_count: int = 0
TICK_REMINDER = 3


def update_todos(todos: list[dict]) -> str:
    """更新 todo 列表"""
    global _todos, _tick_count
    _todos = [{"description": t["description"], "status": t["status"]} for t in todos]
    _tick_count = 0
    return format_todos()


def format_todos() -> str:
    if not _todos:
        return "(暂无待办)"
    icons = {"pending": "[ ]", "in_progress": "[>]", "completed": "[v]", "cancelled": "[x]"}
    return "\n".join(f"  {icons.get(t['status'], '[?]')} {t['description']}" for t in _todos)


def get_todos() -> list:
    return _todos


def tick() -> str | None:
    """每轮调用，连续 N 轮没更新返回提醒"""
    global _tick_count
    if not _todos:
        return None
    _tick_count += 1
    if _tick_count >= TICK_REMINDER:
        _tick_count = 0
        return "<reminder>请更新待办列表以反映进度。</reminder>"
    return None


# ======================== 任务 DAG ========================

def _gen_id() -> str:
    return uuid.uuid4().hex[:8]


def create_task(subject: str, blocked_by: list[str] = None) -> dict:
    task = {"id": _gen_id(), "subject": subject, "status": "pending",
            "owner": "", "blockedBy": blocked_by or [],
            "createdAt": datetime.now().isoformat(), "worktree": ""}
    save_task(task)
    return task


def load_task(task_id: str) -> dict | None:
    fp = TASKS_DIR / f"{task_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_task(task: dict):
    fp = TASKS_DIR / f"{task['id']}.json"
    fp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")


def list_tasks() -> list[dict]:
    if not TASKS_DIR.exists():
        return []
    tasks = []
    for fp in sorted(TASKS_DIR.glob("*.json")):
        try:
            tasks.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception:
            continue
    return tasks


def can_start(task_id: str) -> bool:
    task = load_task(task_id)
    if not task:
        return False
    for dep in task.get("blockedBy", []):
        d = load_task(dep)
        if not d or d["status"] != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str) -> bool:
    task = load_task(task_id)
    if not task or task["status"] != "pending" or task.get("owner"):
        return False
    task["status"] = "in_progress"
    task["owner"] = owner
    save_task(task)
    return True


def complete_task(task_id: str):
    task = load_task(task_id)
    if task and task["status"] == "in_progress":
        task["status"] = "completed"
        save_task(task)


def scan_unclaimed() -> list[dict]:
    return [t for t in list_tasks()
            if t["status"] == "pending" and not t.get("owner") and can_start(t["id"])]


# ======================== 后台任务 ========================

@dataclass
class BgTask:
    id: str
    command: str
    thread: threading.Thread = None
    result: str = ""
    done: bool = False
    error: bool = False
    started: float = field(default_factory=time.time)

_bg_tasks: dict[str, BgTask] = {}
_bg_counter: int = 0

BG_KEYWORDS = ["npm install", "pip install", "apt install", "brew install",
               "make ", "cargo build", "go build", "docker build"]


def should_background(tool_name: str, args: dict) -> bool:
    if tool_name != "bash":
        return False
    if args.get("run_in_background"):
        return True
    return any(k in args.get("command", "") for k in BG_KEYWORDS)


def start_bg(tool_name: str, args: dict, handler) -> str:
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    task = BgTask(id=bg_id, command=args.get("command", str(args)))

    def run():
        try:
            task.result = str(handler(**args))
        except Exception as e:
            task.result = f"[错误] {e}"
            task.error = True
        finally:
            task.done = True

    t = threading.Thread(target=run, daemon=True, name=f"bg-{bg_id}")
    task.thread = t
    _bg_tasks[bg_id] = task
    t.start()
    return bg_id


def collect_bg() -> list[str]:
    """收集已完成的后台任务通知"""
    done_ids = [k for k, v in _bg_tasks.items() if v.done]
    results = []
    for bg_id in done_ids:
        t = _bg_tasks.pop(bg_id)
        status = "已完成" if not t.error else "已失败"
        elapsed = time.time() - t.started
        results.append(
            f"<task_notification>后台任务 {bg_id} {status} ({elapsed:.1f}s)\n"
            f"命令: {t.command}\n结果: {t.result[:1000]}\n</task_notification>"
        )
    return results


# ======================== Cron 调度 ========================

@dataclass
class CronJob:
    id: str; name: str; cron_expr: str; prompt: str
    recurring: bool = True; enabled: bool = True
    next_run: str = ""; last_run: str = ""

_cron_jobs: dict[str, CronJob] = {}
_cron_queue: queue.Queue = queue.Queue()
_cron_running = False


def _parse_field(f: str, lo: int, hi: int) -> list[int]:
    if f == "*":
        return list(range(lo, hi + 1))
    vals = []
    for p in f.split(","):
        if "/" in p:
            base, step = p.split("/", 1)
            vals.extend(range(lo if base == "*" else int(base), hi + 1, int(step)))
        elif "-" in p:
            a, b = p.split("-", 1)
            vals.extend(range(int(a), int(b) + 1))
        else:
            vals.append(int(p))
    return vals


def _next_run(expr: str) -> datetime:
    parts = expr.strip().split()
    if len(parts) != 5:
        return datetime.now() + timedelta(hours=1)
    mins, hrs, doms, mons, dows = (
        _parse_field(parts[0], 0, 59), _parse_field(parts[1], 0, 23),
        _parse_field(parts[2], 1, 31), _parse_field(parts[3], 1, 12),
        _parse_field(parts[4], 0, 6),
    )
    c = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(525960):  # 最多查一年
        if (c.minute in mins and c.hour in hrs and c.day in doms
                and c.month in mons and c.weekday() in dows):
            return c
        c += timedelta(minutes=1)
    return datetime.now() + timedelta(hours=1)


def add_job(name: str, cron_expr: str, prompt: str, recurring: bool = True) -> str:
    jid = uuid.uuid4().hex[:8]
    _cron_jobs[jid] = CronJob(id=jid, name=name, cron_expr=cron_expr, prompt=prompt,
                               recurring=recurring, next_run=_next_run(cron_expr).isoformat())
    _save_schedule()
    return jid


def remove_job(jid: str):
    _cron_jobs.pop(jid, None)
    _save_schedule()


def list_jobs() -> list[dict]:
    return [asdict(j) for j in _cron_jobs.values()]


def _save_schedule():
    SCHEDULE_FILE.write_text(json.dumps({k: asdict(v) for k, v in _cron_jobs.items()},
                                        ensure_ascii=False, indent=2), encoding="utf-8")

def _load_schedule():
    global _cron_jobs
    if SCHEDULE_FILE.exists():
        try:
            _cron_jobs = {k: CronJob(**v) for k, v in json.loads(SCHEDULE_FILE.read_text(encoding="utf-8")).items()}
        except Exception:
            _cron_jobs = {}


def _cron_loop():
    while _cron_running:
        now = datetime.now()
        for j in list(_cron_jobs.values()):
            if not j.enabled:
                continue
            try:
                if now >= datetime.fromisoformat(j.next_run):
                    _cron_queue.put(j.prompt)
                    j.last_run = now.isoformat()
                    j.next_run = _next_run(j.cron_expr).isoformat() if j.recurring else ""
                    if not j.recurring:
                        j.enabled = False
                    _save_schedule()
            except Exception:
                pass
        time.sleep(CRON_POLL_INTERVAL)


def start_scheduler() -> threading.Thread:
    global _cron_running
    _load_schedule()
    _cron_running = True
    t = threading.Thread(target=_cron_loop, daemon=True, name="cron")
    t.start()
    return t


def stop_scheduler():
    global _cron_running
    _cron_running = False


def consume_cron() -> list[str]:
    prompts = []
    while not _cron_queue.empty():
        try:
            prompts.append(f"[定时任务] {_cron_queue.get_nowait()}")
        except queue.Empty:
            break
    return prompts


# ======================== 工具处理函数 ========================

def h_todo(todos: list) -> str:
    return update_todos(todos)

def h_create_task(subject: str, blocked_by: list = None) -> str:
    t = create_task(subject, blocked_by)
    return f"已创建任务 {t['id']}: {subject}"

def h_complete_task(task_id: str) -> str:
    t = load_task(task_id)
    if not t:
        return f"[错误] 任务 {task_id} 未找到"
    complete_task(task_id)
    return f"任务 {task_id} 已完成"

def h_list_tasks() -> str:
    tasks = list_tasks()
    if not tasks:
        return "(暂无任务)"
    lines = []
    for t in tasks:
        deps = f" (阻塞: {', '.join(t.get('blockedBy', []))})" if t.get("blockedBy") else ""
        owner = f" [{t['owner']}]" if t.get("owner") else ""
        lines.append(f"  [{t['status']}] {t['id']}: {t['subject']}{owner}{deps}")
    return "\n".join(lines)
