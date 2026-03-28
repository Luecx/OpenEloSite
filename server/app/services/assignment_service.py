from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
import secrets
import threading


ASSIGNMENT_TTL = timedelta(hours=6)


@dataclass(slots=True)
class ActiveAssignment:
    id: str
    client_id: int
    user_id: int
    engine_version_id: int
    opponent_version_id: int
    rating_list_id: int
    threads_per_engine: int
    hash_per_engine: int
    num_games: int
    seed: int
    created_at: datetime


_lock = threading.Lock()
_assignments_by_id: dict[str, ActiveAssignment] = {}
_assignment_ids_by_client: dict[int, str] = {}


def _cleanup_expired(now: datetime | None = None) -> None:
    cutoff = (now or datetime.utcnow()) - ASSIGNMENT_TTL
    expired_ids = [assignment_id for assignment_id, assignment in _assignments_by_id.items() if assignment.created_at < cutoff]
    for assignment_id in expired_ids:
        assignment = _assignments_by_id.pop(assignment_id, None)
        if assignment is not None:
            _assignment_ids_by_client.pop(assignment.client_id, None)


def get_client_assignment(client_id: int) -> ActiveAssignment | None:
    with _lock:
        _cleanup_expired()
        assignment_id = _assignment_ids_by_client.get(client_id)
        if assignment_id is None:
            return None
        return _assignments_by_id.get(assignment_id)


def create_assignment(
    client,
    engine_version_id: int,
    opponent_version_id: int,
    rating_list_id: int,
    threads_per_engine: int,
    hash_per_engine: int,
    num_games: int,
    seed: int,
) -> ActiveAssignment | None:
    with _lock:
        _cleanup_expired()
        existing_id = _assignment_ids_by_client.get(client.id)
        existing = _assignments_by_id.get(existing_id) if existing_id else None
        if existing is not None:
            return existing

        assignment = ActiveAssignment(
            id=secrets.token_urlsafe(18),
            client_id=client.id,
            user_id=client.user_id,
            engine_version_id=engine_version_id,
            opponent_version_id=opponent_version_id,
            rating_list_id=rating_list_id,
            threads_per_engine=max(1, int(threads_per_engine)),
            hash_per_engine=max(1, int(hash_per_engine)),
            num_games=max(1, int(num_games)),
            seed=int(seed),
            created_at=datetime.utcnow(),
        )
        _assignments_by_id[assignment.id] = assignment
        _assignment_ids_by_client[assignment.client_id] = assignment.id
        return assignment


def consume_assignment(assignment_id: str, client_id: int, user_id: int) -> ActiveAssignment | None:
    with _lock:
        _cleanup_expired()
        assignment = _assignments_by_id.get(assignment_id)
        if assignment is None:
            return None
        if assignment.client_id != client_id or assignment.user_id != user_id:
            return None
        _assignments_by_id.pop(assignment_id, None)
        _assignment_ids_by_client.pop(client_id, None)
        return assignment
