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


STANDARD_FLAG_ORDER = ("popcnt", "bmi2")
STANDARD_FLAG_LABELS = {
    "popcnt": "POPCNT",
    "bmi2": "BMI2",
}
SIMD_CLASS_ORDER = ("sse", "sse2", "sse3", "ssse3", "sse41", "sse42", "avx", "avx2", "avx512")
SIMD_CLASS_LABELS = {
    "sse": "SSE",
    "sse2": "SSE2",
    "sse3": "SSE3",
    "ssse3": "SSSE3",
    "sse41": "SSE4.1",
    "sse42": "SSE4.2",
    "avx": "AVX",
    "avx2": "AVX2",
    "avx512": "AVX512",
}
SIMD_CLASS_CLIENT_FLAGS = {
    "sse": "sse",
    "sse2": "sse2",
    "sse3": "sse3",
    "ssse3": "ssse3",
    "sse41": "sse41",
    "sse42": "sse42",
    "avx": "avx",
    "avx2": "avx2",
    "avx512": "avx512f",
}
AVX512_FLAG_ORDER = ("avx512f", "avx512bw", "avx512dq", "avx512vl", "avx512vnni")
AVX512_FLAG_LABELS = {
    "avx512f": "F",
    "avx512bw": "BW",
    "avx512dq": "DQ",
    "avx512vl": "VL",
    "avx512vnni": "VNNI",
}
AVX512_FLAG_ALIASES = {
    "f": "avx512f",
    "bw": "avx512bw",
    "dq": "avx512dq",
    "vl": "avx512vl",
    "vnni": "avx512vnni",
    "avx512_vnni": "avx512vnni",
    "avx512vnni": "avx512vnni",
    "avx512f": "avx512f",
    "avx512bw": "avx512bw",
    "avx512dq": "avx512dq",
    "avx512vl": "avx512vl",
}


def normalize_simd_class(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in SIMD_CLASS_ORDER else "sse"


def infer_simd_class_from_flags(values: list[str] | tuple[str, ...] | set[str] | str | None) -> str:
    if values is None:
        normalized_values: set[str] = set()
    elif isinstance(values, str):
        normalized_values = {item.strip().lower() for item in values.split(",") if item and item.strip()}
    else:
        normalized_values = {str(item).strip().lower() for item in values if str(item).strip()}
    for simd_class in reversed(SIMD_CLASS_ORDER):
        if SIMD_CLASS_CLIENT_FLAGS[simd_class] in normalized_values:
            return simd_class
    return "sse"


def normalize_avx512_requirement_flags(values: list[str] | tuple[str, ...] | set[str] | str | None) -> list[str]:
    if values is None:
        raw_values: list[str] = []
    elif isinstance(values, str):
        raw_values = values.split(",")
    else:
        raw_values = list(values)
    normalized = {
        AVX512_FLAG_ALIASES.get(item.strip().lower(), item.strip().lower())
        for item in raw_values
        if item and item.strip()
    }
    return [flag for flag in AVX512_FLAG_ORDER if flag in normalized]


def build_required_cpu_flags(
    simd_class: str,
    requires_popcnt: bool = False,
    requires_bmi2: bool = False,
    required_avx512_flags: list[str] | tuple[str, ...] | set[str] | str | None = None,
) -> list[str]:
    normalized_simd = normalize_simd_class(simd_class)
    flags: list[str] = [SIMD_CLASS_CLIENT_FLAGS[normalized_simd]]
    if requires_popcnt:
        flags.append("popcnt")
    if requires_bmi2:
        flags.append("bmi2")
    if normalized_simd == "avx512":
        for flag in normalize_avx512_requirement_flags(required_avx512_flags):
            if flag not in flags:
                flags.append(flag)
    return flags


def describe_requirements(
    simd_class: str,
    requires_popcnt: bool = False,
    requires_bmi2: bool = False,
    required_avx512_flags: list[str] | tuple[str, ...] | set[str] | str | None = None,
) -> list[str]:
    labels = [SIMD_CLASS_LABELS[normalize_simd_class(simd_class)]]
    if requires_popcnt:
        labels.append("POPCNT")
    if requires_bmi2:
        labels.append("BMI2")
    if normalize_simd_class(simd_class) == "avx512":
        labels.extend(AVX512_FLAG_LABELS[flag] for flag in normalize_avx512_requirement_flags(required_avx512_flags))
    return labels


def fairness_key_for_requirements(
    simd_class: str,
    requires_popcnt: bool = False,
    requires_bmi2: bool = False,
    required_avx512_flags: list[str] | tuple[str, ...] | set[str] | str | None = None,
) -> tuple[str, bool, bool]:
    normalized_simd = normalize_simd_class(simd_class)
    return (
        normalized_simd,
        bool(requires_popcnt),
        bool(requires_bmi2),
    )


def fairness_strength_key(fairness_key: tuple[str, bool, bool]) -> tuple[int, int, int]:
    simd_class, requires_popcnt, requires_bmi2 = fairness_key
    return (
        SIMD_CLASS_ORDER.index(normalize_simd_class(simd_class)),
        int(bool(requires_popcnt)),
        int(bool(requires_bmi2)),
    )


class EngineArtifact(Base):
    __tablename__ = "engine_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    engine_version_id: Mapped[int] = mapped_column(ForeignKey("engine_versions.id"))
    system_name: Mapped[str] = mapped_column(String(50), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default=sql_text("0"))
    simd_class: Mapped[str] = mapped_column(String(20), default="sse", server_default=sql_text("'sse'"))
    requires_popcnt: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_bmi2: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx512f: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx512bw: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx512dq: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx512vl: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    requires_avx512vnni: Mapped[bool] = mapped_column(default=False, server_default=sql_text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    engine_version: Mapped["EngineVersion"] = relationship(back_populates="artifacts")

    @property
    def simd_label(self) -> str:
        return SIMD_CLASS_LABELS[normalize_simd_class(self.simd_class)]

    @property
    def standard_flag_labels(self) -> list[str]:
        labels: list[str] = []
        if self.requires_popcnt:
            labels.append(STANDARD_FLAG_LABELS["popcnt"])
        if self.requires_bmi2:
            labels.append(STANDARD_FLAG_LABELS["bmi2"])
        return labels

    @property
    def required_avx512_flags(self) -> list[str]:
        if normalize_simd_class(self.simd_class) != "avx512":
            return []
        flags: list[str] = []
        if self.requires_avx512f:
            flags.append("avx512f")
        if self.requires_avx512bw:
            flags.append("avx512bw")
        if self.requires_avx512dq:
            flags.append("avx512dq")
        if self.requires_avx512vl:
            flags.append("avx512vl")
        if self.requires_avx512vnni:
            flags.append("avx512vnni")
        if "avx512f" not in flags:
            flags.insert(0, "avx512f")
        return [flag for flag in AVX512_FLAG_ORDER if flag in flags]

    @property
    def required_cpu_flags(self) -> list[str]:
        return build_required_cpu_flags(
            simd_class=self.simd_class,
            requires_popcnt=self.requires_popcnt,
            requires_bmi2=self.requires_bmi2,
            required_avx512_flags=self.required_avx512_flags,
        )

    @property
    def required_flag_labels(self) -> list[str]:
        return describe_requirements(
            simd_class=self.simd_class,
            requires_popcnt=self.requires_popcnt,
            requires_bmi2=self.requires_bmi2,
            required_avx512_flags=self.required_avx512_flags,
        )

    @property
    def fairness_key(self) -> tuple[str, bool, bool]:
        return fairness_key_for_requirements(
            simd_class=self.simd_class,
            requires_popcnt=self.requires_popcnt,
            requires_bmi2=self.requires_bmi2,
            required_avx512_flags=self.required_avx512_flags,
        )

    @property
    def runtime_label(self) -> str:
        flags = self.required_flag_labels
        if not flags:
            return self.system_name
        return f"{self.system_name} | {', '.join(flags)}"
