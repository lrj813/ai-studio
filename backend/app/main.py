"""FastAPI 入口：装配依赖、注册路由、托管前端 build、统一错误结构。"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import assets, export, generations, layers, projects, sse, system
from .config import get_settings
from .events import EventBus
from .inference.engine import InferenceEngine
from .store import Store
from .tasks import TaskManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = Store(settings.data_dir)
    bus = EventBus()
    bus.set_loop(asyncio.get_running_loop())
    tasks = TaskManager(store, bus, settings, lambda: InferenceEngine(settings, store))

    app.state.settings = settings
    app.state.store = store
    app.state.bus = bus
    app.state.tasks = tasks
    yield


app = FastAPI(title="端侧 AI Studio", lifespan=lifespan)

for r in (projects.router, assets.router, layers.router, generations.router, system.router, sse.router, export.router):
    app.include_router(r)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "INVALID_PARAMS", "message": "参数不合法"}},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    else:
        content = {"error": {"code": "INTERNAL", "message": str(exc.detail)}}
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


# 前端 build 产物由后端托管（存在则挂载）
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    @app.get("/settings", include_in_schema=False)
    def settings_page():
        return FileResponse(_dist / "index.html")

    @app.get("/project/{pid}", include_in_schema=False)
    def editor_page(pid: str):
        return FileResponse(_dist / "index.html")

    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
