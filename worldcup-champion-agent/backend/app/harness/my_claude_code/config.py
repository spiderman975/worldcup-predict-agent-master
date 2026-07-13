"""
全局配置 — 所有模块共享的常量
"""

from pathlib import Path
import os


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


MODULE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = MODULE_DIR.parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

_load_env_file(BACKEND_DIR / ".env")

# ==================== 模型 ====================
MODEL = os.getenv("LLM_MODEL") or os.getenv("QWEN_MODEL", "qwen-plus")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL") or os.getenv("QWEN_FALLBACK_MODEL", "qwen-turbo")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
ESCALATED_MAX_TOKENS = int(os.getenv("AGENT_ESCALATED_MAX_TOKENS", "16384"))
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or os.getenv("DASHSCOPE_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
).rstrip("/")

# ==================== 工作目录 ====================
WORKDIR = Path(os.getenv("MY_CLAUDE_CODE_WORKDIR", str(PROJECT_ROOT))).resolve()

# ==================== 错误恢复 ====================
MAX_RECOVERY_RETRIES = 3
MAX_RETRIES = 10
BASE_DELAY_MS = 500

# ==================== 上下文压缩 ====================
CONTEXT_TOKEN_THRESHOLD = 150_000
MAX_MESSAGES = 50
KEEP_RECENT_TOOL_RESULTS = 3
TOOL_RESULT_BUDGET = 200_000

# ==================== Memory ====================
CONSOLIDATE_THRESHOLD = 10

# ==================== 后台 / 调度 ====================
MAX_BACKGROUND_THREADS = 5
CRON_POLL_INTERVAL = 1

# ==================== 自主 Agent ====================
IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
SUBAGENT_MAX_TURNS = 30

# ==================== 数据目录 ====================
DATA_DIR = Path(os.getenv("MY_CLAUDE_CODE_DATA_DIR", str(WORKDIR / ".agent_data"))).resolve()
MEMORY_DIR = DATA_DIR / "memory"
TASKS_DIR = DATA_DIR / "tasks"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
MAILBOX_DIR = DATA_DIR / "mailboxes"
WORKTREES_DIR = DATA_DIR / "worktrees"
SKILLS_DIR = DATA_DIR / "skills"
TOOL_OUTPUTS_DIR = DATA_DIR / "tool_outputs"

for _d in [DATA_DIR, MEMORY_DIR, TASKS_DIR, TRANSCRIPTS_DIR,
           MAILBOX_DIR, WORKTREES_DIR, SKILLS_DIR, TOOL_OUTPUTS_DIR]:
    os.makedirs(_d, exist_ok=True)
