from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.db.models.engine import Engine
from app.db.models.engine_request import EngineRequest


PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
DECLINED_STATUS = "declined"


def create_engine_request(
    db: Session,
    requester_user_id: int,
    engine_name: str,
    engine_slug: str,
    protocol: str,
    request_text: str,
    link_url: str | None = None,
) -> EngineRequest:
    engine_request = EngineRequest(
        requester_user_id=requester_user_id,
        engine_name=(engine_name or "").strip(),
        engine_slug=(engine_slug or "").strip(),
        protocol=(protocol or "").strip() or "uci",
        request_text=(request_text or "").strip(),
        link_url=((link_url or "").strip() or None),
        status=PENDING_STATUS,
    )
    db.add(engine_request)
    db.commit()
    db.refresh(engine_request)
    return engine_request


def get_engine_request(db: Session, request_id: int) -> EngineRequest | None:
    return db.scalar(
        select(EngineRequest)
        .options(
            joinedload(EngineRequest.requester),
            joinedload(EngineRequest.reviewer),
            joinedload(EngineRequest.engine),
        )
        .where(EngineRequest.id == request_id)
    )


def get_pending_request_by_slug(db: Session, engine_slug: str) -> EngineRequest | None:
    return db.scalar(
        select(EngineRequest).where(
            EngineRequest.engine_slug == (engine_slug or "").strip(),
            EngineRequest.status == PENDING_STATUS,
        )
    )


def list_requests_for_user(db: Session, user_id: int) -> list[EngineRequest]:
    return list(
        db.scalars(
            select(EngineRequest)
            .options(
                joinedload(EngineRequest.engine),
                joinedload(EngineRequest.reviewer),
            )
            .where(EngineRequest.requester_user_id == user_id)
            .order_by(desc(EngineRequest.created_at))
        )
    )


def list_pending_requests(db: Session, limit: int | None = None) -> list[EngineRequest]:
    query = (
        select(EngineRequest)
        .options(
            joinedload(EngineRequest.requester),
            joinedload(EngineRequest.engine),
        )
        .where(EngineRequest.status == PENDING_STATUS)
        .order_by(EngineRequest.created_at.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def list_recent_requests(db: Session, limit: int = 50) -> list[EngineRequest]:
    return list(
        db.scalars(
            select(EngineRequest)
            .options(
                joinedload(EngineRequest.requester),
                joinedload(EngineRequest.reviewer),
                joinedload(EngineRequest.engine),
            )
            .order_by(desc(EngineRequest.created_at))
            .limit(limit)
        )
    )


def count_pending_requests(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(EngineRequest)
            .where(EngineRequest.status == PENDING_STATUS)
        )
        or 0
    )


def mark_request_approved(
    db: Session,
    engine_request: EngineRequest,
    engine: Engine,
    reviewed_by_user_id: int,
    admin_message: str | None = None,
) -> EngineRequest:
    engine_request.status = APPROVED_STATUS
    engine_request.engine_id = engine.id
    engine_request.reviewed_by_user_id = reviewed_by_user_id
    engine_request.reviewed_at = datetime.utcnow()
    engine_request.admin_message = ((admin_message or "").strip() or None)
    db.commit()
    db.refresh(engine_request)
    return engine_request


def mark_request_declined(
    db: Session,
    engine_request: EngineRequest,
    reviewed_by_user_id: int,
    admin_message: str,
) -> EngineRequest:
    engine_request.status = DECLINED_STATUS
    engine_request.reviewed_by_user_id = reviewed_by_user_id
    engine_request.reviewed_at = datetime.utcnow()
    engine_request.admin_message = (admin_message or "").strip()
    db.commit()
    db.refresh(engine_request)
    return engine_request


def delete_engine_request(db: Session, engine_request: EngineRequest) -> None:
    db.delete(engine_request)
    db.commit()
