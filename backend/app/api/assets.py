import io
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..deps import get_store, get_tasks
from ..schemas import Asset, GenParams
from ..store import Store, new_id, sha256_bytes

router = APIRouter(prefix="/api", tags=["assets"])

ALLOWED_MAGIC = {
    b"\x89PNG": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"RIFF": ".webp",  # WebP: RIFF....WEBP，进一步校验
}
MAX_SIZE = 40 * 1024 * 1024  # 40MB


def _make_thumb(data: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.thumbnail((256, 256))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _detect_suffix(data: bytes) -> str:
    for magic, suffix in ALLOWED_MAGIC.items():
        if data.startswith(magic):
            if suffix == ".webp" and data[8:12] != b"WEBP":
                continue
            return suffix
    return ""


@router.post("/projects/{pid}/assets", response_model=Asset, status_code=201)
async def import_asset(pid: str, file: UploadFile = File(...), store: Store = Depends(get_store)):
    if store.get_project(pid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail={"error": {"code": "INVALID_PARAMS", "message": "文件超过 40MB"}})

    suffix = _detect_suffix(data)
    if not suffix:
        raise HTTPException(
            status_code=415,
            detail={"error": {"code": "INVALID_PARAMS", "message": "仅支持 PNG/JPG/WebP 图片"}},
        )

    # 用 PIL 校验真实可解码，并取尺寸
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        width, height = img.size
    except Exception:
        raise HTTPException(
            status_code=415,
            detail={"error": {"code": "INVALID_PARAMS", "message": "图片文件损坏或无法解析"}},
        )

    aid = new_id("a")
    path = store.write_asset_file(pid, aid, data, suffix)
    thumb = _make_thumb(data)
    thumb_path = store.write_thumb(pid, aid, thumb)

    return store.add_asset(
        project_id=pid,
        kind="original",
        filename=file.filename or f"素材{suffix}",
        path=path,
        width=width,
        height=height,
        sha256=sha256_bytes(data),
        thumb_path=thumb_path,
    )


@router.get("/projects/{pid}/assets", response_model=List[Asset])
def list_assets(pid: str, store: Store = Depends(get_store)):
    if store.get_project(pid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})
    return store.list_assets(pid)


@router.get("/assets/{aid}/file")
def asset_file(aid: str, store: Store = Depends(get_store)):
    asset = store.get_asset(aid)
    if asset is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "ASSET_NOT_FOUND", "message": "素材不存在"}})
    return FileResponse(asset["path"])


@router.get("/assets/{aid}/thumb")
def asset_thumb(aid: str, store: Store = Depends(get_store)):
    asset = store.get_asset(aid)
    if asset is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "ASSET_NOT_FOUND", "message": "素材不存在"}})
    path = asset["thumb_path"] or asset["path"]
    return FileResponse(path)


@router.delete("/assets/{aid}", status_code=204)
def delete_asset(aid: str, store: Store = Depends(get_store)):
    if not store.delete_asset(aid):
        raise HTTPException(status_code=404, detail={"error": {"code": "ASSET_NOT_FOUND", "message": "素材不存在"}})


@router.post("/assets/{aid}/matting", status_code=202)
def matting(aid: str, store: Store = Depends(get_store), tasks=Depends(get_tasks)):
    asset = store.get_asset(aid)
    if asset is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "ASSET_NOT_FOUND", "message": "素材不存在"}})
    params = GenParams(mode="matting", ref_asset_id=aid).model_dump()
    params["provider"] = tasks.provider_for("matting")
    gen = store.create_generation(asset["project_id"], params)
    tasks.submit(gen["id"])
    return {"job_id": gen["id"]}
