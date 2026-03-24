from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class EngineMembership(Base):
    __tablename__ = "engine_memberships"
    __table_args__ = (UniqueConstraint("engine_id", "user_id", name="uq_engine_membership"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_id: Mapped[int] = mapped_column(ForeignKey("engines.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    engine: Mapped["Engine"] = relationship()
    user: Mapped["User"] = relationship(back_populates="editable_engine_links")
