"""Small reliability primitives for harness-facing external calls."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a dependency is temporarily blocked by the circuit breaker."""


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None
    lock: Lock = field(default_factory=Lock)

    def before_call(self) -> None:
        with self.lock:
            if self.opened_at is None:
                return
            if time.monotonic() - self.opened_at >= self.recovery_seconds:
                self.opened_at = None
                self.failures = 0
                return
            raise CircuitOpenError(f"{self.name} 熔断中，请稍后重试")

    def record_success(self) -> None:
        with self.lock:
            self.failures = 0
            self.opened_at = None

    def record_failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.monotonic()


class DeadLetterQueue:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()

    def record(self, *, dependency: str, payload: dict[str, Any], error: BaseException) -> None:
        item = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dependency": dependency,
            "payload": payload,
            "error_type": type(error).__name__,
            "error": str(error),
        }
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")


PROJECT_ROOT = Path(__file__).resolve().parents[3]
dead_letter_queue = DeadLetterQueue(PROJECT_ROOT / "data" / "dead_letters" / "harness.jsonl")
_breakers: dict[str, CircuitBreaker] = {}


def breaker_for(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


def resilient_call(
    dependency: str,
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.25,
    payload: dict[str, Any] | None = None,
) -> T:
    breaker = breaker_for(dependency)
    last_error: BaseException | None = None
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            breaker.before_call()
            result = fn()
            breaker.record_success()
            return result
        except Exception as exc:
            last_error = exc
            breaker.record_failure()
            if attempt < attempts and not isinstance(exc, CircuitOpenError):
                time.sleep(base_delay_seconds * (2 ** (attempt - 1)))
                continue
            dead_letter_queue.record(dependency=dependency, payload=payload or {}, error=exc)
            raise
    assert last_error is not None
    dead_letter_queue.record(dependency=dependency, payload=payload or {}, error=last_error)
    raise last_error
