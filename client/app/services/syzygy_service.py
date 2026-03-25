from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


SYZYGY_NONE = 0
SYZYGY_345 = 5
SYZYGY_6 = 6
SYZYGY_7 = 7
_SYZYGY_EXTENSIONS = {".rtbw", ".rtbz"}
_PIECE_PATTERN = re.compile(r"[KQRBNP]")


def syzygy_label(probe_limit: int | str | None) -> str:
    normalized = normalize_syzygy_probe_limit(probe_limit)
    if normalized == SYZYGY_345:
        return "Syzygy 3-4-5"
    if normalized == SYZYGY_6:
        return "Syzygy 6"
    if normalized == SYZYGY_7:
        return "Syzygy 7"
    return "No tablebase"


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
    if normalized not in {SYZYGY_NONE, SYZYGY_345, SYZYGY_6, SYZYGY_7}:
        raise ValueError("invalid Syzygy level")
    return normalized


@dataclass(frozen=True, slots=True)
class SyzygyLayout:
    root: Path | None
    paths_345: tuple[Path, ...]
    paths_6: tuple[Path, ...]
    paths_7: tuple[Path, ...]

    @property
    def max_pieces(self) -> int:
        if self.paths_345 and self.paths_6 and self.paths_7:
            return SYZYGY_7
        if self.paths_345 and self.paths_6:
            return SYZYGY_6
        if self.paths_345:
            return SYZYGY_345
        return SYZYGY_NONE

    @property
    def label(self) -> str:
        return syzygy_label(self.max_pieces)

    def directories_for_probe_limit(self, probe_limit: int | str | None) -> list[Path]:
        normalized = normalize_syzygy_probe_limit(probe_limit)
        if normalized == SYZYGY_NONE:
            return []
        if normalized == SYZYGY_345 and self.max_pieces < SYZYGY_345:
            raise RuntimeError("Syzygy 3-4-5 was requested, but is not available on this client.")
        if normalized == SYZYGY_6 and self.max_pieces < SYZYGY_6:
            raise RuntimeError("Syzygy 6 was requested, but is not available on this client.")
        if normalized == SYZYGY_7 and self.max_pieces < SYZYGY_7:
            raise RuntimeError("Syzygy 7 was requested, but is not available on this client.")

        paths: set[Path] = set(self.paths_345)
        if normalized >= SYZYGY_6:
            paths.update(self.paths_6)
        if normalized >= SYZYGY_7:
            paths.update(self.paths_7)
        return sorted(paths)

    def joined_path_for_probe_limit(self, probe_limit: int | str | None) -> str:
        return os.pathsep.join(str(path) for path in self.directories_for_probe_limit(probe_limit))


def inspect_syzygy_root(root: Path | None) -> SyzygyLayout:
    if root is None:
        return SyzygyLayout(root=None, paths_345=(), paths_6=(), paths_7=())

    resolved_root = root.expanduser().resolve()
    if not resolved_root.exists():
        raise ValueError(f"Syzygy root not found: {resolved_root}")
    if not resolved_root.is_dir():
        raise ValueError(f"Syzygy root is not a directory: {resolved_root}")

    exact_group_paths: dict[int, set[Path]] = {
        SYZYGY_345: set(),
        SYZYGY_6: set(),
        SYZYGY_7: set(),
    }
    for candidate in _iter_scan_files(resolved_root):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in _SYZYGY_EXTENSIONS:
            continue
        men_count = _count_syzygy_men(candidate.stem)
        if 3 <= men_count <= 5:
            exact_group_paths[SYZYGY_345].add(candidate.parent)
        elif men_count == 6:
            exact_group_paths[SYZYGY_6].add(candidate.parent)
        elif men_count == 7:
            exact_group_paths[SYZYGY_7].add(candidate.parent)

    return SyzygyLayout(
        root=resolved_root,
        paths_345=tuple(sorted(exact_group_paths[SYZYGY_345])),
        paths_6=tuple(sorted(exact_group_paths[SYZYGY_6])),
        paths_7=tuple(sorted(exact_group_paths[SYZYGY_7])),
    )


def _count_syzygy_men(stem: str) -> int:
    return len(_PIECE_PATTERN.findall((stem or "").upper()))


def _iter_scan_files(root: Path):
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        current_dir, depth = pending.pop()
        for entry in current_dir.iterdir():
            if entry.is_dir():
                if depth < 2:
                    pending.append((entry, depth + 1))
                continue
            yield entry
