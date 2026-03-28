from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import Query
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.http import redirect_to
from app.api.templates import templates
from app.db.models.engine_artifact import build_required_cpu_flags
from app.db.repositories import catalog_repository
from app.db.repositories import engine_repository
from app.db.repositories import job_repository
from app.db.repositories import user_repository
from app.db.session import get_db
from app.security.current_user import get_current_user_required
from app.security.role_names import ADMIN_ROLE
from app.services import audit_service
from app.services import job_service
from app.services.job_pgn_service import build_match_pgn_archive
from app.services.storage_service import store_upload
from app.services.template_service import build_context


router = APIRouter(prefix="/owner")


def _is_admin(user) -> bool:
    return user_repository.has_role(user, ADMIN_ROLE)


def _editable_engine_for_user(db: Session, engine_id: int, current_user):
    if current_user is None:
        return None
    if _is_admin(current_user):
        return engine_repository.get_engine(db, engine_id)
    return engine_repository.get_engine_for_user(db, engine_id, current_user.id)


def _manageable_engines_for_user(db: Session, current_user):
    if _is_admin(current_user):
        return engine_repository.list_public_engines(db)
    return engine_repository.list_user_engines(db, current_user.id)


def _parse_required_int(raw_value: str, field_label: str) -> int:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError(f"{field_label} is required.")
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{field_label} must be an integer.") from error


def _parse_optional_int(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError("Version components must be integers.") from error


def _is_checked(raw_value: str | None) -> bool:
    return raw_value is not None


def _artifact_required_flags_from_form(
    simd_class: str,
    requires_popcnt: str | None,
    requires_bmi2: str | None,
    required_avx512_flags: list[str],
) -> list[str]:
    return build_required_cpu_flags(
        simd_class=simd_class,
        requires_popcnt=_is_checked(requires_popcnt),
        requires_bmi2=_is_checked(requires_bmi2),
        required_avx512_flags=required_avx512_flags,
    )


@router.get("/engines")
def engines_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_required)):
    engines = _manageable_engines_for_user(db, current_user)
    context = build_context(
        request,
        current_user,
        engines=engines,
        engine_owners=engine_repository.list_engine_owners_for_engines(db, [item.id for item in engines]),
        can_create_engine=_is_admin(current_user),
        page_title="Meine Engines",
    )
    return templates.TemplateResponse("pages/owner/engines.html", context)


@router.post("/engines")
def create_engine(
    name: str = Form(...),
    description: str = Form(...),
    protocol: str = Form("uci"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    if not _is_admin(current_user):
        return redirect_to("/owner/engines", "Neue Engines koennen nur Admins anlegen.")

    engine = engine_repository.create_engine(
        db=db,
        owner_user_ids=[current_user.id],
        name=name,
        description=description,
        protocol=protocol,
    )
    audit_service.log_action(db, current_user.id, "engine_create", "engine", str(engine.id), "Engine angelegt.")
    return redirect_to(f"/owner/engines/{engine.id}", "Engine angelegt.")


@router.get("/engines/{engine_id}")
def engine_detail(engine_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_required)):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")
    versions = engine_repository.list_versions_for_engine(db, engine.id)
    latest_version = versions[0] if versions else None
    latest_version_leaderboard_entries = (
        sorted(
            [item for item in latest_version.leaderboard_entries if item.rating_list],
            key=lambda item: (item.rank_position or 999999, -item.rating),
        )
        if latest_version is not None
        else []
    )

    context = build_context(
        request,
        current_user,
        engine=engine,
        versions=versions,
        latest_version=latest_version,
        latest_version_leaderboard_entries=latest_version_leaderboard_entries,
        owners=engine_repository.list_engine_owners(db, engine.id),
        tester_users=engine_repository.list_engine_testers(db, engine.id),
        all_users=user_repository.list_users_for_picker(db),
        can_create_engine=_is_admin(current_user),
        page_title=f"Engine {engine.name}",
    )
    return templates.TemplateResponse("pages/owner/engine_detail.html", context)


@router.post("/engines/{engine_id}")
def engine_update(
    engine_id: int,
    description: str = Form(...),
    protocol: str = Form("uci"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")

    engine_repository.update_engine(db, engine, description, protocol)
    audit_service.log_action(db, current_user.id, "engine_update", "engine", str(engine.id), "Engine aktualisiert.")
    return redirect_to(f"/owner/engines/{engine.id}", "Engine gespeichert.")


@router.post("/engines/{engine_id}/owners")
def add_engine_owner(
    engine_id: int,
    owner_username: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    target_user = user_repository.get_user_by_username(db, owner_username)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")
    if target_user is None:
        return redirect_to(f"/owner/engines/{engine_id}", "Owner nicht gefunden.")

    engine_repository.add_owner(db, engine, target_user.id)
    audit_service.log_action(db, current_user.id, "engine_owner_add", "engine", str(engine.id), "Owner hinzugefuegt.")
    return redirect_to(f"/owner/engines/{engine.id}", "Owner hinzugefuegt.")


@router.post("/engines/{engine_id}/owners/{user_id}/remove")
def remove_engine_owner(
    engine_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")

    removed = engine_repository.remove_owner(db, engine, user_id)
    if not removed:
        return redirect_to(f"/owner/engines/{engine.id}", "Owner nicht gefunden.")

    audit_service.log_action(db, current_user.id, "engine_owner_remove", "engine", str(engine.id), f"Owner {user_id} entfernt.")
    return redirect_to(f"/owner/engines/{engine.id}", "Owner entfernt.")


@router.post("/engines/{engine_id}/testers")
def add_engine_tester(
    engine_id: int,
    tester_username: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    target_user = user_repository.get_user_by_username(db, tester_username)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")
    if target_user is None:
        return redirect_to(f"/owner/engines/{engine_id}", "Nutzer nicht gefunden.")

    engine_repository.add_tester(db, engine, target_user.id)
    audit_service.log_action(db, current_user.id, "engine_tester_add", "engine", str(engine.id), "Tester hinzugefuegt.")
    return redirect_to(f"/owner/engines/{engine.id}", "Tester hinzugefuegt.")


@router.post("/engines/{engine_id}/testers/{user_id}/remove")
def remove_engine_tester(
    engine_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")

    removed = engine_repository.remove_tester(db, engine, user_id)
    if not removed:
        return redirect_to(f"/owner/engines/{engine.id}", "Tester nicht gefunden.")

    audit_service.log_action(db, current_user.id, "engine_tester_remove", "engine", str(engine.id), f"Tester {user_id} entfernt.")
    return redirect_to(f"/owner/engines/{engine.id}", "Tester entfernt.")


@router.post("/engines/{engine_id}/versions")
def create_version(
    engine_id: int,
    version_major: str = Form(...),
    version_minor: str = Form(""),
    version_patch: str = Form(""),
    version_additional: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    engine = _editable_engine_for_user(db, engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Engine nicht gefunden.")

    try:
        version = engine_repository.create_version(
            db,
            engine,
            _parse_required_int(version_major, "Major version"),
            _parse_optional_int(version_minor),
            _parse_optional_int(version_patch),
            version_additional,
        )
    except ValueError as error:
        return redirect_to(f"/engines/{engine.slug}", str(error))
    audit_service.log_action(db, current_user.id, "version_create", "engine_version", str(version.id), "Version angelegt.")
    return redirect_to(f"/owner/versions/{version.id}", "Version angelegt.")


@router.get("/versions/{version_id}")
def version_detail(
    version_id: int,
    request: Request,
    rating_list_id: int | None = None,
    opponent: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    version = engine_repository.get_version(db, version_id)
    if version is None:
        return redirect_to("/owner/engines", "Version nicht gefunden.")

    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf diese Version.")

    context = build_context(
        request,
        current_user,
        engine=engine,
        version=version,
        rating_lists=catalog_repository.list_rating_lists(db),
        allowed_rating_lists=engine_repository.list_rating_lists_for_version(db, version.id),
        allowed_rating_list_ids=[item.id for item in engine_repository.list_rating_lists_for_version(db, version.id)],
        artifacts=engine_repository.list_artifacts_for_version(db, version.id),
        matches=job_repository.list_matches_for_version(
            db,
            version.id,
            rating_list_id=rating_list_id,
            opponent_query=opponent,
        ),
        selected_rating_list_id=rating_list_id,
        opponent_query=opponent,
        page_title=f"Version {version.version_name}",
    )
    return templates.TemplateResponse("pages/owner/version_detail.html", context)


@router.post("/versions/{version_id}")
def update_version(
    version_id: int,
    version_major: str = Form(...),
    version_minor: str = Form(""),
    version_patch: str = Form(""),
    version_additional: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    version = engine_repository.get_version(db, version_id)
    if version is None:
        return redirect_to("/owner/engines", "Version nicht gefunden.")

    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf diese Version.")

    try:
        engine_repository.update_version(
            db,
            version,
            _parse_required_int(version_major, "Major version"),
            _parse_optional_int(version_minor),
            _parse_optional_int(version_patch),
            version_additional,
        )
    except ValueError as error:
        return redirect_to(f"/owner/versions/{version.id}", str(error))
    audit_service.log_action(db, current_user.id, "version_update", "engine_version", str(version.id), "Version aktualisiert.")
    return redirect_to(f"/owner/versions/{version.id}", "Version gespeichert.")


@router.post("/versions/{version_id}/rating-lists")
def update_version_rating_lists(
    version_id: int,
    rating_list_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    version = engine_repository.get_version(db, version_id)
    if version is None:
        return redirect_to("/owner/engines", "Version nicht gefunden.")

    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf diese Version.")

    engine_repository.set_rating_lists_for_version(
        db,
        version,
        rating_list_ids,
    )
    audit_service.log_action(db, current_user.id, "version_rating_lists_update", "engine_version", str(version.id), "Rating-Listen aktualisiert.")
    return redirect_to(f"/owner/versions/{version.id}", "Rating-Listen gespeichert.")


@router.post("/versions/{version_id}/artifacts")
def create_artifact(
    version_id: int,
    system_name: str = Form(...),
    simd_class: str = Form("sse"),
    requires_popcnt: str | None = Form(None),
    requires_bmi2: str | None = Form(None),
    required_avx512_flags: list[str] = Form(default=[]),
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    version = engine_repository.get_version(db, version_id)
    if version is None:
        return redirect_to("/owner/engines", "Version nicht gefunden.")

    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf diese Version.")

    target_dir = Path(__file__).resolve().parents[2] / "data" / "artifacts" / str(version.id)
    file_name, file_path, content_hash = store_upload(upload, target_dir)
    artifact = engine_repository.create_artifact(
        db=db,
        version=version,
        system_name=system_name,
        file_name=file_name,
        file_path=file_path,
        content_hash=content_hash,
        required_cpu_flags=_artifact_required_flags_from_form(
            simd_class,
            requires_popcnt,
            requires_bmi2,
            required_avx512_flags,
        ),
    )
    audit_service.log_action(db, current_user.id, "artifact_create", "engine_artifact", str(artifact.id), "Artifact hochgeladen.")
    return redirect_to(f"/owner/versions/{version.id}", "Artifact hochgeladen.")


@router.get("/artifacts/{artifact_id}/edit")
def artifact_detail(
    artifact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    artifact = engine_repository.get_artifact(db, artifact_id)
    if artifact is None:
        return redirect_to("/owner/engines", "Artifact nicht gefunden.")
    version = artifact.engine_version
    if version is None:
        return redirect_to("/owner/engines", "Artifact ohne Version.")
    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf dieses Artifact.")

    context = build_context(
        request,
        current_user,
        engine=engine,
        version=version,
        artifact=artifact,
        page_title=f"Artifact {artifact.file_name}",
    )
    return templates.TemplateResponse("pages/owner/artifact_form.html", context)


@router.post("/artifacts/{artifact_id}")
def update_artifact(
    artifact_id: int,
    system_name: str = Form(...),
    simd_class: str = Form("sse"),
    requires_popcnt: str | None = Form(None),
    requires_bmi2: str | None = Form(None),
    required_avx512_flags: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    artifact = engine_repository.get_artifact(db, artifact_id)
    if artifact is None:
        return redirect_to("/owner/engines", "Artifact nicht gefunden.")
    version = artifact.engine_version
    if version is None:
        return redirect_to("/owner/engines", "Artifact ohne Version.")
    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf dieses Artifact.")

    engine_repository.update_artifact(
        db,
        artifact,
        system_name,
        _artifact_required_flags_from_form(
            simd_class,
            requires_popcnt,
            requires_bmi2,
            required_avx512_flags,
        ),
    )
    audit_service.log_action(db, current_user.id, "artifact_update", "engine_artifact", str(artifact.id), "Artifact aktualisiert.")
    return redirect_to(f"/owner/versions/{version.id}", "Artifact gespeichert.")


@router.post("/artifacts/{artifact_id}/delete")
def delete_artifact(
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    artifact = engine_repository.get_artifact(db, artifact_id)
    if artifact is None:
        return redirect_to("/owner/engines", "Artifact nicht gefunden.")
    version = artifact.engine_version
    if version is None:
        return redirect_to("/owner/engines", "Artifact ohne Version.")
    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf dieses Artifact.")

    version_id = version.id
    engine_repository.delete_artifact(db, artifact)
    audit_service.log_action(db, current_user.id, "artifact_delete", "engine_artifact", str(artifact_id), "Artifact entfernt.")
    return redirect_to(f"/owner/versions/{version_id}", "Artifact entfernt.")


@router.post("/artifacts/{artifact_id}/move")
def move_artifact(
    artifact_id: int,
    direction: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    artifact = engine_repository.get_artifact(db, artifact_id)
    if artifact is None:
        return redirect_to("/owner/engines", "Artifact nicht gefunden.")
    version = artifact.engine_version
    if version is None:
        return redirect_to("/owner/engines", "Artifact ohne Version.")
    engine = _editable_engine_for_user(db, version.engine_id, current_user)
    if engine is None:
        return redirect_to("/owner/engines", "Kein Zugriff auf dieses Artifact.")

    engine_repository.move_artifact_priority(db, artifact, direction)
    audit_service.log_action(db, current_user.id, "artifact_reorder", "engine_artifact", str(artifact.id), f"Artifact {direction}.")
    return redirect_to(f"/owner/versions/{version.id}", "Artifact sortiert.")


@router.post("/versions/{version_id}/matches")
def create_match(
    version_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    version = engine_repository.get_version(db, version_id)
    if version is None or _editable_engine_for_user(db, version.engine_id, current_user) is None:
        return redirect_to("/owner/engines", "Version nicht gefunden.")

    return redirect_to(f"/owner/versions/{version.id}", "Matches werden automatisch vom Matchmaker erstellt.")


@router.api_route("/matches/{match_id}/delete", methods=["POST", "GET"])
def delete_match(
    match_id: int,
    next_path: str = Form(""),
    next_path_query: str = Query(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    match = job_repository.get_match(db, match_id)
    if match is None:
        return redirect_to("/engines", "Match nicht gefunden.")

    owns_primary = engine_repository.get_engine_for_user(db, match.engine_version.engine_id, current_user.id) is not None
    owns_opponent = (
        match.opponent_version is not None
        and engine_repository.get_engine_for_user(db, match.opponent_version.engine_id, current_user.id) is not None
    )
    if not owns_primary and not owns_opponent and not user_repository.has_role(current_user, ADMIN_ROLE):
        return redirect_to("/engines", "Kein Zugriff auf diesen Match.")

    redirect_path = (
        (next_path or next_path_query).strip()
        or f"/engines/{match.engine_version.engine.slug}/versions/{match.engine_version.id}"
    )
    job_service.delete_match(db, match_id)
    audit_service.log_action(db, current_user.id, "match_delete", "match", str(match_id), "Match geloescht.")
    return redirect_to(redirect_path, "Match geloescht.")


@router.api_route("/jobs/{job_id}/delete", methods=["POST", "GET"])
def delete_job(
    job_id: int,
    next_path: str = Form(""),
    next_path_query: str = Query(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    job = job_repository.get_match_job(db, job_id)
    if job is None or job.match is None:
        return redirect_to("/engines", "Job nicht gefunden.")

    match = job.match
    owns_primary = engine_repository.get_engine_for_user(db, match.engine_version.engine_id, current_user.id) is not None
    owns_opponent = (
        match.opponent_version is not None
        and engine_repository.get_engine_for_user(db, match.opponent_version.engine_id, current_user.id) is not None
    )
    if not owns_primary and not owns_opponent and not user_repository.has_role(current_user, ADMIN_ROLE):
        return redirect_to("/engines", "Kein Zugriff auf diesen Job.")

    redirect_path = (
        (next_path or next_path_query).strip()
        or f"/matches/{match.id}"
    )
    job_service.delete_job(db, job_id)
    audit_service.log_action(db, current_user.id, "job_delete", "match_job", str(job_id), "Job geloescht.")
    return redirect_to(redirect_path, "Job geloescht.")


@router.get("/matches/{match_id}/download.zip")
def download_match_pgn_zip(
    match_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_required),
):
    match = job_repository.get_match(db, match_id)
    owns_primary = (
        match is not None
        and _editable_engine_for_user(db, match.engine_version.engine_id, current_user) is not None
    )
    owns_opponent = (
        match is not None
        and match.opponent_version is not None
        and _editable_engine_for_user(db, match.opponent_version.engine_id, current_user) is not None
    )
    if match is None or (not owns_primary and not owns_opponent):
        return redirect_to("/owner/engines", "Match nicht gefunden.")

    file_name = f"{match.engine_version.engine.slug}-{match.engine_version.version_name}-{match.id}-pgn-jobs.zip"
    jobs = job_repository.list_jobs_for_match(db, match.id)
    return Response(
        content=build_match_pgn_archive(match, jobs),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
