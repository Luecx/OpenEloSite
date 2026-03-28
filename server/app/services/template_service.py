from __future__ import annotations

from fastapi import Request

from app.db.models.user import User
from app.db.repositories import user_repository
from app.services.i18n_service import get_language
from app.services.i18n_service import translate
from app.settings import get_settings


def _translate_notice(language: str, value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return translate(language, text)


def build_context(request: Request, current_user: User | None, **extra):
    role_names = user_repository.get_role_names(current_user) if current_user else []
    language = get_language(request)
    theme = request.cookies.get("openeelo_theme", "light").strip().lower() or "light"
    if theme not in {"light", "dark"}:
        theme = "light"
    message = extra.pop("message", request.query_params.get("message"))
    error = extra.pop("error", request.query_params.get("error"))
    return {
        "request": request,
        "settings": get_settings(),
        "current_user": current_user,
        "role_names": role_names,
        "language": language,
        "theme": theme,
        "tr": lambda text: translate(language, text),
        "message": _translate_notice(language, message),
        "error": _translate_notice(language, error),
        **extra,
    }
