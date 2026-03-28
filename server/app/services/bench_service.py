from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

from app.db.repositories import client_repository
from app.services.storage_service import sha256_for_file


BENCH_ROOT = Path(__file__).resolve().parents[2] / "data" / "bench"
BENCH_MANIFEST_PATH = BENCH_ROOT / "manifest.json"


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip())
    return normalized.strip("-") or "bench"


def _normalize_flags(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = values.split(",")
    else:
        raw_values = list(values)
    return client_repository.normalize_cpu_flags(raw_values)


def _artifact_id(relative_path: str, manifest_id: str | None = None) -> str:
    if manifest_id and manifest_id.strip():
        return _safe_id(manifest_id)
    digest = sha256(relative_path.encode("utf-8")).hexdigest()[:12]
    return _safe_id(f"bench-{digest}")


def _default_manifest() -> dict:
    return {
        "artifacts": [],
    }


def _normalize_manifest_priorities(manifest: dict) -> dict:
    raw_artifacts = [item for item in manifest.get("artifacts", []) if isinstance(item, dict)]
    for index, entry in enumerate(raw_artifacts, start=1):
        entry["priority"] = index
    manifest["artifacts"] = raw_artifacts
    return manifest


def _sort_manifest_by_priority(manifest: dict) -> dict:
    raw_artifacts = [item for item in manifest.get("artifacts", []) if isinstance(item, dict)]
    raw_artifacts.sort(key=lambda item: (int(item.get("priority") or 0), str(item.get("id") or item.get("path") or item.get("file_name") or "")))
    for index, entry in enumerate(raw_artifacts, start=1):
        entry["priority"] = index
    manifest["artifacts"] = raw_artifacts
    return manifest


def _load_manifest() -> dict:
    if not BENCH_MANIFEST_PATH.exists():
        return _default_manifest()

    raw_data = json.loads(BENCH_MANIFEST_PATH.read_text(encoding="utf-8"))
    if isinstance(raw_data, list):
        manifest = {
            "artifacts": [item for item in raw_data if isinstance(item, dict)],
        }
        return _sort_manifest_by_priority(manifest)

    if not isinstance(raw_data, dict):
        raise RuntimeError("Bench-Manifest muss ein Objekt sein.")

    inherited_reference_nps = max(0, int(raw_data.get("reference_nps") or 0))
    raw_artifacts = [item for item in raw_data.get("artifacts", []) if isinstance(item, dict)]
    for entry in raw_artifacts:
        if int(entry.get("reference_nps") or 0) <= 0 and inherited_reference_nps > 0:
            entry["reference_nps"] = inherited_reference_nps
    manifest = {
        "artifacts": raw_artifacts,
    }
    return _sort_manifest_by_priority(manifest)


def _save_manifest(manifest: dict) -> None:
    BENCH_ROOT.mkdir(parents=True, exist_ok=True)
    _normalize_manifest_priorities(manifest)
    BENCH_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def list_bench_artifacts() -> list[dict]:
    manifest = _load_manifest()
    artifacts: list[dict] = []
    for entry in manifest["artifacts"]:
        relative_path = (entry.get("path") or entry.get("file_name") or "").strip()
        if not relative_path:
            continue
        file_path = (BENCH_ROOT / relative_path).resolve()
        if not file_path.is_file():
            continue
        system_name = (entry.get("system_name") or "").strip().lower()
        if not system_name:
            continue
        required_cpu_flags = _normalize_flags(entry.get("required_cpu_flags"))
        relative_name = file_path.relative_to(BENCH_ROOT).as_posix()
        artifacts.append(
            {
                "id": _artifact_id(relative_name, entry.get("id")),
                "file_name": file_path.name,
                "relative_path": relative_name,
                "path": file_path,
                "system_name": system_name,
                "required_cpu_flags": required_cpu_flags,
                "priority": max(1, int(entry.get("priority") or 0)),
                "reference_nps": max(0, int(entry.get("reference_nps") or 0)),
                "content_hash": sha256_for_file(file_path),
            }
        )
    return sorted(artifacts, key=lambda item: (int(item.get("priority") or 0), item["id"]))


def get_bench_artifact(artifact_id: str) -> dict | None:
    normalized_id = _safe_id(artifact_id)
    for artifact in list_bench_artifacts():
        if artifact["id"] == normalized_id:
            return artifact
    return None


def create_bench_artifact(
    file_name: str,
    file_path: str,
    content_hash: str,
    system_name: str,
    required_cpu_flags: list[str] | str | None,
    reference_nps: int,
) -> dict:
    manifest = _load_manifest()
    next_priority = len(manifest["artifacts"]) + 1
    relative_path = Path(file_path).resolve().relative_to(BENCH_ROOT).as_posix()
    entry = {
        "id": _artifact_id(relative_path),
        "file_name": file_name.strip(),
        "path": relative_path,
        "system_name": (system_name or "").strip().lower(),
        "required_cpu_flags": _normalize_flags(required_cpu_flags),
        "reference_nps": max(0, int(reference_nps)),
        "priority": next_priority,
        "content_hash": content_hash.strip(),
    }
    manifest["artifacts"] = [
        item for item in manifest["artifacts"]
        if _artifact_id((item.get("path") or item.get("file_name") or "").strip(), item.get("id")) != entry["id"]
    ]
    manifest["artifacts"].append(entry)
    _save_manifest(manifest)
    return get_bench_artifact(entry["id"]) or entry


def update_bench_artifact(
    artifact_id: str,
    system_name: str,
    required_cpu_flags: list[str] | str | None,
    reference_nps: int,
) -> dict | None:
    normalized_id = _safe_id(artifact_id)
    manifest = _load_manifest()
    updated = False
    for entry in manifest["artifacts"]:
        entry_id = _artifact_id((entry.get("path") or entry.get("file_name") or "").strip(), entry.get("id"))
        if entry_id != normalized_id:
            continue
        entry["system_name"] = (system_name or "").strip().lower()
        entry["required_cpu_flags"] = _normalize_flags(required_cpu_flags)
        entry["reference_nps"] = max(0, int(reference_nps))
        updated = True
        break
    if not updated:
        return None
    _save_manifest(manifest)
    return get_bench_artifact(normalized_id)


def delete_bench_artifact(artifact_id: str) -> bool:
    normalized_id = _safe_id(artifact_id)
    manifest = _load_manifest()
    remaining_artifacts: list[dict] = []
    deleted_path: Path | None = None
    deleted = False
    for entry in manifest["artifacts"]:
        entry_id = _artifact_id((entry.get("path") or entry.get("file_name") or "").strip(), entry.get("id"))
        if entry_id == normalized_id:
            relative_path = (entry.get("path") or entry.get("file_name") or "").strip()
            if relative_path:
                deleted_path = (BENCH_ROOT / relative_path).resolve()
            deleted = True
            continue
        remaining_artifacts.append(entry)
    if not deleted:
        return False
    manifest["artifacts"] = remaining_artifacts
    _save_manifest(manifest)
    if deleted_path is not None and deleted_path.exists():
        deleted_path.unlink(missing_ok=True)
    return True


def pick_compatible_bench_artifact(system_name: str, cpu_flags: list[str] | str | set[str] | None) -> dict | None:
    normalized_system = (system_name or "").strip().lower()
    client_flags = client_repository.parse_cpu_flags(
        cpu_flags if isinstance(cpu_flags, str) else client_repository.serialize_cpu_flags(cpu_flags)
    )
    for artifact in list_bench_artifacts():
        if artifact["system_name"] != normalized_system:
            continue
        required_flags = set(artifact["required_cpu_flags"])
        if not required_flags.issubset(client_flags):
            continue
        return artifact
    return None


def move_bench_artifact_priority(artifact_id: str, direction: str) -> dict | None:
    normalized_id = _safe_id(artifact_id)
    manifest = _load_manifest()
    artifacts = manifest["artifacts"]
    artifact_ids = [_artifact_id((item.get("path") or item.get("file_name") or "").strip(), item.get("id")) for item in artifacts]
    if normalized_id not in artifact_ids:
        return None
    current_index = artifact_ids.index(normalized_id)
    if direction == "up":
        swap_index = current_index - 1
    elif direction == "down":
        swap_index = current_index + 1
    else:
        return get_bench_artifact(normalized_id)
    if swap_index < 0 or swap_index >= len(artifacts):
        return get_bench_artifact(normalized_id)
    artifacts[current_index], artifacts[swap_index] = artifacts[swap_index], artifacts[current_index]
    _save_manifest(manifest)
    return get_bench_artifact(normalized_id)


def build_bench_payload(system_name: str, cpu_flags: list[str] | str | set[str] | None) -> dict | None:
    artifact = pick_compatible_bench_artifact(system_name, cpu_flags)
    if artifact is None:
        return None
    reference_nps = max(0, int(artifact.get("reference_nps") or 0))
    if reference_nps <= 0:
        return None
    return {
        "id": artifact["id"],
        "file_name": artifact["file_name"],
        "hash": artifact["content_hash"],
        "system_name": artifact["system_name"],
        "required_cpu_flags": artifact["required_cpu_flags"],
        "priority": artifact["priority"],
        "reference_nps": reference_nps,
        "source": f"/api/client/bench/{artifact['id']}",
    }
