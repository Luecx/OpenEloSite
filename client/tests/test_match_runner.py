from __future__ import annotations

import subprocess
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.runtime.console import Console
from app.runtime.match_runner import MatchRunner
from app.runtime.syzygy import SyzygyLayout


def _make_runner(verbose: bool = False) -> MatchRunner:
    return MatchRunner(
        workspace=MagicMock(),
        fastchess_path=Path("/usr/bin/fastchess"),
        max_threads=4,
        console=Console(),
        syzygy=SyzygyLayout(root=None, paths_345=(), paths_6=(), paths_7=()),
        verbose=verbose,
    )


def test_verbose_defaults_to_false():
    runner = _make_runner()
    assert runner.verbose is False


def test_verbose_set_to_true():
    runner = _make_runner(verbose=True)
    assert runner.verbose is True


def _mock_popen(stdout_lines: list[str], returncode: int = 0):
    """Create a mock Popen context manager yielding given lines."""
    mock_process = MagicMock()
    mock_process.stdout = iter(stdout_lines)
    mock_process.wait.return_value = returncode
    type(mock_process).returncode = PropertyMock(return_value=returncode)
    mock_process.__enter__ = MagicMock(return_value=mock_process)
    mock_process.__exit__ = MagicMock(return_value=False)
    return mock_process


def test_verbose_streams_output_to_console():
    runner = _make_runner(verbose=True)
    console = MagicMock(spec=Console)
    runner.console = console

    mock_proc = _mock_popen(["line1\n", "line2\n"], returncode=0)
    with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
        output_lines, log_text, rc = runner._run_fastchess_process(
            ["fastchess", "--arg"], Path("/tmp")
        )

    assert console.status.call_count == 2
    console.status.assert_any_call("FC", "line1")
    console.status.assert_any_call("FC", "line2")
    assert output_lines == ["line1", "line2"]
    assert rc == 0


def test_quiet_mode_does_not_stream():
    runner = _make_runner(verbose=False)
    console = MagicMock(spec=Console)
    runner.console = console

    mock_proc = _mock_popen(["line1\n", "line2\n"], returncode=0)
    with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
        output_lines, log_text, rc = runner._run_fastchess_process(
            ["fastchess", "--arg"], Path("/tmp")
        )

    console.status.assert_not_called()
    assert output_lines == ["line1", "line2"]
    assert rc == 0


@pytest.mark.parametrize("verbose", [True, False])
def test_log_text_captured_in_both_modes(verbose: bool):
    runner = _make_runner(verbose=verbose)
    runner.console = MagicMock(spec=Console)

    mock_proc = _mock_popen(["alpha\n", "beta\n"], returncode=0)
    with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
        output_lines, log_text, rc = runner._run_fastchess_process(
            ["fastchess"], Path("/tmp")
        )

    assert log_text == "alpha\nbeta"


def test_nonzero_return_code_propagated():
    runner = _make_runner(verbose=False)
    runner.console = MagicMock(spec=Console)

    mock_proc = _mock_popen(["error msg\n"], returncode=1)
    with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
        output_lines, log_text, rc = runner._run_fastchess_process(
            ["fastchess"], Path("/tmp")
        )

    assert rc == 1
    assert log_text == "error msg"


def test_keyboard_interrupt_kills_process():
    runner = _make_runner(verbose=True)
    runner.console = MagicMock(spec=Console)

    mock_proc = MagicMock()

    def raise_on_iter():
        yield "first\n"
        raise KeyboardInterrupt

    mock_proc.stdout = raise_on_iter()
    mock_proc.wait.return_value = -9
    type(mock_proc).returncode = PropertyMock(return_value=-9)
    mock_proc.__enter__ = MagicMock(return_value=mock_proc)
    mock_proc.__exit__ = MagicMock(return_value=False)

    with pytest.raises(KeyboardInterrupt):
        with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
            runner._run_fastchess_process(["fastchess"], Path("/tmp"))

    # Verify kill() was called before wait()
    mock_calls = mock_proc.mock_calls
    kill_index = next(i for i, call in enumerate(mock_calls) if call[0] == "kill")
    wait_index = next(i for i, call in enumerate(mock_calls) if call[0] == "wait")
    assert kill_index < wait_index, "process.kill() must be called before process.wait()"


def test_empty_output_produces_empty_log_text():
    runner = _make_runner(verbose=False)
    runner.console = MagicMock(spec=Console)

    mock_proc = _mock_popen([], returncode=0)
    with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
        output_lines, log_text, rc = runner._run_fastchess_process(
            ["fastchess"], Path("/tmp")
        )

    assert output_lines == []
    assert log_text == ""
    assert rc == 0


def test_empty_output_nonzero_rc():
    runner = _make_runner(verbose=False)
    runner.console = MagicMock(spec=Console)

    mock_proc = _mock_popen([], returncode=1)
    with patch("app.runtime.match_runner.subprocess.Popen", return_value=mock_proc):
        output_lines, log_text, rc = runner._run_fastchess_process(
            ["fastchess"], Path("/tmp")
        )

    assert rc == 1
    assert log_text == ""


@contextmanager
def _make_run_patches(runner, fc_return):
    """Return a context manager for patches needed to test run() error handling.

    Patches all subprocess-related methods so we can test error paths without
    actually running fastchess.
    """
    with ExitStack() as stack:
        stack.enter_context(patch.object(runner, "_run_fastchess_process", return_value=fc_return))
        stack.enter_context(patch.object(runner, "_validate_job_compatibility"))
        stack.enter_context(patch.object(
            runner, "_run_bench",
            return_value=MagicMock(time_factor=1.0, measured_nps=1000, reference_nps=1000),
        ))
        stack.enter_context(patch.object(runner, "_scaled_time_control", return_value="10+0.1"))
        stack.enter_context(patch.object(runner, "_prepare_engine", return_value=Path("/tmp/engine")))
        stack.enter_context(patch.object(runner, "_build_fastchess_command", return_value=["fastchess"]))
        stack.enter_context(patch.object(runner, "_format_command_lines", return_value=["fastchess"]))
        stack.enter_context(patch.object(runner, "_engine_display_name", return_value="engine"))
        stack.enter_context(patch.object(runner, "_resolve_syzygy_run", return_value=MagicMock(probe_limit=0)))
        yield


# Minimal job dict shape; actual field values are unused since run() methods are patched.
_DUMMY_JOB = {
    "engine_1": {}, "engine_2": {}, "threads_per_engine": 1,
    "hash_per_engine": 128, "time_control": "10+0.1",
    "num_games": 2, "seed": 1,
}


def test_run_raises_runtime_error_on_nonzero_rc(tmp_path):
    """Verify run() raises RuntimeError with log text when fastchess fails."""
    runner = _make_runner(verbose=False)
    runner.console = MagicMock(spec=Console)
    runner.workspace = MagicMock()
    runner.workspace.root = tmp_path

    with _make_run_patches(runner, (["error output"], "error output", 1)):
        with pytest.raises(RuntimeError, match="error output"):
            runner.run(
                job=_DUMMY_JOB, book_path=None, cpu_flags=set(),
                server=MagicMock(), system_name="linux",
            )


def test_run_raises_runtime_error_with_rc_on_empty_output(tmp_path):
    """Verify run() includes the return code in the error when output is empty."""
    runner = _make_runner(verbose=False)
    runner.console = MagicMock(spec=Console)
    runner.workspace = MagicMock()
    runner.workspace.root = tmp_path

    with _make_run_patches(runner, ([], "", 1)):
        with pytest.raises(RuntimeError, match="fast-chess exited with return code 1"):
            runner.run(
                job=_DUMMY_JOB, book_path=None, cpu_flags=set(),
                server=MagicMock(), system_name="linux",
            )
