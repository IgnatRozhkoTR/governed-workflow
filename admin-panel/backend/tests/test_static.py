"""Tests for static file routes."""


def test_index_returns_200(client):
    response = client.get("/")

    assert response.status_code == 200


def test_index_sets_no_cache_header(client):
    response = client.get("/")

    assert "no-cache" in response.headers.get("Cache-Control", "")
