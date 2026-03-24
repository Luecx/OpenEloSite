from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.api.server_client import ServerClient


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    return cleaned.strip("-") or "item"


@dataclass(frozen=True, slots=True)
class ResolvedBook:
    path: Path
    status: str


class WorkspaceService:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.books_dir = self.root / "books"
        self.bench_dir = self.root / "bench"
        self.engine1_dir = self.root / "engine1"
        self.engine2_dir = self.root / "engine2"
        self.fastchess_dir = self.root / "fast-chess"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.bench_dir.mkdir(parents=True, exist_ok=True)
        self.engine1_dir.mkdir(parents=True, exist_ok=True)
        self.engine2_dir.mkdir(parents=True, exist_ok=True)

    def cleanup_for_job(self) -> None:
        self.ensure_layout()
        for entry in self.root.iterdir():
            if entry.name in {"books", "bench", "fast-chess"}:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        self.engine1_dir.mkdir(parents=True, exist_ok=True)
        self.engine2_dir.mkdir(parents=True, exist_ok=True)

    def sha256_for_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def detect_book_format(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pgn":
            return "pgn"
        if suffix == ".epd":
            return "epd"

        with path.open("r", errors="ignore") as handle:
            sample = handle.read(4096)
        for line in sample.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("["):
                return "pgn"
            fields = stripped.split()
            if len(fields) >= 4 and "/" in fields[0] and fields[1] in {"w", "b"}:
                return "epd"
            break
        raise RuntimeError(f"Opening-Book-Format konnte nicht erkannt werden: {path}")

    def _cached_book(self, file_name: str, expected_hash: str) -> Path | None:
        target_name = Path(file_name).name if file_name else ""
        if target_name:
            exact_path = self.books_dir / target_name
            if exact_path.is_file():
                try:
                    if self.sha256_for_file(exact_path) == expected_hash:
                        return exact_path
                except OSError:
                    pass

        for candidate in sorted(self.books_dir.iterdir()):
            if not candidate.is_file():
                continue
            try:
                if self.sha256_for_file(candidate) == expected_hash:
                    return candidate
            except OSError:
                continue
        return None

    def _target_book_path(self, book: dict, headers: dict[str, str] | None = None) -> Path:
        file_name = (book.get("file_name") or "").strip()
        if not file_name and headers is not None:
            file_name = self._filename_from_headers(headers)
        if not file_name:
            file_name = _safe_name(book.get("name") or "book")
        return self.books_dir / Path(file_name).name

    def _promote_cached_book(self, cached: Path, target_path: Path) -> Path:
        if cached == target_path:
            return cached
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        cached.replace(target_path)
        return target_path

    def _filename_from_headers(self, headers: dict[str, str]) -> str:
        content_disposition = headers.get("content_disposition", "")
        match = re.search(r'filename="([^"]+)"', content_disposition)
        if match:
            return Path(match.group(1)).name
        return ""

    def ensure_artifact(self, artifact: dict, target_dir: Path, server: ServerClient) -> Path:
        file_name = (artifact.get("file_name") or "").strip()
        expected_hash = (artifact.get("hash") or "").strip()
        source = (artifact.get("source") or "").strip()
        if not file_name:
            raise RuntimeError("Artifact-Dateiname fehlt im Job.")
        if not source:
            raise RuntimeError("Artifact-Quelle fehlt im Job.")

        target_dir.mkdir(parents=True, exist_ok=True)
        temp_path = target_dir / f"{_safe_name(file_name)}.tmp"
        headers = server.download(source, temp_path)
        downloaded_name = self._filename_from_headers(headers)
        final_name = Path(downloaded_name).name if downloaded_name else Path(file_name).name
        final_path = target_dir / final_name
        temp_path.replace(final_path)
        if expected_hash:
            actual_hash = self.sha256_for_file(final_path)
            if actual_hash != expected_hash:
                final_path.unlink(missing_ok=True)
                raise RuntimeError(f"Artifact-Hash stimmt nicht. Erwartet {expected_hash}, erhalten {actual_hash}")
        final_path.chmod(0o755)
        return final_path

    def refresh_bench_artifact(self, artifact: dict, server: ServerClient) -> Path:
        self.bench_dir.mkdir(parents=True, exist_ok=True)
        for entry in self.bench_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        return self.ensure_artifact(artifact, self.bench_dir, server)

    def ensure_book(self, book: dict | None, server: ServerClient) -> ResolvedBook | None:
        if not book:
            return None

        file_name = (book.get("file_name") or "").strip()
        expected_hash = (book.get("hash") or "").strip()
        source = (book.get("source") or "").strip()
        if not source:
            raise RuntimeError("Opening-Book-Quelle fehlt im Job.")

        if expected_hash:
            cached = self._cached_book(file_name, expected_hash)
            if cached is not None:
                target_path = self._target_book_path(book)
                cached = self._promote_cached_book(cached, target_path)
                return ResolvedBook(path=cached, status="using existing")

        target_path = self._target_book_path(book)
        temp_path = self.books_dir / f"{target_path.name}.tmp"
        headers = server.download(source, temp_path)
        final_path = self._target_book_path(book, headers=headers)
        if final_path.exists():
            final_path.unlink(missing_ok=True)
        temp_path.replace(final_path)

        if expected_hash:
            actual_hash = self.sha256_for_file(final_path)
            if actual_hash != expected_hash:
                final_path.unlink(missing_ok=True)
                raise RuntimeError(f"Book-Hash stimmt nicht. Erwartet {expected_hash}, erhalten {actual_hash}")

        return ResolvedBook(path=final_path, status="downloaded")
