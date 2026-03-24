from __future__ import annotations

from fastapi import Request

from app.db.models.user import User
from app.db.repositories import user_repository
from app.services.i18n_service import get_language
from app.services.i18n_service import translate
from app.settings import get_settings


def build_context(request: Request, current_user: User | None, **extra):
    role_names = user_repository.get_role_names(current_user) if current_user else []
    language = get_language(request)
    theme = request.cookies.get("openeelo_theme", "light").strip().lower() or "light"
    if theme not in {"light", "dark"}:
        theme = "light"
    return {
        "request": request,
        "settings": get_settings(),
        "current_user": current_user,
        "role_names": role_names,
        "language": language,
        "theme": theme,
        "tr": lambda text: translate(language, text),
        "message": request.query_params.get("message"),
        **extra,
    }
