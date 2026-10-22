import base64
import io
import os

from PIL import Image


def _b64_png(size=(1080, 1080)):
    img = Image.new("RGBA", size, (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_export_sizes_and_manifest(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/export",
        json={"image_base64": _b64_png(), "sizes": [[800, 800], [750, 1000]], "format": "png"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["files"]) == 2
    assert os.path.exists(body["files"][0]["path"])
    assert os.path.exists(body["manifest"])
    download = client.get(body["files"][0]["url"])
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")


def test_png_export_preserves_source_alpha_and_jpeg_composites_on_white(client, project):
    image = Image.new("RGBA", (32, 16), (20, 40, 60, 0))
    for x in range(16):
        for y in range(16):
            image.putpixel((x, y), (200, 100, 50, 128))
    source = io.BytesIO()
    image.save(source, "PNG")
    encoded = base64.b64encode(source.getvalue()).decode()

    png_response = client.post(
        f"/api/projects/{project['id']}/export",
        json={"image_base64": encoded, "sizes": [[32, 16]], "format": "png"},
    )
    assert png_response.status_code == 200
    with Image.open(png_response.json()["files"][0]["path"]) as exported_png:
        assert exported_png.getpixel((8, 8)) == (200, 100, 50, 128)
        assert exported_png.getpixel((24, 8))[3] == 0

    jpeg_response = client.post(
        f"/api/projects/{project['id']}/export",
        json={"image_base64": encoded, "sizes": [[32, 16]], "format": "jpeg"},
    )
    assert jpeg_response.status_code == 200
    with Image.open(jpeg_response.json()["files"][0]["path"]) as exported_jpeg:
        assert exported_jpeg.mode == "RGB"
        blended = exported_jpeg.getpixel((8, 8))
        assert all(abs(actual - expected) <= 4 for actual, expected in zip(blended, (227, 177, 152)))
        assert all(channel >= 250 for channel in exported_jpeg.getpixel((24, 8)))


def test_export_rejects_unsupported_format_and_unsafe_download(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/export",
        json={"image_base64": _b64_png(), "sizes": [[800, 800]], "format": "gif"},
    )
    assert response.status_code == 422
    assert client.get(f"/api/projects/{project['id']}/exports/../../app.db").status_code == 404


def test_export_invalid_image(client, project):
    r = client.post(
        f"/api/projects/{project['id']}/export",
        json={"image_base64": "not-base64!!", "sizes": [[800, 800]]},
    )
    assert r.status_code == 400
