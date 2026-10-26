"""API keys and endpoints, set by the user and kept on their own machine.

Keys are stored in a small JSON file in the user's settings folder (`~/.psalm-saga/keys.json`, or
`$PSALM_SAGA_HOME/keys.json`), readable only by the user where the system allows, and loaded into
the process environment at start-up under the names LiteLLM reads (OPENAI_API_KEY, …). A key saved
here takes precedence over one set in the environment; a key set only in the environment is shown
as such and keeps working. Keys are never sent back to the browser in full, never written into run
folders, and never logged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# provider -> (label, environment variables, kind of each: key | url | text)
PROVIDERS: dict[str, dict] = {
    "anthropic": {"label": "Anthropic (Claude)", "vars": {"ANTHROPIC_API_KEY": "key"}, "example": "anthropic/claude-sonnet-5-5"},
    "openai": {"label": "OpenAI", "vars": {"OPENAI_API_KEY": "key", "OPENAI_BASE_URL": "url"}, "example": "openai/gpt-5.5"},
    "gemini": {"label": "Google Gemini", "vars": {"GEMINI_API_KEY": "key"}, "example": "gemini/gemini-2.5-pro"},
    "mistral": {"label": "Mistral", "vars": {"MISTRAL_API_KEY": "key"}, "example": "mistral/mistral-large-latest"},
    "moonshot": {"label": "Moonshot (Kimi)", "vars": {"MOONSHOT_API_KEY": "key"}, "example": "moonshot/kimi-k2-0905-preview"},
    "deepseek": {"label": "DeepSeek", "vars": {"DEEPSEEK_API_KEY": "key"}, "example": "deepseek/deepseek-chat"},
    "openrouter": {"label": "OpenRouter (many models, one key)", "vars": {"OPENROUTER_API_KEY": "key"},
                   "example": "openrouter/anthropic/claude-sonnet-5-5"},
    "azure": {"label": "Azure OpenAI", "vars": {"AZURE_API_KEY": "key", "AZURE_API_BASE": "url", "AZURE_API_VERSION": "text"},
              "example": "azure/<deployment>"},
    "ollama": {"label": "Ollama (local)", "vars": {"OLLAMA_API_BASE": "url"}, "example": "ollama/llama3.1"},
    "vllm": {"label": "Self-hosted vLLM / OpenAI-compatible", "vars": {"HOSTED_VLLM_API_BASE": "url", "HOSTED_VLLM_API_KEY": "key"},
             "example": "hosted_vllm/<model>"},
}
_LOADED: dict[str, str] = {}  # variables this module set (so a later "unset" can remove them)


def home() -> Path:
    return Path(os.environ.get("PSALM_SAGA_HOME") or Path.home() / ".psalm-saga")


def path() -> Path:
    return home() / "keys.json"


def _read() -> dict[str, str]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict[str, str]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)


def known_vars() -> dict[str, str]:
    return {v: kind for p in PROVIDERS.values() for v, kind in p["vars"].items()}


def load() -> int:
    """Put saved values into the environment (saved values win). Returns how many were loaded."""
    n = 0
    for var, val in _read().items():
        if var in known_vars() and val:
            os.environ[var] = val
            _LOADED[var] = val
            n += 1
    return n


def set_value(var: str, value: str | None) -> None:
    if var not in known_vars():
        raise KeyError(f"Unknown setting {var!r}")
    data = _read()
    if value:
        data[var] = value.strip()
        os.environ[var] = value.strip()
        _LOADED[var] = value.strip()
    else:
        data.pop(var, None)
        if var in _LOADED:  # only remove what we put there, not the user's own environment
            os.environ.pop(var, None)
            _LOADED.pop(var, None)
    _write(data)


def mask(value: str, kind: str) -> str:
    if kind != "key":
        return value
    return ("•" * 6 + value[-4:]) if len(value) > 8 else "•" * len(value)


def status() -> list[dict]:
    """Per provider and variable: whether it is set, where it comes from, and a masked value."""
    saved = _read()
    out = []
    for pid, p in PROVIDERS.items():
        rows = []
        for var, kind in p["vars"].items():
            val = saved.get(var) or os.environ.get(var) or ""
            src = "saved" if var in saved else "environment" if os.environ.get(var) else ""
            rows.append({"var": var, "kind": kind, "set": bool(val), "source": src, "display": mask(val, kind) if val else ""})
        out.append({"id": pid, "label": p["label"], "example": p["example"], "vars": rows,
                    "ready": any(r["set"] for r in rows)})
    return out
