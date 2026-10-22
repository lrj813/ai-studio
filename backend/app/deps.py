"""FastAPI 依赖注入：从 app.state 取共享对象。"""
from fastapi import Request

from .config import Settings
from .events import EventBus
from .store import Store


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_tasks(request: Request):
    return request.app.state.tasks
