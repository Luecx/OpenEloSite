from __future__ import annotations

import math
import random
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.client import Client
from app.db.models.leaderboard_entry import LeaderboardEntry
from app.db.models.rating_list import RatingList
from app.db.repositories import catalog_repository
from app.db.repositories import engine_repository
from app.db.repositories import job_repository
from app.services import assignment_service
from app.services.syzygy_service import client_supports_syzygy


DEFAULT_GAMES_PER_CONCURRENCY_SLOT = 16
MINIMUM_ASSIGNMENT_GAMES = 8
DEFAULT_RATING = 1200.0
RATING_DIFF_SCALE = 140.0
ENGINE_1_FRESHNESS_WEIGHT = 2.0
ENGINE_1_NOVELTY_WEIGHT = 1.5
ENGINE_1_COVERAGE_WEIGHT = 0.4
ENGINE_2_CLOSENESS_WEIGHT = 2.4
ENGINE_2_PAIR_NOVELTY_WEIGHT = 1.3
ENGINE_2_FRESHNESS_WEIGHT = 0.7
ENGINE_2_NOVELTY_WEIGHT = 0.5
RATING_LIST_CLOSENESS_WEIGHT = 2.0
RATING_LIST_PAIR_NOVELTY_WEIGHT = 1.4
_random = random.SystemRandom()


def _softmax_weights(scores: list[float]) -> list[float]:
    if not scores:
        return []
    maximum = max(scores)
    return [math.exp(score - maximum) for score in scores]


def _softmax_probabilities(scores: list[float]) -> list[float]:
    weights = _softmax_weights(scores)
    total = sum(weights)
    if total <= 0:
        return [0.0 for _ in weights]
    return [weight / total for weight in weights]


def _softmax_sample(items: list, scores: list[float]):
    if not items or len(items) != len(scores):
        return None
    weights = _softmax_weights(scores)
    return _random.choices(items, weights=weights, k=1)[0]


def _version_pair_key(version_a_id: int, version_b_id: int) -> tuple[int, int]:
    return (version_a_id, version_b_id) if version_a_id < version_b_id else (version_b_id, version_a_id)


def _rating_closeness(first_rating: float, second_rating: float) -> float:
    return math.exp(-abs(first_rating - second_rating) / RATING_DIFF_SCALE)


def _games_novelty(games_count: int, scale: int = 32) -> float:
    return 1.0 / math.sqrt(1.0 + (max(0, games_count) / max(1, scale)))


def _normalized_freshness_by_version(versions: list) -> dict[int, float]:
    if not versions:
        return {}
    ordered = sorted(versions, key=lambda item: item.version_sort_key, reverse=True)
    if len(ordered) == 1:
        return {ordered[0].id: 1.0}
    divisor = max(1, len(ordered) - 1)
    return {version.id: 1.0 - (index / divisor) for index, version in enumerate(ordered)}


def _client_can_run_rating_list(client: Client, rating_list: RatingList) -> bool:
    return (
        rating_list.threads_per_engine <= client.max_threads
        and rating_list.hash_per_engine <= client.max_hash
        and client_supports_syzygy(client.syzygy_max_pieces, rating_list.syzygy_probe_limit)
    )


def _build_matchmaker_state(db: Session, client: Client) -> dict:
    rating_lists = [item for item in catalog_repository.list_rating_lists(db) if _client_can_run_rating_list(client, item)]
    if not rating_lists:
        return {
            "rating_lists": [],
            "versions": [],
            "allowed_rating_lists_by_version": {},
            "freshness": {},
            "novelty": {},
            "average_rating": {},
            "rating_by_version_and_list": {},
            "pair_games_total": {},
            "pair_games_by_rating_list": {},
        }

    rating_list_ids = [item.id for item in rating_lists]
    raw_versions = engine_repository.list_matchmaker_versions(db)
    versions: list = []
    allowed_rating_lists_by_version: dict[int, set[int]] = {}
    for version in raw_versions:
        if engine_repository.pick_compatible_artifact(version, client.system_name, client.cpu_flags) is None:
            continue
        if not engine_repository.allows_testing_user(version.engine, client.user_id):
            continue
        allowed_ids = {
            rating_list.id
            for rating_list in rating_lists
            if engine_repository.allows_rating_list(version, rating_list.id)
        }
        if not allowed_ids:
            continue
        versions.append(version)
        allowed_rating_lists_by_version[version.id] = allowed_ids

    version_ids = [item.id for item in versions]
    if len(version_ids) < 2:
        return {
            "rating_lists": rating_lists,
            "versions": versions,
            "allowed_rating_lists_by_version": allowed_rating_lists_by_version,
            "freshness": _normalized_freshness_by_version(versions),
            "novelty": {item.id: 1.0 for item in versions},
            "average_rating": {item.id: DEFAULT_RATING for item in versions},
            "rating_by_version_and_list": {},
            "pair_games_total": {},
            "pair_games_by_rating_list": {},
        }

    leaderboard_entries = list(
        db.scalars(
            select(LeaderboardEntry).where(
                LeaderboardEntry.engine_version_id.in_(version_ids),
                LeaderboardEntry.rating_list_id.in_(rating_list_ids),
            )
        )
    )

    rating_by_version_and_list: dict[tuple[int, int], float] = {}
    total_games_by_version: dict[int, int] = defaultdict(int)
    weighted_rating_sum: dict[int, float] = defaultdict(float)
    weighted_rating_weight: dict[int, int] = defaultdict(int)
    for entry in leaderboard_entries:
        rating_by_version_and_list[(entry.engine_version_id, entry.rating_list_id)] = entry.rating
        total_games_by_version[entry.engine_version_id] += entry.games_played
        weight = max(1, entry.games_played)
        weighted_rating_sum[entry.engine_version_id] += entry.rating * weight
        weighted_rating_weight[entry.engine_version_id] += weight

    average_rating = {
        version.id: (
            weighted_rating_sum[version.id] / weighted_rating_weight[version.id]
            if weighted_rating_weight[version.id] > 0
            else DEFAULT_RATING
        )
        for version in versions
    }
    novelty = {
        version.id: _games_novelty(total_games_by_version[version.id], scale=48)
        for version in versions
    }

    pair_games_total: dict[tuple[int, int], int] = defaultdict(int)
    pair_games_by_rating_list: dict[tuple[int, tuple[int, int]], int] = defaultdict(int)
    for match in job_repository.list_matches_for_rating_lists(db, rating_list_ids):
        if match.engine_version_id is None or match.opponent_version_id is None:
            continue
        pair_key = _version_pair_key(match.engine_version_id, match.opponent_version_id)
        pair_games_total[pair_key] += max(0, match.games_count)
        pair_games_by_rating_list[(match.rating_list_id, pair_key)] += max(0, match.games_count)

    return {
        "rating_lists": rating_lists,
        "versions": versions,
        "allowed_rating_lists_by_version": allowed_rating_lists_by_version,
        "freshness": _normalized_freshness_by_version(versions),
        "novelty": novelty,
        "average_rating": average_rating,
        "rating_by_version_and_list": rating_by_version_and_list,
        "pair_games_total": pair_games_total,
        "pair_games_by_rating_list": pair_games_by_rating_list,
    }


def _first_engine_candidates(state: dict) -> list:
    versions = state["versions"]
    allowed_rating_lists_by_version = state["allowed_rating_lists_by_version"]
    result = []
    for version in versions:
        has_opponent = any(
            other.id != version.id
            and bool(allowed_rating_lists_by_version[version.id] & allowed_rating_lists_by_version[other.id])
            for other in versions
        )
        if has_opponent:
            result.append(version)
    return result


def _score_first_engine(version, state: dict, rating_list_count: int) -> float:
    coverage = len(state["allowed_rating_lists_by_version"][version.id]) / max(1, rating_list_count)
    return (
        ENGINE_1_FRESHNESS_WEIGHT * state["freshness"].get(version.id, 0.0)
        + ENGINE_1_NOVELTY_WEIGHT * state["novelty"].get(version.id, 0.0)
        + ENGINE_1_COVERAGE_WEIGHT * coverage
    )


def _pair_closeness(first_version, second_version, shared_rating_list_ids: set[int], state: dict) -> float:
    rating_by_version_and_list = state["rating_by_version_and_list"]
    average_rating = state["average_rating"]
    closeness_scores: list[float] = []
    for rating_list_id in shared_rating_list_ids:
        first_rating = rating_by_version_and_list.get((first_version.id, rating_list_id), average_rating[first_version.id])
        second_rating = rating_by_version_and_list.get((second_version.id, rating_list_id), average_rating[second_version.id])
        closeness_scores.append(_rating_closeness(first_rating, second_rating))
    if closeness_scores:
        return max(closeness_scores)
    return _rating_closeness(average_rating[first_version.id], average_rating[second_version.id])


def _second_engine_candidates(first_version, state: dict) -> list[tuple]:
    candidates: list[tuple] = []
    allowed_rating_lists_by_version = state["allowed_rating_lists_by_version"]
    for version in state["versions"]:
        if version.id == first_version.id:
            continue
        shared_rating_list_ids = allowed_rating_lists_by_version[first_version.id] & allowed_rating_lists_by_version[version.id]
        if not shared_rating_list_ids:
            continue
        candidates.append((version, shared_rating_list_ids))
    return candidates


def _score_second_engine(first_version, second_version, shared_rating_list_ids: set[int], state: dict) -> float:
    pair_key = _version_pair_key(first_version.id, second_version.id)
    pair_novelty = _games_novelty(state["pair_games_total"].get(pair_key, 0), scale=24)
    closeness = _pair_closeness(first_version, second_version, shared_rating_list_ids, state)
    return (
        ENGINE_2_CLOSENESS_WEIGHT * closeness
        + ENGINE_2_PAIR_NOVELTY_WEIGHT * pair_novelty
        + ENGINE_2_FRESHNESS_WEIGHT * state["freshness"].get(second_version.id, 0.0)
        + ENGINE_2_NOVELTY_WEIGHT * state["novelty"].get(second_version.id, 0.0)
    )


def _rating_list_candidates(first_version, second_version, shared_rating_list_ids: set[int], state: dict) -> tuple[list[RatingList], list[float]]:
    rating_lists_by_id = {item.id: item for item in state["rating_lists"]}
    pair_key = _version_pair_key(first_version.id, second_version.id)
    candidates = [rating_lists_by_id[item_id] for item_id in shared_rating_list_ids if item_id in rating_lists_by_id]
    scores: list[float] = []
    for rating_list in candidates:
        first_rating = state["rating_by_version_and_list"].get((first_version.id, rating_list.id), state["average_rating"][first_version.id])
        second_rating = state["rating_by_version_and_list"].get((second_version.id, rating_list.id), state["average_rating"][second_version.id])
        closeness = _rating_closeness(first_rating, second_rating)
        pair_games = state["pair_games_by_rating_list"].get((rating_list.id, pair_key), 0)
        pair_novelty = _games_novelty(pair_games, scale=12)
        scores.append(
            RATING_LIST_CLOSENESS_WEIGHT * closeness
            + RATING_LIST_PAIR_NOVELTY_WEIGHT * pair_novelty
        )
    return candidates, scores


def preview_matchups_for_client(db: Session, client: Client, limit: int | None = 20) -> list[dict]:
    state = _build_matchmaker_state(db, client)
    if len(state["versions"]) < 2 or not state["rating_lists"]:
        return []

    first_engine_candidates = _first_engine_candidates(state)
    if not first_engine_candidates:
        return []

    rating_list_count = len(state["rating_lists"])
    first_scores = [_score_first_engine(item, state, rating_list_count) for item in first_engine_candidates]
    first_probabilities = _softmax_probabilities(first_scores)

    candidates: list[dict] = []
    for first_version, first_probability in zip(first_engine_candidates, first_probabilities):
        second_engine_candidates = _second_engine_candidates(first_version, state)
        if not second_engine_candidates:
            continue
        second_scores = [
            _score_second_engine(first_version, second_version, shared_rating_list_ids, state)
            for second_version, shared_rating_list_ids in second_engine_candidates
        ]
        second_probabilities = _softmax_probabilities(second_scores)
        for (second_version, shared_rating_list_ids), second_probability in zip(second_engine_candidates, second_probabilities):
            rating_list_candidates, rating_list_scores = _rating_list_candidates(first_version, second_version, shared_rating_list_ids, state)
            rating_list_probabilities = _softmax_probabilities(rating_list_scores)
            for rating_list, rating_list_probability in zip(rating_list_candidates, rating_list_probabilities):
                if assignment_service.has_selection_assignment(rating_list.id, first_version.id, second_version.id):
                    continue
                candidates.append(
                    {
                        "engine_1_version": first_version,
                        "engine_2_version": second_version,
                        "rating_list": rating_list,
                        "probability": first_probability * second_probability * rating_list_probability,
                    }
                )

    total_probability = sum(item["probability"] for item in candidates)
    if total_probability > 0:
        for item in candidates:
            item["probability"] = item["probability"] / total_probability

    candidates.sort(key=lambda item: item["probability"], reverse=True)
    if limit is None:
        return candidates
    return candidates[:max(1, int(limit))]


def estimate_assignment_games(client: Client, threads_per_engine: int) -> int:
    concurrency = max(1, client.max_threads // max(1, threads_per_engine))
    return max(MINIMUM_ASSIGNMENT_GAMES, concurrency * DEFAULT_GAMES_PER_CONCURRENCY_SLOT)


def assign_next_job(db: Session, client: Client):
    candidates = preview_matchups_for_client(db, client, limit=None)
    if not candidates:
        return None

    remaining_candidates = list(candidates)
    while remaining_candidates:
        selected = _random.choices(remaining_candidates, weights=[item["probability"] for item in remaining_candidates], k=1)[0]
        first_version = selected["engine_1_version"]
        second_version = selected["engine_2_version"]
        rating_list = selected["rating_list"]
        num_games = estimate_assignment_games(client, rating_list.threads_per_engine)
        seed = _random.randrange(1, 2**31 - 1)
        assignment = assignment_service.create_assignment(
            client=client,
            engine_version_id=first_version.id,
            opponent_version_id=second_version.id,
            rating_list_id=rating_list.id,
            threads_per_engine=rating_list.threads_per_engine,
            hash_per_engine=rating_list.hash_per_engine,
            num_games=num_games,
            seed=seed,
        )
        if assignment is not None:
            return assignment
        remaining_candidates = [item for item in remaining_candidates if item is not selected]
    return None
