from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


_VERSION_PATTERN = re.compile(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(.+))?\s*$")


def _natural_text_key(value: str | None) -> tuple[tuple[int, int | str], ...]:
    raw_value = (value or "").strip().lower()
    if not raw_value:
        return tuple()
    parts = re.split(r"(\d+)", raw_value)
    result: list[tuple[int, int | str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            result.append((0, int(part)))
        else:
            result.append((1, part))
    return tuple(result)


def parse_version_name(version_name: str | None) -> tuple[int | None, int | None, int | None, str | None]:
    raw_value = (version_name or "").strip()
    if not raw_value:
        return (None, None, None, None)
    match = _VERSION_PATTERN.match(raw_value)
    if not match:
        return (None, None, None, raw_value or None)
    major_raw, minor_raw, patch_raw, additional_raw = match.groups()
    return (
        int(major_raw) if major_raw is not None else None,
        int(minor_raw) if minor_raw is not None else None,
        int(patch_raw) if patch_raw is not None else None,
        additional_raw.strip() if additional_raw and additional_raw.strip() else None,
    )


def compose_version_name(
    major: int,
    minor: int | None = None,
    patch: int | None = None,
    additional: str | None = None,
) -> str:
    base = str(int(major))
    if minor is not None:
        base = f"{base}.{int(minor)}"
    if patch is not None:
        base = f"{base}.{int(patch)}"
    suffix = (additional or "").strip()
    if suffix:
        base = f"{base}-{suffix}"
    return base


class EngineVersion(Base):
    __tablename__ = "engine_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_id: Mapped[int] = mapped_column(ForeignKey("engines.id"))
    version_name: Mapped[str] = mapped_column(String(120))
    version_major: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_patch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_additional: Mapped[str | None] = mapped_column(String(120), nullable=True)
    restrict_to_rating_lists: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    engine: Mapped["Engine"] = relationship(back_populates="versions")
    artifacts: Mapped[list["EngineArtifact"]] = relationship(back_populates="engine_version", cascade="all, delete-orphan")
    matches: Mapped[list["Match"]] = relationship(
        back_populates="engine_version",
        foreign_keys="Match.engine_version_id",
    )
    matches_as_opponent: Mapped[list["Match"]] = relationship(
        back_populates="opponent_version",
        foreign_keys="Match.opponent_version_id",
    )
    leaderboard_entries: Mapped[list["LeaderboardEntry"]] = relationship(back_populates="engine_version")
    rating_list_links: Mapped[list["EngineVersionRatingList"]] = relationship(back_populates="engine_version", cascade="all, delete-orphan")

    @property
    def display_name(self) -> str:
        return f"{self.engine.name} {self.version_name}"

    @property
    def tag(self) -> str:
        return self.version_name

    @property
    def effective_version_components(self) -> tuple[int | None, int | None, int | None, str | None]:
        major = self.version_major
        minor = self.version_minor
        patch = self.version_patch
        additional = self.version_additional
        if major is not None:
            return (major, minor, patch, additional)
        return parse_version_name(self.version_name)

    @property
    def version_sort_key(self) -> tuple:
        major, minor, patch, additional = self.effective_version_components
        return (
            int(major) if major is not None else -1,
            int(minor) if minor is not None else 0,
            int(patch) if patch is not None else 0,
            1 if (additional or "").strip() else 0,
            _natural_text_key(additional),
            self.created_at,
            self.id,
        )

    @property
    def runtime_label(self) -> str:
        if not self.artifacts:
            return "Keine Artifacts"
        return ", ".join(sorted({artifact.system_name for artifact in self.artifacts}))
