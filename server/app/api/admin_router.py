from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.http import redirect_to
from app.api.templates import templates
from app.db.models.audit_log import AuditLog
from app.db.repositories import catalog_repository
from app.db.repositories import client_repository
from app.db.repositories import job_repository
from app.db.repositories import engine_repository
from app.db.repositories import user_repository
from app.db.session import get_db
from app.security.current_user import require_role
from app.security.role_names import ADMIN_ROLE
from app.services import audit_service
from app.services import bench_service
from app.services.dashboard_service import get_summary
from app.services import matchmaker_service
from app.services.storage_service import store_upload
from app.services.template_service import build_context


router = APIRouter(prefix="/admin")


def _parse_optional_int(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    return int(value)


def _parse_optional_float(raw_value: str) -> float | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    return float(value)


@router.get("")
@router.get("/")
def admin_home(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    context = build_context(
        request,
        current_user,
        summary=get_summary(db),
        page_title="Admin",
    )
    return templates.TemplateResponse("pages/admin/index.html", context)


@router.get("/users")
def users_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    return RedirectResponse(url="/users", status_code=303)


@router.post("/users/{user_id}/roles")
def update_user_role(
    user_id: int,
    role_name: str = Form(...),
    operation: str = Form("assign"),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    user = user_repository.get_user_by_id(db, user_id)
    if user is None:
        return redirect_to("/admin/users", "Nutzer nicht gefunden.")

    if operation == "remove":
        user_repository.remove_role(db, user, role_name)
    else:
        user_repository.assign_role(db, user, role_name)
    audit_service.log_action(db, current_user.id, "user_role_update", "user", str(user_id), f"Rolle {role_name} angepasst.")
    return redirect_to("/admin/users", "Rolle aktualisiert.")


@router.get("/versions")
def versions_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/catalog")
def catalog_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    return RedirectResponse(url="/rating-lists", status_code=303)


@router.post("/books")
def create_book(
    name: str = Form(...),
    description: str = Form(""),
    format_name: str = Form("pgn"),
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    target_dir = Path(__file__).resolve().parents[2] / "data" / "books"
    file_name, file_path, content_hash = store_upload(upload, target_dir)
    book = catalog_repository.create_book(
        db=db,
        name=name,
        description=description,
        file_name=file_name,
        file_path=file_path,
        content_hash=content_hash,
        format_name=format_name,
        uploaded_by_user_id=current_user.id,
    )
    audit_service.log_action(db, current_user.id, "book_create", "opening_book", str(book.id), "Opening-Book hochgeladen.")
    return redirect_to("/books", "Book hochgeladen.")


@router.get("/books/new")
def new_book_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    context = build_context(
        request,
        current_user,
        book=None,
        page_title="Neues Book",
    )
    return templates.TemplateResponse("pages/admin/book_form.html", context)


@router.get("/books/{book_id}/edit")
def edit_book_page(book_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    book = catalog_repository.get_book(db, book_id)
    if book is None:
        return redirect_to("/books", "Book nicht gefunden.")
    context = build_context(
        request,
        current_user,
        book=book,
        page_title=f"Book {book.name}",
    )
    return templates.TemplateResponse("pages/admin/book_form.html", context)


@router.post("/books/{book_id}")
def update_book(
    book_id: int,
    name: str = Form(...),
    description: str = Form(""),
    format_name: str = Form("pgn"),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    book = catalog_repository.get_book(db, book_id)
    if book is None:
        return redirect_to("/books", "Book nicht gefunden.")

    catalog_repository.update_book(db, book, name, description, format_name)
    audit_service.log_action(db, current_user.id, "book_update", "opening_book", str(book.id), "Opening-Book aktualisiert.")
    return redirect_to("/books", "Book gespeichert.")


@router.post("/books/{book_id}/delete")
def delete_book(
    book_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    book = catalog_repository.get_book(db, book_id)
    if book is None:
        return redirect_to("/books", "Book nicht gefunden.")
    catalog_repository.delete_book(db, book)
    audit_service.log_action(db, current_user.id, "book_delete", "opening_book", str(book_id), "Opening-Book entfernt.")
    return redirect_to("/books", "Book entfernt.")


@router.get("/bench")
def bench_page(
    request: Request,
    artifact_id: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    edit_artifact = bench_service.get_bench_artifact(artifact_id) if artifact_id else None
    context = build_context(
        request,
        current_user,
        bench_artifacts=bench_service.list_bench_artifacts(),
        edit_artifact=edit_artifact,
        page_title="Bench",
    )
    return templates.TemplateResponse("pages/admin/bench.html", context)


@router.post("/bench/artifacts")
def create_bench_artifact(
    system_name: str = Form(...),
    required_cpu_flags: list[str] = Form(default=[]),
    reference_nps: int = Form(...),
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    target_dir = Path(__file__).resolve().parents[2] / "data" / "bench"
    file_name, file_path, content_hash = store_upload(upload, target_dir)
    artifact = bench_service.create_bench_artifact(
        file_name=file_name,
        file_path=file_path,
        content_hash=content_hash,
        system_name=system_name,
        required_cpu_flags=required_cpu_flags,
        reference_nps=reference_nps,
    )
    audit_service.log_action(db, current_user.id, "bench_artifact_create", "bench", artifact["id"], "Bench-Artifact hochgeladen.")
    return redirect_to("/admin/bench", "Bench-Artifact hochgeladen.")


@router.post("/bench/artifacts/{artifact_id}")
def update_bench_artifact(
    artifact_id: str,
    system_name: str = Form(...),
    required_cpu_flags: list[str] = Form(default=[]),
    reference_nps: int = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    artifact = bench_service.update_bench_artifact(artifact_id, system_name, required_cpu_flags, reference_nps)
    if artifact is None:
        return redirect_to("/admin/bench", "Bench-Artifact nicht gefunden.")
    audit_service.log_action(db, current_user.id, "bench_artifact_update", "bench", artifact_id, "Bench-Artifact aktualisiert.")
    return redirect_to("/admin/bench", "Bench-Artifact gespeichert.")


@router.post("/bench/artifacts/{artifact_id}/delete")
def delete_bench_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    deleted = bench_service.delete_bench_artifact(artifact_id)
    if not deleted:
        return redirect_to("/admin/bench", "Bench-Artifact nicht gefunden.")
    audit_service.log_action(db, current_user.id, "bench_artifact_delete", "bench", artifact_id, "Bench-Artifact entfernt.")
    return redirect_to("/admin/bench", "Bench-Artifact entfernt.")


@router.post("/bench/artifacts/{artifact_id}/move")
def move_bench_artifact(
    artifact_id: str,
    direction: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    artifact = bench_service.move_bench_artifact_priority(artifact_id, direction)
    if artifact is None:
        return redirect_to("/admin/bench", "Bench-Artifact nicht gefunden.")
    audit_service.log_action(db, current_user.id, "bench_artifact_reorder", "bench", artifact_id, f"Bench-Artifact {direction}.")
    return redirect_to("/admin/bench", "Bench-Artifact verschoben.")


@router.post("/rating-lists")
def create_rating_list(
    name: str = Form(...),
    description: str = Form(""),
    time_control_base_seconds: int = Form(60),
    time_control_increment_seconds: int = Form(1),
    time_control_moves: str = Form(""),
    threads_per_engine: int = Form(1),
    hash_per_engine: int = Form(16),
    syzygy_probe_limit: int = Form(0),
    opening_book_id: str = Form(""),
    anchor_engine_version_id: str = Form(""),
    anchor_rating: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    rating_list = catalog_repository.create_rating_list(
        db=db,
        name=name,
        description=description,
        time_control_base_seconds=time_control_base_seconds,
        time_control_increment_seconds=time_control_increment_seconds,
        time_control_moves=_parse_optional_int(time_control_moves),
        threads_per_engine=threads_per_engine,
        hash_per_engine=hash_per_engine,
        syzygy_probe_limit=syzygy_probe_limit,
        opening_book_id=_parse_optional_int(opening_book_id),
        anchor_engine_version_id=_parse_optional_int(anchor_engine_version_id),
        anchor_rating=_parse_optional_float(anchor_rating),
    )
    audit_service.log_action(db, current_user.id, "rating_list_create", "rating_list", str(rating_list.id), "Rating-Liste angelegt.")
    return redirect_to(f"/rating-lists/{rating_list.slug}", "Rating-Liste angelegt.")


@router.get("/rating-lists/new")
def new_rating_list_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    context = build_context(
        request,
        current_user,
        rating_list=None,
        books=catalog_repository.list_books(db),
        versions=engine_repository.list_versions_for_picker(db),
        page_title="Neue Rating-Liste",
    )
    return templates.TemplateResponse("pages/admin/rating_list_form.html", context)


@router.get("/rating-lists/{rating_list_id}/edit")
def edit_rating_list_page(
    rating_list_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    rating_list = catalog_repository.get_rating_list(db, rating_list_id)
    if rating_list is None:
        return redirect_to("/rating-lists", "Rating-Liste nicht gefunden.")
    versions = engine_repository.list_versions_for_rating_list(db, rating_list.id)
    if rating_list.anchor_engine_version is not None and all(item.id != rating_list.anchor_engine_version.id for item in versions):
        versions = [rating_list.anchor_engine_version, *versions]
    context = build_context(
        request,
        current_user,
        rating_list=rating_list,
        books=catalog_repository.list_books(db),
        versions=versions,
        page_title=f"Rating-Liste {rating_list.name}",
    )
    return templates.TemplateResponse("pages/admin/rating_list_form.html", context)


@router.post("/rating-lists/{rating_list_id}")
def update_rating_list(
    rating_list_id: int,
    name: str = Form(...),
    description: str = Form(""),
    time_control_base_seconds: int = Form(60),
    time_control_increment_seconds: int = Form(1),
    time_control_moves: str = Form(""),
    threads_per_engine: int = Form(1),
    hash_per_engine: int = Form(16),
    syzygy_probe_limit: int = Form(0),
    opening_book_id: str = Form(""),
    anchor_engine_version_id: str = Form(""),
    anchor_rating: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    rating_list = catalog_repository.get_rating_list(db, rating_list_id)
    if rating_list is None:
        return redirect_to("/rating-lists", "Rating-Liste nicht gefunden.")

    catalog_repository.update_rating_list(
        db,
        rating_list,
        name,
        description,
        time_control_base_seconds,
        time_control_increment_seconds,
        _parse_optional_int(time_control_moves),
        threads_per_engine,
        hash_per_engine,
        syzygy_probe_limit,
        _parse_optional_int(opening_book_id),
        _parse_optional_int(anchor_engine_version_id),
        _parse_optional_float(anchor_rating),
    )
    audit_service.log_action(db, current_user.id, "rating_list_update", "rating_list", str(rating_list.id), "Rating-Liste aktualisiert.")
    return redirect_to(f"/rating-lists/{rating_list.slug}", "Rating-Liste gespeichert.")


@router.post("/rating-lists/{rating_list_id}/delete")
def delete_rating_list(
    rating_list_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    rating_list = catalog_repository.get_rating_list(db, rating_list_id)
    if rating_list is None:
        return redirect_to("/rating-lists", "Rating-Liste nicht gefunden.")
    catalog_repository.delete_rating_list(db, rating_list)
    audit_service.log_action(db, current_user.id, "rating_list_delete", "rating_list", str(rating_list_id), "Rating-Liste entfernt.")
    return redirect_to("/rating-lists", "Rating-Liste entfernt.")


@router.get("/matchmaker")
def matchmaker_page(
    request: Request,
    user_id: int | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(ADMIN_ROLE)),
):
    preview_user = user_repository.get_user_by_id(db, user_id or current_user.id)
    if preview_user is None:
        return redirect_to("/admin/matchmaker", "Nutzer nicht gefunden.")

    preview_clients = client_repository.list_clients_for_user(db, preview_user.id)
    preview_client = preview_clients[0] if preview_clients else None
    preview_rows = matchmaker_service.preview_matchups_for_client(db, preview_client, limit=20) if preview_client is not None else []
    context = build_context(
        request,
        current_user,
        users=user_repository.list_users_for_picker(db),
        preview_user=preview_user,
        preview_client=preview_client,
        preview_rows=preview_rows,
        page_title="Matchmaker",
    )
    return templates.TemplateResponse("pages/admin/matchmaker.html", context)


@router.get("/system")
def system_page(request: Request, db: Session = Depends(get_db), current_user=Depends(require_role(ADMIN_ROLE))):
    logs = list(db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(25)))
    context = build_context(
        request,
        current_user,
        summary=get_summary(db),
        match_jobs=job_repository.list_recent_match_jobs(db),
        logs=logs,
        page_title="Systemstatus",
    )
    return templates.TemplateResponse("pages/admin/system.html", context)
