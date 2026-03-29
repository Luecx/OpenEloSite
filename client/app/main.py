from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.client import OpenEloClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenELO client")
    parser.add_argument("--server", required=True, help="Base URL of the OpenELO server")
    parser.add_argument("--access-key", required=True, help="Client access token")
    parser.add_argument("--threads", required=True, type=int, help="Maximum threads available on this client")
    parser.add_argument("--hash", required=True, type=int, help="Maximum hash in MB available on this client")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path.cwd() / "workspace",
        help="Workspace directory for books, engines and fast-chess",
    )
    parser.add_argument(
        "--syzygy-root",
        type=Path,
        default=None,
        help="Optional root directory for Syzygy tablebases (scanned recursively up to depth 2)",
    )
    parser.add_argument("--machine-name", default="", help=argparse.SUPPRESS)
    parser.add_argument("--machine-fingerprint", default="", help="Optional stable machine fingerprint override")
    parser.add_argument("--machine-key", dest="machine_fingerprint", default="", help=argparse.SUPPRESS)
    parser.add_argument("--poll-interval", type=int, default=0, help="Optional poll interval override in seconds")
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=0,
        help="Optional heartbeat interval override in seconds",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Stream fastchess output to the terminal in real time",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        client = OpenEloClient(
            server_url=args.server,
            access_key=args.access_key,
            max_threads=args.threads,
            max_hash=args.hash,
            workdir=args.workdir,
            syzygy_root=args.syzygy_root,
            machine_fingerprint=args.machine_fingerprint,
            poll_interval_override=args.poll_interval,
            heartbeat_interval_override=args.heartbeat_interval,
            verbose=args.verbose,
        )
        client.run_forever()
    except (ValueError, RuntimeError) as error:
        print(f"Startup error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
