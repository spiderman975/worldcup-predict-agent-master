"""Unified API cache with Redis-first and in-memory fallback backends."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from app.core.config import get_settings
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class MemoryCacheEntry:
    value: Any
    expires_at: float


class CacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._memory: dict[str, MemoryCacheEntry] = {}
        self._redis_available: bool | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.cache_enabled)

    def backend(self) -> str:
        if not self.enabled:
            return "disabled"
        configured = self.settings.cache_backend
        if configured == "memory":
            return "memory"
        if configured == "redis":
            return "redis" if self._redis_healthy() else "memory"
        return "redis" if self._redis_healthy() else "memory"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured_backend": self.settings.cache_backend,
            "active_backend": self.backend(),
            "redis": redis_client.health(),
            "memory_keys": len(self._memory),
        }

    def key(self, *parts: str) -> str:
        return ":".join(str(part).strip(":") for part in parts if str(part).strip(":"))

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        if self.backend() == "redis":
            namespaced = self._redis_key(key)
            value = redis_client.get(namespaced)
            if value is not None:
                return value
        return self._memory_get(key)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> Any:
        if not self.enabled:
            return value
        ttl = int(ttl_seconds or self.settings.redis_default_ttl_seconds)
        if self.backend() == "redis":
            ok = redis_client.set(self._redis_key(key), value, ttl_seconds=ttl)
            if ok:
                return value
            logger.warning("Redis cache write failed, falling back to memory cache for key=%s", key)
            self._redis_available = False
        self._memory[key] = MemoryCacheEntry(value=value, expires_at=time.time() + ttl)
        return value

    def remember(self, key: str, ttl_seconds: int, loader: Callable[[], T]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = loader()
        self.set(key, value, ttl_seconds)
        return value

    def delete(self, key: str) -> int:
        deleted = 0
        if key in self._memory:
            self._memory.pop(key, None)
            deleted += 1
        if self.backend() == "redis":
            deleted += 1 if redis_client.delete(self._redis_key(key)) else 0
        return deleted

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        for key in list(self._memory):
            if key.startswith(prefix):
                self._memory.pop(key, None)
                deleted += 1
        if self.backend() == "redis":
            deleted += redis_client.delete_prefix(self._redis_key(prefix))
        return deleted

    def invalidate_teams(self) -> int:
        return self.delete_prefix("teams:")

    def invalidate_matches(self, match_id: str | None = None) -> int:
        deleted = self.delete("matches:list") + self.delete("matches:schedule")
        if match_id:
            deleted += self.delete(self.key("match", "detail", match_id.lower()))
            deleted += self.delete(self.key("postmatch", match_id.lower()))
            return deleted
        deleted += self.delete_prefix("match:detail:")
        return deleted

    def _redis_healthy(self) -> bool:
        if self._redis_available is not None:
            return self._redis_available
        if not self.settings.redis_enabled:
            self._redis_available = False
            return False
        health = redis_client.health()
        self._redis_available = bool(health.get("connected"))
        return self._redis_available

    def _redis_key(self, key: str) -> str:
        return redis_client.key("cache", key)

    def _memory_get(self, key: str) -> Any | None:
        entry = self._memory.get(key)
        if not entry:
            return None
        if entry.expires_at <= time.time():
            self._memory.pop(key, None)
            return None
        return entry.value


cache_service = CacheService()
