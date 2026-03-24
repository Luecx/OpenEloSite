from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.client_token import ClientToken
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.security.token_factory import hash_token


def create_session(db: Session, user_id: int, plain_token: str, user_agent: str | None) -> UserSession:
    record = UserSession(
        user_id=user_id,
        token_hash=hash_token(plain_token),
        user_agent=user_agent,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_user_by_session_token(db: Session, plain_token: str) -> User | None:
    now = datetime.utcnow()
    record = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == hash_token(plain_token),
            UserSession.expires_at > now,
        )
    )
    if record is None:
        return None
    return db.get(User, record.user_id)


def revoke_session(db: Session, plain_token: str) -> None:
    record = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(plain_token)))
    if record:
        db.delete(record)
        db.commit()


def create_client_token(db: Session, user_id: int, name: str, plain_token: str) -> ClientToken:
    record = ClientToken(user_id=user_id, name=name.strip(), token_hash=hash_token(plain_token))
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_client_tokens(db: Session, user_id: int) -> list[ClientToken]:
    return list(
        db.scalars(
            select(ClientToken)
            .where(ClientToken.user_id == user_id, ClientToken.revoked_at.is_(None))
            .order_by(ClientToken.created_at.desc())
        )
    )


def revoke_client_token(db: Session, token_id: int, user_id: int) -> None:
    record = db.scalar(select(ClientToken).where(ClientToken.id == token_id, ClientToken.user_id == user_id))
    if record:
        db.delete(record)
        db.commit()


def get_user_by_client_token(db: Session, plain_token: str) -> User | None:
    token = db.scalar(
        select(ClientToken).where(
            ClientToken.token_hash == hash_token(plain_token),
            ClientToken.revoked_at.is_(None),
        )
    )
    if token is None:
        return None
    return db.get(User, token.user_id)


def create_password_reset_token(db: Session, user_id: int, plain_token: str) -> PasswordResetToken:
    record = PasswordResetToken(
        user_id=user_id,
        token_hash=hash_token(plain_token),
        expires_at=datetime.utcnow() + timedelta(hours=3),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_password_reset_token(db: Session, plain_token: str) -> PasswordResetToken | None:
    return db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(plain_token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.utcnow(),
        )
    )
