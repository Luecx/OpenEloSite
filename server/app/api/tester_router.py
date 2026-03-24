from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.http import redirect_to
from app.db.repositories import client_repository
from app.db.session import get_db
from app.security.current_user import require_role
from app.security.role_names import TESTER_ROLE
from app.services import audit_service


router = APIRouter(prefix="/tester")


@router.get("/clients")
def clients_page(current_user=Depends(require_role(TESTER_ROLE))):
    return RedirectResponse(url="/clients", status_code=303)


@router.get("/clients/{client_id}")
def client_detail(client_id: int, current_user=Depends(require_role(TESTER_ROLE))):
    return RedirectResponse(url=f"/clients/{client_id}", status_code=303)


@router.post("/clients/{client_id}/delete")
def client_delete(client_id: int, db: Session = Depends(get_db), current_user=Depends(require_role(TESTER_ROLE))):
    client = client_repository.get_client_for_user(db, client_id, current_user.id)
    if client:
        client_repository.delete_client(db, client)
        audit_service.log_action(db, current_user.id, "client_delete", "client", str(client_id), "Client geloescht.")
    return redirect_to("/tester/clients", "Client entfernt.")
