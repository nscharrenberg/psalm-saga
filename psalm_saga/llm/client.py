"""The single entry point every stage uses to talk to a model.

    text  = await llm.text("draft", system, [Part(bible, cache=True), Part(task)], hints=...)
    plan  = await llm.json("plan", system, parts, Plan)

Responsibilities kept out of the stages:
  * role -> model resolution (per-stage model swapping for experiments)
  * admission control (concurrency, RPM/TPM, shared 429 cooldown)
  * retries with Retry-After, jittered exponential backoff and a hard per-call timeout
  * streaming accumulation, and automatic continuation when output hits max_tokens
  * prompt-cache markers on the stable context prefix
  * structured output: schema in prompt, tolerant parsing, validation-repair round trips
  * on-disk response cache (instant resume and reproducible reruns)
  * token / cost accounting and an optional run budget
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from psalm_saga.config import ModelConfig, PipelineConfig
from psalm_saga.llm.fake import FakeBackend
from psalm_saga.llm.jsonutil import extract_json, schema_text
from psalm_saga.llm.limiter import GLOBAL_LIMITERS, LimiterRegistry, retry_after_seconds

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


def _preview(content, n: int = 160) -> str:
    """The start of an answer, on one line, for the live activity view."""
    return " ".join(str(content or "").split())[:n]


class LLMError(RuntimeError):
    pass


@dataclass
class Part:
    text: str
    cache: bool = False  # stable prefix (bible, spec) — reused across calls


_BUCKET_KEYS = ("calls", "cached_calls", "prompt_tokens", "completion_tokens", "cache_read_tokens", "cost_usd",
                "llm_seconds", "retries", "unpriced_calls")


def _bucket() -> dict[str, float]:
    return dict.fromkeys(_BUCKET_KEYS, 0)


@dataclass
class Usage:
    """Token, cost and model-time accounting for one pipeline invocation.

    `llm_seconds` sums the duration of every call; calls run in parallel, so it can exceed
    wall-clock time (wall-clock per stage is tracked by the pipeline in run.json).
    Cache hits cost nothing; what they *would* have cost on a first run is kept in the
    `replayed_*` fields so cost comparisons survive resumes and reruns.
    """

    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    retries: int = 0
    llm_seconds: float = 0.0
    unpriced_calls: int = 0  # calls whose model had no known or configured price (cost counted as 0)
    replayed_prompt_tokens: int = 0
    replayed_completion_tokens: int = 0
    replayed_cost_usd: float = 0.0
    by_tag: dict[str, dict[str, float]] = field(default_factory=dict)
    by_stage: dict[str, dict[str, float]] = field(default_factory=dict)

    current_stage: str | None = None  # set by the pipeline while a stage runs; else the tag prefix is used

    def _buckets(self, tag: str) -> list[dict[str, float]]:
        tag = tag or "other"
        stage = self.current_stage or tag.split(":", 1)[0]
        return [self.by_tag.setdefault(tag, _bucket()), self.by_stage.setdefault(stage, _bucket())]

    def add(self, tag: str, p: int, c: int, cost: float | None, secs: float, cached: bool = False, cache_read: int = 0):
        unpriced = cost is None and not cached
        cost = cost or 0.0
        self.calls += 1
        self.cached_calls += int(cached)
        self.prompt_tokens += p
        self.completion_tokens += c
        self.cache_read_tokens += cache_read
        self.cost_usd += cost
        self.llm_seconds += secs
        self.unpriced_calls += int(unpriced)
        for b in self._buckets(tag):
            b["calls"] += 1
            b["cached_calls"] += int(cached)
            b["prompt_tokens"] += p
            b["completion_tokens"] += c
            b["cache_read_tokens"] += cache_read
            b["cost_usd"] += cost
            b["llm_seconds"] += secs
            b["unpriced_calls"] += int(unpriced)

    def add_replayed(self, p: int, c: int, cost: float | None) -> None:
        self.replayed_prompt_tokens += p
        self.replayed_completion_tokens += c
        self.replayed_cost_usd += cost or 0.0

    def add_retry(self, tag: str) -> None:
        self.retries += 1
        for b in self._buckets(tag):
            b["retries"] += 1

    def to_dict(self) -> dict:
        def rnd(v):
            if isinstance(v, float):
                return round(v, 6)
            if isinstance(v, dict):
                return {k: rnd(x) for k, x in v.items()}
            return v

        return {k: rnd(v) for k, v in self.__dict__.items() if k != "current_stage"}


_RETRYABLE_NAMES = {
    "RateLimitError", "Timeout", "APIConnectionError", "InternalServerError", "ServiceUnavailableError",
    "BadGatewayError", "APIError", "TimeoutError", "ReadTimeout", "ConnectTimeout", "RemoteProtocolError",
}
_FATAL_NAMES = {"AuthenticationError", "PermissionDeniedError", "NotFoundError", "ContextWindowExceededError",
                "ContentPolicyViolationError", "BudgetExceededError", "UnsupportedParamsError"}


def _is_retryable(exc: BaseException) -> bool:
    names = {c.__name__ for c in type(exc).__mro__}
    if names & _FATAL_NAMES:
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in (408, 409, 425, 429) or status >= 500
    return bool(names & _RETRYABLE_NAMES) or isinstance(exc, asyncio.TimeoutError | ConnectionError)


def _is_rate_limit(exc: BaseException) -> bool:
    return getattr(exc, "status_code", None) == 429 or "RateLimit" in type(exc).__name__ or "rate limit" in str(exc).lower()


def _join(a: str, b: str) -> str:
    """Join a continuation; add a space when both sides are word characters."""
    if a and b and not a[-1].isspace() and not b[0].isspace() and a[-1].isalnum() and b[0].isalnum():
        return f"{a} {b}"
    return a + b


def _wants_cache_markers(model: str) -> bool:
    m = model.lower()
    return m.startswith(("anthropic/", "bedrock/anthropic", "vertex_ai/claude")) or m.startswith("claude")


class LLM:
    def __init__(
        self,
        config: PipelineConfig,
        *,
        cache_dir: Path | None = None,
        on_event: Callable[[dict], None] | None = None,
        limiters: LimiterRegistry = GLOBAL_LIMITERS,
        call_log: Callable[[str, dict], None] | None = None,
    ):
        self.config = config
        self.cache_dir = Path(cache_dir) if (cache_dir and config.cache) else None
        self.on_event = on_event or (lambda e: None)
        self.call_log = call_log
        self._reasoning: dict[str, bool] = {}  # model name -> reasons before answering
        self.limiters = limiters
        self.usage = Usage()
        self._fake = FakeBackend(seed=config.seed or 0)

    # ------------------------------------------------------------------ public API

    async def text(
        self,
        role: str,
        system: str,
        parts: list[Part],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        hints: dict | None = None,
        tag: str = "",
        continuations: int = 2,
    ) -> str:
        messages = self._messages(role, system, parts)
        out = await self._call(role, messages, None, max_tokens, temperature, hints or {}, tag)
        content, finish = out["content"], out.get("finish_reason")
        if finish == "length" and not content.strip():
            # Nothing visible came back: the allowance went to hidden reasoning. Asking to "continue"
            # an empty answer does not help; ask again with room to spare.
            mc = self.config.model_for(role)
            bigger = min(max(4 * (max_tokens or mc.min_output_tokens), 4 * mc.min_output_tokens), mc.max_output_tokens)
            self.on_event({"type": "llm_retry", "tag": tag, "model": mc.name, "attempt": 1, "wait_s": 0,
                           "error": f"empty answer at the output limit; retrying with {bigger} tokens"})
            out = await self._call(role, messages, None, bigger, temperature, hints or {}, f"{tag}:roomier")
            content, finish = out["content"], out.get("finish_reason")
        # Hit the output cap mid-prose: ask the model to continue rather than failing.
        while finish == "length" and continuations > 0:
            continuations -= 1
            messages = [*messages, {"role": "assistant", "content": content},
                        {"role": "user", "content": "Continue exactly where you stopped. Do not repeat anything; no preamble."}]
            more = await self._call(role, messages, None, max_tokens, temperature, hints or {}, f"{tag}:continue")
            content, finish = _join(content, more["content"]), more.get("finish_reason")
        return content.strip()

    async def json(
        self,
        role: str,
        system: str,
        parts: list[Part],
        schema: type[T],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        hints: dict | None = None,
        tag: str = "",
        repairs: int = 2,
    ) -> T:
        instruction = (
            "Respond with a single JSON object that validates against this JSON Schema. "
            "No prose before or after it, no markdown fences.\nSCHEMA: " + schema_text(schema)
        )
        messages = self._messages(role, system, [*parts, Part(instruction)])
        last_err: Exception | None = None
        for attempt in range(repairs + 1):
            out = await self._call(role, messages, schema, max_tokens, temperature, hints or {}, tag,
                                   use_cache=attempt == 0)
            raw = out["content"]
            try:
                return schema.model_validate(extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_err = exc
                truncated = out.get("finish_reason") == "length"
                fix = ("Your JSON was cut off by the output limit. Return a complete but more concise object."
                       if truncated else f"That output did not validate: {str(exc)[:1500]}\nReturn the corrected JSON object only.")
                messages = [*messages, {"role": "assistant", "content": raw[-6000:]}, {"role": "user", "content": fix}]
                self.on_event({"type": "llm_repair", "tag": tag, "attempt": attempt + 1, "error": str(exc)[:300]})
        raise LLMError(f"{tag or role}: model output never matched {schema.__name__}: {last_err}")

    # ------------------------------------------------------------------ internals

    def _messages(self, role: str, system: str, parts: list[Part]) -> list[dict]:
        mc = self.config.model_for(role)
        if mc.prompt_cache and _wants_cache_markers(mc.name) and any(p.cache for p in parts):
            last_cached = max(i for i, p in enumerate(parts) if p.cache)
            content = []
            for i, p in enumerate(parts):
                block: dict[str, Any] = {"type": "text", "text": p.text}
                if i == last_cached:
                    block["cache_control"] = {"type": "ephemeral"}
                content.append(block)
            sys_block = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            return [{"role": "system", "content": sys_block}, {"role": "user", "content": content}]
        return [{"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(p.text for p in parts if p.text)}]

    def _cache_key(self, mc: ModelConfig, messages, schema, max_tokens, temperature, hints) -> str:
        blob = json.dumps(
            [mc.name, messages, schema.__name__ if schema else None, max_tokens, temperature,
             mc.extra, self.config.seed, hints.get("variant")],
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        if not self.cache_dir:
            return None
        p = self.cache_dir / key[:2] / f"{key}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _cache_put(self, key: str, value: dict) -> None:
        if not self.cache_dir or value.get("finish_reason") == "error":
            return
        p = self.cache_dir / key[:2] / f"{key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def _check_budget(self) -> None:
        cap = self.config.limits.max_cost_usd
        if cap is not None and self.usage.cost_usd >= cap:
            raise BudgetExceeded(f"Run budget of ${cap:.2f} reached (spent ${self.usage.cost_usd:.2f})")

    def is_reasoning(self, mc: ModelConfig) -> bool:
        if mc.reasoning is not None:
            return mc.reasoning
        if mc.name not in self._reasoning:
            if mc.name.startswith("fake/"):
                self._reasoning[mc.name] = bool(mc.extra.get("fake_reasoning_tokens"))
            else:
                try:
                    import litellm

                    self._reasoning[mc.name] = bool(litellm.supports_reasoning(model=mc.name))
                except Exception:
                    self._reasoning[mc.name] = False
        return self._reasoning[mc.name]

    def allowance(self, mc: ModelConfig, visible: int | None) -> int:
        """Output tokens to allow: what the visible answer needs, plus headroom for a reasoning model."""
        want = visible or mc.max_output_tokens
        cap = mc.max_output_tokens
        if self.is_reasoning(mc):
            want += mc.reasoning_headroom
            cap = max(cap, want)
            try:  # never above what the provider accepts
                import litellm

                if (prov := litellm.get_max_tokens(mc.name)) and prov > 0:
                    cap = min(cap, int(prov))
            except Exception:
                pass
        return min(max(want, mc.min_output_tokens), cap)

    def _log(self, call_id: str, record: dict) -> None:
        if self.call_log is not None:
            try:
                self.call_log(call_id, record)
            except Exception:  # a log must never break a run
                pass

    async def _call(self, role, messages, schema, max_tokens, temperature, hints, tag, use_cache=True) -> dict:
        mc = self.config.model_for(role)
        max_tokens = self.allowance(mc, max_tokens)
        temperature = mc.temperature if temperature is None else temperature
        key = self._cache_key(mc, messages, schema, max_tokens, temperature, hints)
        call_id = uuid.uuid4().hex[:12]
        base = {"id": call_id, "tag": tag, "role": role, "model": mc.name, "max_tokens": max_tokens,
                "temperature": temperature, "schema": getattr(schema, "__name__", None), "messages": messages}
        if use_cache and (hit := self._cache_get(key)) is not None:
            self.usage.add(tag, 0, 0, 0.0, 0.0, cached=True)
            hu = hit.get("usage", {})
            hp, hc = int(hu.get("prompt_tokens", 0)), int(hu.get("completion_tokens", 0))
            self.usage.add_replayed(hp, hc, self._cost(mc, hp, hc, int(hu.get("cached_tokens", 0))))
            self._log(call_id, {**base, "status": "cached", "started": time.time(), "content": hit.get("content"),
                                "reasoning": hit.get("reasoning"), "finish": hit.get("finish_reason"), "usage": hu})
            self.on_event({"type": "llm_call", "tag": tag, "model": mc.name, "cached": True, "call": call_id,
                           "preview": _preview(hit.get("content"))})
            return hit
        self._check_budget()

        est = sum(len(json.dumps(m["content"], ensure_ascii=False)) for m in messages) // 4 + max_tokens
        limiter = self.limiters.get(mc.name, mc.max_concurrency, mc.rpm, mc.tpm)
        delay = 2.0
        for attempt in range(mc.max_retries + 1):
            await limiter.acquire(est)
            t0 = time.monotonic()
            # Lets a live view show calls in flight (one line per call; negligible next to the call itself).
            started = time.time()
            self._log(call_id, {**base, "status": "running", "attempt": attempt + 1, "started": started})
            self.on_event({"type": "llm_start", "tag": tag, "model": mc.name, "attempt": attempt + 1,
                           "max_tokens": max_tokens, "call": call_id})
            try:
                out = await asyncio.wait_for(
                    self._backend(mc, messages, schema, max_tokens, temperature, hints), timeout=mc.timeout_s
                )
            except BaseException as exc:
                limiter.release()
                if isinstance(exc, asyncio.CancelledError) or not _is_retryable(exc) or attempt == mc.max_retries:
                    if isinstance(exc, asyncio.CancelledError):
                        self._log(call_id, {**base, "status": "cancelled", "attempt": attempt + 1, "started": started})
                        raise
                    self._log(call_id, {**base, "status": "failed", "attempt": attempt + 1, "started": started,
                                        "error": f"{type(exc).__name__}: {exc}"[:2000]})
                    raise LLMError(f"{tag or role} via {mc.name}: {type(exc).__name__}: {exc}") from exc
                hinted = retry_after_seconds(exc)
                wait = (hinted + 0.5) if hinted is not None else delay * random.uniform(0.7, 1.3)
                if _is_rate_limit(exc):
                    limiter.penalize(wait)
                self.usage.add_retry(tag)
                self._log(call_id, {**base, "status": "retrying", "attempt": attempt + 1, "started": started,
                                    "error": f"{type(exc).__name__}: {exc}"[:2000], "wait_s": round(wait, 1)})
                self.on_event({"type": "llm_retry", "tag": tag, "model": mc.name, "attempt": attempt + 1, "call": call_id,
                               "wait_s": round(wait, 1), "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                await asyncio.sleep(wait)
                delay = min(delay * 2, 120.0)
                continue
            limiter.release()
            secs = time.monotonic() - t0
            u = out.get("usage", {})
            p, c = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
            cache_read = int(u.get("cached_tokens", 0))
            cost = self._cost(mc, p, c, cache_read)
            self.usage.add(tag, p, c, cost, secs, cache_read=cache_read)
            rt = int(u.get("reasoning_tokens", 0) or 0)
            if rt and mc.reasoning is None and not self._reasoning.get(mc.name):
                self._reasoning[mc.name] = True  # seen reasoning: later calls get headroom
                self.on_event({"type": "warning", "message": f"{mc.name} reasons before answering ({rt} tokens on "
                               f"{tag}); later calls get {mc.reasoning_headroom} tokens of headroom for it"})
            self._log(call_id, {**base, "status": "done", "attempt": attempt + 1, "started": started,
                                "seconds": round(secs, 2), "content": out.get("content"), "reasoning": out.get("reasoning"),
                                "finish": out.get("finish_reason"), "usage": u,
                                "cost_usd": None if cost is None else round(cost, 6)})
            self.on_event({"type": "llm_call", "tag": tag, "model": mc.name, "prompt_tokens": p, "call": call_id,
                           "completion_tokens": c, "reasoning_tokens": rt, "cache_read_tokens": cache_read,
                           "seconds": round(secs, 2), "max_tokens": max_tokens,
                           "cost_usd": None if cost is None else round(cost, 6), "finish": out.get("finish_reason"),
                           "preview": _preview(out.get("content"))})
            self._cache_put(key, out)
            return out
        raise LLMError("unreachable")

    @staticmethod
    def _cost(mc: ModelConfig, p: int, c: int, cache_read: int = 0) -> float | None:
        """USD cost of one call. Configured prices win; else LiteLLM's price table; None if unknown."""
        if mc.input_cost_per_mtok is not None or mc.output_cost_per_mtok is not None:
            cached_price = mc.cached_input_cost_per_mtok
            if cached_price is None:
                cached_price = mc.input_cost_per_mtok or 0.0
            fresh = max(p - cache_read, 0)
            return (fresh * (mc.input_cost_per_mtok or 0.0) + cache_read * cached_price
                    + c * (mc.output_cost_per_mtok or 0.0)) / 1_000_000
        if mc.name.startswith("fake/"):
            return 0.0
        try:
            import litellm

            a, b = litellm.cost_per_token(model=mc.name, prompt_tokens=p, completion_tokens=c)
            return float(a + b)
        except Exception:
            return None

    async def _backend(self, mc: ModelConfig, messages, schema, max_tokens, temperature, hints) -> dict:
        if mc.name.startswith("fake/"):
            return await self._fake.complete(messages=messages, schema=schema, hints=hints, extra=mc.extra)

        import litellm

        litellm.drop_params = True  # tolerate provider-specific unsupported params (e.g. temperature on reasoning models)
        litellm.suppress_debug_info = True
        kwargs: dict[str, Any] = {"model": mc.name, "messages": messages, "max_tokens": max_tokens,
                                  "timeout": mc.timeout_s, "num_retries": 0, **mc.extra}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.config.seed is not None:
            kwargs["seed"] = self.config.seed
        if schema is not None and mc.extra.get("json_mode", True):
            kwargs.pop("json_mode", None)
            try:
                if litellm.supports_response_schema(model=mc.name) or mc.name.startswith(("openai/", "gpt")):
                    kwargs["response_format"] = {"type": "json_object"}
            except Exception:
                pass
        else:
            kwargs.pop("json_mode", None)

        if mc.stream:
            resp = await litellm.acompletion(stream=True, stream_options={"include_usage": True}, **kwargs)
            chunks: list[str] = []
            thinking: list[str] = []
            finish, usage = None, None
            async for chunk in resp:
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if chunk.choices:
                    ch = chunk.choices[0]
                    delta = getattr(ch.delta, "content", None)
                    if delta:
                        chunks.append(delta)
                    rdelta = getattr(ch.delta, "reasoning_content", None)
                    if rdelta:
                        thinking.append(rdelta)
                    if ch.finish_reason:
                        finish = ch.finish_reason
            content = "".join(chunks)
            reasoning = "".join(thinking)
        else:
            resp = await litellm.acompletion(**kwargs)
            content = resp.choices[0].message.content or ""
            reasoning = getattr(resp.choices[0].message, "reasoning_content", None) or ""
            finish, usage = resp.choices[0].finish_reason, resp.usage
        p = getattr(usage, "prompt_tokens", None) or sum(len(str(m["content"])) for m in messages) // 4
        c = getattr(usage, "completion_tokens", None) or len(content) // 4
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or getattr(usage, "cache_read_input_tokens", 0) or 0
        if finish in ("max_tokens",):
            finish = "length"
        cdet = getattr(usage, "completion_tokens_details", None)
        rtok = getattr(cdet, "reasoning_tokens", 0) or 0
        return {"content": content, "finish_reason": finish, **({"reasoning": reasoning} if reasoning else {}),
                "usage": {"prompt_tokens": p, "completion_tokens": c, "cached_tokens": cached, "reasoning_tokens": rtok}}
