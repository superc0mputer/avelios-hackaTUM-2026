"""The judge's own API keys, stored on their computer only.

The packaged app asks for an OpenAI and an ElevenLabs key on first start. They are kept in
the user's app-data folder, encrypted for the signed-in Windows user (DPAPI), and are only
ever sent to OpenAI and ElevenLabs. Elsewhere (macOS, tests) the file is plain JSON with
user-only permissions.

    save({"OPENAI_API_KEY": "...", "ELEVENLABS_API_KEY": "..."})
    load() -> dict          # {} if nothing is stored or the file cannot be read
    clear()
    apply_to_environ()      # put stored keys into os.environ unless already set
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

KEY_NAMES = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID")


def store_path() -> Path:
    override = os.getenv("VIP_KEYSTORE_PATH")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "VIPPatient" / "keys.bin"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _ENTROPY = b"VIPPatient keys v1"

    def _call(fn, data: bytes) -> bytes:
        source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
        entropy = _Blob(len(_ENTROPY), ctypes.cast(ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY)), ctypes.POINTER(ctypes.c_char)))
        result = _Blob()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1: never show a prompt
        if not fn(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(result)):
            raise OSError(ctypes.get_last_error() or "DPAPI call failed")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            _kernel32.LocalFree(result.pbData)

    def _protect(data: bytes) -> bytes:
        return _call(_crypt32.CryptProtectData, data)

    def _unprotect(data: bytes) -> bytes:
        return _call(_crypt32.CryptUnprotectData, data)

else:

    def _protect(data: bytes) -> bytes:
        return data

    def _unprotect(data: bytes) -> bytes:
        return data


def load() -> dict[str, str]:
    path = store_path()
    try:
        values = json.loads(_unprotect(path.read_bytes()).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in values.items() if k in KEY_NAMES and v}


def save(values: dict[str, str]) -> None:
    """Merge these keys into the store (an empty value removes that key)."""
    current = load()
    for name, value in values.items():
        if name not in KEY_NAMES:
            raise ValueError(f"unknown key {name}")
        value = (value or "").strip()
        if value:
            current[name] = value
        else:
            current.pop(name, None)
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_protect(json.dumps(current).encode("utf-8")))
    if sys.platform != "win32":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def clear() -> None:
    try:
        store_path().unlink()
    except FileNotFoundError:
        pass


def apply_to_environ() -> list[str]:
    """Copy stored keys into os.environ (values already set win). Returns the names applied."""
    applied = []
    for name, value in load().items():
        if not os.environ.get(name):
            os.environ[name] = value
            applied.append(name)
    return applied
