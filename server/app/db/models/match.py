from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_version_id: Mapped[int] = mapped_column(ForeignKey("engine_versions.id"))
    opponent_version_id: Mapped[int] = mapped_column(ForeignKey("engine_versions.id"))
    rating_list_id: Mapped[int] = mapped_column(ForeignKey("rating_lists.id"))
    status: Mapped[str] = mapped_column(String(50), default="completed")
    wins: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    games_count: Mapped[int] = mapped_column(Integer, default=0)
    result_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    engine_version: Mapped["EngineVersion"] = relationship(
        back_populates="matches",
        foreign_keys=[engine_version_id],
    )
    opponent_version: Mapped["EngineVersion | None"] = relationship(
        back_populates="matches_as_opponent",
        foreign_keys=[opponent_version_id],
    )
    rating_list: Mapped["RatingList"] = relationship(back_populates="matches")
    jobs: Mapped[list["MatchJob"]] = relationship(back_populates="match", cascade="all, delete-orphan")

    @property
    def time_control_label(self) -> str:
        return self.rating_list.time_control_label

    @property
    def job_count(self) -> int:
        return len([job for job in self.jobs if job.status in {"completed", "failed"}])

    @property
    def engine_version_label(self) -> str:
        return f"{self.engine_version.engine.name} {self.engine_version.version_name}"

    @property
    def opponent_version_label(self) -> str:
        return f"{self.opponent_version.engine.name} {self.opponent_version.version_name}"

    @property
    def opening_book(self):
        return self.rating_list.opening_book

    @property
    def time_control_moves(self) -> int | None:
        return self.rating_list.time_control_moves

    @property
    def threads_per_engine(self) -> int:
        return self.rating_list.threads_per_engine

    @property
    def hash_per_engine(self) -> int:
        return self.rating_list.hash_per_engine

    @property
    def syzygy_probe_limit(self) -> int:
        return self.rating_list.syzygy_probe_limit

    @property
    def syzygy_label(self) -> str:
        return self.rating_list.syzygy_label
