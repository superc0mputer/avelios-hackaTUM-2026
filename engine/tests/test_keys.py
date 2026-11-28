"""Key store and key checks (no network: requests are faked)."""

import io
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import key_check  # noqa: E402
import keystore  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "keys.bin"
    monkeypatch.setenv("VIP_KEYSTORE_PATH", str(path))
    return path


def test_round_trip_and_merge(store):
    assert keystore.load() == {}
    keystore.save({"OPENAI_API_KEY": "sk-one", "ELEVENLABS_API_KEY": "el-one"})
    keystore.save({"ELEVENLABS_API_KEY": "el-two"})
    assert keystore.load() == {"OPENAI_API_KEY": "sk-one", "ELEVENLABS_API_KEY": "el-two"}


def test_file_does_not_contain_the_key_in_plain_text_on_windows(store):
    keystore.save({"OPENAI_API_KEY": "sk-visible-marker"})
    if sys.platform == "win32":
        assert b"sk-visible-marker" not in store.read_bytes()


def test_empty_value_removes_and_clear_deletes(store):
    keystore.save({"OPENAI_API_KEY": "sk-one", "ELEVENLABS_API_KEY": "el-one"})
    keystore.save({"OPENAI_API_KEY": ""})
    assert keystore.load() == {"ELEVENLABS_API_KEY": "el-one"}
    keystore.clear()
    assert keystore.load() == {} and not store.exists()


def test_unknown_key_is_refused(store):
    with pytest.raises(ValueError):
        keystore.save({"SOMETHING_ELSE": "x"})


def test_corrupt_file_reads_as_empty(store):
    store.write_bytes(b"not a valid store")
    assert keystore.load() == {}


def test_apply_to_environ_keeps_existing_values(store, monkeypatch):
    keystore.save({"OPENAI_API_KEY": "sk-stored", "ELEVENLABS_API_KEY": "el-stored"})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert keystore.apply_to_environ() == ["ELEVENLABS_API_KEY"]
    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-from-env"
    assert os.environ["ELEVENLABS_API_KEY"] == "el-stored"


def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))


def test_openai_check(monkeypatch):
    monkeypatch.setattr(key_check, "_get", lambda url, headers: {"data": [{"id": "gpt-6-luna"}]})
    assert key_check.check_openai("sk-x", "gpt-6-luna")["ok"] is True
    missing = key_check.check_openai("sk-x", "other-model")
    assert missing["ok"] is False and "other-model" in missing["error"]
    assert key_check.check_openai("")["ok"] is False


def test_openai_bad_key(monkeypatch):
    def fail(url, headers):
        raise _http_error(401)
    monkeypatch.setattr(key_check, "_get", fail)
    assert key_check.check_openai("sk-bad") == {"ok": False, "error": "OpenAI did not accept this key."}


def test_elevenlabs_check_reports_credits(monkeypatch):
    monkeypatch.setattr(
        key_check, "_get", lambda url, headers: {"tier": "free", "character_count": 2500, "character_limit": 10000}
    )
    assert key_check.check_elevenlabs("el-x") == {
        "ok": True, "tier": "free", "credits_left": 7500, "credits_limit": 10000,
    }


def test_elevenlabs_offline(monkeypatch):
    def fail(url, headers):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(key_check, "_get", fail)
    assert "internet" in key_check.check_elevenlabs("el-x")["error"]
