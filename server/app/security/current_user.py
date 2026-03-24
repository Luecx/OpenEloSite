from __future__ import annotations

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy.orm import Session

from app.db.repositories import token_repository
from app.db.repositories import user_repository
from app.db.session import get_db


def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("openeelo_session")
    if not session_token:
        return None

    user = token_repository.get_user_by_session_token(db, session_token)
    if user is None:
        return None

    user.last_active_at = user_repository.utcnow()
    db.commit()
    db.refresh(user)
    return user


def get_current_user_required(user=Depends(get_current_user_optional)):
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_role(role_name: str):
    def dependency(user=Depends(get_current_user_required)):
        if role_name not in user_repository.get_role_names(user):
            raise HTTPException(status_code=403, detail="Missing role")
        return user

    return dependency

