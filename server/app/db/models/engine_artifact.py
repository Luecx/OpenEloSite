from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base


class EngineArtifact(Base):
    __tablename__ = "engine_artifacts"

    CPU_FLAG_FIELDS = (
        ("requires_sse4", "SSE4"),
        ("requires_popcnt", "POPCNT"),
        ("requires_avx", "AVX"),
        ("requires_avx2", "AVX2"),
        ("requires_bmi2", "BMI2"),
        ("requires_avx512", "AVX-512"),
        ("requires_vnni", "VNNI"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_version_id: Mapped[int] = mapped_column(ForeignKey("engine_versions.id"))
    system_name: Mapped[str] = mapped_column(String(50), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"))
    requires_sse4: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_popcnt: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx2: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_bmi2: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx512: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_vnni: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    engine_version: Mapped["EngineVersion"] = relationship(back_populates="artifacts")

    @property
    def required_flag_labels(self) -> list[str]:
        return [label for field_name, label in self.CPU_FLAG_FIELDS if getattr(self, field_name, False)]

    @property
    def runtime_label(self) -> str:
        flags = self.required_flag_labels
        if not flags:
            return self.system_name
        return f"{self.system_name} | {', '.join(flags)}"
