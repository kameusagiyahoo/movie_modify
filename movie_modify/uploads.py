"""Bounded, resumable LAN uploads. Source bytes never go to cloud services.

Sessions survive a browser refresh and (except an in-flight FFmpeg job) server
restart. Their opaque random identifiers are scoped by the API auth cookie.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path, PureWindowsPath

MAX_VIDEO_BYTES = 50 * 1024**3
MAX_CHUNK_BYTES = 8 * 1024**2
MAX_SESSION_AGE = 24 * 60 * 60
EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


class UploadIssue(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **metadata):
        super().__init__(message)
        self.code, self.status, self.metadata = code, status, metadata


class UploadStore:
    def __init__(self, storage: Path):
        self.root = storage / ".uploads"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _dir(self, session: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", session):
            raise UploadIssue("not_found", "Upload session not found", 404)
        folder = self.root / session
        if not folder.is_dir():
            raise UploadIssue("not_found", "Upload session not found", 404)
        return folder

    def _meta(self, session: str) -> dict:
        folder = self._dir(session)
        try:
            return json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UploadIssue("invalid_session", "Upload session metadata corrupted", 409) from exc

    def _save_meta(self, session: str, meta: dict) -> None:
        folder = self._dir(session)
        temporary = folder / "meta.tmp"
        temporary.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        temporary.replace(folder / "meta.json")

    def cleanup(self) -> None:
        with self.lock:
            now = time.time()
            for folder in self.root.iterdir():
                if folder.is_dir() and now - folder.stat().st_mtime > MAX_SESSION_AGE:
                    shutil.rmtree(folder, ignore_errors=True)

    def create(self, filename: str, size: int, projection: str, last_modified: int = 0) -> dict:
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_VIDEO_BYTES:
            raise UploadIssue("bad_size", "Video size must be 1 byte to 50 GiB")
        if projection not in ("flat", "equirect"):
            raise UploadIssue("bad_projection", "Unsupported video projection")
        if not isinstance(filename, str) or not 0 < len(filename) <= 250:
            raise UploadIssue("bad_filename", "Invalid video filename")
        name = PureWindowsPath(filename).name
        name = Path(name).name
        suffix = Path(name).suffix.lower()
        if suffix not in EXTENSIONS:
            raise UploadIssue("bad_extension", "Please convert camera-native video to MP4/MOV")
        if not isinstance(last_modified, int) or last_modified < 0:
            raise UploadIssue("bad_timestamp", "Invalid modification timestamp")
        with self.lock:
            self.cleanup()
            session = uuid.uuid4().hex
            folder = self.root / session
            folder.mkdir(mode=0o700)
            meta = dict(id=session, filename=name, size=size, projection=projection,
                        last_modified=last_modified, received=0, completed=False)
            self._save_meta(session, meta)
            (folder / "source.part").touch()
            return dict(meta)

    def status(self, session: str) -> dict:
        with self.lock:
            meta = self._meta(session)
            if not meta["completed"]:
                meta["received"] = (self._dir(session) / "source.part").stat().st_size
            return dict(meta)

    def append(self, session: str, offset: int, payload: bytes) -> dict:
        with self.lock:
            meta = self._meta(session)
            if meta["completed"]:
                raise UploadIssue("completed", "Upload already completed", 409)
            if not isinstance(offset, int) or offset < 0:
                raise UploadIssue("bad_offset", "Invalid upload offset")
            if not payload or len(payload) > MAX_CHUNK_BYTES:
                raise UploadIssue("bad_chunk", "Chunk must contain 1–8 MiB", 413)
            source = self._dir(session) / "source.part"
            received = source.stat().st_size
            if offset < received and offset + len(payload) <= received:
                # Safe idempotent retry when a completed chunk's ACK was lost.
                with source.open("rb") as fd:
                    fd.seek(offset)
                    if fd.read(len(payload)) == payload:
                        return self.status(session)
            if offset != received:
                raise UploadIssue("offset_mismatch", "Upload offset changed", 409,
                                  received=received)
            if received + len(payload) > meta["size"]:
                raise UploadIssue("upload_overflow", "Chunk exceeds declared file size", 413)
            with source.open("ab") as fd:
                fd.write(payload)
            meta["received"] = received + len(payload)
            self._save_meta(session, meta)
            os.utime(self._dir(session), None)
            return dict(meta)

    def ready_source(self, session: str) -> tuple[dict, Path]:
        with self.lock:
            meta = self.status(session)
            if meta["completed"]:
                raise UploadIssue("completed", "Upload already completed", 409,
                                  project_id=meta.get("project_id"))
            if meta["received"] != meta["size"]:
                raise UploadIssue("incomplete", "Video transfer is incomplete", 409,
                                  received=meta["received"])
            return meta, self._dir(session) / "source.part"

    def mark_complete(self, session: str, project_id: str, job_id: str) -> dict:
        with self.lock:
            meta = self._meta(session)
            meta.update(completed=True, project_id=project_id, job_id=job_id,
                        received=meta["size"])
            self._save_meta(session, meta)
            os.utime(self._dir(session), None)
            return dict(meta)
