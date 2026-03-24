from __future__ import annotations

import base64
from dataclasses import dataclass
import re
import shlex
import subprocess
import time
from pathlib import Path
import zipfile

from app.api.server_client import ServerClient
from app.services.syzygy_service import SyzygyLayout
from app.services.syzygy_service import normalize_syzygy_probe_limit
from app.services.syzygy_service import syzygy_label
from app.services.workspace_service import WorkspaceService


@dataclass(frozen=True, slots=True)
class BenchResult:
    measured_nps: int
    reference_nps: int
    time_factor: float


@dataclass(frozen=True, slots=True)
class SyzygyRunConfig:
    probe_limit: int
    label: str
    joined_path: str
    directories: tuple[Path, ...]


class JobRunner:
    def __init__(self, workspace: WorkspaceService, fastchess_path: Path, max_threads: int, console, syzygy: SyzygyLayout):
        self.workspace = workspace
        self.fastchess_path = fastchess_path.expanduser().resolve()
        self.max_threads = max_threads
        self.console = console
        self.syzygy = syzygy
        self.bench_path: Path | None = None
        self.bench_reference_nps: int | None = None

    def configure_bench(self, bench_path: Path, reference_nps: int) -> None:
        if reference_nps <= 0:
            raise ValueError("bench reference nps muss groesser als 0 sein")
        self.bench_path = bench_path.expanduser().resolve()
        self.bench_reference_nps = int(reference_nps)

    def run(self, job: dict, book_path: Path | None, cpu_flags: set[str], server: ServerClient, system_name: str) -> dict:
        self.workspace.cleanup_for_job()
        self._check_required_flags(job, cpu_flags, system_name)
        start_time = time.monotonic()

        concurrency = self.max_threads // max(1, int(job["threads_per_engine"]))
        if concurrency <= 0:
            raise RuntimeError("threads_per_engine ist groesser als die verfuegbaren Client-Threads.")

        bench_result = self._run_bench()
        effective_tc = self._scaled_time_control(job, bench_result.time_factor)
        self.console.section(
            "BENCH",
            [
                ("Executable", self.bench_path),
                ("Measured NPS", bench_result.measured_nps),
                ("Reference NPS", bench_result.reference_nps),
                ("TC Factor", f"{bench_result.time_factor:.3f}"),
                ("Effective TC", effective_tc),
            ],
        )

        engine1_path = self._prepare_engine(job["engine_1"], self.workspace.engine1_dir, "engine1", server)
        engine2_path = self._prepare_engine(job["engine_2"], self.workspace.engine2_dir, "engine2", server)
        self.console.section(
            "ARTIFACTS",
            [
                ("Engine 1 target", self.workspace.engine1_dir),
                ("Engine 1 ready", engine1_path),
                ("Engine 2 target", self.workspace.engine2_dir),
                ("Engine 2 ready", engine2_path),
            ],
        )
        syzygy_run = self._resolve_syzygy_run(job)
        if syzygy_run.probe_limit > 0:
            self.console.section(
                "SYZYGY",
                [
                    ("Requested", syzygy_run.label),
                    ("Probe Limit", syzygy_run.probe_limit),
                    ("Folders", len(syzygy_run.directories)),
                    ("Path", syzygy_run.joined_path),
                ],
            )

        pgn_path = self.workspace.root / "games.pgn"
        log_path = self.workspace.root / "fastchess.log"
        if pgn_path.exists():
            pgn_path.unlink()
        if log_path.exists():
            log_path.unlink()

        engine1_name = self._engine_display_name(job["engine_1"])
        engine2_name = self._engine_display_name(job["engine_2"])
        command = self._build_fastchess_command(
            job=job,
            engine1_path=engine1_path,
            engine2_path=engine2_path,
            engine1_name=engine1_name,
            engine2_name=engine2_name,
            book_path=book_path,
            pgn_path=pgn_path,
            concurrency=concurrency,
            time_factor=bench_result.time_factor,
            syzygy_run=syzygy_run,
        )

        self.console.command(self._format_command_lines(command))
        process = subprocess.run(command, cwd=self.workspace.root, capture_output=True, text=True, check=False)
        log_text = "\n".join(part for part in [process.stdout.strip(), process.stderr.strip()] if part).strip()
        log_path.write_text(log_text)
        runtime_seconds = max(1, int(time.monotonic() - start_time))

        if process.returncode != 0:
            raise RuntimeError(log_text or f"fast-chess beendet mit Rueckgabecode {process.returncode}")

        if not pgn_path.exists():
            raise RuntimeError("fast-chess hat keine PGN-Datei erzeugt.")

        pgn_text = pgn_path.read_text(errors="ignore")
        wins, draws, losses = self._count_results(pgn_text, engine1_name)
        games_count = wins + draws + losses
        if games_count <= 0:
            raise RuntimeError("Keine gueltigen Resultate in der PGN-Datei gefunden.")
        pgn_zip_base64 = self._build_pgn_zip_base64(pgn_path)

        return {
            "status": "completed",
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "games_count": games_count,
            "pgn_zip_base64": pgn_zip_base64,
            "runtime_seconds": runtime_seconds,
        }

    def _check_required_flags(self, job: dict, cpu_flags: set[str], system_name: str) -> None:
        for engine_key in ("engine_1", "engine_2"):
            artifact = job[engine_key].get("artifact") or {}
            required = sorted({item.strip().lower() for item in artifact.get("required_cpu_flags", []) if item})
            missing = [flag for flag in required if flag not in cpu_flags]
            if missing:
                raise RuntimeError(f"{engine_key} benoetigt nicht vorhandene CPU-Flags: {', '.join(missing)}")
            artifact_system = (artifact.get("system_name") or "").strip().lower()
            if artifact_system and artifact_system != system_name.strip().lower():
                raise RuntimeError(f"{engine_key} benoetigt System {artifact_system}, Client ist {system_name}")

    def _prepare_engine(self, engine: dict, target_dir: Path, label: str, server: ServerClient) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        artifact = engine.get("artifact") or {}
        return self.workspace.ensure_artifact(artifact, target_dir, server)

    def _build_fastchess_command(
        self,
        job: dict,
        engine1_path: Path,
        engine2_path: Path,
        engine1_name: str,
        engine2_name: str,
        book_path: Path | None,
        pgn_path: Path,
        concurrency: int,
        time_factor: float,
        syzygy_run: SyzygyRunConfig,
    ) -> list[str]:
        num_games = max(1, int(job["num_games"]))
        use_repeat = num_games % 2 == 0
        rounds = self._rounds_for_job(job)

        command = [
            str(self.fastchess_path),
            "-engine",
            f"cmd={engine1_path}",
            f"name={engine1_name}",
            f"dir={engine1_path.parent}",
            "-engine",
            f"cmd={engine2_path}",
            f"name={engine2_name}",
            f"dir={engine2_path.parent}",
        ]
        if book_path is not None:
            book_format = self.workspace.detect_book_format(book_path)
            command.extend(
                [
                    "-openings",
                    f"file={book_path}",
                    f"format={book_format}",
                    "order=random",
                    "-srand",
                    str(int(job["seed"] or 1)),
                ]
            )
        command.extend(
            [
                "-each",
                f"tc={self._scaled_time_control(job, time_factor)}",
                f"option.Threads={int(job['threads_per_engine'])}",
                f"option.Hash={int(job['hash_per_engine'])}",
            ]
        )
        if syzygy_run.probe_limit > 0:
            command.extend(
                [
                    f"option.SyzygyPath={syzygy_run.joined_path}",
                    f"option.SyzygyProbeLimit={syzygy_run.probe_limit}",
                ]
            )
        command.extend(
            [
                "-rounds",
                str(max(1, rounds)),
                "-concurrency",
                str(concurrency),
                "-pgnout",
                f"file={pgn_path}",
                "notation=san",
                "nodes=true",
                "seldepth=true",
            ]
        )
        if use_repeat:
            command.append("-repeat")
        else:
            command.extend(["-games", "1"])
        return command

    def _run_bench(self) -> BenchResult:
        if self.bench_path is None or self.bench_reference_nps is None:
            raise RuntimeError("Bench ist nicht konfiguriert.")
        if not self.bench_path.exists():
            raise RuntimeError(f"Bench executable nicht gefunden: {self.bench_path}")

        process = subprocess.run(
            [str(self.bench_path), "bench", "exit"],
            cwd=self.bench_path.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        output = "\n".join(part for part in [process.stdout.strip(), process.stderr.strip()] if part).strip()
        if process.returncode != 0:
            raise RuntimeError(output or f"Bench fehlgeschlagen mit Rueckgabecode {process.returncode}")

        matches = re.findall(r"OVERALL:\s+\d+\s+nodes\s+(\d+)\s+nps", output, flags=re.IGNORECASE)
        if not matches:
            raise RuntimeError("Bench-Ausgabe enthaelt keinen OVERALL-NPS-Wert.")
        measured_nps = int(matches[-1])
        if measured_nps <= 0:
            raise RuntimeError("Bench-NPS ist ungueltig.")

        factor = self.bench_reference_nps / measured_nps
        return BenchResult(
            measured_nps=measured_nps,
            reference_nps=self.bench_reference_nps,
            time_factor=max(0.001, factor),
        )

    def _scaled_time_control(self, job: dict, time_factor: float) -> str:
        base_seconds = float(job.get("time_control_base_seconds", 0) or 0)
        increment_seconds = float(job.get("time_control_increment_seconds", 0) or 0)
        time_control_moves = job.get("time_control_moves")
        if base_seconds <= 0:
            return str(job["time_control"])

        scaled_base = max(0.001, base_seconds * time_factor)
        scaled_increment = max(0.0, increment_seconds * time_factor)
        if time_control_moves:
            return f"{int(time_control_moves)}/{self._format_tc_value(scaled_base)}+{self._format_tc_value(scaled_increment)}"
        return f"{self._format_tc_value(scaled_base)}+{self._format_tc_value(scaled_increment)}"

    def _resolve_syzygy_run(self, job: dict) -> SyzygyRunConfig:
        probe_limit = normalize_syzygy_probe_limit(job.get("syzygy_probe_limit", 0))
        if probe_limit <= 0:
            return SyzygyRunConfig(probe_limit=0, label=syzygy_label(0), joined_path="", directories=())
        directories = tuple(self.syzygy.directories_for_probe_limit(probe_limit))
        return SyzygyRunConfig(
            probe_limit=probe_limit,
            label=syzygy_label(probe_limit),
            joined_path=self.syzygy.joined_path_for_probe_limit(probe_limit),
            directories=directories,
        )

    def _format_tc_value(self, seconds: float) -> str:
        rounded = round(seconds, 3)
        if abs(rounded - round(rounded)) < 1e-9:
            return str(int(round(rounded)))
        return f"{rounded:.3f}".rstrip("0").rstrip(".")

    def _count_results(self, pgn_text: str, engine1_name: str) -> tuple[int, int, int]:
        whites = re.findall(r'^\[White "([^"]+)"\]$', pgn_text, flags=re.MULTILINE)
        blacks = re.findall(r'^\[Black "([^"]+)"\]$', pgn_text, flags=re.MULTILINE)
        results = re.findall(r'^\[Result "([^"]+)"\]$', pgn_text, flags=re.MULTILINE)
        wins = 0
        draws = 0
        losses = 0
        for white, black, result in zip(whites, blacks, results):
            if result == "1/2-1/2":
                draws += 1
                continue
            if result == "1-0":
                if white == engine1_name:
                    wins += 1
                elif black == engine1_name:
                    losses += 1
                continue
            if result == "0-1":
                if black == engine1_name:
                    wins += 1
                elif white == engine1_name:
                    losses += 1
        return wins, draws, losses

    def _build_pgn_zip_base64(self, pgn_path: Path) -> str:
        zip_path = pgn_path.with_suffix(".pgn.zip")
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(pgn_path, arcname="games.pgn")
        return base64.b64encode(zip_path.read_bytes()).decode("ascii")

    def _engine_display_name(self, engine: dict) -> str:
        display_name = (engine.get("display_name") or "").strip()
        if display_name:
            return display_name
        name = (engine.get("name") or "").strip()
        version_name = (engine.get("version_name") or "").strip()
        if name and version_name:
            return f"{name} {version_name}"
        if name:
            return name
        raise RuntimeError("Engine-Name fehlt im Job.")

    def _rounds_for_job(self, job: dict) -> int:
        num_games = max(1, int(job["num_games"]))
        if num_games % 2 == 0:
            return num_games // 2
        return num_games

    def _format_command_lines(self, command: list[str]) -> list[str]:
        if not command:
            return []
        lines = [f"{command[0]} \\"]
        groups: list[list[str]] = []
        current: list[str] = []
        for token in command[1:]:
            if token.startswith("-") and current:
                groups.append(current)
                current = [token]
            else:
                current.append(token)
        if current:
            groups.append(current)

        for group_index, group in enumerate(groups):
            is_last_group = group_index == len(groups) - 1
            if len(group) == 1:
                lines.append(f"  {self._display_token(group[0])}" + ("" if is_last_group else " \\"))
                continue

            first_line = f"  {self._display_token(group[0])} {self._display_token(group[1])}"
            lines.append(first_line + (" \\" if (not is_last_group or len(group) > 2) else ""))
            for token_index, token in enumerate(group[2:]):
                is_last_token = token_index == len(group[2:]) - 1
                lines.append(
                    f"      {self._display_token(token)}"
                    + ("" if is_last_group and is_last_token else " \\")
                )
        return lines

    def _display_token(self, token: str) -> str:
        if token.startswith("name="):
            escaped_name = token[5:].replace('"', '\\"')
            return f'name="{escaped_name}"'
        if any(character.isspace() for character in token):
            return shlex.quote(token)
        return token
