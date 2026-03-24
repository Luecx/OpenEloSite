from __future__ import annotations


SYZYGY_NONE = 0
SYZYGY_345 = 5
SYZYGY_6 = 6
SYZYGY_7 = 7
SYZYGY_PROBE_LIMITS = (SYZYGY_NONE, SYZYGY_345, SYZYGY_6, SYZYGY_7)

_LABELS = {
    SYZYGY_NONE: "Keine Tablebases",
    SYZYGY_345: "Syzygy 3-4-5",
    SYZYGY_6: "Syzygy 6",
    SYZYGY_7: "Syzygy 7",
}


def normalize_syzygy_probe_limit(value: int | str | None) -> int:
    if value is None:
        return SYZYGY_NONE
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"", "none", "0"}:
            return SYZYGY_NONE
        if raw in {"345", "3-4-5", "5", "syzygy 3-4-5"}:
            return SYZYGY_345
        if raw in {"6", "syzygy 6"}:
            return SYZYGY_6
        if raw in {"7", "syzygy 7"}:
            return SYZYGY_7
        value = int(raw)
    normalized = int(value)
    if normalized not in SYZYGY_PROBE_LIMITS:
        raise ValueError("ungueltige Syzygy-Stufe")
    return normalized


def syzygy_label(probe_limit: int | str | None) -> str:
    return _LABELS[normalize_syzygy_probe_limit(probe_limit)]


def client_supports_syzygy(client_max_pieces: int | str | None, required_probe_limit: int | str | None) -> bool:
    client_value = normalize_syzygy_probe_limit(client_max_pieces)
    required_value = normalize_syzygy_probe_limit(required_probe_limit)
    if required_value == SYZYGY_NONE:
        return True
    return client_value >= required_value
