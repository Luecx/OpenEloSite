from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.engine_version import EngineVersion
from app.db.models.leaderboard_entry import LeaderboardEntry
from app.db.models.match import Match
from app.db.models.rating_list import RatingList
from app.db.repositories import engine_repository
from app.db.repositories import job_repository
from app.db.session import SessionLocal
from app.services.elofit import EloConfig
from app.services.elofit import EloDatabase
from app.services.elofit import EloEstimate
from app.services.elofit import EloSolver
from app.services.elofit import UNKNOWN_ELO


REFRESH_INTERVAL_SECONDS = 30


@dataclass(slots=True)
class _LeaderboardStats:
    wins: int = 0
    draws: int = 0
    losses: int = 0
    games_played: int = 0


class LeaderboardRefreshThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                rebuild_all_leaderboards()
            except Exception as error:
                print(f"[OpenELO Server] Leaderboard refresh failed: {error}", flush=True)
            if self.stop_event.wait(REFRESH_INTERVAL_SECONDS):
                break

    def stop(self) -> None:
        self.stop_event.set()


def _engine_key(version_id: int) -> str:
    return str(int(version_id))


def _collect_version_stats(matches: list[Match]) -> dict[int, _LeaderboardStats]:
    stats_by_version: dict[int, _LeaderboardStats] = defaultdict(_LeaderboardStats)
    for match in matches:
        if match.engine_version_id is None or match.opponent_version_id is None or match.games_count <= 0:
            continue
        first_stats = stats_by_version[match.engine_version_id]
        first_stats.wins += int(match.wins)
        first_stats.draws += int(match.draws)
        first_stats.losses += int(match.losses)
        first_stats.games_played += int(match.games_count)

        second_stats = stats_by_version[match.opponent_version_id]
        second_stats.wins += int(match.losses)
        second_stats.draws += int(match.draws)
        second_stats.losses += int(match.wins)
        second_stats.games_played += int(match.games_count)
    return stats_by_version


def _fit_rating_list_elos(db: Session, rating_list: RatingList, matches: list[Match]) -> dict[int, EloEstimate]:
    anchor_version_id = (
        int(rating_list.anchor_engine_version_id)
        if rating_list.anchor_engine_version_id is not None and rating_list.anchor_rating is not None
        else None
    )
    anchor_rating = float(rating_list.anchor_rating) if anchor_version_id is not None else None

    version_ids = {
        version_id
        for match in matches
        for version_id in (match.engine_version_id, match.opponent_version_id)
        if version_id is not None and match.games_count > 0
    }
    if anchor_version_id is not None:
        version_ids.add(anchor_version_id)
    if not version_ids:
        return {}

    versions = list(db.scalars(select(EngineVersion).where(EngineVersion.id.in_(version_ids))))
    versions_by_id = {version.id: version for version in versions}
    if not versions_by_id:
        return {}

    database = EloDatabase(
        engines={},
        matchups=[],
        config=EloConfig(scale=None, solver=EloSolver.LBFGS_B, verbose=False),
    )
    for version in versions:
        is_anchor = version.id == anchor_version_id and anchor_rating is not None
        database.add_engine(
            _engine_key(version.id),
            fixed=is_anchor,
            elo=anchor_rating if is_anchor else UNKNOWN_ELO,
        )

    for match in matches:
        if (
            match.engine_version_id is None
            or match.opponent_version_id is None
            or match.games_count <= 0
            or match.engine_version_id == match.opponent_version_id
        ):
            continue
        if match.engine_version_id not in versions_by_id or match.opponent_version_id not in versions_by_id:
            continue
        database.add_matchup(
            _engine_key(match.engine_version_id),
            _engine_key(match.opponent_version_id),
            wins_a=int(match.wins),
            wins_b=int(match.losses),
            draws=int(match.draws),
        )

    if not database.matchups:
        if anchor_version_id is not None and anchor_rating is not None:
            return {
                anchor_version_id: EloEstimate(
                    elo=anchor_rating,
                    stderr=0.0,
                    ci_lower=anchor_rating,
                    ci_upper=anchor_rating,
                )
            }
        return {}

    result = database.fit_elo_values(apply=False)
    return {int(name): estimate for name, estimate in result.estimates.items()}


def rebuild_rating_list_leaderboard(db: Session, rating_list_id: int) -> None:
    rating_list = db.get(RatingList, rating_list_id)
    if rating_list is None:
        return

    matches = [
        match
        for match in db.scalars(
            select(Match)
            .where(Match.rating_list_id == rating_list_id)
            .order_by(Match.created_at.asc(), Match.id.asc())
        )
        if match.games_count > 0
    ]
    stats_by_version = _collect_version_stats(matches)
    elo_by_version_id = _fit_rating_list_elos(db, rating_list, matches)

    job_repository.delete_leaderboard_entries_for_rating_list(db, rating_list_id)
    if not elo_by_version_id:
        return

    versions = list(db.scalars(select(EngineVersion).where(EngineVersion.id.in_(list(elo_by_version_id)))))
    versions_by_id = {version.id: version for version in versions}
    for version_id, estimate in elo_by_version_id.items():
        version = versions_by_id.get(version_id)
        if version is None:
            continue
        stats = stats_by_version.get(version_id, _LeaderboardStats())
        db.add(
            LeaderboardEntry(
                engine_id=version.engine_id,
                engine_version_id=version.id,
                rating_list_id=rating_list_id,
                rating=float(estimate.elo),
                rating_stderr=float(estimate.stderr),
                rating_lower=float(estimate.ci_lower),
                rating_upper=float(estimate.ci_upper),
                wins=int(stats.wins),
                draws=int(stats.draws),
                losses=int(stats.losses),
                games_played=int(stats.games_played),
            )
        )
    db.commit()
    engine_repository.refresh_ranking_positions(db, rating_list_id)


def rebuild_all_leaderboards() -> None:
    db = SessionLocal()
    try:
        rating_list_ids = list(db.scalars(select(RatingList.id).order_by(RatingList.id.asc())))
        for rating_list_id in rating_list_ids:
            try:
                rebuild_rating_list_leaderboard(db, int(rating_list_id))
            except Exception as error:
                db.rollback()
                print(f"[OpenELO Server] Leaderboard refresh failed for rating list {rating_list_id}: {error}", flush=True)
    finally:
        db.close()
