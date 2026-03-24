from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog


def log_action(db: Session, user_id: int | None, action: str, target_type: str, target_id: str, message: str) -> None:
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                message=message,
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
