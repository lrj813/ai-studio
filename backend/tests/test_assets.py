import io

from PIL import Image


def _png_bytes():
    img = Image.new("RGB", (32, 32), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_png(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("商品图.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "original"
    assert body["width"] == 32
    assert body["height"] == 32


def test_upload_reject_non_image(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("恶意.txt", b"hello world, not an image", "text/plain")},
    )
    assert r.status_code == 415


def test_upload_reject_too_large(client, project, monkeypatch):
    import app.api.assets as assets

    monkeypatch.setattr(assets, "MAX_SIZE", 10)
    r = client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("big.png", b"\x89PNG" + b"0" * 100, "image/png")},
    )
    assert r.status_code == 413


def test_list_assets(client, project):
    client.post(
        f"/api/projects/{project['id']}/assets",
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    r = client.get(f"/api/projects/{project['id']}/assets")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_asset_not_found(client):
    assert client.delete("/api/assets/a_none").status_code == 404
