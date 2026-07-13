"""Optional Redis integration for cache, checkpoints, sessions, and locks."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import get_settings

logger = logging.getLogger(__name__)

try:
    import redis
except Exception:  # pragma: no cover - depends on optional runtime package
    redis = None  # type: ignore[assignment]


class RedisClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.redis_enabled and redis is not None)

    @property
    def client(self) -> Any | None:
        if not self.enabled:
            return None
        if self._client is None:
            self._client = redis.Redis.from_url(self.settings.redis_url, decode_responses=True)
        return self._client

    def key(self, *parts: str) -> str:
        return ":".join([self.settings.redis_key_prefix, *[str(part).strip(":") for part in parts]])

    def health(self) -> dict[str, Any]:
        if not self.settings.redis_enabled:
            return {"enabled": False, "connected": False, "reason": "REDIS_ENABLED=false"}
        if redis is None:
            return {"enabled": True, "connected": False, "reason": "python redis package is not installed"}
        try:
            assert self.client is not None
            self.client.ping()
            return {"enabled": True, "connected": True, "url": self.settings.redis_url}
        except Exception as exc:
            return {"enabled": True, "connected": False, "reason": str(exc)}

    def get(self, key: str) -> Any | None:
        if not self.client:
            return None
        try:
            raw = self.client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("Redis get failed: %s", exc)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> bool:
        if not self.client:
            return False
        ttl = ttl_seconds or self.settings.redis_default_ttl_seconds
        try:
            self.client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
            return True
        except Exception as exc:
            logger.warning("Redis set failed: %s", exc)
            return False

    def delete(self, key: str) -> bool:
        if not self.client:
            return False
        try:
            self.client.delete(key)
            return True
        except Exception as exc:
            logger.warning("Redis delete failed: %s", exc)
            return False

    @contextmanager
    def lock(self, name: str, ttl_seconds: int = 60) -> Iterator[bool]:
        key = self.key("lock", name)
        acquired = False
        if self.client:
            try:
                acquired = bool(self.client.set(key, "1", nx=True, ex=ttl_seconds))
            except Exception as exc:
                logger.warning("Redis lock failed: %s", exc)
        try:
            yield acquired or not self.client
        finally:
            if acquired:
                self.delete(key)


redis_client = RedisClient()
