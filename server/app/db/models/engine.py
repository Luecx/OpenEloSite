from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class Engine(Base):
    __tablename__ = "engines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)
    protocol: Mapped[str] = mapped_column(String(50), default="uci")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions: Mapped[list["EngineVersion"]] = relationship(back_populates="engine", cascade="all, delete-orphan")
    leaderboard_entries: Mapped[list["LeaderboardEntry"]] = relationship(back_populates="engine")
    tester_links: Mapped[list["EngineTester"]] = relationship(back_populates="engine", cascade="all, delete-orphan")
