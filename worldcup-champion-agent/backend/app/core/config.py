from functools import lru_cache
import os
from pathlib import Path

class Settings:
    """集中管理后端配置，避免把密钥或环境差异写死在代码里。"""

    def __init__(self) -> None:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        self.app_name = os.getenv("APP_NAME", "世界杯冠军预测 Agent")
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./worldcup_agent.db")
        self.cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        self.dashscope_api_key = os.getenv("DASHSCOPE_API_KEY") or None
        self.qwen_api_key = os.getenv("QWEN_API_KEY") or None
        self.qwen_model = os.getenv("QWEN_MODEL", "qwen-plus")
        self.dashscope_base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.llm_enabled = os.getenv("LLM_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.llm_api_key = os.getenv("LLM_API_KEY") or self.qwen_api_key or self.dashscope_api_key
        self.llm_base_url = os.getenv("LLM_BASE_URL", self.dashscope_base_url).rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL", self.qwen_model)
        self.llm_agent_names = [
            item.strip()
            for item in os.getenv(
                "LLM_AGENT_NAMES",
                "PlannerAgent,DataScoutAgent,FootballAnalystAgent,NarratorAgent,CriticAgent",
            ).split(",")
            if item.strip()
        ]
        self.llm_timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
        self.llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.25"))
        self.llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "900"))
        self.match_prediction_concurrency = int(os.getenv("MATCH_PREDICTION_CONCURRENCY", "8"))
        self.default_monte_carlo_runs = int(os.getenv("DEFAULT_MONTE_CARLO_RUNS", "1000"))
        self.my_claude_runtime_enabled = os.getenv("MY_CLAUDE_RUNTIME_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.bocha_api_key = os.getenv("BOCHA_API_KEY") or None
        self.redis_enabled = os.getenv("REDIS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_key_prefix = os.getenv("REDIS_KEY_PREFIX", "worldcup-agent")
        self.redis_default_ttl_seconds = int(os.getenv("REDIS_DEFAULT_TTL_SECONDS", "900"))
        self.cache_enabled = os.getenv("CACHE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.cache_backend = os.getenv("CACHE_BACKEND", "auto").strip().lower()
        self.cache_teams_ttl_seconds = int(os.getenv("CACHE_TEAMS_TTL_SECONDS", "43200"))
        self.cache_ratings_ttl_seconds = int(os.getenv("CACHE_RATINGS_TTL_SECONDS", "43200"))
        self.cache_matches_ttl_seconds = int(os.getenv("CACHE_MATCHES_TTL_SECONDS", "900"))
        self.cache_match_detail_ttl_seconds = int(os.getenv("CACHE_MATCH_DETAIL_TTL_SECONDS", "300"))
        self.cache_prematch_ttl_seconds = int(os.getenv("CACHE_PREMATCH_TTL_SECONDS", "900"))
        self.cache_postmatch_ttl_seconds = int(os.getenv("CACHE_POSTMATCH_TTL_SECONDS", "86400"))
        self.checkpoint_ttl_seconds = int(os.getenv("CHECKPOINT_TTL_SECONDS", "86400"))
        self.checkpoint_running_timeout_seconds = int(os.getenv("CHECKPOINT_RUNNING_TIMEOUT_SECONDS", "1800"))
        self.scheduler_enabled = os.getenv("SCHEDULER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.scheduler_poll_seconds = int(os.getenv("SCHEDULER_POLL_SECONDS", "300"))
        self.pre_match_update_minutes = int(os.getenv("PRE_MATCH_UPDATE_MINUTES", "30"))
        self.pre_match_include_web = os.getenv("PRE_MATCH_INCLUDE_WEB", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.post_match_result_hours = int(os.getenv("POST_MATCH_RESULT_HOURS", "3"))
        self.post_match_include_web = os.getenv("POST_MATCH_INCLUDE_WEB", "true").strip().lower() in {"1", "true", "yes", "on"}

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置转换为 FastAPI 可用的列表。"""

        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次请求重复读取环境变量。"""

    return Settings()
