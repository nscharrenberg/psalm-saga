"""Per-model admission control shared by every concurrent call in a process.

Three mechanisms, all per model id:
  * a concurrency semaphore,
  * token buckets for requests/min and tokens/min (when the provider tier is known),
  * a shared cooldown: when any call gets a 429 with a Retry-After hint, *every*
    call to that model waits until the cooldown passes instead of each one
    discovering the limit separately and hammering the endpoint.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field

_RETRY_RE = re.compile(
    r"(?:try again|retry)(?: after| in)?\s*([\d.]+)\s*(ms|milliseconds|s|sec|seconds|m|min|minutes)?",
    re.IGNORECASE,
)
_UNITS = {"ms": 0.001, "milliseconds": 0.001, "s": 1, "sec": 1, "seconds": 1, "m": 60, "min": 60, "minutes": 60}


def retry_after_seconds(exc: BaseException) -> float | None:
    """Provider-suggested wait, from a Retry-After header or the error message."""
    for attr in ("response", "litellm_response"):
        headers = getattr(getattr(exc, attr, None), "headers", None)
        if headers:
            for key in ("retry-after-ms", "retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
                val = headers.get(key)
                if val:
                    try:
                        sec = float(str(val).rstrip("s"))
                        return sec / 1000 if key.endswith("-ms") else sec
                    except ValueError:
                        pass
    m = _RETRY_RE.search(str(exc))
    if m:
        return float(m.group(1)) * _UNITS.get((m.group(2) or "s").lower(), 1)
    return None


class _Bucket:
    def __init__(self, per_minute: int):
        self.capacity = float(per_minute)
        self.tokens = float(per_minute)
        self.rate = per_minute / 60.0
        self.stamp = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now

    def wait_time(self, amount: float) -> float:
        self._refill()
        amount = min(amount, self.capacity)
        if self.tokens >= amount:
            self.tokens -= amount
            return 0.0
        return (amount - self.tokens) / self.rate

    def refund(self, amount: float) -> None:
        self.tokens = min(self.capacity, self.tokens + amount)


@dataclass
class ModelLimiter:
    max_concurrency: int = 4
    rpm: int | None = None
    tpm: int | None = None
    _sem: asyncio.Semaphore | None = None
    _lock: asyncio.Lock | None = None
    _rpm: _Bucket | None = None
    _tpm: _Bucket | None = None
    cooldown_until: float = 0.0
    stats: dict = field(default_factory=lambda: {"rate_limited": 0, "waited_s": 0.0})

    def __post_init__(self) -> None:
        self._rpm = _Bucket(self.rpm) if self.rpm else None
        self._tpm = _Bucket(self.tpm) if self.tpm else None

    def _ensure(self) -> None:
        # Created lazily so the limiter can be built outside a running loop.
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.max_concurrency)
            self._lock = asyncio.Lock()

    async def acquire(self, est_tokens: int) -> None:
        self._ensure()
        await self._sem.acquire()
        try:
            while True:
                async with self._lock:
                    wait = max(0.0, self.cooldown_until - time.monotonic())
                    if wait == 0 and self._rpm:
                        wait = self._rpm.wait_time(1)
                    if wait == 0 and self._tpm:
                        wait = self._tpm.wait_time(est_tokens)
                        if wait and self._rpm:
                            self._rpm.refund(1)
                if wait <= 0:
                    return
                self.stats["waited_s"] += wait
                await asyncio.sleep(wait + random.uniform(0, 0.25))
        except BaseException:
            self._sem.release()
            raise

    def release(self) -> None:
        if self._sem is not None:
            self._sem.release()

    def penalize(self, seconds: float) -> None:
        self.stats["rate_limited"] += 1
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + seconds)


class LimiterRegistry:
    def __init__(self) -> None:
        self._by_model: dict[str, ModelLimiter] = {}

    def get(self, model: str, max_concurrency: int, rpm: int | None, tpm: int | None) -> ModelLimiter:
        if model not in self._by_model:
            self._by_model[model] = ModelLimiter(max_concurrency=max_concurrency, rpm=rpm, tpm=tpm)
        return self._by_model[model]

    def stats(self) -> dict[str, dict]:
        return {m: dict(lim.stats) for m, lim in self._by_model.items()}


GLOBAL_LIMITERS = LimiterRegistry()
