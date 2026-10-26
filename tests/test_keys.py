"""API keys are kept in the user's settings folder, loaded into the environment, never returned in full."""

import json
import os


def test_keys_saved_loaded_masked_and_removed(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from psalm_saga import keys
    from psalm_saga.web.app import create_app

    monkeypatch.setenv("PSALM_SAGA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-environment-1234")
    with TestClient(create_app(tmp_path / "runs")) as c:
        st = {p["id"]: p for p in c.get("/api/keys").json()["providers"]}
        oa = st["openai"]["vars"][0]
        assert oa["source"] == "environment" and oa["display"].endswith("1234") and "sk-" not in oa["display"]
        r = c.put("/api/keys", json={"var": "MISTRAL_API_KEY", "value": "secret-mistral-9876"})
        assert r.status_code == 200 and "secret-mistral" not in r.text      # never echoed in full
        assert os.environ["MISTRAL_API_KEY"] == "secret-mistral-9876"
        saved = json.loads(keys.path().read_text())
        assert saved == {"MISTRAL_API_KEY": "secret-mistral-9876"}
        assert c.put("/api/keys", json={"var": "NOT_A_KEY", "value": "x"}).status_code == 400
        c.put("/api/keys", json={"var": "MISTRAL_API_KEY", "value": ""})
        assert "MISTRAL_API_KEY" not in os.environ and json.loads(keys.path().read_text()) == {}
    assert os.environ["OPENAI_API_KEY"] == "sk-from-environment-1234"   # the user's own environment is left alone
