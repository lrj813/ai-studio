from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_store
from ..schemas import Layer, LayersReplace
from ..store import Store

router = APIRouter(prefix="/api/projects/{pid}/layers", tags=["layers"])


def _check_project(pid: str, store: Store):
    if store.get_project(pid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})


@router.get("", response_model=List[Layer])
def get_layers(pid: str, store: Store = Depends(get_store)):
    _check_project(pid, store)
    return store.get_layers(pid)


@router.get("/snapshot")
def get_latest_snapshot(pid: str, store: Store = Depends(get_store)):
    _check_project(pid, store)
    return store.latest_valid_snapshot(pid)


@router.put("", status_code=204)
def put_layers(pid: str, body: LayersReplace, store: Store = Depends(get_store)):
    _check_project(pid, store)
    store.replace_layers(pid, [layer.model_dump() for layer in body.layers])


@router.post("/beacon", status_code=204)
def save_layers_on_exit(pid: str, body: LayersReplace, store: Store = Depends(get_store)):
    _check_project(pid, store)
    store.replace_layers(pid, [layer.model_dump() for layer in body.layers])
