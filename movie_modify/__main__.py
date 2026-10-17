"""Cross-platform local server launcher.

Windows: py -3 -m movie_modify
Linux:   python3 -m movie_modify
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="movie_modify",
        description="Start the Movie Modify local video-editing server.",
    )
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    parser.add_argument("--lan", action="store_true",
                        help="Allow access from a phone on the local network; requires MOVIE_MODIFY_TOKEN")
    parser.add_argument("--data-dir", type=Path,
                        help="Directory for private originals, proxies, projects and renders")
    args = parser.parse_args(argv)

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.data_dir:
        os.environ["MOVIE_MODIFY_DATA"] = str(args.data_dir.expanduser().resolve())

    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        print(
            "FFmpeg is not available on PATH: " + ", ".join(missing) + "\n"
            "Windows: install with winget install --id Gyan.FFmpeg -e and reopen the terminal.\n"
            "Ubuntu:  sudo apt install ffmpeg.",
            file=sys.stderr,
        )
        return 2

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    if args.lan and not os.environ.get("MOVIE_MODIFY_TOKEN", "").strip():
        print(
            "LAN access requires MOVIE_MODIFY_TOKEN (a long unique passphrase).\n"
            "Set it in the terminal before running with --lan.\n"
            "Never forward port 8000 to the public Internet; HTTP is not encrypted.",
            file=sys.stderr,
        )
        return 2

    # Load the app after MOVIE_MODIFY_DATA is configured.
    import uvicorn

    print("Movie Modify is running at http://127.0.0.1:" + str(args.port))
    if args.lan:
        print("To open on iPhone, use http://<computer LAN IP>:" + str(args.port))
        print("LAN traffic uses plain HTTP. Use HTTPS or a trusted VPN for sensitive footage.")
    uvicorn.run("movie_modify.server:app", host=host, port=args.port, reload=False, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
