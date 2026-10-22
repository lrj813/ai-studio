from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_store, get_tasks
from ..schemas import Generation, GenParams, RetryGenerationRequest
from ..store import Store

router = APIRouter(prefix="/api", tags=["generations"])


@router.post("/projects/{pid}/generations", status_code=202)
def create_generation(pid: str, body: GenParams, store: Store = Depends(get_store), tasks=Depends(get_tasks)):
    if store.get_project(pid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})
    if body.mode not in ("txt2img", "matting"):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "NOT_SUPPORTED", "message": f"本阶段不支持模式：{body.mode}"}},
        )
    if body.mode == "txt2img" and not body.prompt.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_PARAMS", "message": "提示词不能为空"}},
        )
    if body.mode == "txt2img" and not body.confirm_cost:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "COST_CONFIRMATION_REQUIRED",
                    "message": "云端图片生成可能产生费用；请先核对账号额度与当前价格，再明确确认提交",
                }
            },
        )
    params = body.model_dump()
    params["provider"] = tasks.provider_for(body.mode)
    image_count = params.pop("num_images", 1)
    job_ids = []
    for _ in range(image_count):
        gen = store.create_generation(pid, {**params, "num_images": 1})
        tasks.submit(gen["id"])
        job_ids.append(gen["id"])
    return {"job_id": job_ids[0], "job_ids": job_ids}


@router.get("/projects/{pid}/generations", response_model=List[Generation])
def list_generations(pid: str, store: Store = Depends(get_store)):
    if store.get_project(pid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "PROJECT_NOT_FOUND", "message": "项目不存在"}})
    return store.list_generations(pid)


@router.get("/generations/{gid}", response_model=Generation)
def get_generation(gid: str, store: Store = Depends(get_store)):
    gen = store.get_generation(gid)
    if gen is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "TASK_FAILED", "message": "任务不存在"}})
    return gen


@router.post("/generations/{gid}/cancel", response_model=Generation)
def cancel_generation(gid: str, store: Store = Depends(get_store), tasks=Depends(get_tasks)):
    if store.get_generation(gid) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "TASK_FAILED", "message": "任务不存在"}})
    tasks.cancel(gid)
    return store.get_generation(gid)


@router.post("/generations/{gid}/retry", status_code=202)
def retry_generation(
    gid: str,
    body: RetryGenerationRequest = RetryGenerationRequest(),
    store: Store = Depends(get_store),
    tasks=Depends(get_tasks),
):
    gen = store.get_generation(gid)
    if gen is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "TASK_FAILED", "message": "任务不存在"}})
    if gen["status"] not in ("failed", "cancelled", "interrupted"):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "INVALID_PARAMS", "message": "仅失败或已取消的任务可重试"}},
        )
    if tasks.requires_unknown_status_confirmation(gen) and not body.confirm_unknown_status:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "TASK_STATUS_UNKNOWN",
                    "message": "任务中断时云端状态不明；请先核对百炼控制台，确认未生成/扣费后再勾选确认重试",
                }
            },
        )
    if tasks.requires_cost_confirmation(gen) and not body.confirm_cost:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "COST_CONFIRMATION_REQUIRED",
                    "message": "重试会再次提交云端生成请求并可能产生费用；请核对账号额度与当前价格后确认",
                }
            },
        )
    new_gen = store.create_generation(gen["project_id"], gen["params"])
    tasks.submit(new_gen["id"])
    return {"job_id": new_gen["id"]}
