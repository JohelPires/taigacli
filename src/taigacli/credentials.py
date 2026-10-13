from __future__ import annotations

import json

# Remembered login for silent token renewal: the OS keyring keeps the
# password so the CLI can authenticate again when a token expires.
# Every operation soft-fails — no keyring means "not remembered", not a crash.

SERVICE = "taigacli"


def _keyring():
    """The keyring module, or None when unavailable/unusable."""
    try:
        import keyring
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
        from keyring.backends import fail

        if isinstance(backend, fail.Keyring):
            return None
    except Exception:
        return None
    return keyring


def available() -> bool:
    return _keyring() is not None


def save(api_url: str, username: str, password: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(
            SERVICE, api_url, json.dumps({"username": username, "password": password})
        )
        return True
    except Exception:
        return False


def load(api_url: str) -> tuple[str, str] | None:
    """The remembered (username, password) for this API URL, or None."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        secret = kr.get_password(SERVICE, api_url)
    except Exception:
        return None
    if not secret:
        return None
    try:
        blob = json.loads(secret)
        username, password = blob["username"], blob["password"]
    except (ValueError, KeyError, TypeError):
        return None
    if not username or not password:
        return None
    return username, password


def forget(api_url: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, api_url)
        return True
    except Exception:
        return False
