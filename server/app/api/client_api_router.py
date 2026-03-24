from __future__ import annotations

from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.repositories import catalog_repository
from app.db.repositories import client_repository
from app.db.repositories import engine_repository
from app.db.repositories import token_repository
from app.db.session import get_db
from app.services import bench_service
from app.services.client_task_service import get_client_task_worker


router = APIRouter(prefix="/api/client")


def get_api_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.replace("Bearer ", "", 1).strip()
    user = token_repository.get_user_by_client_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid client token")
    return user


def _register_or_update_client(payload: dict, db: Session, user):
    machine_key = (payload.get("machine_key") or "").strip()
    machine_name = (payload.get("machine_name") or machine_key or "client").strip()
    if not machine_key:
        raise HTTPException(status_code=400, detail="machine_key fehlt")
    try:
        return client_repository.register_client_session(
            db=db,
            user_id=user.id,
            machine_key=machine_key,
            machine_name=machine_name,
            system_name=payload.get("system_name", "linux"),
            max_threads=payload.get("max_threads", 1),
            max_hash=payload.get("max_hash", 256),
            syzygy_max_pieces=payload.get("syzygy_max_pieces", 0),
            cpu_flags=payload.get("cpu_flags") or [],
            last_state=payload.get("state", "idle"),
        )
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

@router.post("/register")
def register_client(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_api_user),
):
    client = _register_or_update_client(payload, db, user)
    bench = bench_service.build_bench_payload(client.system_name, client.cpu_flags)
    if bench is None:
        raise HTTPException(status_code=503, detail="Kein passendes Bench-Artifact fuer diesen Client gefunden")
    return {
        "client_id": client.id,
        "heartbeat_interval_seconds": 15,
        "poll_interval_seconds": 5,
        "bench": bench,
    }


@router.post("/heartbeat")
def heartbeat(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user=Depends(get_api_user),
):
    client_id = payload.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id fehlt")
    client = client_repository.get_client_for_user(db, int(client_id), user.id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    client_repository.touch_client(db, client, state=payload.get("state"))
    return {"client_id": client.id, "status": "ok"}


@router.post("/jobs/next")
def next_job(
    payload: dict = Body(...),
    user=Depends(get_api_user),
):
    return get_client_task_worker().submit_next_job(user.id, payload)


@router.post("/jobs/{job_id}/complete")
def complete_job(
    job_id: str,
    payload: dict = Body(...),
    user=Depends(get_api_user),
):
    return get_client_task_worker().submit_complete_job(user.id, job_id, payload)


@router.get("/books/{book_id}")
def download_book(book_id: int, db: Session = Depends(get_db), user=Depends(get_api_user)):
    book = catalog_repository.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    with open(book.file_path, "rb") as handle:
        content = handle.read()
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{book.file_name}"'},
    )


@router.get("/artifacts/{artifact_id}")
def download_artifact(artifact_id: int, db: Session = Depends(get_db), user=Depends(get_api_user)):
    artifact = engine_repository.get_artifact(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    with open(artifact.file_path, "rb") as handle:
        content = handle.read()
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{artifact.file_name}"'},
    )


@router.get("/bench/{artifact_id}")
def download_bench_artifact(artifact_id: str, user=Depends(get_api_user)):
    artifact = bench_service.get_bench_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Bench artifact not found")
    with open(artifact["path"], "rb") as handle:
        content = handle.read()
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{artifact["file_name"]}"'},
    )
