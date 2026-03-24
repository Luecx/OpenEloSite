from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.services.syzygy_service import syzygy_label


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    machine_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    machine_fingerprint: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    machine_name: Mapped[str] = mapped_column(String(120))
    system_name: Mapped[str] = mapped_column(String(50), default="linux")
    max_threads: Mapped[int] = mapped_column(Integer, default=1)
    max_hash: Mapped[int] = mapped_column(Integer, default=256)
    syzygy_max_pieces: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    cpu_flags: Mapped[str] = mapped_column(Text, default="")
    last_state: Mapped[str] = mapped_column(String(50), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="clients")
    match_jobs: Mapped[list["MatchJob"]] = relationship(back_populates="client")

    @property
    def syzygy_label(self) -> str:
        return syzygy_label(self.syzygy_max_pieces)
