import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..deps import get_bus
from ..events import EventBus

router = APIRouter(prefix="/api", tags=["sse"])


@router.get("/sse/tasks")
async def sse_tasks(request: Request, project_id: str | None = None, bus: EventBus = Depends(get_bus)):
    q = bus.subscribe()

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if project_id and event.get("project_id") != project_id:
                    continue
                etype = event.get("type", "task_update")
                yield f"event: {etype}\n"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
