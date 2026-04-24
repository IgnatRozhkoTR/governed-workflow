"""Tests for ``core.device_settings`` — the device-level key/value store."""
import pytest

from core.db import get_db
from core.device_settings import (
    ADMIN_TOKEN_HASH_KEY,
    BIND_HOST_KEY,
    DEFAULT_BIND_HOST,
    DISABLE_AUTH_ENV_VAR,
    NETWORK_BIND_HOST,
    TOKEN_PREFIX,
    auth_disabled_by_env,
    clear_admin_token,
    delete_setting,
    generate_token,
    get_admin_token_hash,
    get_bind_host,
    get_setting,
    hash_token,
    set_admin_token,
    set_bind_host,
    set_setting,
    verify_token,
)


@pytest.fixture
def db():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def test_set_setting_persists_value(db):
    set_setting(db, "custom_key", "hello")

    assert get_setting(db, "custom_key") == "hello"


def test_get_setting_returns_default_when_missing(db):
    assert get_setting(db, "missing_key") is None
    assert get_setting(db, "missing_key", "fallback") == "fallback"


def test_set_setting_updates_existing_value(db):
    set_setting(db, "custom_key", "one")
    set_setting(db, "custom_key", "two")

    assert get_setting(db, "custom_key") == "two"


def test_delete_setting_removes_value(db):
    set_setting(db, "custom_key", "x")

    delete_setting(db, "custom_key")

    assert get_setting(db, "custom_key") is None


def test_hash_token_is_deterministic():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")


def test_generate_token_is_prefixed_and_unique():
    a = generate_token()
    b = generate_token()

    assert a.startswith(TOKEN_PREFIX)
    assert b.startswith(TOKEN_PREFIX)
    assert a != b


def test_set_admin_token_stores_hash(db):
    token = generate_token()

    set_admin_token(db, token)

    assert get_setting(db, ADMIN_TOKEN_HASH_KEY) == hash_token(token)
    assert get_admin_token_hash(db) == hash_token(token)


def test_set_admin_token_never_persists_plaintext(db):
    token = generate_token()

    set_admin_token(db, token)

    row = db.execute(
        "SELECT value FROM device_settings WHERE key = ?",
        (ADMIN_TOKEN_HASH_KEY,),
    ).fetchone()
    assert row["value"] != token
    assert row["value"] == hash_token(token)


def test_clear_admin_token_removes_hash(db):
    token = generate_token()
    set_admin_token(db, token)

    clear_admin_token(db)

    assert get_setting(db, ADMIN_TOKEN_HASH_KEY) is None
    assert get_admin_token_hash(db) is None


def test_verify_token_returns_true_when_token_matches(db):
    token = generate_token()
    set_admin_token(db, token)

    assert verify_token(db, token) is True


def test_verify_token_returns_false_when_token_wrong(db):
    set_admin_token(db, generate_token())

    assert verify_token(db, "gwf_wrong") is False


def test_verify_token_returns_false_when_no_token_configured(db):
    assert verify_token(db, "anything") is False


def test_verify_token_returns_false_when_presented_token_empty(db):
    set_admin_token(db, generate_token())

    assert verify_token(db, "") is False


def test_auth_disabled_by_env_reads_env_var(monkeypatch):
    monkeypatch.delenv(DISABLE_AUTH_ENV_VAR, raising=False)
    assert auth_disabled_by_env() is False

    monkeypatch.setenv(DISABLE_AUTH_ENV_VAR, "1")
    assert auth_disabled_by_env() is True

    monkeypatch.setenv(DISABLE_AUTH_ENV_VAR, "true")
    assert auth_disabled_by_env() is False

    monkeypatch.setenv(DISABLE_AUTH_ENV_VAR, "0")
    assert auth_disabled_by_env() is False


def test_get_bind_host_defaults_to_localhost(db):
    assert get_bind_host(db) == DEFAULT_BIND_HOST


def test_get_bind_host_returns_default_when_value_invalid(db):
    set_setting(db, BIND_HOST_KEY, "10.0.0.1")

    assert get_bind_host(db) == DEFAULT_BIND_HOST


def test_set_bind_host_accepts_localhost(db):
    set_bind_host(db, DEFAULT_BIND_HOST)

    assert get_bind_host(db) == DEFAULT_BIND_HOST


def test_set_bind_host_accepts_network_mode(db):
    set_bind_host(db, NETWORK_BIND_HOST)

    assert get_bind_host(db) == NETWORK_BIND_HOST


def test_set_bind_host_rejects_other_values(db):
    with pytest.raises(ValueError):
        set_bind_host(db, "10.0.0.1")

    with pytest.raises(ValueError):
        set_bind_host(db, "")
