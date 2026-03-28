from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import queue
import threading
from typing import Any

from fastapi import HTTPException

from app.db.models.engine_version import EngineVersion
from app.db.models.rating_list import RatingList
from app.db.repositories import catalog_repository
from app.db.repositories import client_repository
from app.db.repositories import engine_repository
from app.db.session import SessionLocal
from app.services import assignment_service
from app.services import job_service
from app.services import matchmaker_service
from app.services.syzygy_service import syzygy_label


def _build_job_payload(db, client, assignment) -> dict:
    engine_1_version = db.get(EngineVersion, assignment.engine_version_id)
    engine_2_version = db.get(EngineVersion, assignment.opponent_version_id)
    rating_list = db.get(RatingList, assignment.rating_list_id)
    if engine_1_version is None or engine_2_version is None or rating_list is None:
        raise HTTPException(status_code=500, detail="Assignment is incomplete")

    book = rating_list.opening_book
    if book is not None:
        book = catalog_repository.ensure_book_hash(db, book)

    artifact_pair = engine_repository.pick_fair_artifact_pair(
        engine_1_version,
        engine_2_version,
        client.system_name,
        client.cpu_flags,
    )
    if artifact_pair is None:
        raise HTTPException(status_code=500, detail="No fair artifact pair was found for the client")
    engine_1_artifact, engine_2_artifact = artifact_pair

    return {
        "job_id": assignment.id,
        "time_control": rating_list.time_control_label,
        "time_control_base_seconds": rating_list.time_control_base_seconds,
        "time_control_increment_seconds": rating_list.time_control_increment_seconds,
        "time_control_moves": rating_list.time_control_moves,
        "opening_book": {
            "name": book.name,
            "file_name": book.file_name,
            "hash": book.content_hash,
            "source": f"/api/client/books/{book.id}",
        } if book is not None else None,
        "engine_1": {
            "name": engine_1_version.engine.name,
            "version_name": engine_1_version.version_name,
            "display_name": engine_1_version.display_name,
            "artifact": {
                "id": engine_1_artifact.id,
                "file_name": engine_1_artifact.file_name,
                "hash": engine_1_artifact.content_hash,
                "system_name": engine_1_artifact.system_name,
                "required_cpu_flags": engine_1_artifact.required_cpu_flags,
                "source": f"/api/client/artifacts/{engine_1_artifact.id}",
            },
        },
        "engine_2": {
            "name": engine_2_version.engine.name,
            "version_name": engine_2_version.version_name,
            "display_name": engine_2_version.display_name,
            "artifact": {
                "id": engine_2_artifact.id,
                "file_name": engine_2_artifact.file_name,
                "hash": engine_2_artifact.content_hash,
                "system_name": engine_2_artifact.system_name,
                "required_cpu_flags": engine_2_artifact.required_cpu_flags,
                "source": f"/api/client/artifacts/{engine_2_artifact.id}",
            },
        },
        "hash_per_engine": assignment.hash_per_engine,
        "syzygy_probe_limit": rating_list.syzygy_probe_limit,
        "syzygy_label": syzygy_label(rating_list.syzygy_probe_limit),
        "threads_per_engine": assignment.threads_per_engine,
        "num_games": assignment.num_games,
        "seed": assignment.seed,
    }


@dataclass(slots=True)
class _ClientTask:
    kind: str
    user_id: int
    payload: dict[str, Any]
    job_id: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


class ClientTaskThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._queue: queue.Queue[_ClientTask | None] = queue.Queue()

    def submit_next_job(self, user_id: int, payload: dict[str, Any]) -> dict:
        task = _ClientTask(kind="next_job", user_id=user_id, payload=dict(payload))
        return self._submit(task)

    def submit_complete_job(self, user_id: int, job_id: str, payload: dict[str, Any]) -> dict:
        task = _ClientTask(kind="complete_job", user_id=user_id, payload=dict(payload), job_id=job_id)
        return self._submit(task)

    def _submit(self, task: _ClientTask) -> dict:
        if not self.is_alive():
            raise HTTPException(status_code=503, detail="Client task worker is not running")
        self._queue.put(task)
        task.done.wait()
        if task.error is not None:
            raise task.error
        return task.result

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                self._queue.task_done()
                break
            try:
                if task.kind == "next_job":
                    task.result = self._handle_next_job(task.user_id, task.payload)
                elif task.kind == "complete_job":
                    task.result = self._handle_complete_job(task.user_id, task.job_id or "", task.payload)
                else:
                    raise RuntimeError(f"Unknown client task: {task.kind}")
            except Exception as error:
                task.error = error
            finally:
                task.done.set()
                self._queue.task_done()

    def _handle_next_job(self, user_id: int, payload: dict[str, Any]) -> dict:
        client_id = payload.get("client_id")
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id is required")

        db = SessionLocal()
        try:
            client = client_repository.get_client_for_user(db, int(client_id), user_id)
            if client is None:
                raise HTTPException(status_code=404, detail="Client not found")

            client_repository.touch_client(db, client, state="idle")
            assignment = assignment_service.get_client_assignment(client.id)
            if assignment is None:
                assignment = matchmaker_service.assign_next_job(db, client)
            if assignment is None:
                return {"job": None}
            client_repository.touch_client(db, client, state="running")
            return {"job": _build_job_payload(db, client, assignment)}
        finally:
            db.close()

    def _handle_complete_job(self, user_id: int, job_id: str, payload: dict[str, Any]) -> dict:
        client_id = payload.get("client_id")
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id is required")

        db = SessionLocal()
        try:
            client = client_repository.get_client_for_user(db, int(client_id), user_id)
            if client is None:
                raise HTTPException(status_code=404, detail="Client not found")
            assignment = assignment_service.consume_assignment(job_id, client.id, user_id)
            if assignment is None:
                raise HTTPException(status_code=404, detail="Job not found")

            job_service.record_match_result(
                db=db,
                assignment=assignment,
                wins=int(payload.get("wins", 0) or 0),
                draws=int(payload.get("draws", 0) or 0),
                losses=int(payload.get("losses", 0) or 0),
                games_count=int(payload.get("games_count", 0) or 0),
                pgn_zip_base64=payload.get("pgn_zip_base64", ""),
                status=payload.get("status", "completed"),
                error_text=payload.get("error"),
                runtime_seconds=int(payload.get("runtime_seconds", 0) or 0) or None,
            )
            client_repository.touch_client(db, client, state="idle")
            return {"status": "ok"}
        finally:
            db.close()


_client_task_worker: ClientTaskThread | None = None


def start_client_task_worker() -> ClientTaskThread:
    global _client_task_worker
    if _client_task_worker is not None and _client_task_worker.is_alive():
        return _client_task_worker
    _client_task_worker = ClientTaskThread()
    _client_task_worker.start()
    return _client_task_worker


def get_client_task_worker() -> ClientTaskThread:
    if _client_task_worker is None or not _client_task_worker.is_alive():
        raise HTTPException(status_code=503, detail="Client task worker is not running")
    return _client_task_worker


def stop_client_task_worker() -> None:
    global _client_task_worker
    if _client_task_worker is None:
        return
    _client_task_worker.stop()
    _client_task_worker.join(timeout=2)
    _client_task_worker = None
