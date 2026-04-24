"""Device-scoped settings backed by the ``device_settings`` SQLite table.

All values are stored as TEXT and parsed in the getter helpers. The table is a
generic key/value store deliberately reused for multiple concerns (admin token
hash, bind host) so we do not grow a new config surface for each device-level
toggle.

Auth is always on. Every protected HTTP route requires a valid admin token.
The only way to mint a token is ``python3 backend/app.py auth-token`` run in a
shell on the host — there is no API or web-facing endpoint that creates one,
and there is no environment variable or runtime flag that can disable the
middleware. The pytest suite authenticates via a fixture-based test client
wrapper that injects a real token minted against this same table.

Known keys
----------
- ``admin_token_hash`` — SHA-256 hex of the raw admin token. Never stores the
  raw token. Empty/absent means no token has been configured yet and every
  protected route will 401 until one is minted via the CLI.
- ``bind_host`` — Host the Flask server binds to (``127.0.0.1`` or ``0.0.0.0``).
  Defaults to ``127.0.0.1`` for a safe-by-default local-only install.
"""
import hashlib
import hmac
import secrets
from datetime import datetime

ADMIN_TOKEN_HASH_KEY = "admin_token_hash"
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
    """Persist the SHA-256 hash of ``raw_token`` as the configured admin token.

    Auth is always on; there is no flag to flip, so this only writes the hash.
    """
    set_setting(db, ADMIN_TOKEN_HASH_KEY, hash_token(raw_token))


def clear_admin_token(db) -> None:
    """Remove the configured admin token hash.

    After this call every protected route will 401 until a new token is minted
    via the ``auth-token`` CLI. Auth itself cannot be turned off — it is always
    required.
    """
    delete_setting(db, ADMIN_TOKEN_HASH_KEY)


def get_admin_token_hash(db) -> str | None:
    return get_setting(db, ADMIN_TOKEN_HASH_KEY)


def verify_token(db, presented_token: str) -> bool:
    """Constant-time compare the presented token against the stored hash.

    Returns False when no token is configured or the presented token is empty
    or does not match.
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
