from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class MatchJob(Base):
    __tablename__ = "match_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    client_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_user_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    client_machine_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    client_machine_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    client_system_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client_cpu_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    threads_per_engine: Mapped[int] = mapped_column(Integer, default=1)
    hash_per_engine: Mapped[int] = mapped_column(Integer, default=16)
    num_games: Mapped[int] = mapped_column(Integer, default=128)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="completed")
    wins: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    games_count: Mapped[int] = mapped_column(Integer, default=0)
    result_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pgn_zip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    match: Mapped["Match | None"] = relationship(back_populates="jobs")
    client: Mapped["Client | None"] = relationship(back_populates="match_jobs")

    @property
    def time_control_label(self) -> str:
        return self.match.time_control_label
