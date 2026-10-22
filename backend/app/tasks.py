"""任务队列：串行 worker + 状态持久化 + SSE 广播。"""
import queue
import threading
from typing import Any, Callable, Dict

from .config import Settings
from .events import EventBus
from .inference.engine import InferenceEngine
from .inference.errors import InferenceError
from .store import Store, now_iso


class TaskManager:
    def __init__(
        self,
        store: Store,
        bus: EventBus,
        settings: Settings,
        engine_factory: Callable[[], InferenceEngine],
    ) -> None:
        self.store = store
        self.bus = bus
        self.settings = settings
        self.engine_factory = engine_factory
        self._engine: InferenceEngine | None = None
        self._q: queue.Queue = queue.Queue()
        self._recover()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="task-worker")
        self._worker.start()

    def _recover(self) -> None:
        """恢复未完成任务；云端生成不确定时绝不自动重提。"""
        queued = self.store.list_generations_by_status(["queued"])
        for gen in queued:
            self._q.put(gen["id"])
        running = self.store.list_generations_by_status(["running"])
        for gen in running:
            cloud_task = self.is_cloud_task(gen)
            error = (
                "进程中断，百炼任务状态/费用不明；请先核对控制台，避免重复提交"
                if cloud_task
                else "进程中断，本地任务已停止；如仍需处理，请手动重试"
            )
            self.store.update_generation_if_status(
                gen["id"],
                ("running",),
                status="interrupted",
                error=error,
                finished_at=now_iso(),
            )

    def provider_for(self, mode: str) -> str:
        return self.settings.matting_provider if mode == "matting" else self.settings.inference_provider

    def is_cloud_task(self, gen: Dict[str, Any]) -> bool:
        provider = gen["params"].get("provider") or self.provider_for(gen["params"].get("mode", "txt2img"))
        return provider == "dashscope"

    def requires_cost_confirmation(self, gen: Dict[str, Any]) -> bool:
        return self.is_cloud_task(gen)

    def requires_unknown_status_confirmation(self, gen: Dict[str, Any]) -> bool:
        return gen["status"] == "interrupted" and self.is_cloud_task(gen)

    @property
    def engine(self) -> InferenceEngine:
        if self._engine is None:
            self._engine = self.engine_factory()
        return self._engine

    def submit(self, gen_id: str) -> None:
        gen = self.store.get_generation(gen_id)
        project_id = gen["project_id"] if gen else None
        self.store.update_generation(gen_id, status="queued")
        self._q.put(gen_id)
        self.bus.publish(
            {
                "type": "task_update",
                "job_id": gen_id,
                "project_id": project_id,
                "status": "queued",
                "progress": 0,
                "stage": "queued",
                "queue_position": self._q.qsize(),
            }
        )

    def cancel(self, gen_id: str):
        gen = self.store.get_generation(gen_id)
        if gen is None:
            return None
        status = gen["status"]
        if status == "queued":
            status = "cancelled"
            error = "任务已取消，尚未开始执行。"
            changed = self.store.update_generation_if_status(
                gen_id, ("queued",), status=status, error=error, finished_at=now_iso()
            )
        elif status == "running":
            cloud_task = self.is_cloud_task(gen)
            status = "interrupted" if cloud_task else "cancelled"
            error = (
                "已停止等待；百炼请求无法保证被远端取消。结果/费用状态可能未知，请先核对控制台，避免重复提交。"
                if cloud_task
                else "本地任务已取消；正在运行的计算会在下一个进度回调处停止并丢弃结果，不会提交云端请求。"
            )
            changed = self.store.update_generation_if_status(
                gen_id, ("running",), status=status, error=error, finished_at=now_iso()
            )
        else:
            return status

        if changed:
            current = self.store.get_generation(gen_id)
            self.bus.publish(
                {
                    "type": "task_update",
                    "job_id": gen_id,
                    "project_id": current["project_id"] if current else gen["project_id"],
                    "status": current["status"] if current else status,
                    "progress": current["progress"] if current else gen["progress"],
                    "stage": status,
                    "queue_position": 0,
                    "error": error,
                }
            )
            return status
        current = self.store.get_generation(gen_id)
        return current["status"] if current else status

    def _loop(self) -> None:
        while True:
            gen_id = self._q.get()
            gen = self.store.get_generation(gen_id)
            if gen is None or gen["status"] != "queued":
                continue
            try:
                self._execute(gen_id)
            except Exception as e:  # 兜底，保证任何失败都收尾
                failed = self.store.update_generation_if_status(
                    gen_id, ("queued", "running"), status="failed", error=str(e), finished_at=now_iso()
                )
                if not failed:
                    continue
                gen = self.store.get_generation(gen_id)
                self.bus.publish(
                    {
                        "type": "error",
                        "job_id": gen_id,
                        "project_id": gen["project_id"] if gen else None,
                        "error": {"code": "TASK_FAILED", "message": str(e)},
                    }
                )

    def _execute(self, gen_id: str) -> None:
        gen = self.store.get_generation(gen_id)
        if gen is None:
            return
        project_id = gen["project_id"]
        params: Dict[str, Any] = gen["params"]
        mode = params.get("mode", "txt2img")
        started_at = now_iso()
        if not self.store.update_generation_if_status(
            gen_id,
            ("queued",),
            status="running",
            progress=0,
            stage="loading_model",
            started_at=started_at,
        ):
            return

        def on_progress(percent: int, stage: str) -> None:
            updated = self.store.update_generation_if_status(
                gen_id, ("running",), progress=int(percent), stage=stage
            )
            if not updated:
                raise InferenceError("TASK_CANCELLED", "任务已停止，忽略后续推理结果")
            self.bus.publish(
                {
                    "type": "task_update",
                    "job_id": gen_id,
                    "project_id": project_id,
                    "status": "running",
                    "progress": int(percent),
                    "stage": stage,
                    "queue_position": 0,
                }
            )

        try:
            result = self.engine.run(mode, params, project_id, on_progress)
        except InferenceError as e:
            current = self.store.get_generation(gen_id)
            if current and current["status"] in ("cancelled", "interrupted"):
                return
            if e.code == "TASK_CANCELLED":
                cancelled = self.store.update_generation_if_status(
                    gen_id, ("running",), status="cancelled", error=e.message, finished_at=now_iso()
                )
                if cancelled:
                    self.bus.publish(
                        {"type": "task_update", "job_id": gen_id, "project_id": project_id, "status": "cancelled", "progress": 0, "stage": "cancelled", "queue_position": 0, "error": e.message}
                    )
            else:
                failed = self.store.update_generation_if_status(
                    gen_id, ("running",), status="failed", error=e.message, finished_at=now_iso()
                )
                if failed:
                    self.bus.publish(
                        {"type": "error", "job_id": gen_id, "project_id": project_id, "error": {"code": e.code, "message": e.message}}
                    )
            return

        asset_ids = result.get("asset_ids", [])
        current = self.store.get_generation(gen_id)
        succeeded = self.store.update_generation_if_status(
            gen_id,
            ("running",),
            status="succeeded",
            progress=100,
            stage="done",
            result_asset_ids=asset_ids,
            error=None,
            finished_at=now_iso(),
        )
        if not succeeded:
            current = self.store.get_generation(gen_id)
            if current and current["status"] in ("cancelled", "interrupted") and asset_ids:
                cloud_task = self.is_cloud_task(current)
                error = (
                    "停止等待后百炼仍返回了结果，结果已保存为素材；任务保持待确认状态，不会自动重提。"
                    if cloud_task
                    else "取消时本地计算刚好完成，结果已保存为素材；任务保持已取消状态。"
                )
                self.store.update_generation_if_status(
                    gen_id,
                    (current["status"],),
                    result_asset_ids=asset_ids,
                    error=error,
                )
                self.bus.publish(
                    {"type": "task_update", "job_id": gen_id, "project_id": project_id,
                     "status": current["status"], "progress": current["progress"],
                     "stage": current["stage"], "queue_position": 0,
                     "result_asset_ids": asset_ids, "error": error}
                )
            return
        self.bus.publish(
            {"type": "done", "job_id": gen_id, "project_id": project_id, "status": "succeeded", "result_asset_ids": asset_ids}
        )
