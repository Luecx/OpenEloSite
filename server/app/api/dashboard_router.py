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
from app.security.current_user import get_current_user_required
from app.security.token_factory import create_plain_token
from app.services import audit_service
from app.services.template_service import build_context
from fastapi.responses import RedirectResponse

from app.db.repositories import client_repository
from app.db.repositories import engine_repository


router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_required)):
    return RedirectResponse(url="/profile", status_code=303)


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_required)):
    context = build_context(
        request,
        current_user,
        client_tokens=token_repository.list_client_tokens(db, current_user.id),
        my_clients=client_repository.list_clients_for_user(db, current_user.id),
        my_engines=engine_repository.list_user_engines(db, current_user.id),
        page_title="Profil",
    )
    return templates.TemplateResponse("pages/profile/index.html", context)


@router.post("/profile")
def profile_update(
    request: Request,
    display_name: str = Form(...),
    bio: str = Form(""),
    github_url: str = Form(""),
    organization: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    user_repository.update_profile(db, current_user, display_name, bio, github_url, organization)
    audit_service.log_action(db, current_user.id, "profile_update", "user", str(current_user.id), "Profil aktualisiert.")
    return redirect_to("/profile", "Profil gespeichert.")


@router.post("/profile/client-tokens")
def create_client_token(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    plain_token = create_plain_token("client")
    token_repository.create_client_token(db, current_user.id, name, plain_token)
    audit_service.log_action(db, current_user.id, "client_token_create", "client_token", name, "Client-Token erstellt.")
    context = build_context(
        request,
        current_user,
        client_tokens=token_repository.list_client_tokens(db, current_user.id),
        my_clients=client_repository.list_clients_for_user(db, current_user.id),
        my_engines=engine_repository.list_user_engines(db, current_user.id),
        new_client_token=plain_token,
        page_title="Profil",
    )
    return templates.TemplateResponse("pages/profile/index.html", context)


@router.post("/profile/client-tokens/{token_id}/revoke")
def revoke_client_token(token_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user_required)):
    token_repository.revoke_client_token(db, token_id, current_user.id)
    audit_service.log_action(db, current_user.id, "client_token_revoke", "client_token", str(token_id), "Client-Token geloescht.")
    return redirect_to("/profile", "Client-Token geloescht.")
