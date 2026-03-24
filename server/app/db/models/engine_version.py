from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class EngineVersion(Base):
    __tablename__ = "engine_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_id: Mapped[int] = mapped_column(ForeignKey("engines.id"))
    version_name: Mapped[str] = mapped_column(String(120))
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
    def runtime_label(self) -> str:
        if not self.artifacts:
            return "Keine Artifacts"
        return ", ".join(sorted({artifact.system_name for artifact in self.artifacts}))
