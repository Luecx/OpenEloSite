from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from app.api.server_client import ServerClient


CLIENT_ROOT = Path(__file__).resolve().parents[2]


def _should_include(relative_path: Path) -> bool:
    if not relative_path.parts:
        return False
    if any(part in {"__pycache__", ".pytest_cache"} for part in relative_path.parts):
        return False
    if relative_path.name.endswith((".pyc", ".pyo", "~")):
        return False
    return True


def _iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if not _should_include(relative_path):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def compute_client_bundle_hash(root: Path | None = None) -> str:
    source_root = (root or CLIENT_ROOT).resolve()
    digest = hashlib.sha256()
    for path in _iter_source_files(source_root):
        relative_path = path.relative_to(source_root).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _sync_client_tree(source_root: Path, target_root: Path) -> None:
    expected_files = {path.relative_to(source_root) for path in _iter_source_files(source_root)}

    for source_path in _iter_source_files(source_root):
        relative_path = source_path.relative_to(source_root)
        target_path = target_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f"{target_path.name}.update-tmp")
        shutil.copy2(source_path, temp_path)
        os.replace(temp_path, target_path)

    for current_path in sorted(target_root.rglob("*"), reverse=True):
        relative_path = current_path.relative_to(target_root)
        if not _should_include(relative_path):
            continue
        if current_path.is_file() and relative_path not in expected_files:
            current_path.unlink(missing_ok=True)

    for current_path in sorted(target_root.rglob("*"), reverse=True):
        if current_path.is_dir():
            try:
                current_path.rmdir()
            except OSError:
                pass


def ensure_client_bundle_current(server: ServerClient, console) -> str:
    local_hash = compute_client_bundle_hash(CLIENT_ROOT)
    metadata = server.get_json("/api/client/bundle/meta")
    remote_hash = str(metadata.get("hash") or "").strip()
    source = str(metadata.get("source") or "").strip()
    if not remote_hash:
        raise RuntimeError("Server did not provide a client bundle hash.")
    if not source:
        raise RuntimeError("Server did not provide a client bundle source.")

    if local_hash == remote_hash:
        console.section(
            "INIT",
            [
                ("Status", "current"),
                ("Bundle Hash", local_hash[:12]),
            ],
            subtitle="Client Bundle",
        )
        return local_hash

    console.section(
        "INIT",
        [
            ("Status", "updating"),
            ("Local Hash", local_hash[:12]),
            ("Remote Hash", remote_hash[:12]),
        ],
        subtitle="Client Bundle",
    )

    with tempfile.TemporaryDirectory(prefix="client-update-", dir=str(CLIENT_ROOT.parent)) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        bundle_path = temp_dir / "client-bundle.zip"
        extract_root = temp_dir / "extract"
        server.download(source, bundle_path)
        with zipfile.ZipFile(bundle_path, "r") as archive:
            archive.extractall(extract_root)
        extracted_client_root = extract_root / "client"
        if not extracted_client_root.is_dir():
            raise RuntimeError("Downloaded client bundle is invalid.")
        extracted_hash = compute_client_bundle_hash(extracted_client_root)
        if extracted_hash != remote_hash:
            raise RuntimeError("Downloaded client bundle hash mismatch.")
        _sync_client_tree(extracted_client_root, CLIENT_ROOT)

    final_hash = compute_client_bundle_hash(CLIENT_ROOT)
    if final_hash != remote_hash:
        raise RuntimeError("Client bundle verification failed after update.")

    console.status("INIT", f"Client bundle updated to {remote_hash[:12]}. Restarting ...")
    os.execv(sys.executable, [sys.executable, *sys.argv])
    raise RuntimeError("Client restart failed after update.")
