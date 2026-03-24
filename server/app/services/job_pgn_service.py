from __future__ import annotations

import base64
import io
from pathlib import Path
import zipfile

from app.db.models.match import Match
from app.db.models.match_job import MatchJob
from app.services.pgn_service import annotate_pgn_with_scale_factor
from app.services.pgn_service import join_pgn_blocks


_PGN_ROOT = Path(__file__).resolve().parents[2] / "data" / "job-pgns"


def _job_zip_path(job_id: int) -> Path:
    shard = f"{int(job_id) // 1000:05d}"
    return _PGN_ROOT / shard / f"job-{int(job_id)}.pgn.zip"


def store_job_pgn_zip(job_id: int, pgn_zip_base64: str) -> str | None:
    encoded = (pgn_zip_base64 or "").strip()
    if not encoded:
        return None
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as error:  # pragma: no cover - defensive
        raise ValueError("Ungueltige PGN-ZIP-Daten") from error

    target_path = _job_zip_path(job_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    return str(target_path)


def get_job_pgn_zip_path(job: MatchJob) -> Path | None:
    path_text = (job.pgn_zip_path or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_file():
        return None
    return path


def delete_job_pgn_zip(job: MatchJob) -> None:
    path = get_job_pgn_zip_path(job)
    if path is None:
        return
    path.unlink(missing_ok=True)


def read_job_pgn_text(job: MatchJob) -> str:
    path = get_job_pgn_zip_path(job)
    if path is None:
        return ""
    with zipfile.ZipFile(path, "r") as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if not members:
            return ""
        with archive.open(members[0], "r") as handle:
            return handle.read().decode("utf-8", errors="ignore")


def build_match_pgn_archive(match: Match, jobs: list[MatchJob]) -> bytes:
    buffer = io.BytesIO()
    folder_name = f"match-{match.id}"
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for job in jobs:
            path = get_job_pgn_zip_path(job)
            if path is None:
                continue
            archive.writestr(f"{folder_name}/{path.name}", path.read_bytes())
    return buffer.getvalue()


def build_annotated_match_pgn_text(match: Match, jobs: list[MatchJob]) -> str:
    target_base_seconds = match.rating_list.time_control_base_seconds if match.rating_list else None
    return join_pgn_blocks(
        [
            annotate_pgn_with_scale_factor(read_job_pgn_text(job), target_base_seconds)
            for job in jobs
            if get_job_pgn_zip_path(job) is not None
        ]
    )
