from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_id: Mapped[int] = mapped_column(ForeignKey("engines.id"))
    engine_version_id: Mapped[int] = mapped_column(ForeignKey("engine_versions.id"))
    rating_list_id: Mapped[int] = mapped_column(ForeignKey("rating_lists.id"), index=True)
    rating: Mapped[float] = mapped_column(Float, default=1200)
    rating_stderr: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wins: Mapped[int] = mapped_column(default=0)
    draws: Mapped[int] = mapped_column(default=0)
    losses: Mapped[int] = mapped_column(default=0)
    games_played: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    engine: Mapped["Engine"] = relationship(back_populates="leaderboard_entries")
    engine_version: Mapped["EngineVersion"] = relationship(back_populates="leaderboard_entries")
    rating_list: Mapped["RatingList"] = relationship(back_populates="leaderboard_entries")
