from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class EngineRequest(Base):
    __tablename__ = "engine_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    engine_id: Mapped[int | None] = mapped_column(ForeignKey("engines.id"), nullable=True, index=True)
    engine_name: Mapped[str] = mapped_column(String(120), index=True)
    engine_slug: Mapped[str] = mapped_column(String(120), index=True)
    protocol: Mapped[str] = mapped_column(String(50), default="uci")
    request_text: Mapped[str] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    admin_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requester: Mapped["User"] = relationship("User", foreign_keys=[requester_user_id])
    reviewer: Mapped["User | None"] = relationship("User", foreign_keys=[reviewed_by_user_id])
    engine: Mapped["Engine | None"] = relationship("Engine")
