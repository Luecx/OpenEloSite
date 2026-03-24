from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_role import UserRole


def utcnow() -> datetime:
    return datetime.utcnow()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username.strip()))


def get_user_by_login(db: Session, login: str) -> User | None:
    normalized = (login or "").strip()
    if not normalized:
        return None
    user = get_user_by_username(db, normalized)
    if user is not None:
        return user
    return get_user_by_email(db, normalized)


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())))


def list_users_for_picker(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.display_name.asc(), User.username.asc())))


def list_roles(db: Session) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.name.asc())))


def get_role_by_name(db: Session, role_name: str) -> Role | None:
    return db.scalar(select(Role).where(Role.name == role_name))


def get_role_names(user: User) -> list[str]:
    return [item.role.name for item in user.roles]


def has_role(user: User, role_name: str) -> bool:
    return role_name in get_role_names(user)


def create_user(
    db: Session,
    username: str,
    display_name: str,
    email: str,
    password_hash: str,
    account_status: str = "active",
) -> User:
    user = User(
        username=username.strip(),
        display_name=display_name.strip(),
        email=email.lower().strip(),
        password_hash=password_hash,
        account_status=account_status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_profile(
    db: Session,
    user: User,
    display_name: str,
    bio: str,
    github_url: str,
    organization: str,
) -> User:
    user.display_name = display_name.strip()
    user.bio = bio.strip() or None
    user.github_url = github_url.strip() or None
    user.organization = organization.strip() or None
    user.last_active_at = utcnow()
    db.commit()
    db.refresh(user)
    return user


def ensure_role(db: Session, name: str, label: str, description: str) -> Role:
    existing = get_role_by_name(db, name)
    if existing:
        return existing

    role = Role(name=name, label=label, description=description)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def assign_role(db: Session, user: User, role_name: str) -> None:
    role = get_role_by_name(db, role_name)
    if role is None:
        return

    if has_role(user, role_name):
        return

    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    db.refresh(user)


def remove_role(db: Session, user: User, role_name: str) -> None:
    role = get_role_by_name(db, role_name)
    if role is None:
        return

    link = db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id))
    if link is None:
        return

    db.delete(link)
    db.commit()
    db.refresh(user)
