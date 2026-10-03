"""
booklib_web.__main__ – CLI entrypoint for headless BookLib web server.
Usage:
    python -m booklib_web --host 127.0.0.1 --port 8765 --db /path/to/library.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from waitress.server import create_server

from booklib_web.app import create_app
from booklib_web.config import WebConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Ratnodadhi BookLib Web & OPDS Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--db", type=str, default=None, help="Path to library.db database file")
    parser.add_argument("--allow-changes", action="store_true", help="Allow updating status, rating, and notes")
    args = parser.parse_args()

    cfg = WebConfig(
        host=args.host,
        port=args.port,
        allow_changes=args.allow_changes,
    )
    if args.db:
        cfg.db_path = Path(args.db)

    print(f"Starting BookLib Web Server on http://{cfg.host}:{cfg.port}")
    print(f"Database: {cfg.db_path}")

    app = create_app(cfg)
    try:
        server = create_server(app, host=cfg.host, port=cfg.port, threads=8)
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        sys.exit(0)


if __name__ == "__main__":
    main()
