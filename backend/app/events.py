"""进程内 SSE 事件总线：任务 worker 线程 → 各 SSE 订阅者。"""
import asyncio
import threading


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        loop = self._loop
        if loop is None:
            return
        for q in subs:
            try:
                asyncio.run_coroutine_threadsafe(q.put(event), loop)
            except Exception:
                pass
