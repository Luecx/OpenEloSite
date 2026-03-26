from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.engine import Engine
from app.db.models.engine_artifact import EngineArtifact
from app.db.models.engine_membership import EngineMembership
from app.db.models.engine_tester import EngineTester
from app.db.models.engine_version import EngineVersion
from app.db.models.engine_version import compose_version_name
from app.db.models.engine_version_rating_list import EngineVersionRatingList
from app.db.models.leaderboard_entry import LeaderboardEntry
from app.db.models.rating_list import RatingList
from app.db.models.user import User
from app.db.repositories import client_repository


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "engine"


def list_public_engines(db: Session, q: str = "", protocol: str = "") -> list[Engine]:
    query = select(Engine)
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(Engine.name.ilike(pattern))
    if protocol.strip():
        query = query.where(Engine.protocol == protocol.strip())
    return list(db.scalars(query.order_by(Engine.updated_at.desc())))


def list_user_engines(db: Session, user_id: int) -> list[Engine]:
    return list(
        db.scalars(
            select(Engine)
            .join(EngineMembership, EngineMembership.engine_id == Engine.id)
            .where(EngineMembership.user_id == user_id)
            .distinct()
            .order_by(Engine.updated_at.desc())
        )
    )


def get_engine(db: Session, engine_id: int) -> Engine | None:
    return db.get(Engine, engine_id)


def get_public_engine_by_slug(db: Session, slug: str) -> Engine | None:
    return db.scalar(select(Engine).where(Engine.slug == slug))


def get_engine_for_user(db: Session, engine_id: int, user_id: int) -> Engine | None:
    return db.scalar(
        select(Engine)
        .join(EngineMembership, EngineMembership.engine_id == Engine.id)
        .where(Engine.id == engine_id, EngineMembership.user_id == user_id)
    )


def create_engine(
    db: Session,
    owner_user_ids: list[int],
    name: str,
    description: str,
    protocol: str,
) -> Engine:
    normalized_user_ids: list[int] = []
    for user_id in owner_user_ids:
        if user_id not in normalized_user_ids:
            normalized_user_ids.append(user_id)
    if not normalized_user_ids:
        raise ValueError("owner_user_ids darf nicht leer sein")

    engine = Engine(
        name=name.strip(),
        slug=slugify(name),
        description=description.strip(),
        protocol=protocol.strip() or "uci",
    )
    db.add(engine)
    db.commit()
    db.refresh(engine)

    for user_id in normalized_user_ids:
        db.add(EngineMembership(engine_id=engine.id, user_id=user_id))
    db.commit()
    db.refresh(engine)
    return engine


def update_engine(
    db: Session,
    engine: Engine,
    description: str,
    protocol: str,
) -> Engine:
    engine.description = description.strip()
    engine.protocol = protocol.strip() or "uci"
    db.commit()
    db.refresh(engine)
    return engine


def _normalize_targets(values: list[str]) -> set[str]:
    return {item.strip().lower() for item in values if item and item.strip()}


def _apply_required_cpu_flags(record: EngineArtifact, required_cpu_flags: list[str]) -> None:
    flag_values = _normalize_targets(required_cpu_flags)
    record.requires_sse4 = "sse4" in flag_values
    record.requires_avx = "avx" in flag_values
    record.requires_avx2 = "avx2" in flag_values
    record.requires_pext = "pext" in flag_values
    record.requires_avx512 = "avx512" in flag_values


def _artifact_required_flags(artifact: EngineArtifact) -> set[str]:
    required: set[str] = set()
    if artifact.requires_sse4:
        required.add("sse4")
    if artifact.requires_avx:
        required.add("avx")
    if artifact.requires_avx2:
        required.add("avx2")
    if artifact.requires_pext:
        required.add("pext")
    if artifact.requires_avx512:
        required.add("avx512")
    return required


def list_engine_owners(db: Session, engine_id: int) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(EngineMembership, EngineMembership.user_id == User.id)
            .where(EngineMembership.engine_id == engine_id)
            .order_by(User.display_name.asc(), User.username.asc())
        )
    )


def list_engine_owners_for_engines(db: Session, engine_ids: list[int]) -> dict[int, list[User]]:
    if not engine_ids:
        return {}

    owners_by_engine: dict[int, list[User]] = defaultdict(list)
    rows = db.execute(
        select(EngineMembership.engine_id, User)
        .join(User, User.id == EngineMembership.user_id)
        .where(EngineMembership.engine_id.in_(engine_ids))
        .order_by(EngineMembership.engine_id.asc(), User.display_name.asc(), User.username.asc())
    )
    for engine_id, user in rows:
        owners_by_engine[engine_id].append(user)
    return dict(owners_by_engine)


def list_engine_testers(db: Session, engine_id: int) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(EngineTester, EngineTester.user_id == User.id)
            .where(EngineTester.engine_id == engine_id)
            .order_by(User.display_name.asc(), User.username.asc())
        )
    )


def add_owner(db: Session, engine: Engine, user_id: int) -> None:
    exists = db.scalar(
        select(EngineMembership).where(
            EngineMembership.engine_id == engine.id,
            EngineMembership.user_id == user_id,
        )
    )
    if exists:
        return

    db.add(EngineMembership(engine_id=engine.id, user_id=user_id))
    db.commit()
    db.refresh(engine)


def add_tester(db: Session, engine: Engine, user_id: int) -> None:
    exists = db.scalar(
        select(EngineTester).where(
            EngineTester.engine_id == engine.id,
            EngineTester.user_id == user_id,
        )
    )
    if exists:
        return

    db.add(EngineTester(engine_id=engine.id, user_id=user_id))
    db.commit()
    db.refresh(engine)


def remove_owner(db: Session, engine: Engine, user_id: int) -> bool:
    owner_links = list(
        db.scalars(
            select(EngineMembership).where(
                EngineMembership.engine_id == engine.id,
                EngineMembership.user_id == user_id,
            )
        )
    )
    if not owner_links:
        return False

    for item in owner_links:
        db.delete(item)
    db.flush()
    db.commit()
    db.refresh(engine)
    return True


def remove_tester(db: Session, engine: Engine, user_id: int) -> bool:
    tester_links = list(
        db.scalars(
            select(EngineTester).where(
                EngineTester.engine_id == engine.id,
                EngineTester.user_id == user_id,
            )
        )
    )
    if not tester_links:
        return False

    for item in tester_links:
        db.delete(item)
    db.flush()
    db.commit()
    db.refresh(engine)
    return True


def allows_testing_user(engine: Engine | None, user_id: int | None) -> bool:
    if engine is None or user_id is None:
        return False
    restricted_user_ids = {item.user_id for item in engine.tester_links}
    if not restricted_user_ids:
        return True
    return user_id in restricted_user_ids


def _normalize_version_fields(
    version_major: int,
    version_minor: int | None = None,
    version_patch: int | None = None,
    version_additional: str | None = None,
) -> tuple[int, int | None, int | None, str | None, str]:
    major = int(version_major)
    minor = int(version_minor) if version_minor is not None else None
    patch = int(version_patch) if version_patch is not None else None
    additional = (version_additional or "").strip() or None

    if major < 0:
        raise ValueError("Major version must be greater than or equal to 0.")
    if minor is not None and minor < 0:
        raise ValueError("Minor version must be greater than or equal to 0.")
    if patch is not None and patch < 0:
        raise ValueError("Patch version must be greater than or equal to 0.")
    if patch is not None and minor is None:
        raise ValueError("Minor version is required when patch is set.")

    version_name = compose_version_name(major, minor, patch, additional)
    return major, minor, patch, additional, version_name


def _sorted_versions(versions: list[EngineVersion]) -> list[EngineVersion]:
    return sorted(versions, key=lambda item: item.version_sort_key, reverse=True)


def create_version(
    db: Session,
    engine: Engine,
    version_major: int,
    version_minor: int | None = None,
    version_patch: int | None = None,
    version_additional: str | None = None,
) -> EngineVersion:
    major, minor, patch, additional, version_name = _normalize_version_fields(
        version_major,
        version_minor,
        version_patch,
        version_additional,
    )
    version = EngineVersion(
        engine_id=engine.id,
        version_name=version_name,
        version_major=major,
        version_minor=minor,
        version_patch=patch,
        version_additional=additional,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def list_versions_for_engine(db: Session, engine_id: int) -> list[EngineVersion]:
    return _sorted_versions(
        list(
            db.scalars(
                select(EngineVersion)
                .where(EngineVersion.engine_id == engine_id)
            )
        )
    )


def list_public_versions_for_engine(db: Session, engine_id: int) -> list[EngineVersion]:
    return list_versions_for_engine(db, engine_id)


def list_versions_for_picker(db: Session) -> list[EngineVersion]:
    versions = list(
        db.scalars(
            select(EngineVersion)
            .join(Engine, Engine.id == EngineVersion.engine_id)
        )
    )
    versions_by_engine: dict[str, list[EngineVersion]] = defaultdict(list)
    for version in versions:
        versions_by_engine[version.engine.name.lower()].append(version)
    ordered: list[EngineVersion] = []
    for engine_name in sorted(versions_by_engine):
        ordered.extend(_sorted_versions(versions_by_engine[engine_name]))
    return ordered


def list_matchmaker_versions(db: Session) -> list[EngineVersion]:
    return [version for version in _sorted_versions(list(db.scalars(select(EngineVersion)))) if version.artifacts]


def get_version(db: Session, version_id: int) -> EngineVersion | None:
    return db.get(EngineVersion, version_id)


def update_version(
    db: Session,
    version: EngineVersion,
    version_major: int,
    version_minor: int | None = None,
    version_patch: int | None = None,
    version_additional: str | None = None,
) -> EngineVersion:
    major, minor, patch, additional, version_name = _normalize_version_fields(
        version_major,
        version_minor,
        version_patch,
        version_additional,
    )
    version.version_name = version_name
    version.version_major = major
    version.version_minor = minor
    version.version_patch = patch
    version.version_additional = additional
    db.commit()
    db.refresh(version)
    return version


def list_rating_lists_for_version(db: Session, version_id: int) -> list[RatingList]:
    return list(
        db.scalars(
            select(RatingList)
            .join(EngineVersionRatingList, EngineVersionRatingList.rating_list_id == RatingList.id)
            .where(EngineVersionRatingList.engine_version_id == version_id)
            .order_by(RatingList.name.asc())
        )
    )


def list_versions_for_rating_list(db: Session, rating_list_id: int) -> list[EngineVersion]:
    versions = list(
        db.scalars(
            select(EngineVersion)
            .join(Engine, Engine.id == EngineVersion.engine_id)
            .join(EngineVersionRatingList, EngineVersionRatingList.engine_version_id == EngineVersion.id)
            .where(EngineVersionRatingList.rating_list_id == rating_list_id)
        )
    )
    versions_by_engine: dict[str, list[EngineVersion]] = defaultdict(list)
    for version in versions:
        versions_by_engine[version.engine.name.lower()].append(version)
    ordered: list[EngineVersion] = []
    for engine_name in sorted(versions_by_engine):
        ordered.extend(_sorted_versions(versions_by_engine[engine_name]))
    return ordered


def set_rating_lists_for_version(db: Session, version: EngineVersion, rating_list_ids: list[int]) -> EngineVersion:
    normalized_ids: list[int] = []
    for rating_list_id in rating_list_ids:
        if rating_list_id not in normalized_ids:
            normalized_ids.append(rating_list_id)

    existing_links = list(
        db.scalars(
            select(EngineVersionRatingList).where(EngineVersionRatingList.engine_version_id == version.id)
        )
    )
    for link in existing_links:
        db.delete(link)
    db.flush()

    for rating_list_id in normalized_ids:
        db.add(EngineVersionRatingList(engine_version_id=version.id, rating_list_id=rating_list_id))

    version.restrict_to_rating_lists = True
    db.commit()
    db.refresh(version)
    return version


def allows_rating_list(version: EngineVersion | None, rating_list_id: int | None) -> bool:
    if version is None or rating_list_id is None:
        return False
    return any(link.rating_list_id == rating_list_id for link in version.rating_list_links)


def list_artifacts_for_version(db: Session, version_id: int) -> list[EngineArtifact]:
    artifacts = list(
        db.scalars(
            select(EngineArtifact)
            .where(EngineArtifact.engine_version_id == version_id)
            .order_by(EngineArtifact.priority.asc(), EngineArtifact.id.asc())
        )
    )
    return _normalize_artifact_priorities(db, artifacts)


def _normalize_artifact_priorities(db: Session, artifacts: list[EngineArtifact]) -> list[EngineArtifact]:
    changed = False
    for index, artifact in enumerate(artifacts, start=1):
        if artifact.priority != index:
            artifact.priority = index
            changed = True
    if changed:
        db.commit()
        for artifact in artifacts:
            db.refresh(artifact)
    return artifacts


def create_artifact(
    db: Session,
    version: EngineVersion,
    system_name: str,
    file_name: str,
    file_path: str,
    content_hash: str,
    required_cpu_flags: list[str],
) -> EngineArtifact:
    existing_artifacts = list_artifacts_for_version(db, version.id)
    artifact = EngineArtifact(
        engine_version_id=version.id,
        system_name=(system_name or "").strip().lower(),
        file_name=file_name.strip(),
        file_path=file_path.strip(),
        content_hash=content_hash.strip(),
        priority=len(existing_artifacts) + 1,
    )
    _apply_required_cpu_flags(artifact, required_cpu_flags)
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


def get_artifact(db: Session, artifact_id: int) -> EngineArtifact | None:
    return db.get(EngineArtifact, artifact_id)


def update_artifact(
    db: Session,
    artifact: EngineArtifact,
    system_name: str,
    required_cpu_flags: list[str],
) -> EngineArtifact:
    artifact.system_name = (system_name or "").strip().lower()
    _apply_required_cpu_flags(artifact, required_cpu_flags)
    db.commit()
    db.refresh(artifact)
    return artifact


def delete_artifact(db: Session, artifact: EngineArtifact) -> None:
    version_id = artifact.engine_version_id
    artifact_path = Path(artifact.file_path)
    db.delete(artifact)
    db.commit()
    if artifact_path.exists():
        artifact_path.unlink(missing_ok=True)
    remaining = list(
        db.scalars(
            select(EngineArtifact)
            .where(EngineArtifact.engine_version_id == version_id)
            .order_by(EngineArtifact.priority.asc(), EngineArtifact.id.asc())
        )
    )
    _normalize_artifact_priorities(db, remaining)


def pick_compatible_artifact(version: EngineVersion | None, system_name: str, cpu_flags: list[str] | str | set[str] | None) -> EngineArtifact | None:
    if version is None:
        return None

    normalized_system = (system_name or "").strip().lower()
    client_flags = client_repository.parse_cpu_flags(cpu_flags if isinstance(cpu_flags, str) else client_repository.serialize_cpu_flags(cpu_flags))
    ordered_artifacts = sorted(version.artifacts, key=lambda item: (item.priority, item.id))
    for artifact in ordered_artifacts:
        if artifact.system_name.strip().lower() != normalized_system:
            continue
        required_flags = _artifact_required_flags(artifact)
        if not required_flags.issubset(client_flags):
            continue
        return artifact
    return None


def move_artifact_priority(db: Session, artifact: EngineArtifact, direction: str) -> EngineArtifact:
    artifacts = list_artifacts_for_version(db, artifact.engine_version_id)
    artifact_ids = [item.id for item in artifacts]
    if artifact.id not in artifact_ids:
        return artifact

    current_index = artifact_ids.index(artifact.id)
    if direction == "up":
        swap_index = current_index - 1
    elif direction == "down":
        swap_index = current_index + 1
    else:
        return artifact

    if swap_index < 0 or swap_index >= len(artifacts):
        return artifact

    artifacts[current_index], artifacts[swap_index] = artifacts[swap_index], artifacts[current_index]
    _normalize_artifact_priorities(db, artifacts)
    return db.get(EngineArtifact, artifact.id) or artifact


def list_leaderboard(db: Session, rating_list_id: int | None = None, best_per_engine: bool = False) -> list[LeaderboardEntry]:
    query = (
        select(LeaderboardEntry)
        .join(Engine, Engine.id == LeaderboardEntry.engine_id)
        .join(EngineVersion, EngineVersion.id == LeaderboardEntry.engine_version_id)
    )
    if rating_list_id:
        query = query.where(LeaderboardEntry.rating_list_id == rating_list_id)
    entries = list(db.scalars(query.order_by(LeaderboardEntry.rating.desc(), LeaderboardEntry.games_played.desc(), LeaderboardEntry.id.asc())))
    if not best_per_engine:
        return entries

    best_entries: list[LeaderboardEntry] = []
    seen_engine_ids: set[int] = set()
    for entry in entries:
        if entry.engine_id in seen_engine_ids:
            continue
        seen_engine_ids.add(entry.engine_id)
        best_entries.append(entry)
    return best_entries


def ensure_leaderboard_entry(db: Session, engine_id: int, engine_version_id: int, rating_list_id: int) -> LeaderboardEntry:
    entry = db.scalar(
        select(LeaderboardEntry).where(
            LeaderboardEntry.engine_id == engine_id,
            LeaderboardEntry.engine_version_id == engine_version_id,
            LeaderboardEntry.rating_list_id == rating_list_id,
        )
    )
    if entry:
        return entry

    entry = LeaderboardEntry(engine_id=engine_id, engine_version_id=engine_version_id, rating_list_id=rating_list_id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def refresh_ranking_positions(db: Session, rating_list_id: int) -> None:
    entries = list_leaderboard(db, rating_list_id=rating_list_id)
    for index, item in enumerate(entries, start=1):
        item.rank_position = index
    db.commit()
