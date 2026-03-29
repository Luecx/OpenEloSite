from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.main import build_parser, main


def test_parser_accepts_verbose_short_flag():
    args = build_parser().parse_args([
        "--server", "http://localhost",
        "--access-key", "key123",
        "--threads", "4",
        "--hash", "256",
        "-v",
    ])
    assert args.verbose is True


def test_parser_accepts_verbose_long_flag():
    args = build_parser().parse_args([
        "--server", "http://localhost",
        "--access-key", "key123",
        "--threads", "4",
        "--hash", "256",
        "--verbose",
    ])
    assert args.verbose is True


def test_parser_verbose_defaults_to_false():
    args = build_parser().parse_args([
        "--server", "http://localhost",
        "--access-key", "key123",
        "--threads", "4",
        "--hash", "256",
    ])
    assert args.verbose is False


@pytest.mark.parametrize("verbose_flag,expected", [
    (["--verbose"], True),
    ([], False),
])
def test_main_forwards_verbose_to_open_elo_client(verbose_flag, expected):
    """main() must pass verbose=args.verbose to OpenEloClient."""
    base_args = [
        "--server", "http://localhost",
        "--access-key", "key123",
        "--threads", "4",
        "--hash", "256",
    ]
    mock_client = MagicMock()
    mock_client.run_forever.return_value = None

    with patch("app.main.OpenEloClient", return_value=mock_client) as mock_cls, \
         patch("sys.argv", ["prog"] + base_args + verbose_flag):
        main()

    _, kwargs = mock_cls.call_args
    assert kwargs.get("verbose") is expected
