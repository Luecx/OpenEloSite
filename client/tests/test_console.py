from __future__ import annotations

import threading
from unittest.mock import patch, MagicMock

from app.runtime.console import Console


def test_print_acquires_lock():
    """Verify _print uses the internal lock."""
    console = Console()
    acquired = []

    def tracking_print(*args, **kwargs):
        acquired.append(console._lock.locked())
        # Do not call real print; we only care about lock state

    with patch("builtins.print", side_effect=tracking_print):
        console._print("hello")

    assert acquired == [True]


def test_concurrent_status_calls_complete_without_deadlock():
    """Spawn threads calling status concurrently; verify no deadlock."""
    console = Console()
    errors: list[Exception] = []

    # Patch print to suppress output during test
    with patch("builtins.print"):
        def call_status(n: int) -> None:
            try:
                for i in range(50):
                    console.status("T", f"thread-{n} line-{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=call_status, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        for t in threads:
            assert not t.is_alive(), "Thread deadlocked"
        assert errors == []


def test_concurrent_section_and_status_no_deadlock():
    """Spawn threads calling section() and status() concurrently; verify no deadlock."""
    console = Console()
    errors: list[Exception] = []

    # Patch print to suppress output during test
    with patch("builtins.print"):
        def section_loop() -> None:
            try:
                for _ in range(20):
                    console.section("SEC", [("key", "val")])
            except Exception as exc:
                errors.append(exc)

        def status_loop() -> None:
            try:
                for _ in range(100):
                    console.status("WARN", "interrupt")
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=section_loop),
            threading.Thread(target=status_loop),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        for t in threads:
            assert not t.is_alive(), "Thread deadlocked"
        assert errors == []
