import asyncio
import uuid
from typing import Dict, List, Optional
from fastapi import WebSocket

from backend.models import BatchTask, ProcessResult, TaskStatus


class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, BatchTask] = {}
        self.connections: Dict[str, List[WebSocket]] = {}
        self._cancel_flags: Dict[str, bool] = {}

    def create_task(self, image_ids: List[str], filenames: List[str]) -> BatchTask:
        batch_id = str(uuid.uuid4())[:8]
        task = BatchTask(
            batch_id=batch_id,
            total=len(image_ids),
            status=TaskStatus.PENDING,
            results=[
                ProcessResult(id=img_id, filename=fn, status="pending")
                for img_id, fn in zip(image_ids, filenames)
            ],
        )
        self.tasks[batch_id] = task
        self.connections[batch_id] = []
        self._cancel_flags[batch_id] = False
        return task

    def get_task(self, batch_id: str) -> Optional[BatchTask]:
        return self.tasks.get(batch_id)

    def cancel_task(self, batch_id: str):
        self._cancel_flags[batch_id] = True

    def is_cancelled(self, batch_id: str) -> bool:
        return self._cancel_flags.get(batch_id, False)

    async def update_result(self, batch_id: str, result: ProcessResult):
        task = self.tasks.get(batch_id)
        if not task:
            return

        # 更新对应结果
        for i, r in enumerate(task.results):
            if r.id == result.id:
                task.results[i] = result
                break

        done_count = sum(1 for r in task.results if r.status in ("done", "error"))
        failed_count = sum(1 for r in task.results if r.status == "error")
        task.done = done_count
        task.failed = failed_count

        if done_count >= task.total:
            task.status = TaskStatus.DONE
        elif task.status == TaskStatus.PENDING:
            task.status = TaskStatus.RUNNING

        await self._broadcast(batch_id, {
            "batch_id": batch_id,
            "total": task.total,
            "done": task.done,
            "failed": task.failed,
            "status": task.status.value,
            "result": result.model_dump(),
        })

    async def register_ws(self, batch_id: str, ws: WebSocket):
        if batch_id not in self.connections:
            self.connections[batch_id] = []
        self.connections[batch_id].append(ws)

    async def remove_ws(self, batch_id: str, ws: WebSocket):
        if batch_id in self.connections:
            self.connections[batch_id] = [
                c for c in self.connections[batch_id] if c is not ws
            ]

    async def _broadcast(self, batch_id: str, data: dict):
        connections = self.connections.get(batch_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            connections.remove(ws)


task_manager = TaskManager()
