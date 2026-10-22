"""导出：把前端渲染的画布成品等比缩放为多尺寸并落盘，附 CSV 清单。"""
import base64
import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from ..deps import get_store
from ..store import Store

router = APIRouter(prefix="/api", tags=["export"])


class ExportRequest(BaseModel):
    image_base64: str  # dataURL 或纯 base64
    sizes: list[list[int]] = Field(default_factory=lambda: [[800, 800], [750, 1000], [1080, 1080]])
    format: str = "png"

    @field_validator("format")
    @classmethod
    def supported_format(cls, value: str) -> str:
        if value not in ("png", "jpeg"):
            raise ValueError("仅支持 PNG 或 JPEG")
        return value

    @field_validator("sizes")
    @classmethod
    def valid_sizes(cls, value: list[list[int]]) -> list[list[int]]:
        if not value or any(
            len(size) != 2 or any(dimension < 1 or dimension > 8192 for dimension in size)
            for size in value
        ):
            raise ValueError("导出尺寸必须在 1–8192 像素之间")
        return value


def _fit_letterbox(img, w: int, h: int, fmt: str):
    img = img.convert("RGBA")
    scale = min(w / img.width, h / img.height)
    nw = max(1, round(img.width * scale))
    nh = max(1, round(img.height * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    bg = (255, 255, 255, 0) if fmt == "png" else (255, 255, 255, 255)
    canvas = Image.new("RGBA", (w, h), bg)
    canvas.alpha_composite(resized, ((w - nw) // 2, (h - nh) // 2))
    return canvas


@router.post("/projects/{pid}/export")
def export_project(pid: str, body: ExportRequest, store: Store = Depends(get_store)):
    project = store.get_project(pid)
    if project is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})

    data = body.image_base64
    if "," in data and data.startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        raise HTTPException(status_code=400, detail={"error": {"code": "INVALID_PARAMS", "message": "画布图像数据无法解析"}})

    export_dir = store.data_dir / "projects" / pid / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    files = []
    name = re.sub(r'[\\/:*?"<>|]+', "-", project["name"]).strip(" .") or "作品"
    for w, h in body.sizes:
        out = _fit_letterbox(img, w, h, body.format)
        ext = "png" if body.format == "png" else "jpg"
        fname = f"{name}_{w}x{h}.{ext}"
        path = export_dir / fname
        if body.format == "png":
            out.save(path, "PNG")
        else:
            out.convert("RGB").save(path, "JPEG", quality=90)
        files.append(
            {
                "filename": fname,
                "path": str(path),
                "url": f"/api/projects/{pid}/exports/{fname}",
                "width": w,
                "height": h,
            }
        )

    manifest_name = "导出清单.csv"
    manifest = export_dir / manifest_name
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["尺寸", "文件名", "时间"])
        now = datetime.now(timezone.utc).isoformat()
        for fi in files:
            size = fi["filename"].split("_")[-1].split(".")[0]
            writer.writerow([size, fi["filename"], now])

    return {
        "files": files,
        "manifest": str(manifest),
        "manifest_url": f"/api/projects/{pid}/exports/{manifest_name}",
        "dir": str(export_dir),
    }


@router.get("/projects/{pid}/exports/{filename:path}")
def download_export(pid: str, filename: str, store: Store = Depends(get_store)):
    if store.get_project(pid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})
    export_dir = (store.projects_dir / pid / "exports").resolve()
    path = (export_dir / filename).resolve()
    if path.parent != export_dir or not path.is_file():
        raise HTTPException(status_code=404, detail={"error": {"code": "ASSET_NOT_FOUND", "message": "导出文件不存在"}})
    return FileResponse(path, filename=path.name)
