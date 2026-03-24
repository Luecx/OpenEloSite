from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import Request
from sqlalchemy.orm import Session

from app.api.http import redirect_to
from app.api.templates import templates
from app.db.repositories import token_repository
from app.db.repositories import user_repository
from app.db.session import get_db
from app.security.current_user import get_current_user_optional
from app.services import audit_service
from app.services import auth_service
from app.services.template_service import build_context


router = APIRouter(prefix="/auth")


@router.get("/register")
def register_page(request: Request, current_user=Depends(get_current_user_optional)):
    context = build_context(request, current_user, page_title="Registrierung")
    return templates.TemplateResponse("pages/auth/register.html", context)


@router.post("/register")
def register_action(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if user_repository.get_user_by_email(db, email) or user_repository.get_user_by_username(db, username):
        context = build_context(request, None, error="E-Mail oder Benutzername existiert bereits.", page_title="Registrierung")
        return templates.TemplateResponse("pages/auth/register.html", context)

    user = auth_service.register_user(db, username, display_name, email, password)
    audit_service.log_action(db, user.id, "register", "user", str(user.id), "Neues Konto erstellt.")
    return redirect_to("/auth/login", "Konto erstellt. Bitte einloggen.")


@router.get("/login")
def login_page(request: Request, current_user=Depends(get_current_user_optional)):
    context = build_context(request, current_user, page_title="Login")
    return templates.TemplateResponse("pages/auth/login.html", context)


@router.post("/login")
def login_action(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth_service.authenticate_user(db, login, password)
    if user is None:
        context = build_context(request, None, error="Login fehlgeschlagen.", page_title="Login")
        return templates.TemplateResponse("pages/auth/login.html", context)

    session_token = auth_service.create_login_session(db, user, request.headers.get("user-agent"))
    audit_service.log_action(db, user.id, "login", "user", str(user.id), "Login erfolgreich.")
    response = redirect_to("/dashboard", "Willkommen bei OpenELO.")
    response.set_cookie("openeelo_session", session_token, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout_action(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    session_token = request.cookies.get("openeelo_session")
    if session_token:
        token_repository.revoke_session(db, session_token)
    if current_user:
        audit_service.log_action(db, current_user.id, "logout", "user", str(current_user.id), "Logout.")
    response = redirect_to("/", "Abgemeldet.")
    response.delete_cookie("openeelo_session")
    return response


@router.get("/password-reset")
def password_reset_page(request: Request, current_user=Depends(get_current_user_optional)):
    context = build_context(request, current_user, page_title="Passwort zuruecksetzen")
    return templates.TemplateResponse("pages/auth/password_reset_request.html", context)


@router.post("/password-reset")
def password_reset_request(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = user_repository.get_user_by_email(db, email)
    reset_token = None
    if user:
        reset_token = auth_service.create_password_reset(db, user)
        audit_service.log_action(db, user.id, "password_reset_request", "user", str(user.id), "Passwort-Reset angefragt.")

    context = build_context(
        request,
        None,
        reset_token=reset_token,
        page_title="Passwort zuruecksetzen",
        message="Falls die E-Mail existiert, wurde ein Reset-Token erzeugt.",
    )
    return templates.TemplateResponse("pages/auth/password_reset_request.html", context)


@router.get("/password-reset/{token}")
def password_reset_confirm_page(request: Request, token: str, current_user=Depends(get_current_user_optional)):
    context = build_context(request, current_user, token=token, page_title="Neues Passwort setzen")
    return templates.TemplateResponse("pages/auth/password_reset_confirm.html", context)


@router.post("/password-reset/{token}")
def password_reset_confirm(
    request: Request,
    token: str,
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = auth_service.reset_password(db, token, password)
    if user is None:
        context = build_context(request, None, token=token, error="Token ungueltig oder abgelaufen.", page_title="Neues Passwort setzen")
        return templates.TemplateResponse("pages/auth/password_reset_confirm.html", context)

    audit_service.log_action(db, user.id, "password_reset_complete", "user", str(user.id), "Passwort zurueckgesetzt.")
    return redirect_to("/auth/login", "Passwort aktualisiert.")
