import io
import sys
from pathlib import Path

import pytest

# 让 `app` 包可导入（backend/ 目录加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.engine import ModelNotReadyError  # noqa: E402
from app.store import new_id, sha256_bytes  # noqa: E402


class FakeEngine:
    """mock 推理引擎：不加载真实模型，离线可跑。"""

    def __init__(self, store):
        self.store = store
        self.backend = "mps"

    def run(self, mode, params, project_id, on_progress):
        on_progress(50, "sampling")
        if params.get("prompt") == "FAIL":
            raise ModelNotReadyError("MODEL_NOT_READY", "主模型未就绪")

        from PIL import Image

        img = Image.new("RGB", (64, 64), (200, 100, 100))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        aid = new_id("a")
        path = self.store.write_asset_file(project_id, aid, data, ".png")
        kind = "generated" if mode == "txt2img" else "matting"
        self.store.add_asset(
            project_id=project_id,
            kind=kind,
            filename="fake.png",
            path=path,
            width=64,
            height=64,
            sha256=sha256_bytes(data),
            asset_id=aid,
        )
        on_progress(100, "done")
        return {"asset_ids": [aid]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.app.state.tasks._engine = FakeEngine(c.app.state.store)
        yield c


@pytest.fixture()
def project(client):
    resp = client.post("/api/projects", json={"name": "口红主图", "canvas": {"w": 1080, "h": 1080}})
    assert resp.status_code == 201
    return resp.json()
