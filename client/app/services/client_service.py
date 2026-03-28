from __future__ import annotations

import threading
import time
from pathlib import Path

from app.api.server_client import ServerClient
from app.services.console_service import ClientConsole
from app.services.fastchess_service import ensure_fastchess
from app.services.hardware_service import collect_hardware_snapshot
from app.services.job_runner import JobRunner
from app.services.self_update_service import ensure_client_bundle_current
from app.services.syzygy_service import inspect_syzygy_root
from app.services.workspace_service import WorkspaceService


class _HeartbeatThread(threading.Thread):
    def __init__(self, service: "ClientService"):
        super().__init__(daemon=True)
        self.service = service
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.wait(self.service.heartbeat_interval):
            try:
                self.service.send_heartbeat()
            except Exception as error:
                self.service.console.status("WARN", f"Heartbeat failed: {error}")

    def stop(self) -> None:
        self.stop_event.set()


class ClientService:
    def __init__(
        self,
        server_url: str,
        access_key: str,
        max_threads: int,
        max_hash: int,
        workdir: Path,
        syzygy_root: Path | None = None,
        machine_name: str = "",
        machine_fingerprint: str = "",
        poll_interval_override: int = 0,
        heartbeat_interval_override: int = 0,
    ):
        if max_threads <= 0:
            raise ValueError("threads must be greater than 0")
        if max_hash <= 0:
            raise ValueError("hash must be greater than 0")

        self.console = ClientConsole()
        self.console.banner("OpenELO Client")
        self.server = ServerClient(server_url, access_key)
        self.client_bundle_hash = ensure_client_bundle_current(self.server, self.console)
        self.max_threads = int(max_threads)
        self.max_hash = int(max_hash)
        hardware = collect_hardware_snapshot()
        self.machine_name = machine_name.strip() or str(hardware["machine_name"])
        self.machine_fingerprint = machine_fingerprint.strip() or str(hardware["machine_fingerprint"])
        self.poll_interval_override = max(0, int(poll_interval_override))
        self.heartbeat_interval_override = max(0, int(heartbeat_interval_override))
        self.poll_interval = 5
        self.heartbeat_interval = 15
        self.state = "starting"
        self.client_id: int | None = None
        self.system_name = str(hardware["system_name"])
        self.cpu_flags = set(hardware["cpu_flags"])
        self.cpu_name = str(hardware["cpu_name"] or "").strip() or "unknown cpu"
        self.ram_total_mb = max(0, int(hardware["ram_total_mb"] or 0))
        self.ram_speed_mt_s = int(hardware["ram_speed_mt_s"] or 0)
        self.workspace = WorkspaceService(workdir)
        self.syzygy = inspect_syzygy_root(syzygy_root)

        fastchess_setup = ensure_fastchess(self.workspace.root)
        fastchess_rows: list[tuple[str, object]] = []
        if fastchess_setup.git_target:
            fastchess_rows.append(("Git target", fastchess_setup.git_target))
        fastchess_rows.append(("Path", fastchess_setup.path))
        self.console.section("INIT", fastchess_rows, subtitle="Fast-chess")
        self.console.section(
            "INIT",
            [
                ("Root", self.syzygy.root or "-"),
                ("3-4-5", "yes" if self.syzygy.max_pieces >= 5 else "no"),
                ("6-man", "yes" if self.syzygy.max_pieces >= 6 else "no"),
                ("7-man", "yes" if self.syzygy.max_pieces >= 7 else "no"),
            ],
            subtitle="Syzygy",
        )
        self.runner = JobRunner(self.workspace, fastchess_setup.path, self.max_threads, self.console, self.syzygy)

    def register(self) -> int:
        payload = {
            "client_bundle_hash": self.client_bundle_hash,
            "machine_fingerprint": self.machine_fingerprint,
            "machine_name": self.machine_name,
            "system_name": self.system_name,
            "max_threads": self.max_threads,
            "max_hash": self.max_hash,
            "syzygy_max_pieces": self.syzygy.max_pieces,
            "cpu_flags": sorted(self.cpu_flags),
            "cpu_name": self.cpu_name,
            "ram_total_mb": self.ram_total_mb,
            "ram_speed_mt_s": self.ram_speed_mt_s,
            "state": "idle",
        }
        try:
            response = self.server.post("/api/client/register", payload)
        except RuntimeError as error:
            if "Client bundle is outdated" in str(error):
                self.console.status("INIT", "Server reported an outdated client bundle. Updating ...")
                self.client_bundle_hash = ensure_client_bundle_current(self.server, self.console)
            raise
        self.client_id = int(response["client_id"])
        self.heartbeat_interval = self.heartbeat_interval_override or int(response.get("heartbeat_interval_seconds", 15) or 15)
        self.poll_interval = self.poll_interval_override or int(response.get("poll_interval_seconds", 5) or 5)
        bench = response.get("bench")
        if not isinstance(bench, dict):
            raise RuntimeError("Server did not provide a bench artifact.")
        bench_path = self.workspace.refresh_bench_artifact(bench, self.server)
        self.runner.configure_bench(bench_path, int(bench.get("reference_nps", 0) or 0))
        self.state = "idle"
        self.console.section(
            "INIT",
            [
                ("Download target", self.workspace.bench_dir),
                ("Ready", bench_path),
            ],
            subtitle="Bench Artifact",
        )
        self.console.section(
            "INIT",
            [
                ("Client ID", self.client_id),
                ("Fingerprint", self.machine_fingerprint),
                ("Machine", self.machine_name),
                ("System", self.system_name),
                ("CPU", self.cpu_name),
                ("CPU Flags", ", ".join(sorted(self.cpu_flags)) if self.cpu_flags else "none"),
                ("RAM", self._format_ram_summary()),
                ("Threads", self.max_threads),
                ("Hash", f"{self.max_hash} MB"),
                ("Workdir", self.workspace.root),
            ],
            subtitle="Client Registration",
        )
        return self.client_id

    def _format_ram_summary(self) -> str:
        if self.ram_total_mb <= 0:
            return "-"
        total_gb = self.ram_total_mb / 1024.0
        base = f"{total_gb:.1f} GB"
        if self.ram_speed_mt_s > 0:
            return f"{base} @ {self.ram_speed_mt_s} MT/s"
        return base

    def send_heartbeat(self) -> None:
        if self.client_id is None:
            return
        self.server.post(
            "/api/client/heartbeat",
            {
                "client_id": self.client_id,
                "state": self.state,
            },
        )

    def request_next_job(self) -> dict | None:
        if self.client_id is None:
            raise RuntimeError("Client is not registered.")
        response = self.server.post("/api/client/jobs/next", {"client_id": self.client_id})
        return response.get("job")

    def complete_job(self, job_id: str, payload: dict) -> None:
        if self.client_id is None:
            raise RuntimeError("Client is not registered.")
        full_payload = dict(payload)
        full_payload["client_id"] = self.client_id
        self.server.post(f"/api/client/jobs/{job_id}/complete", full_payload)

    def run_forever(self) -> None:
        self.register()
        heartbeat_thread = _HeartbeatThread(self)
        heartbeat_thread.start()
        try:
            while True:
                job = None
                try:
                    job = self.request_next_job()
                    if job is None:
                        self.state = "idle"
                        time.sleep(self.poll_interval)
                        continue

                    self.state = "running"
                    self.console.job_banner(job["job_id"])
                    concurrency = self.max_threads // max(1, int(job["threads_per_engine"]))
                    rounds = int(job["num_games"]) // 2 if int(job["num_games"]) % 2 == 0 else int(job["num_games"])
                    self.console.section(
                        "MATCH",
                        [
                            ("Engine 1", job["engine_1"].get("display_name") or job["engine_1"]["name"]),
                            ("Engine 2", job["engine_2"].get("display_name") or job["engine_2"]["name"]),
                            ("Time Control", job["time_control"]),
                            ("Threads / Engine", int(job["threads_per_engine"])),
                            ("Hash / Engine", f"{int(job['hash_per_engine'])} MB"),
                            ("Syzygy", job.get("syzygy_label") or "No tablebase"),
                            ("Total Games", int(job["num_games"])),
                            ("Rounds", rounds),
                            ("Concurrency", concurrency),
                        ],
                    )
                    resolved_book = self.workspace.ensure_book(job.get("opening_book"), self.server)
                    self.console.section(
                        "BOOK",
                        [
                            ("Status", resolved_book.status if resolved_book is not None else "none"),
                            ("File", resolved_book.path if resolved_book is not None else "-"),
                        ],
                    )
                    result = self.runner.run(
                        job,
                        resolved_book.path if resolved_book is not None else None,
                        self.cpu_flags,
                        self.server,
                        self.system_name,
                    )
                    self.complete_job(job["job_id"], result)
                    points = float(result["wins"]) + 0.5 * float(result["draws"])
                    self.console.section(
                        "RESULT",
                        [
                            ("Score", f"{result['wins']}W {result['draws']}D {result['losses']}L"),
                            ("Points", f"{points:.1f} / {int(result['games_count'])}"),
                            ("Status", result["status"]),
                        ],
                    )
                    self.state = "idle"
                except Exception as error:
                    self.state = "idle"
                    self.console.error(str(error))
                    if self.client_id is not None and job is not None and "job_id" in job:
                        try:
                            self.complete_job(
                                job["job_id"],
                                {
                                    "status": "failed",
                                    "wins": 0,
                                    "draws": 0,
                                    "losses": 0,
                                    "games_count": 0,
                                    "error": str(error),
                                },
                            )
                        except Exception as complete_error:
                            self.console.status("WARN", f"Failed to report failed job: {complete_error}")
                    if "Client not found" in str(error):
                        self.console.status("WARN", "Client registration expired. Re-registering.")
                        self.register()
                    time.sleep(self.poll_interval)
        finally:
            heartbeat_thread.stop()
            heartbeat_thread.join(timeout=1)
