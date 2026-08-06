"""Tests for terminal REST routes (paste-image upload)."""
import base64
import io
from pathlib import Path

# 1x1 transparent PNG, decoded per-test so uploads carry real image bytes.
_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
    "2mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

PASTE_URL = "/api/ws/test-project/feature/test/terminal/paste-image"


def _png_bytes():
    return base64.b64decode(_PNG_BASE64)


def test_paste_image_saves_png_and_returns_path(client, workspace):
    png = _png_bytes()
    data = {"image": (io.BytesIO(png), "screenshot.png", "image/png")}

    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 200
    assert r.json["ok"] is True

    saved = Path(r.json["path"])
    expected_dir = Path(workspace["working_dir"]) / ".claude" / "state" / "pasted-images"
    assert saved.parent == expected_dir
    assert saved.suffix == ".png"
    assert saved.exists()
    assert saved.read_bytes() == png


def test_paste_image_rejects_non_image(client, workspace):
    data = {"image": (io.BytesIO(b"not an image"), "notes.txt", "text/plain")}

    r = client.post(PASTE_URL, data=data, content_type="multipart/form-data")

    assert r.status_code == 400
    assert "not an image" in r.json["error"].lower()


def test_paste_image_missing_file_returns_400(client, workspace):
    r = client.post(PASTE_URL, data={}, content_type="multipart/form-data")

    assert r.status_code == 400
    assert r.json["error"] == "No image provided"


def test_paste_image_unknown_workspace_returns_404(client, workspace):
    png = _png_bytes()
    data = {"image": (io.BytesIO(png), "screenshot.png", "image/png")}

    r = client.post(
        "/api/ws/test-project/feature/does-not-exist/terminal/paste-image",
        data=data,
        content_type="multipart/form-data",
    )

    assert r.status_code == 404
    assert r.json["error"] == "Workspace not found"
