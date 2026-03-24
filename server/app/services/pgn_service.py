from __future__ import annotations

import re


_HEADER_PATTERN = re.compile(r'^\[(\w+) "([^"]*)"\]$', flags=re.MULTILINE)
_SCALE_FACTOR_PATTERN = re.compile(r'^\[ScaleFactor "[^"]*"\]\n?', flags=re.MULTILINE)


def split_pgn_blocks(pgn_text: str) -> list[str]:
    normalized = (pgn_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    blocks: list[str] = []
    current: list[str] = []
    for line in normalized.split("\n"):
        if line.startswith("[Event ") and current:
            blocks.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def join_pgn_blocks(blocks: list[str]) -> str:
    return "\n\n".join(block.strip() for block in blocks if (block or "").strip())


def parse_headers(pgn_block: str) -> dict[str, str]:
    return {key: value for key, value in _HEADER_PATTERN.findall(pgn_block or "")}


def parse_time_control(tc_value: str | None) -> tuple[int | None, float | None, float]:
    if not tc_value:
        return None, None, 0.0
    raw_value = tc_value.strip()
    moves: int | None = None
    control = raw_value
    if "/" in raw_value:
        moves_text, _, tail = raw_value.partition("/")
        try:
            moves = int(moves_text.strip())
            control = tail.strip()
        except ValueError:
            control = raw_value

    base_text, plus, increment_text = control.partition("+")
    try:
        base_seconds = float(base_text.strip())
    except ValueError:
        return moves, None, 0.0

    try:
        increment_seconds = float(increment_text.strip()) if plus else 0.0
    except ValueError:
        increment_seconds = 0.0
    return moves, base_seconds, increment_seconds


def compute_scale_factor(target_base_seconds: int | float | None, actual_time_control: str | None) -> float | None:
    if target_base_seconds is None:
        return None
    _, actual_base_seconds, _ = parse_time_control(actual_time_control)
    if actual_base_seconds is None or actual_base_seconds <= 0:
        return None
    return float(target_base_seconds) / float(actual_base_seconds)


def inject_scale_factor_header(pgn_block: str, scale_factor: float | None) -> str:
    if not pgn_block.strip() or scale_factor is None:
        return pgn_block
    separator = pgn_block.find("\n\n")
    if separator == -1:
        return pgn_block

    header_section = pgn_block[:separator]
    body_section = pgn_block[separator:]
    header_section = _SCALE_FACTOR_PATTERN.sub("", header_section).rstrip("\n")
    return f'{header_section}\n[ScaleFactor "{scale_factor:.12g}"]{body_section}'


def annotate_pgn_with_scale_factor(pgn_text: str, target_base_seconds: int | float | None) -> str:
    blocks = split_pgn_blocks(pgn_text)
    if not blocks:
        return pgn_text or ""
    annotated_blocks = []
    for block in blocks:
        headers = parse_headers(block)
        factor = compute_scale_factor(target_base_seconds, headers.get("TimeControl"))
        annotated_blocks.append(inject_scale_factor_header(block, factor))
    return join_pgn_blocks(annotated_blocks)
