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


# How a provider's keys start, to catch a key pasted into the wrong provider's field.
KEY_PREFIX = {"OPENROUTER_API_KEY": ("sk-or-",), "ANTHROPIC_API_KEY": ("sk-ant-",), "OPENAI_API_KEY": ("sk-",),
              "DEEPSEEK_API_KEY": ("sk-",)}


def clean(var: str, value: str | None) -> str:
    """A pasted value as the provider expects it: without surrounding whitespace or quotes, a leading
    "Bearer " or "VAR=" (copied from a shell or a request), or line breaks inside."""
    v = (value or "").strip()
    if v.startswith(f"{var}="):
        v = v[len(var) + 1:].strip()
    if v.lower().startswith("export "):
        v = v.split("=", 1)[-1].strip()
    v = v.strip("'\"").strip()
    if v.lower().startswith("bearer "):
        v = v[7:].strip()
    return "".join(v.split()) if known_vars().get(var) == "key" else v


def problem(var: str, value: str) -> str | None:
    """A warning when a key does not look like the provider's keys."""
    pre = KEY_PREFIX.get(var)
    if value and pre and not value.startswith(pre):
        return (f"this does not look like a {var.split('_API_KEY')[0].title()} key (those start with "
                f"{' or '.join(pre)}); check that it is the right key for this provider")
    return None


def source(var: str) -> dict:
    """Where the value of a variable comes from, masked, for messages: {"set", "source", "display"}."""
    saved = _read()
    val = saved.get(var) or os.environ.get(var) or ""
    src = "saved here" if var in saved else "from the environment" if os.environ.get(var) else ""
    return {"set": bool(val), "source": src, "display": mask(val, known_vars().get(var, "key")) if val else ""}


def set_value(var: str, value: str | None) -> None:
    if var not in known_vars():
        raise KeyError(f"Unknown setting {var!r}")
    value = clean(var, value)
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


# Cheap requests that check a key without calling a model: (url, header name, header value format).
_CHECKS = {
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1/auth/key", "Authorization", "Bearer {}"),
    "OPENAI_API_KEY": ("{OPENAI_BASE_URL}/models", "Authorization", "Bearer {}"),
    "ANTHROPIC_API_KEY": ("https://api.anthropic.com/v1/models", "x-api-key", "{}"),
    "MISTRAL_API_KEY": ("https://api.mistral.ai/v1/models", "Authorization", "Bearer {}"),
    "DEEPSEEK_API_KEY": ("https://api.deepseek.com/models", "Authorization", "Bearer {}"),
    "GEMINI_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/models?key={}", None, None),
}


def can_check(var: str) -> bool:
    return var in _CHECKS


async def check(var: str, timeout_s: float = 20) -> dict:
    """Ask the provider whether it accepts the key (no model call, no cost). Returns {"ok", "message"}."""
    import httpx

    val = os.environ.get(var) or _read().get(var)
    if not val:
        return {"ok": False, "message": f"{var} is not set"}
    url, header, fmt = _CHECKS[var]
    base = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    url = url.replace("{OPENAI_BASE_URL}", base)
    headers = {"anthropic-version": "2023-06-01"} if var == "ANTHROPIC_API_KEY" else {}
    if header:
        headers[header] = fmt.format(val)
    else:
        url = url.format(val)
    shown = f"{var} {mask(val, 'key')} ({source(var)['source']})"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(url, headers=headers)
    except Exception as exc:
        return {"ok": False, "message": f"could not reach the provider to check {shown}: {type(exc).__name__}: {exc}"[:500]}
    if r.status_code == 200:
        extra = ""
        if var == "OPENROUTER_API_KEY":
            try:
                d = r.json().get("data") or {}
                bits = [f"label {d['label']!r}" if d.get("label") else "", "free tier" if d.get("is_free_tier") else "",
                        f"limit {d['limit']}" if d.get("limit") is not None else ""]
                extra = " (" + ", ".join(b for b in bits if b) + ")" if any(bits) else ""
            except Exception:
                pass
        return {"ok": True, "message": f"the provider accepts {shown}{extra}"}
    try:
        detail = r.json().get("error") or r.json()
        detail = detail.get("message", detail) if isinstance(detail, dict) else detail
    except Exception:
        detail = r.text[:200]
    hint = {401: "the provider does not recognise this key: it may be mistyped, deleted, expired or for another "
                 "provider. Create a new key at the provider and paste it again.",
            403: "the key is known but not allowed (disabled, or no access).",
            402: "the key works but the account has no credit left."}.get(r.status_code, "")
    return {"ok": False, "message": f"the provider rejected {shown}: HTTP {r.status_code} {detail}. {hint}"[:700]}


def status() -> list[dict]:
    """Per provider and variable: whether it is set, where it comes from, and a masked value."""
    saved = _read()
    out = []
    for pid, p in PROVIDERS.items():
        rows = []
        for var, kind in p["vars"].items():
            val = saved.get(var) or os.environ.get(var) or ""
            src = "saved" if var in saved else "environment" if os.environ.get(var) else ""
            rows.append({"var": var, "kind": kind, "set": bool(val), "source": src, "display": mask(val, kind) if val else "",
                         "checkable": can_check(var)})
        out.append({"id": pid, "label": p["label"], "example": p["example"], "vars": rows,
                    "ready": any(r["set"] for r in rows)})
    return out
