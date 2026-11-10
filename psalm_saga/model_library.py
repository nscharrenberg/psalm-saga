"""The model library: every model is described once, then chosen by name for any task.

A model's description holds everything that belongs to the model and its endpoint: the LiteLLM id,
the address of a self-hosted server, how much it reasons, its context and output limits, how many
calls it takes at once, and its price. What belongs to a *task* (the temperature of analysis, the
judges' temperature 0, which model writes and which one judges) is set where the task is, by
choosing a library model:

    models.default.use: mistral-large-4          # the writer
    models.extract.use: claude-sonnet-5-5        # analysis on another model (optional)
    judges.model: claude-sonnet-5-5              # the primary judge
    judges.panel: [gpt-6-luna, qwen3.5-397b]     # further judges

Built-in entries cover the models of the paper's experiments and an offline test model; entries
the user adds or edits are kept on their machine (`~/.psalm-saga/models.json`, next to the API
keys) and take precedence. When a run is created, the chosen entries are copied into its settings,
so a run keeps the exact model settings it was made with even if the library changes later;
choosing a model again (an override of `...use`, `judges.model` or `judges.panel`) refreshes them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Fields of a library entry that become ModelConfig fields; api_base, reasoning_effort and OpenRouter's
# provider routing go to `extra`.
MODEL_FIELDS = ("name", "context_window", "max_output_tokens", "min_output_tokens", "reasoning", "reasoning_headroom",
                "reasoning_max_tokens",
                "timeout_s", "timeout_retries", "max_retries", "max_concurrency", "rpm", "tpm", "stream", "prompt_cache",
                "input_cost_per_mtok", "output_cost_per_mtok", "cached_input_cost_per_mtok")
EXTRA_FIELDS = ("api_base", "reasoning_effort", "provider_order", "provider_sort", "provider_fallbacks")
ENTRY_FIELDS = ("label", "kind", "notes", *MODEL_FIELDS, *EXTRA_FIELDS, "extra")

BUILTIN: dict[str, dict[str, Any]] = {
    "mistral-large-4": {"label": "Mistral Large 4", "kind": "api", "name": "mistral/mistral-large-4-0",
                        "context_window": 1_000_000, "max_output_tokens": 16000, "max_concurrency": 6,
                        "notes": "Writer in the paper's experiments. Public preview: pin the dated snapshot."},
    "gemma-4-e4b": {"label": "Gemma 4 E4B (Ollama, this computer)", "kind": "local", "name": "ollama_chat/gemma4:e4b",
                    "api_base": "http://localhost:11434", "context_window": 131072, "max_output_tokens": 8192,
                    "max_concurrency": 1, "timeout_s": 1200, "input_cost_per_mtok": 0, "output_cost_per_mtok": 0,
                    "notes": "Small open writer (about 4.5B effective parameters, Apache 2.0). `ollama pull gemma4:e4b`; "
                             "check the tag with `ollama list`."},
    "claude-sonnet-5-5": {"label": "Claude Sonnet 5.5", "kind": "api", "name": "anthropic/claude-sonnet-5-5",
                          "max_output_tokens": 16000, "max_concurrency": 6, "notes": "Primary judge in the paper's experiments."},
    "gpt-6-luna": {"label": "OpenAI GPT-6 Luna", "kind": "api", "name": "openai/gpt-6-luna", "max_output_tokens": 16000,
                   "max_concurrency": 6, "notes": "Agreement judge in the paper's experiments."},
    "qwen3.5-397b": {"label": "Qwen3.5-397B-A17B (vLLM server)", "kind": "local", "name": "hosted_vllm/Qwen/Qwen3.5-397B-A17B",
                     "api_base": "http://localhost:8000/v1", "context_window": 262144, "max_output_tokens": 16000,
                     "input_cost_per_mtok": 0, "output_cost_per_mtok": 0,
                     "notes": "Open-weight agreement judge, self-hosted. Set the address of your vLLM server."},
    "offline-test": {"label": "Offline test model (free, no key)", "kind": "local", "name": "fake/demo",
                     "input_cost_per_mtok": 0, "output_cost_per_mtok": 0,
                     "notes": "Writes filler text instantly: for trying the interface and the pipeline without cost."},
}


def path() -> Path:
    from psalm_saga.keys import home

    return home() / "models.json"


def _read_user() -> dict[str, dict]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_user(data: dict[str, dict]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)


def library() -> dict[str, dict]:
    """All entries, built-in and the user's (the user's win), each with `alias` and `source`."""
    out = {a: {**e, "alias": a, "source": "built-in"} for a, e in BUILTIN.items()}
    for a, e in _read_user().items():
        out[a] = {**e, "alias": a, "source": "edited built-in" if a in BUILTIN else "yours"}
    return out


def get(alias: str | None) -> dict | None:
    if not alias or not isinstance(alias, str):
        return None
    return library().get(alias)


def save(alias: str, entry: dict) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][\w.:-]{0,63}", alias or ""):
        raise ValueError("a model's short name uses letters, digits and . _ - : (at most 64 characters)")
    clean = {k: v for k, v in entry.items() if k in ENTRY_FIELDS and v not in (None, "")}
    if not clean.get("name"):
        raise ValueError("a model needs its LiteLLM id, e.g. mistral/mistral-large-4-0")
    to_model_config(clean)  # validates the values
    data = _read_user()
    data[alias] = clean
    _write_user(data)
    return library()[alias]


def delete(alias: str) -> None:
    """Remove the user's entry (an edited built-in falls back to the built-in one)."""
    data = _read_user()
    data.pop(alias, None)
    _write_user(data)


def model_fields(entry: dict) -> dict:
    """The ModelConfig fields of an entry (without temperature, which belongs to the task)."""
    out = {k: entry[k] for k in MODEL_FIELDS if k in entry and entry[k] is not None}
    extra = dict(entry.get("extra") or {})
    for k in EXTRA_FIELDS:
        if entry.get(k) not in (None, ""):
            extra[k] = entry[k]
    out["extra"] = extra
    return out


def to_model_config(entry: dict, **task):
    from psalm_saga.config import ModelConfig

    return ModelConfig(**{**model_fields(entry), **task})


def expand(ref: Any) -> dict | None:
    """A library reference as the dict stored in a configuration ({"use": alias, ...model fields}), or
    None when `ref` is not a library name (a raw LiteLLM id or an explicit dict)."""
    if isinstance(ref, dict):
        e = get(ref.get("use"))
        return {**ref, **model_fields(e), "use": ref["use"]} if e else None
    e = get(ref)
    return {"use": ref, **model_fields(e)} if e else None


def resolve(ref: Any, base=None, **task):
    """ModelConfig for any model reference: a library name, a dict ({"use": ...} or {"name": ..., ...}) or
    a raw LiteLLM id. Fields the reference does not set come from `base` (else the defaults); `task`
    fields (e.g. temperature=0 for judges) are applied last."""
    from psalm_saga.config import ModelConfig

    known = set(ModelConfig.model_fields)
    fields: dict = base.model_dump() if base is not None else {}
    if isinstance(ref, str):
        e = get(ref)
        if e:
            fields = {**fields, **model_fields(e), "use": ref}
        elif fields.get("name") == ref:
            pass  # the base model itself
        else:
            fields = {**fields, "name": ref, "use": None,
                      "extra": {k: v for k, v in (fields.get("extra") or {}).items() if k not in ("api_base",)
                                and not k.startswith("fake_")}}
    elif isinstance(ref, dict):
        e = get(ref.get("use")) if ref.get("use") else None
        if e and not ref.get("name"):
            fields = {**fields, **model_fields(e)}
        elif ref.get("name"):  # a model of its own: the base's endpoint does not apply to it
            fields = {**fields, "extra": {k: v for k, v in (fields.get("extra") or {}).items()
                                          if k != "api_base" and not k.startswith("fake_")}}
        own = {k: v for k, v in ref.items() if k in known}
        extra = {**(fields.get("extra") or {}), **(own.pop("extra", None) or {}),
                 **{k: v for k, v in ref.items() if k not in known}}
        fields = {**fields, **own, "extra": extra}
    return ModelConfig(**{**fields, **task})


def label(ref: Any) -> str:
    """How a model reference is shown to a person."""
    if isinstance(ref, dict):
        ref = ref.get("use") or ref.get("name")
    e = get(ref)
    return e["label"] if e else str(ref or "")
