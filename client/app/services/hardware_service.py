from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import uuid
from pathlib import Path

RELEVANT_CPU_FLAGS = ("sse4", "avx", "avx2", "pext", "avx512")


def _run_command(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""


def _read_linux_machine_id() -> str:
    machine_id_path = Path("/etc/machine-id")
    if machine_id_path.exists():
        value = machine_id_path.read_text().strip()
        if value:
            return value
    return ""


def build_machine_fingerprint() -> str:
    fingerprint = _read_linux_machine_id() or f"{uuid.getnode():012x}" or platform.node() or "local-machine"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"client-{digest}"


def build_machine_key() -> str:
    return build_machine_fingerprint()


def build_machine_name() -> str:
    return platform.node() or "local-machine"


def _is_wsl() -> bool:
    osrelease_path = Path("/proc/sys/kernel/osrelease")
    if not osrelease_path.exists():
        return False
    return "microsoft" in osrelease_path.read_text(errors="ignore").strip().lower()


def detect_system_name() -> str:
    raw = (platform.system() or "").strip().lower()
    if raw.startswith("linux"):
        return "linux"
    if raw.startswith("windows"):
        return "windows"
    if raw.startswith("darwin") or raw.startswith("mac"):
        return "darwin"
    return raw or "linux"


def _linux_cpuinfo_value(target_key: str) -> str:
    cpuinfo_path = Path("/proc/cpuinfo")
    if not cpuinfo_path.exists():
        return ""
    for line in cpuinfo_path.read_text(errors="ignore").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == target_key:
            normalized = value.strip()
            if normalized:
                return normalized
    return ""


def detect_cpu_name() -> str:
    system_name = detect_system_name()
    if system_name == "linux":
        return _linux_cpuinfo_value("model name") or platform.processor() or platform.machine() or "unknown cpu"
    if system_name == "darwin":
        return _run_command(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor() or platform.machine() or "unknown cpu"
    if system_name == "windows":
        output = _run_command(["wmic", "cpu", "get", "name"])
        lines = [line.strip() for line in output.splitlines() if line.strip() and line.strip().lower() != "name"]
        if lines:
            return lines[0]
    return platform.processor() or platform.machine() or "unknown cpu"


def _parse_size_to_mb(value: str, unit: str) -> int:
    normalized_unit = unit.strip().lower()
    amount = float(value)
    if normalized_unit in {"kb", "kib"}:
        return int(amount / 1024.0)
    if normalized_unit in {"mb", "mib"}:
        return int(amount)
    if normalized_unit in {"gb", "gib"}:
        return int(amount * 1024.0)
    if normalized_unit in {"tb", "tib"}:
        return int(amount * 1024.0 * 1024.0)
    return 0


def _parse_lshw_total_mb(text: str) -> int:
    for line in text.splitlines():
        stripped = line.strip().lower()
        if not stripped.startswith("size:"):
            continue
        match = re.search(r"size:\s*([0-9.]+)\s*([kmgt]i?b)", stripped, flags=re.IGNORECASE)
        if match:
            return _parse_size_to_mb(match.group(1), match.group(2))
    return 0


def detect_ram_total_mb() -> int:
    system_name = detect_system_name()
    if system_name == "linux" and _is_wsl():
        total_mb, _speed = _detect_windows_host_memory()
        if total_mb > 0:
            return total_mb
    if system_name == "linux":
        lshw_output = _run_command(["lshw", "-class", "memory"])
        total_mb = _parse_lshw_total_mb(lshw_output)
        if total_mb > 0:
            return total_mb
        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.exists():
            for line in meminfo_path.read_text(errors="ignore").splitlines():
                if not line.startswith("MemTotal:"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return max(0, int(parts[1]) // 1024)
        return 0
    if system_name == "darwin":
        value = _run_command(["sysctl", "-n", "hw.memsize"])
        if value.isdigit():
            return max(0, int(value) // (1024 * 1024))
        return 0
    if system_name == "windows":
        output = _run_command(["wmic", "computersystem", "get", "totalphysicalmemory"])
        lines = [line.strip() for line in output.splitlines() if line.strip() and line.strip().lower() != "totalphysicalmemory"]
        if lines and lines[0].isdigit():
            return max(0, int(lines[0]) // (1024 * 1024))
    return 0


def _parse_memory_speed_candidates(text: str) -> list[int]:
    speeds: list[int] = []
    for line in text.splitlines():
        lowered = line.strip().lower()
        if (
            "configured memory speed" not in lowered
            and "configuredclockspeed" not in lowered
            and "clock:" not in lowered
            and not lowered.startswith("speed")
            and " speed:" not in lowered
        ):
            continue
        match = re.search(r"(\d+)\s*(?:mt/s|mhz)?", line, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if value > 0:
                speeds.append(value)
    return speeds


def _detect_windows_host_memory() -> tuple[int, int | None]:
    json_commands = [
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,ConfiguredClockSpeed,Speed | ConvertTo-Json -Compress",
        ],
        [
            "pwsh.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,ConfiguredClockSpeed,Speed | ConvertTo-Json -Compress",
        ],
    ]
    for command in json_commands:
        output = _run_command(command)
        if not output:
            continue
        try:
            payload = json.loads(output)
        except Exception:
            continue
        rows = payload if isinstance(payload, list) else [payload]
        total_bytes = 0
        speed_candidates: list[int] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            capacity = str(row.get("Capacity") or "").strip()
            if capacity.isdigit():
                total_bytes += int(capacity)
            for key in ("ConfiguredClockSpeed", "Speed"):
                value = row.get(key)
                if value is None:
                    continue
                text_value = str(value).strip()
                if text_value.isdigit() and int(text_value) > 0:
                    speed_candidates.append(int(text_value))
        if total_bytes > 0:
            return max(0, total_bytes // (1024 * 1024)), (max(speed_candidates) if speed_candidates else None)

    total_commands = [
        ["powershell.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
        ["pwsh.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
    ]
    for command in total_commands:
        output = _run_command(command)
        if output.isdigit():
            return max(0, int(output) // (1024 * 1024)), None
    return 0, None


def detect_ram_speed_mt_s() -> int | None:
    system_name = detect_system_name()
    if system_name == "linux":
        if _is_wsl():
            _total_mb, speed = _detect_windows_host_memory()
            if speed:
                return speed
        output = _run_command(["dmidecode", "--type", "17"])
        speeds = _parse_memory_speed_candidates(output)
        if speeds:
            return max(speeds)
        lshw_output = _run_command(["lshw", "-class", "memory"])
        speeds = _parse_memory_speed_candidates(lshw_output)
        return max(speeds) if speeds else None
    if system_name == "darwin":
        output = _run_command(["system_profiler", "SPMemoryDataType"])
        speeds = _parse_memory_speed_candidates(output)
        return max(speeds) if speeds else None
    if system_name == "windows":
        output = _run_command(["wmic", "memorychip", "get", "speed"])
        speeds = [int(line.strip()) for line in output.splitlines() if line.strip().isdigit() and int(line.strip()) > 0]
        return max(speeds) if speeds else None
    return None


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
        output = _run_command(["sysctl", "-n", "machdep.cpu.features", "machdep.cpu.leaf7_features"])
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


def collect_hardware_snapshot() -> dict[str, object]:
    return {
        "machine_fingerprint": build_machine_fingerprint(),
        "machine_name": build_machine_name(),
        "system_name": detect_system_name(),
        "cpu_name": detect_cpu_name(),
        "ram_total_mb": detect_ram_total_mb(),
        "ram_speed_mt_s": detect_ram_speed_mt_s(),
        "cpu_flags": collect_cpu_flags(),
    }
