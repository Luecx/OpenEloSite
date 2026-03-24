from __future__ import annotations

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.client import Client
from app.db.models.engine import Engine
from app.db.models.engine_version import EngineVersion
from app.db.models.match import Match
from app.db.repositories import client_repository


def get_summary(db: Session) -> dict[str, int]:
    return {
        "engines": db.scalar(select(func.count(Engine.id))) or 0,
        "versions": db.scalar(select(func.count(EngineVersion.id))) or 0,
        "clients": client_repository.count_active_clients(db),
        "matches": db.scalar(select(func.count(Match.id))) or 0,
    }
