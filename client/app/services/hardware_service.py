from __future__ import annotations

import hashlib
import platform
import subprocess
import uuid
from pathlib import Path

RELEVANT_CPU_FLAGS = ("sse4", "avx", "avx2", "pext", "avx512")


def _read_linux_machine_id() -> str:
    machine_id_path = Path("/etc/machine-id")
    if machine_id_path.exists():
        value = machine_id_path.read_text().strip()
        if value:
            return value
    return ""


def build_machine_key() -> str:
    fingerprint = _read_linux_machine_id() or f"{uuid.getnode():012x}" or platform.node() or "local-machine"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"client-{digest}"


def build_machine_name() -> str:
    return platform.node() or "local-machine"


def detect_system_name() -> str:
    raw = (platform.system() or "").strip().lower()
    if raw.startswith("linux"):
        return "linux"
    if raw.startswith("windows"):
        return "windows"
    if raw.startswith("darwin") or raw.startswith("mac"):
        return "darwin"
    return raw or "linux"


def collect_cpu_flags() -> list[str]:
    detected_tokens: set[str] = set()
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(errors="ignore").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip().lower() == "flags":
                detected_tokens = {item.strip().lower() for item in value.split() if item.strip()}
                break

    if not detected_tokens:
        try:
            output = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.features", "machdep.cpu.leaf7_features"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            output = ""
        normalized = output.replace("\n", " ").replace(",", " ").lower()
        detected_tokens = {item.strip() for item in normalized.split() if item.strip()}

    relevant_flags: set[str] = set()
    if {"sse4", "sse4_1", "sse4_2"} & detected_tokens:
        relevant_flags.add("sse4")
    if "avx" in detected_tokens or "avx1.0" in detected_tokens:
        relevant_flags.add("avx")
    if "avx2" in detected_tokens:
        relevant_flags.add("avx2")
    if "pext" in detected_tokens or "bmi2" in detected_tokens:
        relevant_flags.add("pext")
    if any(token.startswith("avx512") for token in detected_tokens):
        relevant_flags.add("avx512")
    return [flag for flag in RELEVANT_CPU_FLAGS if flag in relevant_flags]
