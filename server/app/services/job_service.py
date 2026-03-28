from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.match import Match
from app.db.models.match_job import MatchJob
from app.db.repositories import client_repository
from app.db.repositories import job_repository
from app.services import job_pgn_service
from app.services import leaderboard_service
from app.services import poor_job_service


def summarize_counts(wins: int, draws: int, losses: int) -> str:
    total_games = wins + draws + losses
    if total_games <= 0:
        return "-"
    if total_games == 1:
        if wins:
            return "1-0"
        if losses:
            return "0-1"
        return "1/2-1/2"
    return f"{wins}W {draws}D {losses}L"


def get_match_job_counts(job: MatchJob) -> tuple[int, int, int, int]:
    if job.games_count:
        return job.wins, job.draws, job.losses, job.games_count

    wins, draws, losses = job.wins, job.draws, job.losses
    return wins, draws, losses, wins + draws + losses


def rebuild_leaderboard_for_rating_list(db: Session, rating_list_id: int) -> None:
    leaderboard_service.rebuild_rating_list_leaderboard(db, rating_list_id)


def delete_match(db: Session, match_id: int) -> bool:
    match = job_repository.get_match(db, match_id)
    if match is None:
        return False
    for job in job_repository.list_jobs_for_match(db, match.id):
        job_pgn_service.delete_job_pgn_zip(job)
    job_repository.delete_match(db, match)
    return True


def delete_job(db: Session, job_id: int) -> bool:
    job = job_repository.get_match_job(db, job_id)
    if job is None:
        return False
    match_id = job.match_id
    job_pgn_service.delete_job_pgn_zip(job)
    job_repository.delete_match_job(db, job)
    match = db.get(Match, match_id) if match_id else None
    if match is not None:
        remaining_jobs = job_repository.list_jobs_for_match(db, match.id)
        if remaining_jobs:
            poor_job_service.review_match_by_id(db, match.id)
            db.commit()
        else:
            job_repository.delete_match(db, match)
    return True


def _normalize_counts(payload: dict) -> tuple[int, int, int, int]:
    wins = int(payload.get("wins", 0) or 0)
    draws = int(payload.get("draws", 0) or 0)
    losses = int(payload.get("losses", 0) or 0)
    games_count = int(payload.get("games_count", 0) or 0)
    if games_count <= 0:
        games_count = wins + draws + losses
    return wins, draws, losses, games_count


def record_match_result(
    db: Session,
    assignment,
    wins: int,
    draws: int,
    losses: int,
    games_count: int,
    pgn_zip_base64: str,
    status: str = "completed",
    error_text: str | None = None,
    runtime_seconds: int | None = None,
):
    payload = {
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "games_count": games_count,
    }
    normalized_status = "completed" if status == "completed" else "failed"
    normalized_wins, normalized_draws, normalized_losses, normalized_games_count = _normalize_counts(payload)
    client = client_repository.get_client(db, assignment.client_id) if assignment.client_id else None
    match = job_repository.get_matchup(
        db,
        rating_list_id=assignment.rating_list_id,
        version_a_id=assignment.engine_version_id,
        version_b_id=assignment.opponent_version_id,
    )
    if match is None:
        match = job_repository.create_match(
            db=db,
            engine_version_id=assignment.engine_version_id,
            opponent_version_id=assignment.opponent_version_id,
            rating_list_id=assignment.rating_list_id,
            status=normalized_status,
        )

    stored_wins = normalized_wins if normalized_status == "completed" else 0
    stored_draws = normalized_draws if normalized_status == "completed" else 0
    stored_losses = normalized_losses if normalized_status == "completed" else 0
    if match.engine_version_id != assignment.engine_version_id:
        stored_wins, stored_losses = stored_losses, stored_wins

    completed = job_repository.create_match_job_record(
        db=db,
        match_id=match.id,
        client_id=assignment.client_id,
        client_user_id=client.user_id if client is not None else None,
        client_user_display_name=client.user.display_name if client is not None and client.user is not None else None,
        client_session_key=client.machine_key if client is not None else None,
        client_machine_fingerprint=client.machine_fingerprint if client is not None else None,
        client_machine_name=client.machine_name if client is not None else None,
        client_system_name=client.system_name if client is not None else None,
        client_cpu_name=client.cpu_name if client is not None else None,
        client_ram_total_mb=client.ram_total_mb if client is not None else None,
        client_ram_speed_mt_s=client.ram_speed_mt_s if client is not None else None,
        client_cpu_flags=client.cpu_flags if client is not None else None,
        threads_per_engine=assignment.threads_per_engine,
        hash_per_engine=assignment.hash_per_engine,
        num_games=assignment.num_games,
        seed=assignment.seed,
        status=normalized_status,
        result_text=summarize_counts(stored_wins, stored_draws, stored_losses) if normalized_status == "completed" else normalized_status,
        pgn_zip_path=None,
        wins=stored_wins,
        draws=stored_draws,
        losses=stored_losses,
        games_count=normalized_games_count if normalized_status == "completed" else 0,
        error_text=error_text,
        runtime_seconds=runtime_seconds,
    )
    if normalized_status == "completed":
        if not (pgn_zip_base64 or "").strip():
            raise ValueError("A completed job did not provide a PGN ZIP.")
        completed.pgn_zip_path = job_pgn_service.store_job_pgn_zip(completed.id, pgn_zip_base64)
        db.add(completed)
        db.commit()
        db.refresh(completed)
    match = job_repository.get_match(db, completed.match_id) if completed.match_id else None
    if match is not None and match.rating_list_id:
        poor_job_service.review_match_by_id(db, match.id)
        db.commit()
    return completed
