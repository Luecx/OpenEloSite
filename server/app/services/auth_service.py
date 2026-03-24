from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.repositories import token_repository
from app.db.repositories import user_repository
from app.security.password_hasher import hash_password
from app.security.password_hasher import verify_password
from app.security.role_names import TESTER_ROLE
from app.security.token_factory import create_plain_token


def register_user(db: Session, username: str, display_name: str, email: str, password: str) -> User:
    user = user_repository.create_user(
        db=db,
        username=username,
        display_name=display_name,
        email=email,
        password_hash=hash_password(password),
    )
    user_repository.assign_role(db, user, TESTER_ROLE)
    db.refresh(user)
    return user


def authenticate_user(db: Session, login: str, password: str) -> User | None:
    user = user_repository.get_user_by_login(db, login)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if user.account_status in {"blocked", "disabled"}:
        return None
    return user


def create_login_session(db: Session, user: User, user_agent: str | None) -> str:
    plain_token = create_plain_token("sess")
    token_repository.create_session(db, user.id, plain_token, user_agent)
    return plain_token


def create_password_reset(db: Session, user: User) -> str:
    plain_token = create_plain_token("reset")
    token_repository.create_password_reset_token(db, user.id, plain_token)
    return plain_token


def reset_password(db: Session, plain_token: str, new_password: str) -> User | None:
    record = token_repository.get_password_reset_token(db, plain_token)
    if record is None:
        return None

    user = user_repository.get_user_by_id(db, record.user_id)
    if user is None:
        return None

    user.password_hash = hash_password(new_password)
    record.used_at = user_repository.utcnow()
    db.commit()
    db.refresh(user)
    return user
