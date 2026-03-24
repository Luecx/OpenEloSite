from __future__ import annotations

import secrets
from datetime import datetime
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.client import Client
from app.services.syzygy_service import normalize_syzygy_probe_limit


ACTIVE_CLIENT_TTL_SECONDS = 120
RELEVANT_CPU_FLAGS = ("sse4", "avx", "avx2", "pext", "avx512")


def _active_cutoff() -> datetime:
    return datetime.utcnow() - timedelta(seconds=ACTIVE_CLIENT_TTL_SECONDS)


def normalize_cpu_flags(values: list[str] | tuple[str, ...] | set[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = values.split(",")
    else:
        raw_values = list(values)
    allowed = set(RELEVANT_CPU_FLAGS)
    normalized = {item.strip().lower() for item in raw_values if item and item.strip() and item.strip().lower() in allowed}
    return [flag for flag in RELEVANT_CPU_FLAGS if flag in normalized]


def serialize_cpu_flags(values: list[str] | tuple[str, ...] | set[str] | str | None) -> str:
    return ",".join(normalize_cpu_flags(values))


def parse_cpu_flags(value: str | None) -> set[str]:
    return set(normalize_cpu_flags(value or ""))


def _build_session_machine_key(machine_fingerprint: str) -> str:
    base = (machine_fingerprint or "client").strip().replace(" ", "-")[:80] or "client"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(4)
    return f"{base}-{timestamp}-{suffix}"[:120]


def list_clients_for_user(db: Session, user_id: int) -> list[Client]:
    return list(
        db.scalars(
            select(Client)
            .where(Client.user_id == user_id, Client.last_seen_at.is_not(None), Client.last_seen_at >= _active_cutoff())
            .order_by(Client.last_seen_at.desc(), Client.created_at.desc())
        )
    )


def list_active_clients(db: Session) -> list[Client]:
    return list(
        db.scalars(
            select(Client)
            .where(Client.last_seen_at.is_not(None), Client.last_seen_at >= _active_cutoff())
            .order_by(Client.last_seen_at.desc(), Client.created_at.desc())
        )
    )


def is_client_active(client: Client) -> bool:
    return client.last_seen_at is not None and client.last_seen_at >= _active_cutoff()


def get_client_for_user(db: Session, client_id: int, user_id: int) -> Client | None:
    return db.scalar(
        select(Client).where(
            Client.id == client_id,
            Client.user_id == user_id,
            Client.last_seen_at.is_not(None),
            Client.last_seen_at >= _active_cutoff(),
        )
    )


def get_client(db: Session, client_id: int) -> Client | None:
    return db.get(Client, client_id)


def get_active_client(db: Session, client_id: int) -> Client | None:
    return db.scalar(
        select(Client).where(
            Client.id == client_id,
            Client.last_seen_at.is_not(None),
            Client.last_seen_at >= _active_cutoff(),
        )
    )


def get_client_by_machine_key(db: Session, machine_key: str) -> Client | None:
    return db.scalar(select(Client).where(Client.machine_key == machine_key))


def count_active_clients(db: Session) -> int:
    return db.scalar(
        select(func.count(Client.id)).where(
            Client.last_seen_at.is_not(None),
            Client.last_seen_at >= _active_cutoff(),
        )
    ) or 0


def create_client(
    db: Session,
    user_id: int,
    machine_fingerprint: str,
    machine_name: str,
    system_name: str,
    max_threads: int,
    max_hash: int,
    syzygy_max_pieces: int | str | None,
    cpu_flags: list[str] | str | None,
    last_state: str = "idle",
) -> Client:
    record = Client(
        user_id=user_id,
        machine_key=_build_session_machine_key(machine_fingerprint),
        machine_fingerprint=machine_fingerprint.strip() or None,
        machine_name=machine_name.strip(),
        system_name=(system_name or "linux").strip().lower() or "linux",
        max_threads=max(1, int(max_threads)),
        max_hash=max(1, int(max_hash)),
        syzygy_max_pieces=normalize_syzygy_probe_limit(syzygy_max_pieces),
        cpu_flags=serialize_cpu_flags(cpu_flags),
        last_state=(last_state or "idle").strip() or "idle",
        last_seen_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def delete_client(db: Session, client: Client) -> None:
    db.delete(client)
    db.commit()


def register_client_session(
    db: Session,
    user_id: int,
    machine_key: str,
    machine_name: str,
    system_name: str,
    max_threads: int,
    max_hash: int,
    syzygy_max_pieces: int | str | None,
    cpu_flags: list[str] | str | None,
    last_state: str = "idle",
) -> Client:
    return create_client(
        db=db,
        user_id=user_id,
        machine_fingerprint=machine_key,
        machine_name=machine_name,
        system_name=system_name,
        max_threads=max_threads,
        max_hash=max_hash,
        syzygy_max_pieces=syzygy_max_pieces,
        cpu_flags=cpu_flags,
        last_state=last_state,
    )


def touch_client(db: Session, client: Client, state: str | None = None) -> Client:
    client.last_seen_at = datetime.utcnow()
    if state is not None and state.strip():
        client.last_state = state.strip()
    db.commit()
    db.refresh(client)
    return client
