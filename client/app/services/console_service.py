from __future__ import annotations

from dataclasses import dataclass


_SEPARATOR_WIDTH = 60
_LABEL_WIDTH = 18


def _format_value(value) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


@dataclass(slots=True)
class ClientConsole:
    def _print(self, text: str = "") -> None:
        print(text, flush=True)

    def banner(self, title: str) -> None:
        self._print("=" * _SEPARATOR_WIDTH)
        self._print(f" {title}")
        self._print("=" * _SEPARATOR_WIDTH)
        self._print()

    def job_banner(self, job_id: str) -> None:
        self._print("=" * _SEPARATOR_WIDTH)
        self._print(f" Job: {job_id}")
        self._print("=" * _SEPARATOR_WIDTH)
        self._print()

    def section(self, title: str, rows: list[tuple[str, object]], subtitle: str = "") -> None:
        heading = f"[{title}]"
        if subtitle:
            heading = f"{heading} {subtitle}"
        self._print(heading)
        for label, value in rows:
            self._print(f"  {label:<{_LABEL_WIDTH}}: {_format_value(value)}")
        self._print()

    def lines(self, title: str, lines: list[str], subtitle: str = "") -> None:
        heading = f"[{title}]"
        if subtitle:
            heading = f"{heading} {subtitle}"
        self._print(heading)
        for line in lines:
            self._print(f"  {line}")
        self._print()

    def command(self, command_lines: list[str]) -> None:
        self._print("[RUN]")
        self._print("  Starting fast-chess ...")
        self._print()
        self._print("  Command:")
        for line in command_lines:
            self._print(f"    {line}")
        self._print()

    def status(self, tag: str, message: str) -> None:
        self._print(f"[{tag}] {message}")

    def error(self, message: str) -> None:
        self.section("ERROR", [("Message", message)])
