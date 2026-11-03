"""API keys: pasted values are cleaned, wrong-looking keys are flagged, a key can be checked with the
provider, and an authentication error says which key was sent."""

import httpx
import pytest

from psalm_saga import keys
from psalm_saga.config import ModelConfig


@pytest.mark.parametrize("pasted", ['  sk-or-v1-abc  ', '"sk-or-v1-abc"', "Bearer sk-or-v1-abc",
                                    "OPENROUTER_API_KEY=sk-or-v1-abc", "export OPENROUTER_API_KEY='sk-or-v1-abc'",
                                    "sk-or-v1-\nabc"])
def test_pasted_keys_are_cleaned(pasted):
    assert keys.clean("OPENROUTER_API_KEY", pasted) == "sk-or-v1-abc"


def test_a_key_for_another_provider_is_flagged():
    assert keys.problem("OPENROUTER_API_KEY", "sk-ant-xyz")
    assert keys.problem("OPENROUTER_API_KEY", "sk-or-v1-xyz") is None
    assert keys.problem("MISTRAL_API_KEY", "anything") is None


def test_saved_key_is_stored_clean_and_reported_masked(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    keys.set_value("OPENROUTER_API_KEY", ' "sk-or-v1-1234567890abcd" ')
    s = keys.source("OPENROUTER_API_KEY")
    assert s["set"] and s["source"] == "saved here" and s["display"].endswith("abcd") and "1234" not in s["display"]
    keys.set_value("OPENROUTER_API_KEY", "")


def test_auth_error_hint_names_the_key_that_was_sent(monkeypatch):
    from psalm_saga.preflight import _key_hint

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert "No OPENROUTER_API_KEY is set" in _key_hint(ModelConfig(name="openrouter/google/gemma-4-26b-a4b-it"))
    keys.set_value("OPENROUTER_API_KEY", "sk-ant-wrongprovider99")
    h = _key_hint(ModelConfig(name="openrouter/google/gemma-4-26b-a4b-it"))
    assert "OPENROUTER_API_KEY" in h and "er99" in h and "saved here" in h and "does not look like" in h
    keys.set_value("OPENROUTER_API_KEY", "")


class _Client:
    def __init__(self, status, body):
        self.status, self.body, self.seen = status, body, {}

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        self.seen = {"url": url, "headers": headers}
        return httpx.Response(self.status, json=self.body)


async def test_key_check_with_the_provider(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-good0000")
    ok = _Client(200, {"data": {"label": "mine", "is_free_tier": True}})
    monkeypatch.setattr(httpx, "AsyncClient", ok)
    r = await keys.check("OPENROUTER_API_KEY")
    assert r["ok"] and "free tier" in r["message"] and ok.seen["headers"]["Authorization"] == "Bearer sk-or-v1-good0000"
    monkeypatch.setattr(httpx, "AsyncClient", _Client(401, {"error": {"message": "User not found.", "code": 401}}))
    r = await keys.check("OPENROUTER_API_KEY")
    assert not r["ok"] and "User not found" in r["message"] and "does not recognise this key" in r["message"]
