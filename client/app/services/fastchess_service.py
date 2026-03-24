from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


FASTCHESS_REPO_URL = "https://github.com/Disservin/fastchess.git"


@dataclass(frozen=True, slots=True)
class FastchessSetup:
    path: Path
    git_target: str | None = None


def _run(command: list[str], cwd: Path, label: str) -> None:
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if process.returncode == 0:
        return
    output = "\n".join(part for part in [process.stdout.strip(), process.stderr.strip()] if part).strip()
    raise RuntimeError(f"{label} fehlgeschlagen.\n{output or f'Rueckgabecode {process.returncode}'}")


def _run_bash(script: str, cwd: Path, label: str) -> None:
    process = subprocess.run(["bash", "-lc", script], cwd=cwd, capture_output=True, text=True, check=False)
    if process.returncode == 0:
        return
    output = "\n".join(part for part in [process.stdout.strip(), process.stderr.strip()] if part).strip()
    raise RuntimeError(f"{label} fehlgeschlagen.\n{output or f'Rueckgabecode {process.returncode}'}")


def _binary_from_path() -> Path | None:
    for name in ("fastchess", "fast-chess"):
        executable = shutil.which(name)
        if executable:
            return Path(executable).resolve()
    return None


def ensure_fastchess(workdir: Path) -> FastchessSetup:
    path_binary = _binary_from_path()
    if path_binary is not None:
        _run([str(path_binary), "-version"], path_binary.parent, "fast-chess check")
        return FastchessSetup(path=path_binary)

    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git wurde nicht gefunden. fast-chess kann nicht automatisch geclont werden.")

    repo_dir = workdir / "fast-chess"
    if repo_dir.exists() and not (repo_dir / ".git").exists():
        raise RuntimeError(f"{repo_dir} existiert, ist aber kein git-Repository.")

    if not repo_dir.exists():
        _run([git_executable, "clone", "--depth", "1", FASTCHESS_REPO_URL, str(repo_dir)], workdir, "fast-chess clone")
    else:
        _run([git_executable, "pull", "--ff-only"], repo_dir, "fast-chess pull")

    _run_bash("make -j", repo_dir, "fast-chess build")

    for candidate in (repo_dir / "fastchess", repo_dir / "fast-chess"):
        if candidate.exists() and candidate.is_file():
            candidate.chmod(0o755)
            _run([str(candidate), "-version"], candidate.parent, "fast-chess check")
            return FastchessSetup(path=candidate.resolve(), git_target=FASTCHESS_REPO_URL)

    raise RuntimeError(f"fast-chess wurde gebaut, aber keine Binary gefunden: {repo_dir}")
