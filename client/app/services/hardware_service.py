from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import uuid
from pathlib import Path

RELEVANT_CPU_FLAGS = (
    "sse",
    "sse2",
    "sse3",
    "ssse3",
    "sse41",
    "sse42",
    "popcnt",
    "avx",
    "avx2",
    "bmi2",
    "avx512f",
    "avx512bw",
    "avx512dq",
    "avx512vl",
    "avx512vnni",
)


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


def _linux_cpuinfo_int(target_key: str) -> int | None:
    value = _linux_cpuinfo_value(target_key)
    if not value:
        return None
    match = re.search(r"\d+", value)
    if not match:
        return None
    return int(match.group(0))


def _is_amd_vendor() -> bool:
    vendor = _linux_cpuinfo_value("vendor_id").strip().lower()
    return vendor == "authenticamd"


def _is_probable_zen2(cpu_name: str) -> bool:
    normalized_name = cpu_name.strip().lower()
    if not normalized_name or "amd" not in normalized_name:
        return False

    family = _linux_cpuinfo_int("cpu family")
    model = _linux_cpuinfo_int("model")
    if _is_amd_vendor() and family == 23 and model is not None:
        zen2_models = {
            24,
            49,
            68,
            71,
            96,
            104,
            113,
            144,
            160,
        }
        if model in zen2_models:
            return True

    explicit_patterns = (
        r"ryzen\s+threadripper\s+39\d{2}",
        r"epyc\s+7\d{2}2",
        r"ryzen\s+[3579]\s+4\d{3}(?:u|h|hs)?",
        r"ryzen\s+[3579]\s+(3600|3700|3800|3900|3950)\b",
        r"ryzen\s+[3579]\s+3\d{3}x\b",
        r"ryzen\s+9\s+3900xt\b",
        r"ryzen\s+9\s+3950x\b",
        r"ryzen\s+7\s+3800xt\b",
        r"ryzen\s+7\s+3700x\b",
        r"ryzen\s+5\s+3600xt\b",
        r"ryzen\s+5\s+3600x\b",
        r"ryzen\s+5\s+3600\b",
    )
    return any(re.search(pattern, normalized_name) for pattern in explicit_patterns)


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
    current_is_memory_root = False
    current_is_bank = False
    memory_root_total_mb = 0
    bank_total_mb = 0

    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped:
            continue
        if stripped.startswith("*-"):
            current_is_memory_root = stripped.startswith("*-memory")
            current_is_bank = stripped.startswith("*-bank")
            continue
        if lowered.startswith("description:"):
            description = lowered.split(":", 1)[1].strip()
            if "system memory" in description:
                current_is_memory_root = True
                current_is_bank = False
            elif "bank" in description or "memory device" in description or "dimm" in description:
                current_is_bank = True
                current_is_memory_root = False
            continue
        if not lowered.startswith("size:"):
            continue
        match = re.search(r"size:\s*([0-9.]+)\s*([kmgt]i?b)", lowered, flags=re.IGNORECASE)
        if not match:
            continue
        size_mb = _parse_size_to_mb(match.group(1), match.group(2))
        if size_mb <= 0:
            continue
        if current_is_memory_root:
            memory_root_total_mb = max(memory_root_total_mb, size_mb)
        elif current_is_bank:
            bank_total_mb += size_mb

    if memory_root_total_mb > 0:
        return memory_root_total_mb
    if bank_total_mb > 0:
        return bank_total_mb
    return 0


def _read_linux_meminfo_total_mb() -> int:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return 0
    for line in meminfo_path.read_text(errors="ignore").splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return max(0, int(parts[1]) // 1024)
    return 0


def detect_ram_total_mb() -> int:
    system_name = detect_system_name()
    if system_name == "linux" and _is_wsl():
        total_mb, _speed = _detect_windows_host_memory()
        if total_mb > 0:
            return total_mb
    if system_name == "linux":
        meminfo_total_mb = _read_linux_meminfo_total_mb()
        lshw_output = _run_command(["lshw", "-class", "memory"])
        lshw_total_mb = _parse_lshw_total_mb(lshw_output)
        return max(meminfo_total_mb, lshw_total_mb)
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


def _parse_feature_tokens(text: str) -> set[str]:
    normalized = text.replace("\n", " ").replace(",", " ").lower()
    return {item.strip() for item in normalized.split() if item.strip()}


def _collect_detected_cpu_tokens() -> set[str]:
    detected_tokens: set[str] = set()
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(errors="ignore").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip().lower()
            if normalized_key == "flags":
                detected_tokens.update(_parse_feature_tokens(value))
            elif normalized_key == "features":
                detected_tokens.update(_parse_feature_tokens(value))

    if detect_system_name() == "linux":
        lscpu_output = _run_command(["lscpu"])
        for line in lscpu_output.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip().lower()
            if normalized_key in {"flags", "features"}:
                detected_tokens.update(_parse_feature_tokens(value))

    if not detected_tokens:
        output = _run_command(["sysctl", "-n", "machdep.cpu.features", "machdep.cpu.leaf7_features"])
        detected_tokens = _parse_feature_tokens(output)

    return detected_tokens


def _has_avx512_vnni(detected_tokens: set[str]) -> bool:
    if {"avx512vnni", "avx512_vnni"} & detected_tokens:
        return True
    return "vnni" in detected_tokens and "avx512f" in detected_tokens


def collect_cpu_flags() -> list[str]:
    detected_tokens = _collect_detected_cpu_tokens()

    relevant_flags: set[str] = set()
    if "sse" in detected_tokens:
        relevant_flags.add("sse")
    if "sse2" in detected_tokens:
        relevant_flags.add("sse2")
    if "pni" in detected_tokens or "sse3" in detected_tokens:
        relevant_flags.add("sse3")
    if "ssse3" in detected_tokens:
        relevant_flags.add("ssse3")
    if {"sse4_1", "sse4.1", "sse41"} & detected_tokens:
        relevant_flags.add("sse41")
    if {"sse4_2", "sse4.2", "sse42", "sse4"} & detected_tokens:
        relevant_flags.add("sse42")
    if "popcnt" in detected_tokens:
        relevant_flags.add("popcnt")
    if "avx" in detected_tokens or "avx1.0" in detected_tokens:
        relevant_flags.add("avx")
    if "avx2" in detected_tokens:
        relevant_flags.add("avx2")
    if "pext" in detected_tokens or "bmi2" in detected_tokens:
        relevant_flags.add("bmi2")
    if "avx512f" in detected_tokens or "avx512" in detected_tokens:
        relevant_flags.add("avx512f")
    if "avx512bw" in detected_tokens:
        relevant_flags.add("avx512bw")
    if "avx512dq" in detected_tokens:
        relevant_flags.add("avx512dq")
    if "avx512vl" in detected_tokens:
        relevant_flags.add("avx512vl")
    if _has_avx512_vnni(detected_tokens):
        relevant_flags.add("avx512vnni")

    if "avx512f" in relevant_flags:
        relevant_flags.update({"avx", "avx2", "sse", "sse2", "sse3", "ssse3", "sse41", "sse42"})
    elif "avx2" in relevant_flags:
        relevant_flags.update({"avx", "sse", "sse2", "sse3", "ssse3", "sse41", "sse42"})
    elif "avx" in relevant_flags:
        relevant_flags.update({"sse", "sse2", "sse3", "ssse3", "sse41", "sse42"})
    elif "sse42" in relevant_flags:
        relevant_flags.update({"sse", "sse2", "sse3", "ssse3", "sse41"})
    elif "sse41" in relevant_flags:
        relevant_flags.update({"sse", "sse2", "sse3", "ssse3"})
    elif "ssse3" in relevant_flags:
        relevant_flags.update({"sse", "sse2", "sse3"})
    elif "sse3" in relevant_flags:
        relevant_flags.update({"sse", "sse2"})
    elif "sse2" in relevant_flags:
        relevant_flags.add("sse")

    return [flag for flag in RELEVANT_CPU_FLAGS if flag in relevant_flags]


def collect_hardware_snapshot() -> dict[str, object]:
    cpu_name = detect_cpu_name()
    cpu_flags = collect_cpu_flags()
    if "bmi2" in cpu_flags and _is_probable_zen2(cpu_name):
        cpu_flags = [flag for flag in cpu_flags if flag != "bmi2"]
    return {
        "machine_fingerprint": build_machine_fingerprint(),
        "machine_name": build_machine_name(),
        "system_name": detect_system_name(),
        "cpu_name": cpu_name,
        "ram_total_mb": detect_ram_total_mb(),
        "ram_speed_mt_s": detect_ram_speed_mt_s(),
        "cpu_flags": cpu_flags,
    }
