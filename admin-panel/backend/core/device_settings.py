"""Device-scoped settings backed by the ``device_settings`` SQLite table.

All values are stored as TEXT and parsed in the getter helpers. The table is a
generic key/value store deliberately reused for multiple concerns (admin token,
auth-enabled flag, bind host) so we do not grow a new config surface for each
device-level toggle.

Known keys
----------
- ``admin_token_hash`` — SHA-256 hex of the raw admin token. Never stores the
  raw token. Empty/absent means auth has not been configured yet.
- ``auth_enabled`` — ``"1"`` when the token is required, ``"0"`` to bypass.
  Defaults to ``"1"`` once a token has been generated so auth is on by default.
- ``bind_host`` — Host the Flask server binds to (``127.0.0.1`` or ``0.0.0.0``).
  Defaults to ``127.0.0.1`` for a safe-by-default local-only install.
"""
import hashlib
import hmac
import secrets
from datetime import datetime

ADMIN_TOKEN_HASH_KEY = "admin_token_hash"
AUTH_ENABLED_KEY = "auth_enabled"
BIND_HOST_KEY = "bind_host"

DEFAULT_BIND_HOST = "127.0.0.1"
NETWORK_BIND_HOST = "0.0.0.0"

TOKEN_PREFIX = "gwf_"


def get_setting(db, key: str, default: str | None = None) -> str | None:
    row = db.execute(
        "SELECT value FROM device_settings WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return default
    return row["value"]


def set_setting(db, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO device_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, datetime.now().isoformat()),
    )


def delete_setting(db, key: str) -> None:
    db.execute("DELETE FROM device_settings WHERE key = ?", (key,))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """Return a new high-entropy admin token.

    The raw token is returned once to the caller (CLI). Only the hash is
    persisted — the plaintext is never stored so the admin panel itself has
    no way to recover it.
    """
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def set_admin_token(db, raw_token: str) -> None:
    set_setting(db, ADMIN_TOKEN_HASH_KEY, hash_token(raw_token))
    set_setting(db, AUTH_ENABLED_KEY, "1")


def clear_admin_token(db) -> None:
    delete_setting(db, ADMIN_TOKEN_HASH_KEY)
    set_setting(db, AUTH_ENABLED_KEY, "0")


def get_admin_token_hash(db) -> str | None:
    return get_setting(db, ADMIN_TOKEN_HASH_KEY)


def is_auth_enabled(db) -> bool:
    stored_hash = get_setting(db, ADMIN_TOKEN_HASH_KEY)
    if not stored_hash:
        return False
    flag = get_setting(db, AUTH_ENABLED_KEY, "1")
    return flag == "1"


def verify_token(db, presented_token: str) -> bool:
    """Constant-time compare the presented token against the stored hash.

    Returns False when auth is not enabled (no token configured). Callers use
    ``is_auth_enabled`` to decide whether to require a token at all; this
    helper only answers "does this token match the configured one".
    """
    if not presented_token:
        return False
    stored_hash = get_setting(db, ADMIN_TOKEN_HASH_KEY)
    if not stored_hash:
        return False
    return hmac.compare_digest(stored_hash, hash_token(presented_token))


def get_bind_host(db) -> str:
    value = get_setting(db, BIND_HOST_KEY, DEFAULT_BIND_HOST)
    if value in (DEFAULT_BIND_HOST, NETWORK_BIND_HOST):
        return value
    return DEFAULT_BIND_HOST


def set_bind_host(db, host: str) -> None:
    if host not in (DEFAULT_BIND_HOST, NETWORK_BIND_HOST):
        raise ValueError(f"bind_host must be '{DEFAULT_BIND_HOST}' or '{NETWORK_BIND_HOST}'")
    set_setting(db, BIND_HOST_KEY, host)
