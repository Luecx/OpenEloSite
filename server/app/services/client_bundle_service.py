from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT_SOURCE_ROOT = REPO_ROOT / "client"
BUNDLE_ROOT = Path(__file__).resolve().parents[2] / "data" / "client-bundles"
MANIFEST_PATH = BUNDLE_ROOT / "manifest.json"
_FIXED_ZIP_DATETIME = (2024, 1, 1, 0, 0, 0)


def _should_include(relative_path: Path) -> bool:
    if not relative_path.parts:
        return False
    if any(part in {"__pycache__", ".pytest_cache"} for part in relative_path.parts):
        return False
    if relative_path.name.endswith((".pyc", ".pyo", "~")):
        return False
    return True


def _iter_source_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Client source directory not found: {root}")
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if not _should_include(relative_path):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _iter_source_files(root):
        relative_path = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _bundle_name(bundle_hash: str) -> str:
    return f"client-{bundle_hash[:12]}.zip"


def _load_manifest() -> dict | None:
    if not MANIFEST_PATH.exists():
        return None
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _write_manifest(payload: dict) -> None:
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _cleanup_old_bundles(current_name: str) -> None:
    if not BUNDLE_ROOT.exists():
        return
    for candidate in BUNDLE_ROOT.glob("client-*.zip"):
        if candidate.name == current_name:
            continue
        candidate.unlink(missing_ok=True)


def _build_bundle(bundle_path: Path) -> None:
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path in _iter_source_files(CLIENT_SOURCE_ROOT):
            relative_path = source_path.relative_to(CLIENT_SOURCE_ROOT)
            zip_info = zipfile.ZipInfo((Path("client") / relative_path).as_posix())
            zip_info.date_time = _FIXED_ZIP_DATETIME
            zip_info.compress_type = zipfile.ZIP_DEFLATED
            zip_info.external_attr = 0o644 << 16
            archive.writestr(zip_info, source_path.read_bytes())


def ensure_client_bundle() -> dict:
    bundle_hash = _tree_hash(CLIENT_SOURCE_ROOT)
    file_name = _bundle_name(bundle_hash)
    bundle_path = BUNDLE_ROOT / file_name
    manifest = _load_manifest()

    if manifest and manifest.get("hash") == bundle_hash and manifest.get("file_name") == file_name and bundle_path.is_file():
        return {
            "hash": bundle_hash,
            "file_name": file_name,
            "path": bundle_path,
            "built_at": manifest.get("built_at"),
        }

    _build_bundle(bundle_path)
    built_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _write_manifest(
        {
            "hash": bundle_hash,
            "file_name": file_name,
            "built_at": built_at,
        }
    )
    _cleanup_old_bundles(file_name)
    return {
        "hash": bundle_hash,
        "file_name": file_name,
        "path": bundle_path,
        "built_at": built_at,
    }
