from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import UploadFile


def sanitize_file_name(file_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip())
    return cleaned or "upload.dat"


def ensure_storage_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unique_target_path(target_dir: Path, file_name: str) -> Path:
    base_path = target_dir / file_name
    if not base_path.exists():
        return base_path

    stem = base_path.stem
    suffix = base_path.suffix
    counter = 2
    while True:
        candidate = target_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_upload(upload: UploadFile, target_dir: Path) -> tuple[str, str, str]:
    safe_name = sanitize_file_name(upload.filename or "upload.dat")
    ensure_storage_dir(target_dir)
    target_path = _unique_target_path(target_dir, safe_name)
    with target_path.open("wb") as handle:
        handle.write(upload.file.read())
    return target_path.name, str(target_path), sha256_for_file(target_path)
