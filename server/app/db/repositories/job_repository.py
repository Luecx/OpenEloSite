from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.db.models.engine_version import EngineVersion
from app.db.models.leaderboard_entry import LeaderboardEntry
from app.db.models.match import Match
from app.db.models.match_job import MatchJob
from app.db.models.rating_list import RatingList


def create_match(
    db: Session,
    engine_version_id: int,
    opponent_version_id: int,
    rating_list_id: int,
    status: str = "completed",
) -> Match:
    match = Match(
        engine_version_id=engine_version_id,
        opponent_version_id=opponent_version_id,
        rating_list_id=rating_list_id,
        status=status,
    )
    db.add(match)
    db.flush()
    db.refresh(match)
    return match


def list_recent_match_jobs(db: Session, rating_list_id: int | None = None) -> list[MatchJob]:
    query = select(MatchJob).join(Match, Match.id == MatchJob.match_id).where(MatchJob.status.in_(["completed", "failed"]))
    if rating_list_id:
        query = query.where(Match.rating_list_id == rating_list_id)
    return list(db.scalars(query.order_by(desc(MatchJob.created_at)).limit(30)))


def list_recent_matches(db: Session, rating_list_id: int | None = None) -> list[Match]:
    query = select(Match).options(
        selectinload(Match.jobs),
        joinedload(Match.engine_version).joinedload(EngineVersion.engine),
        joinedload(Match.opponent_version).joinedload(EngineVersion.engine),
        joinedload(Match.rating_list).joinedload(RatingList.opening_book),
    ).where(
        exists(
            select(MatchJob.id).where(
                MatchJob.match_id == Match.id,
                MatchJob.status.in_(["completed", "failed"]),
            )
        )
    )
    if rating_list_id:
        query = query.where(Match.rating_list_id == rating_list_id)
    return list(db.scalars(query.order_by(desc(Match.created_at)).limit(30)))


def list_match_jobs_for_version(
    db: Session,
    version_id: int,
    rating_list_id: int | None = None,
    result_text: str = "",
    opponent_query: str = "",
    status: str = "",
) -> list[MatchJob]:
    query = (
        select(MatchJob)
        .join(Match, Match.id == MatchJob.match_id)
        .where(Match.engine_version_id == version_id)
    )
    if rating_list_id:
        query = query.where(Match.rating_list_id == rating_list_id)
    if result_text.strip():
        query = query.where(MatchJob.result_text == result_text.strip())
    if status.strip():
        query = query.where(MatchJob.status == status.strip())

    items = list(db.scalars(query.order_by(desc(MatchJob.created_at))))
    if not opponent_query.strip():
        return items

    pattern = opponent_query.strip().lower()
    filtered: list[MatchJob] = []
    for item in items:
        match = item.match
        if match is None:
            continue
        names = [
            match.opponent_version.display_name,
            match.opponent_version.engine.name,
            match.opponent_version.version_name,
        ]
        if any(pattern in (candidate or "").lower() for candidate in names):
            filtered.append(item)
    return filtered


def list_matches_for_version(
    db: Session,
    version_id: int,
    rating_list_id: int | None = None,
    opponent_query: str = "",
) -> list[Match]:
    query = select(Match).options(
        selectinload(Match.jobs),
        joinedload(Match.engine_version).joinedload(EngineVersion.engine),
        joinedload(Match.opponent_version).joinedload(EngineVersion.engine),
        joinedload(Match.rating_list).joinedload(RatingList.opening_book),
    ).where(
        exists(
            select(MatchJob.id).where(
                MatchJob.match_id == Match.id,
                MatchJob.status.in_(["completed", "failed"]),
            )
        ),
        or_(
            Match.engine_version_id == version_id,
            Match.opponent_version_id == version_id,
        )
    )
    if rating_list_id:
        query = query.where(Match.rating_list_id == rating_list_id)
    items = list(db.scalars(query.order_by(desc(Match.created_at))))
    visible_items = items
    if not opponent_query.strip():
        return visible_items

    pattern = opponent_query.strip().lower()
    filtered: list[Match] = []
    for item in visible_items:
        names = [
            item.opponent_version.display_name,
            item.opponent_version.engine.name,
            item.opponent_version.version_name,
            item.engine_version.display_name,
        ]
        if any(pattern in (candidate or "").lower() for candidate in names):
            filtered.append(item)
    return filtered


def get_match_job(db: Session, match_job_id: int) -> MatchJob | None:
    return db.get(MatchJob, match_job_id)


def get_match(db: Session, match_id: int) -> Match | None:
    match = db.scalar(
        select(Match).options(
            selectinload(Match.jobs),
            joinedload(Match.engine_version).joinedload(EngineVersion.engine),
            joinedload(Match.opponent_version).joinedload(EngineVersion.engine),
            joinedload(Match.rating_list).joinedload(RatingList.opening_book),
        ).where(Match.id == match_id)
    )
    if match is None:
        return None
    has_terminal_job = db.scalar(
        select(MatchJob.id)
        .where(MatchJob.match_id == match.id, MatchJob.status.in_(["completed", "failed"]))
        .limit(1)
    )
    if has_terminal_job is None:
        return None
    return match


def list_jobs_for_match(db: Session, match_id: int) -> list[MatchJob]:
    return list(
        db.scalars(
            select(MatchJob)
            .where(MatchJob.match_id == match_id, MatchJob.status.in_(["completed", "failed"]))
            .order_by(MatchJob.created_at.asc())
        )
    )


def _terminal_jobs(jobs: list[MatchJob]) -> list[MatchJob]:
    return [job for job in jobs if job.status in {"completed", "failed"}]


def _counted_jobs(jobs: list[MatchJob]) -> list[MatchJob]:
    return [job for job in jobs if job.status == "completed" and not bool(job.is_poor)]


def apply_match_results_from_jobs(match: Match, jobs: list[MatchJob]) -> Match:
    terminal_jobs = _terminal_jobs(jobs)
    counted_jobs = _counted_jobs(terminal_jobs)

    match.wins = sum(item.wins for item in counted_jobs)
    match.draws = sum(item.draws for item in counted_jobs)
    match.losses = sum(item.losses for item in counted_jobs)
    match.games_count = sum(item.games_count for item in counted_jobs)

    has_completed_jobs = any(item.status == "completed" for item in terminal_jobs)
    has_failed_jobs = any(item.status == "failed" for item in terminal_jobs)
    if has_completed_jobs:
        match.status = "completed"
    elif has_failed_jobs:
        match.status = "failed"
    else:
        match.status = "completed"

    if match.games_count <= 0:
        match.result_text = None
    elif match.games_count == 1:
        if match.wins:
            match.result_text = "1-0"
        elif match.losses:
            match.result_text = "0-1"
        else:
            match.result_text = "1/2-1/2"
    else:
        match.result_text = f"{match.wins}W {match.draws}D {match.losses}L"
    return match


def list_matches_for_rating_lists(db: Session, rating_list_ids: list[int]) -> list[Match]:
    if not rating_list_ids:
        return []
    return list(db.scalars(select(Match).where(Match.rating_list_id.in_(rating_list_ids)).order_by(desc(Match.created_at))))


def create_match_job_record(
    db: Session,
    match_id: int,
    client_id: int | None,
    client_user_id: int | None,
    client_user_display_name: str | None,
    client_session_key: str | None,
    client_machine_fingerprint: str | None,
    client_machine_name: str | None,
    client_system_name: str | None,
    client_cpu_name: str | None,
    client_ram_total_mb: int | None,
    client_ram_speed_mt_s: int | None,
    client_cpu_flags: str | None,
    threads_per_engine: int,
    hash_per_engine: int,
    num_games: int,
    seed: int,
    status: str,
    wins: int,
    draws: int,
    losses: int,
    games_count: int,
    result_text: str | None,
    pgn_zip_path: str | None,
    error_text: str | None = None,
    runtime_seconds: int | None = None,
) -> MatchJob:
    job = MatchJob(
        match_id=match_id,
        client_id=client_id,
        client_user_id=client_user_id,
        client_user_display_name=(client_user_display_name or "").strip() or None,
        client_session_key=(client_session_key or "").strip() or None,
        client_machine_fingerprint=(client_machine_fingerprint or "").strip() or None,
        client_machine_name=(client_machine_name or "").strip() or None,
        client_system_name=(client_system_name or "").strip().lower() or None,
        client_cpu_name=(client_cpu_name or "").strip() or None,
        client_ram_total_mb=client_ram_total_mb,
        client_ram_speed_mt_s=client_ram_speed_mt_s,
        client_cpu_flags=(client_cpu_flags or "").strip() or None,
        threads_per_engine=max(1, int(threads_per_engine)),
        hash_per_engine=max(1, int(hash_per_engine)),
        num_games=max(1, int(num_games)),
        seed=int(seed),
        status=status,
        wins=wins,
        draws=draws,
        losses=losses,
        games_count=games_count,
        result_text=result_text,
        pgn_zip_path=pgn_zip_path,
        error_text=error_text,
        runtime_seconds=runtime_seconds,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_matchup(db: Session, rating_list_id: int, version_a_id: int, version_b_id: int) -> Match | None:
    return db.scalar(
        select(Match)
        .where(
            Match.rating_list_id == rating_list_id,
            or_(
                (Match.engine_version_id == version_a_id) & (Match.opponent_version_id == version_b_id),
                (Match.engine_version_id == version_b_id) & (Match.opponent_version_id == version_a_id),
            ),
        )
        .order_by(desc(Match.created_at))
        .limit(1)
    )


def refresh_match(db: Session, match: Match) -> Match:
    finished_jobs = list_jobs_for_match(db, match.id)
    apply_match_results_from_jobs(match, finished_jobs)
    db.commit()
    db.refresh(match)
    return match


def delete_match(db: Session, match: Match) -> None:
    db.delete(match)
    db.commit()


def delete_match_job(db: Session, job: MatchJob) -> None:
    db.delete(job)
    db.commit()


def delete_leaderboard_entries_for_rating_list(db: Session, rating_list_id: int) -> None:
    entries = list(db.scalars(select(LeaderboardEntry).where(LeaderboardEntry.rating_list_id == rating_list_id)))
    for entry in entries:
        db.delete(entry)
    db.commit()
