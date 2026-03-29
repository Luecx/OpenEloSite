from __future__ import annotations

import math
from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Form
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.http import redirect_to
from app.api.http import redirect_to_error
from app.api.templates import templates
from app.db.repositories import catalog_repository
from app.db.repositories import client_repository
from app.db.repositories import engine_repository
from app.db.repositories import engine_request_repository
from app.db.repositories import job_repository
from app.db.repositories import user_repository
from app.db.session import get_db
from app.security.current_user import get_current_user_optional
from app.security.role_names import ADMIN_ROLE
from app.services import audit_service
from app.services.dashboard_service import get_summary
from app.services.bayeselo_service import summarize_match
from app.services.job_pgn_service import build_annotated_match_pgn_text
from app.services.job_pgn_service import build_match_pgn_archive
from app.services.job_pgn_service import get_job_pgn_zip_path
from app.services.pgn_service import join_pgn_blocks
from app.services.template_service import build_context


router = APIRouter()


def _editable_engine_for_user(db: Session, engine_id: int, current_user):
    if current_user is None:
        return None
    if user_repository.has_role(current_user, ADMIN_ROLE):
        return engine_repository.get_engine(db, engine_id)
    return engine_repository.get_engine_for_user(db, engine_id, current_user.id)


def _format_ram_summary(ram_total_mb: int | None, ram_speed_mt_s: int | None) -> str:
    total_mb = int(ram_total_mb or 0)
    if total_mb <= 0:
        return "-"
    total_gb = total_mb / 1024.0
    summary = f"{total_gb:.1f} GB"
    speed = int(ram_speed_mt_s or 0)
    if speed > 0:
        summary = f"{summary} @ {speed} MT/s"
    return summary


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _pairwise_los(entry_a, entry_b) -> float | None:
    if entry_a is None or entry_b is None:
        return None
    stderr_a = float(entry_a.rating_stderr) if entry_a.rating_stderr is not None else None
    stderr_b = float(entry_b.rating_stderr) if entry_b.rating_stderr is not None else None
    if stderr_a is None or stderr_b is None:
        return None

    combined_stderr = math.sqrt(stderr_a * stderr_a + stderr_b * stderr_b)
    delta = float(entry_a.rating) - float(entry_b.rating)
    if combined_stderr <= 0:
        if delta > 0:
            return 1.0
        if delta < 0:
            return 0.0
        return 0.5
    return max(0.0, min(1.0, _normal_cdf(delta / combined_stderr)))


@router.get("/logo.png")
def app_logo():
    logo_path = Path(__file__).resolve().parents[3] / "logo.png"
    if not logo_path.exists():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(logo_path, media_type="image/png")


@router.get("/favicon.ico")
def app_favicon():
    favicon_path = Path(__file__).resolve().parents[3] / "favicon.ico"
    if not favicon_path.exists():
        raise HTTPException(status_code=404, detail="Favicon not found")
    return FileResponse(favicon_path, media_type="image/x-icon")


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    summary = get_summary(db)
    engines = engine_repository.list_public_engines(db)[:5]
    all_rating_lists = catalog_repository.list_rating_lists(db)
    all_books = catalog_repository.list_books(db)
    context = build_context(
        request,
        current_user,
        summary=summary,
        engines=engines,
        rating_lists=all_rating_lists[:4],
        rating_list_count=len(all_rating_lists),
        book_count=len(all_books),
        page_title="Start",
    )
    return templates.TemplateResponse("pages/public/home.html", context)


@router.get("/engines")
def engines(
    request: Request,
    q: str = "",
    protocol: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    filtered_engines = engine_repository.list_public_engines(db, q=q, protocol=protocol)
    my_engines: list = []
    my_engine_requests: list = []
    all_engines = filtered_engines
    if current_user is not None:
        assigned_engine_ids = {item.id for item in engine_repository.list_user_engines(db, current_user.id)}
        my_engines = [item for item in filtered_engines if item.id in assigned_engine_ids]
        my_engine_requests = engine_request_repository.list_requests_for_user(db, current_user.id)
    context = build_context(
        request,
        current_user,
        engines=filtered_engines,
        my_engines=my_engines,
        my_engine_requests=my_engine_requests,
        all_engines=all_engines,
        can_create_engine=bool(current_user and user_repository.has_role(current_user, ADMIN_ROLE)),
        can_request_engine=bool(current_user and not user_repository.has_role(current_user, ADMIN_ROLE)),
        q=q,
        protocol=protocol,
        page_title="Engine-Liste",
    )
    return templates.TemplateResponse("pages/public/engines.html", context)


@router.post("/engines/requests")
def create_engine_request(
    engine_name: str = Form(...),
    protocol: str = Form("uci"),
    request_text: str = Form(...),
    link_url: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    if current_user is None:
        return redirect_to_error("/auth/login", "Bitte logge dich ein, um eine Engine anzufragen.")
    if user_repository.has_role(current_user, ADMIN_ROLE):
        return redirect_to_error("/engines", "Admins koennen Engines direkt anlegen.")

    normalized_name = (engine_name or "").strip()
    normalized_text = (request_text or "").strip()
    if not normalized_name:
        return redirect_to_error("/engines", "Der Engine-Name ist erforderlich.")
    if not normalized_text:
        return redirect_to_error("/engines", "Ein Beschreibungstext ist erforderlich.")

    requested_slug = engine_repository.slugify(normalized_name)
    if engine_repository.get_engine_by_slug(db, requested_slug) is not None:
        return redirect_to_error("/engines", "Diese Engine existiert bereits.")
    if engine_request_repository.get_pending_request_by_slug(db, requested_slug) is not None:
        return redirect_to_error("/engines", "Es gibt bereits eine offene Anfrage fuer diese Engine.")

    engine_request = engine_request_repository.create_engine_request(
        db=db,
        requester_user_id=current_user.id,
        engine_name=normalized_name,
        engine_slug=requested_slug,
        protocol=protocol,
        request_text=normalized_text,
        link_url=link_url,
    )
    audit_service.log_action(
        db,
        current_user.id,
        "engine_request_create",
        "engine_request",
        str(engine_request.id),
        "Engine-Anfrage erstellt.",
    )
    return redirect_to("/engines", "Engine-Anfrage gesendet.")


@router.get("/engines/{slug}")
def engine_detail(slug: str, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    engine = engine_repository.get_public_engine_by_slug(db, slug)
    if engine is None:
        raise HTTPException(status_code=404, detail="Engine not found")
    editable_engine = _editable_engine_for_user(db, engine.id, current_user)
    versions = engine_repository.list_public_versions_for_engine(db, engine.id)
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
        can_edit_engine=editable_engine is not None,
        owner_users=engine_repository.list_engine_owners(db, engine.id),
        tester_users=engine_repository.list_engine_testers(db, engine.id),
        all_users=user_repository.list_users_for_picker(db) if editable_engine is not None else [],
        page_title=engine.name,
    )
    return templates.TemplateResponse("pages/public/engine_detail.html", context)


@router.get("/engines/{slug}/versions/{version_id}")
def version_detail(
    slug: str,
    version_id: int,
    request: Request,
    rating_list_id: int | None = None,
    opponent: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    engine = engine_repository.get_public_engine_by_slug(db, slug)
    version = engine_repository.get_version(db, version_id)
    if engine is None or version is None or version.engine_id != engine.id:
        raise HTTPException(status_code=404, detail="Version not found")

    rating_lists = catalog_repository.list_rating_lists(db)

    context = build_context(
        request,
        current_user,
        engine=engine,
        version=version,
        can_edit_engine=_editable_engine_for_user(db, engine.id, current_user) is not None,
        rating_lists=rating_lists,
        allowed_rating_lists=engine_repository.list_rating_lists_for_version(db, version.id),
        allowed_rating_list_ids=[item.id for item in engine_repository.list_rating_lists_for_version(db, version.id)],
        leaderboard_entries=sorted(
            [item for item in version.leaderboard_entries if item.rating_list],
            key=lambda item: (item.rank_position or 999999, -item.rating),
        ),
        rating_list_rows=engine_repository.build_rating_list_rows(version, rating_lists),
        matches=job_repository.list_matches_for_version(
            db,
            version_id=version.id,
            rating_list_id=rating_list_id,
            opponent_query=opponent,
        ),
        selected_rating_list_id=rating_list_id,
        opponent_query=opponent,
        page_title=f"{engine.name} {version.version_name}",
    )
    return templates.TemplateResponse("pages/public/version_detail.html", context)


@router.get("/engines/{slug}/versions/{version_id}/insights")
def version_insights(
    slug: str,
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    engine = engine_repository.get_public_engine_by_slug(db, slug)
    version = engine_repository.get_version(db, version_id)
    if engine is None or version is None or version.engine_id != engine.id:
        raise HTTPException(status_code=404, detail="Version not found")

    context = build_context(
        request,
        current_user,
        insights_title=f"{engine.name} {version.version_name}",
        insights_kind="Versions-Insights",
        insights_subtitle="Lade alle PGNs dieser Version und werte die Engine-Daten direkt im Browser aus.",
        insights_source_label="Version",
        insights_pgn_url=f"/engines/{engine.slug}/versions/{version.id}/insights.pgn",
        insights_download_url=f"/engines/{engine.slug}/versions/{version.id}/insights.pgn",
        insights_download_label="PGN herunterladen",
        back_url=f"/engines/{engine.slug}/versions/{version.id}",
        back_label="Zurueck zur Version",
        page_title=f"Insights {engine.name} {version.version_name}",
    )
    return templates.TemplateResponse("pages/public/pgn_insights.html", context)


@router.get("/engines/{slug}/versions/{version_id}/insights.pgn")
def download_version_insights_pgn(
    slug: str,
    version_id: int,
    db: Session = Depends(get_db),
):
    engine = engine_repository.get_public_engine_by_slug(db, slug)
    version = engine_repository.get_version(db, version_id)
    if engine is None or version is None or version.engine_id != engine.id:
        raise HTTPException(status_code=404, detail="Version not found")

    matches = job_repository.list_matches_for_version(db, version.id)
    pgn_text = join_pgn_blocks(
        [
            build_annotated_match_pgn_text(match, job_repository.list_jobs_for_match(db, match.id))
            for match in matches
        ]
    )
    file_name = f"{engine.slug}-{version.id}-insights.pgn"
    return Response(
        content=pgn_text,
        media_type="application/x-chess-pgn",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/books")
def books_page(
    request: Request,
    q: str = "",
    edit: int | None = None,
    manage: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    context = build_context(
        request,
        current_user,
        books=catalog_repository.list_books(db, q=q),
        edit_book=catalog_repository.get_book(db, edit) if edit else None,
        show_manage=bool(manage or edit),
        q=q,
        page_title="Books",
    )
    return templates.TemplateResponse("pages/public/books.html", context)


@router.get("/books/{book_id}/download")
def download_book_public(book_id: int, db: Session = Depends(get_db)):
    book = catalog_repository.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    book_path = Path(book.file_path)
    if not book_path.exists():
        raise HTTPException(status_code=404, detail="Book file not found")
    return Response(
        content=book_path.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{book.file_name}"'},
    )


@router.get("/rating-lists")
def rating_lists_page(
    request: Request,
    q: str = "",
    edit: int | None = None,
    manage: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    context = build_context(
        request,
        current_user,
        rating_lists=catalog_repository.list_rating_lists(db, q=q),
        books=catalog_repository.list_books(db),
        edit_rating_list=catalog_repository.get_rating_list(db, edit) if edit else None,
        show_manage=bool(manage or edit),
        q=q,
        page_title="Rating-Listen",
    )
    return templates.TemplateResponse("pages/public/rating_lists.html", context)


@router.get("/leaderboard")
def leaderboard_redirect():
    return RedirectResponse(url="/rating-lists", status_code=303)


@router.get("/clients")
def clients_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    context = build_context(
        request,
        current_user,
        clients=client_repository.list_active_clients(db),
        page_title="Clients",
    )
    return templates.TemplateResponse("pages/tester/clients.html", context)


@router.get("/clients/{client_id}")
def client_detail_page(client_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    client = client_repository.get_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    client_flag_rows = [
        ("SSE", "sse"),
        ("SSE2", "sse2"),
        ("SSE3", "sse3"),
        ("SSSE3", "ssse3"),
        ("SSE4.1", "sse41"),
        ("SSE4.2", "sse42"),
        ("POPCNT", "popcnt"),
        ("AVX", "avx"),
        ("AVX2", "avx2"),
        ("BMI2", "bmi2"),
        ("AVX512-F", "avx512f"),
        ("AVX512-BW", "avx512bw"),
        ("AVX512-DQ", "avx512dq"),
        ("AVX512-VL", "avx512vl"),
        ("AVX512-VNNI", "avx512vnni"),
    ]
    context = build_context(
        request,
        current_user,
        client=client,
        is_online=client_repository.is_client_active(client),
        supported_cpu_flags=client_repository.parse_cpu_flags(client.cpu_flags),
        client_ram_summary=_format_ram_summary(client.ram_total_mb, client.ram_speed_mt_s),
        client_flag_rows=client_flag_rows,
        page_title=client.display_name,
    )
    return templates.TemplateResponse("pages/tester/client_detail.html", context)


@router.get("/users")
def users_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    active_clients = client_repository.list_active_clients(db)
    active_clients_by_user: dict[int, list] = {}
    for client in active_clients:
        active_clients_by_user.setdefault(client.user_id, []).append(client)
    users = user_repository.list_users(db)
    user_role_names_by_user = {user.id: user_repository.get_role_names(user) for user in users}
    context = build_context(
        request,
        current_user,
        users=users,
        roles=user_repository.list_roles(db),
        active_clients_by_user=active_clients_by_user,
        user_role_names_by_user=user_role_names_by_user,
        page_title="Users",
    )
    return templates.TemplateResponse("pages/public/users.html", context)


@router.get("/users/{user_id}")
def user_detail_page(user_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    if current_user is not None and current_user.id == user_id:
        return RedirectResponse(url="/profile", status_code=303)
    user = user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    context = build_context(
        request,
        current_user,
        profile_user=user,
        profile_roles=user_repository.get_role_names(user),
        profile_clients=client_repository.list_clients_for_user(db, user.id),
        profile_engines=engine_repository.list_user_engines(db, user.id),
        page_title=user.display_name,
    )
    return templates.TemplateResponse("pages/public/user_detail.html", context)


@router.get("/rating-lists/{slug}")
def rating_list_detail(
    slug: str,
    request: Request,
    view: str = "best",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    rating_list = catalog_repository.get_rating_list_by_slug(db, slug)
    if rating_list is None:
        raise HTTPException(status_code=404, detail="Rating list not found")
    ranking_view = "all" if (view or "").strip().lower() == "all" else "best"
    ranking_entries = engine_repository.list_leaderboard(
        db,
        rating_list_id=rating_list.id,
        best_per_engine=(ranking_view == "best"),
    )

    context = build_context(
        request,
        current_user,
        rating_list=rating_list,
        all_rating_lists_url="/rating-lists",
        ranking_view=ranking_view,
        ranking_rows=[
            {
                "display_rank": index + 1,
                "entry": entry,
                "los_to_next": _pairwise_los(entry, ranking_entries[index + 1]) if index + 1 < len(ranking_entries) else None,
            }
            for index, entry in enumerate(ranking_entries)
        ],
        page_title=rating_list.name,
    )
    return templates.TemplateResponse("pages/public/rating_list_detail.html", context)


@router.get("/matches/{match_id}")
def match_detail(match_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    match = job_repository.get_match(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    can_manage_match = False
    if current_user is not None:
        can_manage_match = (
            user_repository.has_role(current_user, ADMIN_ROLE)
            or engine_repository.get_engine_for_user(db, match.engine_version.engine_id, current_user.id) is not None
            or (
                match.opponent_version is not None
                and engine_repository.get_engine_for_user(db, match.opponent_version.engine_id, current_user.id) is not None
            )
        )

    context = build_context(
        request,
        current_user,
        match=match,
        jobs=job_repository.list_jobs_for_match(db, match_id),
        match_summary=summarize_match(match.wins, match.draws, match.losses),
        can_manage_match=can_manage_match,
        page_title=f"Match #{match_id}",
    )
    return templates.TemplateResponse("pages/public/match_detail.html", context)


@router.get("/matches/{match_id}/insights")
def match_insights(match_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user_optional)):
    match = job_repository.get_match(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    context = build_context(
        request,
        current_user,
        match=match,
        insights_title=f"{match.engine_version_label} vs {match.opponent_version_label}",
        insights_kind="Match-Insights",
        insights_subtitle="Lade die Match-PGNs und berechne Kennzahlen aus den Kommentardaten im Browser.",
        insights_source_label="Match",
        insights_pgn_url=f"/matches/{match.id}/insights.pgn",
        insights_download_url=f"/matches/{match.id}/download.zip",
        insights_download_label="PGN ZIPs herunterladen",
        back_url=f"/matches/{match.id}",
        back_label="Zurueck zum Match",
        page_title=f"Insights Match {match.id}",
    )
    return templates.TemplateResponse("pages/public/pgn_insights.html", context)


@router.get("/matches/{match_id}/insights.pgn")
def download_match_insights_pgn(match_id: int, db: Session = Depends(get_db)):
    match = job_repository.get_match(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    jobs = job_repository.list_jobs_for_match(db, match.id)
    return Response(
        content=build_annotated_match_pgn_text(match, jobs),
        media_type="application/x-chess-pgn",
        headers={"Content-Disposition": f'attachment; filename="match-{match_id}-insights.pgn"'},
    )


@router.get("/matches/{match_id}/download.zip")
def download_match_pgn_zip(match_id: int, db: Session = Depends(get_db)):
    match = job_repository.get_match(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    jobs = job_repository.list_jobs_for_match(db, match.id)
    return Response(
        content=build_match_pgn_archive(match, jobs),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="match-{match_id}-pgn-jobs.zip"'},
    )


@router.get("/jobs/{job_id}/download.zip")
def download_job_pgn_zip(job_id: int, db: Session = Depends(get_db)):
    job = job_repository.get_match_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    zip_path = get_job_pgn_zip_path(job)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="Job PGN ZIP not found")
    file_name = f"job-{job_id}.pgn.zip"
    return Response(
        content=zip_path.read_bytes(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )
