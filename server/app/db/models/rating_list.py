from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.services.syzygy_service import syzygy_label


class RatingList(Base):
    __tablename__ = "rating_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_control_base_seconds: Mapped[int] = mapped_column(Integer, default=60)
    time_control_increment_seconds: Mapped[int] = mapped_column(Integer, default=1)
    time_control_moves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threads_per_engine: Mapped[int] = mapped_column(Integer, default=1)
    hash_per_engine: Mapped[int] = mapped_column(Integer, default=16)
    syzygy_probe_limit: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    opening_book_id: Mapped[int | None] = mapped_column(ForeignKey("opening_books.id"), nullable=True)
    anchor_engine_version_id: Mapped[int | None] = mapped_column(ForeignKey("engine_versions.id"), nullable=True)
    anchor_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    opening_book: Mapped["OpeningBook"] = relationship(back_populates="rating_lists")
    anchor_engine_version: Mapped["EngineVersion | None"] = relationship(foreign_keys=[anchor_engine_version_id])
    matches: Mapped[list["Match"]] = relationship(back_populates="rating_list")
    leaderboard_entries: Mapped[list["LeaderboardEntry"]] = relationship(back_populates="rating_list")
    version_links: Mapped[list["EngineVersionRatingList"]] = relationship(back_populates="rating_list", cascade="all, delete-orphan")

    @property
    def time_control_label(self) -> str:
        if self.time_control_moves:
            return f"{self.time_control_moves}/{self.time_control_base_seconds}+{self.time_control_increment_seconds}"
        return f"{self.time_control_base_seconds}+{self.time_control_increment_seconds}"

    @property
    def syzygy_label(self) -> str:
        return syzygy_label(self.syzygy_probe_limit)
