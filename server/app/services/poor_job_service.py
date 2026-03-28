from __future__ import annotations

from dataclasses import dataclass
import logging
import math

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.match import Match
from app.db.models.match_job import MatchJob
from app.db.repositories import job_repository
from app.db.session import SessionLocal

DIRICHLET_PRIOR = 1.0
MIN_BASELINE_GAMES = 32
POOR_JOB_P_VALUE_THRESHOLD = 1e-6
logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True, slots=True)
class JobReview:
    is_poor: bool
    p_value: float | None
    reason: str | None


def _completed_jobs(match: Match) -> list[MatchJob]:
    return [
        job
        for job in match.jobs
        if job.status == "completed" and int(job.games_count or 0) > 0
    ]


def _job_vector(job: MatchJob) -> np.ndarray:
    return np.array(
        [
            float(job.wins or 0),
            float(job.draws or 0),
            float(job.losses or 0),
        ],
        dtype=np.float64,
    )


def _score_fraction(vector: np.ndarray) -> float:
    games = float(np.sum(vector))
    if games <= 0:
        return 0.0
    return float((vector[0] + (0.5 * vector[1])) / games)


def _dirichlet_multinomial_p_value(observed: np.ndarray, other_totals: np.ndarray) -> float:
    alpha = other_totals + DIRICHLET_PRIOR
    alpha_total = float(np.sum(alpha))
    games = float(np.sum(observed))
    probabilities = alpha / max(1e-12, alpha_total)
    mean = games * probabilities
    covariance = (
        games
        * ((games + alpha_total) / max(1e-12, 1.0 + alpha_total))
        * (np.diag(probabilities) - np.outer(probabilities, probabilities))
    )
    delta = observed - mean
    information = np.linalg.pinv(covariance)
    distance = float(delta.T @ information @ delta)
    if not math.isfinite(distance) or distance <= 0.0:
        return 1.0
    # The count vector has one linear dependency because W + D + L = N.
    return max(0.0, min(1.0, math.exp(-0.5 * distance)))


def _review_job(job: MatchJob, all_completed_jobs: list[MatchJob]) -> JobReview:
    if job.status != "completed" or int(job.games_count or 0) <= 0:
        return JobReview(is_poor=False, p_value=None, reason=None)

    observed = _job_vector(job)
    other_jobs = [item for item in all_completed_jobs if item.id != job.id]
    if not other_jobs:
        return JobReview(is_poor=False, p_value=None, reason=None)

    other_totals = np.sum([_job_vector(item) for item in other_jobs], axis=0)
    if float(np.sum(other_totals)) < MIN_BASELINE_GAMES:
        return JobReview(is_poor=False, p_value=None, reason=None)

    p_value = _dirichlet_multinomial_p_value(observed, other_totals)
    if p_value >= POOR_JOB_P_VALUE_THRESHOLD:
        return JobReview(is_poor=False, p_value=p_value, reason=None)

    observed_score = _score_fraction(observed)
    expected_score = _score_fraction(other_totals)
    reason = (
        "Excluded as a poor outlier "
        f"(p={p_value:.1e}, score {observed_score:.3f} vs baseline {expected_score:.3f})"
    )
    return JobReview(is_poor=True, p_value=p_value, reason=reason)


def _apply_review(job: MatchJob, review: JobReview) -> bool:
    changed = False
    if bool(job.is_poor) != bool(review.is_poor):
        job.is_poor = bool(review.is_poor)
        changed = True
    if job.poor_p_value != review.p_value:
        job.poor_p_value = review.p_value
        changed = True
    normalized_reason = (review.reason or "").strip() or None
    if (job.poor_reason or None) != normalized_reason:
        job.poor_reason = normalized_reason
        changed = True
    return changed


def review_match(match: Match) -> bool:
    completed_jobs = _completed_jobs(match)
    changed = False
    for job in match.jobs:
        review = _review_job(job, completed_jobs)
        changed = _apply_review(job, review) or changed

    previous_counts = (match.wins, match.draws, match.losses, match.games_count, match.result_text)
    job_repository.apply_match_results_from_jobs(match, list(match.jobs))
    next_counts = (match.wins, match.draws, match.losses, match.games_count, match.result_text)
    return changed or previous_counts != next_counts


def review_match_by_id(db, match_id: int) -> bool:
    match = db.scalar(
        select(Match)
        .options(selectinload(Match.jobs))
        .where(Match.id == match_id)
    )
    if match is None:
        return False
    return review_match(match)


def review_all_matches() -> None:
    db = SessionLocal()
    try:
        matches = list(
            db.scalars(
                select(Match)
                .options(selectinload(Match.jobs))
                .order_by(Match.id.asc())
            )
        )
        changed_matches = 0
        changed_jobs = 0
        for match in matches:
            before = {
                job.id: (bool(job.is_poor), job.poor_p_value, job.poor_reason)
                for job in match.jobs
            }
            changed = review_match(match)
            if not changed:
                continue
            changed_matches += 1
            changed_jobs += sum(
                1
                for job in match.jobs
                if before.get(job.id) != (bool(job.is_poor), job.poor_p_value, job.poor_reason)
            )
            db.add(match)
        if changed_matches > 0:
            db.commit()
            logger.info(
                "[poor-jobs] reviewed matches=%s changed_matches=%s changed_jobs=%s",
                len(matches),
                changed_matches,
                changed_jobs,
            )
        else:
            db.rollback()
    finally:
        db.close()
