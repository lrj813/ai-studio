import io
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image

from ..deps import get_store
from ..schemas import Project, ProjectCreate, ProjectUpdate
from ..store import Store, new_id, sha256_bytes

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _not_found():
    return HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})


@router.post("", response_model=Project, status_code=201)
def create_project(body: ProjectCreate, store: Store = Depends(get_store)):
    return store.create_project(body.name, body.canvas.w, body.canvas.h)


@router.post("/preset", response_model=Project, status_code=201)
def create_preset_project(store: Store = Depends(get_store)):
    """Create an editable finished sample using a bundled public-domain product photo."""
    image_path = Path(__file__).resolve().parents[1] / "demo_assets" / "perfume-bottle.jpg"
    if not image_path.is_file():
        raise HTTPException(status_code=500, detail={"error": {"code": "INTERNAL", "message": "示例商品图缺失"}})

    project = store.create_project("香氛·复古香水主图", 1080, 1080)
    data = image_path.read_bytes()
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image_id = new_id("a")
    path = store.write_asset_file(project["id"], image_id, data, ".jpg")
    image.thumbnail((256, 256))
    thumb_buffer = io.BytesIO()
    image.save(thumb_buffer, format="PNG")
    thumb_path = store.write_thumb(project["id"], image_id, thumb_buffer.getvalue())
    store.add_asset(
        project_id=project["id"],
        kind="original",
        filename="公共领域示例-复古香水瓶.jpg",
        path=path,
        width=1280,
        height=1516,
        sha256=sha256_bytes(data),
        thumb_path=thumb_path,
        asset_id=image_id,
    )

    def shape(layer_id: str, name: str, z: int, x: float, y: float, w: float, h: float, fill: str):
        return {
            "id": layer_id,
            "project_id": project["id"],
            "type": "shape",
            "name": name,
            "z": z,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "opacity": 1,
            "visible": True,
            "locked": False,
            "blend": "normal",
            "content": {"shape": "rect", "fill": fill, "radius": 1},
        }

    def text(layer_id: str, name: str, z: int, x: float, y: float, value: str, size: int, color: str):
        return {
            "id": layer_id,
            "project_id": project["id"],
            "type": "text",
            "name": name,
            "z": z,
            "x": x,
            "y": y,
            "opacity": 1,
            "visible": True,
            "locked": False,
            "blend": "normal",
            "content": {"text": value, "font_size": size, "color": color},
        }

    store.replace_layers(
        project["id"],
        [
            shape("demo_bg", "暖调底色", 0, 0, 0, 1080, 1080, "#f3eee6"),
            {
                "id": "demo_product",
                "project_id": project["id"],
                "type": "image",
                "name": "复古香水瓶 · 公共领域示例",
                "z": 1,
                "x": 286,
                "y": 258,
                "w": 508,
                "h": 602,
                "opacity": 1,
                "visible": True,
                "locked": False,
                "blend": "normal",
                "content": {"asset_id": image_id},
            },
            shape("demo_rule", "品牌分隔线", 2, 96, 164, 888, 2, "#b77c59"),
            text("demo_eyebrow", "品牌标识", 3, 100, 90, "ATELIER  ·  PARFUMS", 25, "#46382e"),
            text("demo_title", "商品标题", 4, 98, 196, "复古玫瑰香氛", 48, "#2d251f"),
            text("demo_subtitle", "商品副标题", 5, 100, 904, "Eau de Parfum   /   50 ml", 24, "#6b5949"),
            text("demo_note", "素材来源说明", 6, 100, 966, "示例商品摄影 · Public domain", 16, "#8b7a6a"),
            shape("demo_badge", "系列角标", 7, 820, 850, 164, 66, "#7c3f36"),
            text("demo_badge_text", "角标文字", 8, 846, 869, "限量珍藏", 22, "#fffaf2"),
        ],
    )
    return project


@router.get("", response_model=List[Project])
def list_projects(store: Store = Depends(get_store)):
    return store.list_projects()


@router.get("/{pid}", response_model=Project)
def get_project(pid: str, store: Store = Depends(get_store)):
    project = store.get_project(pid)
    if project is None:
        raise _not_found()
    return project


@router.patch("/{pid}", response_model=Project)
def update_project(pid: str, body: ProjectUpdate, store: Store = Depends(get_store)):
    project = store.update_project(pid, body.name)
    if project is None:
        raise _not_found()
    return project


@router.delete("/{pid}", status_code=204)
def delete_project(pid: str, store: Store = Depends(get_store)):
    if not store.delete_project(pid):
        raise _not_found()
