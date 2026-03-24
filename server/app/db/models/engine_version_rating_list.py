from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class EngineVersionRatingList(Base):
    __tablename__ = "engine_version_rating_lists"
    __table_args__ = (UniqueConstraint("engine_version_id", "rating_list_id", name="uq_engine_version_rating_list"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_version_id: Mapped[int] = mapped_column(ForeignKey("engine_versions.id"))
    rating_list_id: Mapped[int] = mapped_column(ForeignKey("rating_lists.id"))

    engine_version: Mapped["EngineVersion"] = relationship(back_populates="rating_list_links")
    rating_list: Mapped["RatingList"] = relationship(back_populates="version_links")
