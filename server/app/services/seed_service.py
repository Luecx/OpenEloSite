from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import user_repository
from app.security.password_hasher import hash_password
from app.security.role_names import ADMIN_ROLE
from app.security.role_names import ENGINE_OWNER_ROLE
from app.security.role_names import TESTER_ROLE
from app.settings import get_settings


def ensure_roles(db: Session) -> None:
    user_repository.ensure_role(db, ADMIN_ROLE, "Admin", "Kann das gesamte System verwalten.")
    user_repository.ensure_role(db, TESTER_ROLE, "Tester", "Kann Clients registrieren und verwalten.")
    user_repository.ensure_role(db, ENGINE_OWNER_ROLE, "Engine Owner", "Kann Engines und Versionen verwalten.")


def ensure_admin(db: Session) -> None:
    settings = get_settings()
    existing = user_repository.get_user_by_email(db, settings.default_admin_email)
    if existing:
        user_repository.assign_role(db, existing, ADMIN_ROLE)
        user_repository.assign_role(db, existing, TESTER_ROLE)
        user_repository.assign_role(db, existing, ENGINE_OWNER_ROLE)
        return

    admin = user_repository.create_user(
        db=db,
        username=settings.default_admin_username,
        display_name="Administrator",
        email=settings.default_admin_email,
        password_hash=hash_password(settings.default_admin_password),
    )
    user_repository.assign_role(db, admin, ADMIN_ROLE)
    user_repository.assign_role(db, admin, TESTER_ROLE)
    user_repository.assign_role(db, admin, ENGINE_OWNER_ROLE)
