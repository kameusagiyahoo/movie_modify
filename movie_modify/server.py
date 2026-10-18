"""FastAPI application. Videos never leave this machine.

Run: python -m uvicorn movie_modify.server:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import gzip
import hmac
import math
import importlib.util
import json
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .core import apply_suggestions, fresh_segment, normalize_segments
from .media import (auto_editor_suggestions, available, create_proxy, inspect_video,
                    panorama_frame, preview_frame, render, silence_suggestions, create_panorama_proxy)
from .tracking import track_panorama
from .uploads import UploadStore, UploadIssue, MAX_CHUNK_BYTES

ROOT = Path(__file__).resolve().parent.parent
STORAGE = Path(os.environ.get("MOVIE_MODIFY_DATA", str(ROOT / "data"))).expanduser().resolve()
WEB = ROOT / "web" / "index.html"
STORAGE.mkdir(parents=True, exist_ok=True)
PASSWORD = os.environ.get("MOVIE_MODIFY_TOKEN", "")
# A single process and one heavy operation at a time protect memory / I/O usage.
EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict] = {}
PREVIEW_JOBS: dict[str, str] = {}
JOB_LOCK = threading.Lock()
# Serializes read→check→write for every project mutation, including background jobs.
PROJECT_LOCK = threading.RLock()
UPLOADS = UploadStore(STORAGE)
app = FastAPI(title="Movie Modify", docs_url=None, redoc_url=None)


class EditPayload(BaseModel):
    segments: list[dict]
    expected_revision: int


class RestoreRevisionPayload(BaseModel):
    target_revision: int
    expected_revision: int


class AnalyzePayload(BaseModel):
    method: str = "silence"
    noise_db: int = -36
    min_seconds: float = 3.0


class ApplyPayload(BaseModel):
    indices: list[int]
    expected_revision: int


class RenderPayload(BaseModel):
    size: str = "720p"


class TrackPayload(BaseModel):
    segment_index: int
    x: float
    y: float
    box: float = 0.10
    expected_revision: int
    start_time: float | None = None


class UploadStartPayload(BaseModel):
    filename: str
    size: int
    projection: str = "flat"
    last_modified: int = 0


class LoginPayload(BaseModel):
    password: str


@app.middleware("http")
async def restrict_api(request: Request, call_next):
    # Optional LAN passphrase. On untrusted networks, run behind HTTPS + auth.
    if PASSWORD and request.url.path.startswith("/api/") and request.url.path not in ("/api/login", "/api/health"):
        provided = request.cookies.get("movie_modify_auth", "")
        if not hmac.compare_digest(provided, PASSWORD):
            return JSONResponse({"detail": "Login required"}, status_code=401)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def homepage():
    return WEB.read_text(encoding="utf-8")


# The same GitHub Pages editor can run on the local server. Pages (HTTPS)
# cannot directly call an HTTP/LAN backend because browsers block mixed content
# and Private Network Access requests. Serving this at one origin avoids CORS.
@app.get("/studio")
def studio_redirect():
    return RedirectResponse(url="/studio/", status_code=307)


@app.get("/studio/", response_class=HTMLResponse)
def studio_home():
    return (ROOT / "docs" / "index.html").read_text(encoding="utf-8")


@app.get("/studio/pages.js")
def studio_script():
    return FileResponse(ROOT / "docs" / "pages.js", media_type="text/javascript")


@app.get("/studio/pages.css")
def studio_styles():
    return FileResponse(ROOT / "docs" / "pages.css", media_type="text/css")


@app.get("/studio/live_preview.js")
def studio_webgl():
    return FileResponse(ROOT / "docs" / "live_preview.js", media_type="text/javascript")


@app.get("/studio/edit_history.js")
def studio_edit_history():
    return FileResponse(ROOT / "docs" / "edit_history.js", media_type="text/javascript")


@app.get("/studio/bridge_client.js")
def studio_bridge():
    return FileResponse(ROOT / "docs" / "bridge_client.js", media_type="text/javascript")


@app.get("/assets/responsive_ui.css")
def adaptive_editor_css():
    return FileResponse(ROOT / "web" / "responsive_ui.css", media_type="text/css")


@app.get("/assets/responsive_ui.js")
def adaptive_editor_js():
    return FileResponse(ROOT / "web" / "responsive_ui.js", media_type="text/javascript")


@app.get("/assets/edit_history.js")
def advanced_edit_history():
    return FileResponse(ROOT / "docs" / "edit_history.js", media_type="text/javascript")


@app.get("/assets/live_preview.js")
def panorama_viewer_script():
    """Serve client renderer locally; no CDN required."""
    return FileResponse(ROOT / "web" / "live_preview.js", media_type="text/javascript")


@app.post("/api/login")
def login(payload: LoginPayload, response: Response):
    if not PASSWORD or not hmac.compare_digest(payload.password, PASSWORD):
        raise HTTPException(401, "Incorrect access token")
    response.set_cookie("movie_modify_auth", PASSWORD, httponly=True, samesite="strict", secure=False)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ffmpeg": available("ffmpeg"), "ffprobe": available("ffprobe"),
            "auto_editor": available("auto-editor"),
            "tracking": importlib.util.find_spec("cv2") is not None, "auth_required": bool(PASSWORD),
            "storage": str(STORAGE)}


def _directory(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", project_id):
        raise HTTPException(404, "Unknown project")
    directory = STORAGE / project_id
    if not directory.is_dir():
        raise HTTPException(404, "Unknown project")
    return directory


def _project(project_id: str) -> dict:
    with PROJECT_LOCK:
        result = json.loads((_directory(project_id) / "project.json").read_text(encoding="utf-8"))
        # Compatibility with pre-R03 projects.
        result.setdefault("edit_revision", 0)
        return result


def _save(project: dict):
    with PROJECT_LOCK:
        directory = _directory(project["id"])
        project.setdefault("edit_revision", 0)
        temp = directory / ("project." + uuid.uuid4().hex + ".tmp")
        try:
            temp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(directory / "project.json")
        finally:
            temp.unlink(missing_ok=True)


def _require_revision(project: dict, expected: int) -> None:
    if expected != project["edit_revision"]:
        raise HTTPException(status_code=409, detail={
            "code": "revision_conflict",
            "message": "Other device or tab saved newer edits. Reload before saving.",
            "current_revision": project["edit_revision"],
        })


def _revision_folder(project_id: str) -> Path:
    folder = _directory(project_id) / "edit_history"
    folder.mkdir(mode=0o700, exist_ok=True)
    return folder


def _archive_edits(project: dict) -> None:
    """Persist a compressed edit-only checkpoint before changing the EDL."""
    folder = _revision_folder(project["id"])
    filename = folder / f"{project['edit_revision']:010d}.json.gz"
    if not filename.exists():
        temporary = folder / ("history." + uuid.uuid4().hex + ".tmp")
        try:
            with gzip.open(temporary, "wt", encoding="utf-8") as stream:
                json.dump({
                    "revision": project["edit_revision"],
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "segments": project["segments"],
                }, stream, ensure_ascii=False)
            temporary.replace(filename)
        finally:
            temporary.unlink(missing_ok=True)
    # Preserve the last 30 checkpoints. Video bytes are never duplicated.
    old = sorted(folder.glob("[0-9]*.json.gz"))
    for entry in old[:-30]:
        entry.unlink(missing_ok=True)


def _commit_edits(project: dict, segments: list[dict]) -> dict:
    if segments != project["segments"]:
        _archive_edits(project)
        project["segments"] = segments
        project["edit_revision"] += 1
        _save(project)
    return project


def _job(fn):
    job_id = uuid.uuid4().hex
    with JOB_LOCK:
        JOBS[job_id] = {"id": job_id, "state": "queued", "progress": 0, "error": None}

    def update(progress):
        with JOB_LOCK:
            JOBS[job_id]["progress"] = progress

    def runner():
        with JOB_LOCK:
            JOBS[job_id]["state"] = "running"
        try:
            fn(update)
        except Exception as exc:
            with JOB_LOCK:
                JOBS[job_id]["state"] = "failed"
                JOBS[job_id]["error"] = str(exc)[-1200:]
        else:
            with JOB_LOCK:
                JOBS[job_id]["state"] = "done"
                JOBS[job_id]["progress"] = 100

    EXECUTOR.submit(runner)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    return JOBS[job_id]


@app.get("/api/projects")
def projects():
    items = []
    for file in STORAGE.glob("*/project.json"):
        try:
            entry = json.loads(file.read_text(encoding="utf-8"))
            items.append({k: entry[k] for k in ("id", "name", "projection", "duration", "width", "height", "proxy_ready")})
        except (KeyError, ValueError, OSError):
            pass
    return sorted(items, key=lambda x: x["id"], reverse=True)


@app.exception_handler(UploadIssue)
async def upload_issue_handler(_request: Request, issue: UploadIssue):
    return JSONResponse(status_code=issue.status, content={"detail": {
        "code": issue.code, "message": str(issue), **issue.metadata
    }})


@app.post("/api/uploads")
def create_resumable_upload(payload: UploadStartPayload):
    if not available("ffprobe") or not available("ffmpeg"):
        raise HTTPException(503, "Install ffmpeg and ffprobe")
    return UPLOADS.create(payload.filename, payload.size, payload.projection,
                          payload.last_modified)


@app.get("/api/uploads/{session_id}")
def get_resumable_upload(session_id: str):
    return UPLOADS.status(session_id)


@app.put("/api/uploads/{session_id}/chunk")
async def receive_video_chunk(session_id: str, request: Request, offset: int):
    data = bytearray()
    async for piece in request.stream():
        data.extend(piece)
        if len(data) > MAX_CHUNK_BYTES:
            raise HTTPException(413, "Upload chunk exceeds 8 MiB")
    return UPLOADS.append(session_id, offset, bytes(data))


@app.delete("/api/uploads/{session_id}")
def cancel_resumable_upload(session_id: str):
    # Do not delete the original video of a completed project.
    with UPLOADS.lock:
        meta = UPLOADS.status(session_id)
        if meta["completed"]:
            raise HTTPException(409, "Completed upload cannot be deleted")
        shutil.rmtree(UPLOADS._dir(session_id))
    return {"ok": True}


@app.post("/api/uploads/{session_id}/complete")
def complete_resumable_upload(session_id: str):
    # The session lock makes duplicate commit attempts idempotent.
    with UPLOADS.lock:
        meta = UPLOADS.status(session_id)
        if meta["completed"]:
            project = _project(meta["project_id"])
            return {"project": project, "job_id": meta["job_id"],
                    "completed": True}
        meta, part = UPLOADS.ready_source(session_id)
        metadata = inspect_video(part)
        if meta["projection"] == "equirect" and metadata["width"] / max(metadata["height"], 1) < 1.7:
            raise HTTPException(400, "360 footage must be stitched to equirectangular format")
        project_id = uuid.uuid4().hex
        directory = STORAGE / project_id
        directory.mkdir(mode=0o700)
        suffix = Path(meta["filename"]).suffix.lower()
        source = directory / ("original" + suffix)
        try:
            shutil.move(str(part), str(source))
            project = dict(
                id=project_id, name=meta["filename"],
                projection=meta["projection"], source_name=source.name,
                proxy_ready=False, suggestions=[], edit_revision=0,
                segments=[fresh_segment(0, metadata["duration"])], **metadata
            )
            _save(project)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

        def make_proxy(update):
            if meta["projection"] == "equirect":
                create_panorama_proxy(source, directory / "proxy360.mp4")
            else:
                create_proxy(source, directory / "proxy.mp4", meta["projection"])
            with PROJECT_LOCK:
                latest = _project(project_id)
                latest["proxy_ready"] = True
                _save(latest)

        task = _job(make_proxy)
        if meta["projection"] == "equirect":
            with JOB_LOCK:
                PREVIEW_JOBS[project_id] = task["job_id"]
        UPLOADS.mark_complete(session_id, project_id, task["job_id"])
        return {"project": project, **task, "completed": True}


@app.post("/api/projects")
async def import_video(file: UploadFile = File(...), projection: str = Form("flat")):
    if projection not in ("flat", "equirect"):
        raise HTTPException(400, "Only flat or already-stitched equirect videos are supported")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".mp4", ".mov", ".m4v", ".mkv", ".webm"):
        raise HTTPException(400, "Convert camera-native footage to MP4/MOV first")
    if not available("ffprobe") or not available("ffmpeg"):
        raise HTTPException(503, "Install ffmpeg and ffprobe")
    project_id = uuid.uuid4().hex
    directory = STORAGE / project_id
    directory.mkdir(mode=0o700)
    source = directory / f"original{ext}"
    total = 0
    try:
        with source.open("wb") as out:
            while chunk := await file.read(4 * 1024 * 1024):
                total += len(chunk)
                if total > 50 * 1024**3:
                    raise HTTPException(413, "Video exceeds 50 GiB upload limit")
                out.write(chunk)
        metadata = inspect_video(source)
        if projection == "equirect" and metadata["width"] / max(metadata["height"], 1) < 1.7:
            raise HTTPException(400, "360 equirectangular input must be approximately 2:1")
        project = dict(id=project_id, name=Path(file.filename or "Video").name, projection=projection,
                       source_name=source.name, proxy_ready=False, suggestions=[],
                       edit_revision=0, segments=[fresh_segment(0, metadata["duration"])], **metadata)
        _save(project)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        await file.close()

    def make_proxy(update):
        if projection == "equirect":
            # New 360 imports need just one low-resolution 2:1 proxy.
            # The live WebGL viewport replaces the old fixed-angle transcode.
            create_panorama_proxy(source, directory / "proxy360.mp4")
        else:
            create_proxy(source, directory / "proxy.mp4", projection)
        with PROJECT_LOCK:
            latest = _project(project_id)
            latest["proxy_ready"] = True
            _save(latest)
    task = _job(make_proxy)
    if projection == "equirect":
        # Reuse the upload transcoding job if the editor opens before it finishes.
        with JOB_LOCK:
            PREVIEW_JOBS[project_id] = task["job_id"]
    return {"project": project, **task}


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str):
    return _project(project_id)


@app.get("/api/projects/{project_id}/preview")
def preview(project_id: str):
    directory = _directory(project_id)
    path = directory / "proxy.mp4"
    if not path.is_file() and _project(project_id)["projection"] == "equirect":
        path = directory / "proxy360.mp4"
    if not path.is_file():
        raise HTTPException(409, "Proxy still processing")
    return FileResponse(path, media_type="video/mp4", filename="preview.mp4", content_disposition_type="inline")


@app.post("/api/projects/{project_id}/prepare-preview360")
def prepare_preview360(project_id: str):
    """Build once; legacy projects receive their pano proxy on demand."""
    project = _project(project_id)
    if project["projection"] != "equirect":
        raise HTTPException(400, "Panoramic playback requires equirectangular footage")
    directory = _directory(project_id)
    output = directory / "proxy360.mp4"
    if output.is_file():
        return {"ready": True}
    with JOB_LOCK:
        active_id = PREVIEW_JOBS.get(project_id)
        if active_id and JOBS.get(active_id, {}).get("state") in ("queued", "running"):
            return {"ready": False, "job_id": active_id}

    def transcode(update):
        temp = directory / "proxy360_work.mp4"
        try:
            create_panorama_proxy(directory / project["source_name"], temp)
            temp.replace(output)
            update(100)
        finally:
            temp.unlink(missing_ok=True)

    result = _job(transcode)
    with JOB_LOCK:
        PREVIEW_JOBS[project_id] = result["job_id"]
    return {"ready": False, **result}


@app.get("/api/projects/{project_id}/preview360")
def preview360(project_id: str):
    project = _project(project_id)
    if project["projection"] != "equirect":
        raise HTTPException(400, "Not an equirectangular project")
    output = _directory(project_id) / "proxy360.mp4"
    if not output.is_file():
        raise HTTPException(409, "Panoramic preview is not prepared yet")
    return FileResponse(output, media_type="video/mp4",
                        filename="preview360.mp4", content_disposition_type="inline")


@app.get("/api/projects/{project_id}/frame")
def frame(project_id: str, time: float = 0, yaw: float = 0, pitch: float = 0, fov: float = 90):
    project = _project(project_id)
    if not 0 <= time <= project["duration"] or not -180 <= yaw <= 180 or not -90 <= pitch <= 90 or not 35 <= fov <= 140:
        raise HTTPException(400, "Invalid frame params")
    source = _directory(project_id) / project["source_name"]
    try:
        data = preview_frame(source, time, project["projection"], yaw, pitch, fov)
    except Exception as exc:
        raise HTTPException(500, str(exc)[-300:]) from exc
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})



@app.get("/api/projects/{project_id}/panorama")
def panorama(project_id: str, time: float = 0):
    project = _project(project_id)
    if project["projection"] != "equirect":
        raise HTTPException(422, "360 panorama only")
    if not 0 <= time < project["duration"]:
        raise HTTPException(400, "Invalid source time")
    try:
        data = panorama_frame(_directory(project_id) / project["source_name"], time)
    except Exception as exc:
        raise HTTPException(500, str(exc)[-300:]) from exc
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{project_id}/track")
def track(project_id: str, payload: TrackPayload):
    project = _project(project_id)
    if project["projection"] != "equirect":
        raise HTTPException(422, "Tracking requires stitched 360 footage")
    if importlib.util.find_spec("cv2") is None:
        raise HTTPException(503, "pip install -r requirements-tracking.txt")
    if not 0 <= payload.segment_index < len(project["segments"]):
        raise HTTPException(422, "Unknown segment")
    _require_revision(project, payload.expected_revision)
    segment = project["segments"][payload.segment_index]
    if not segment["keep"]:
        raise HTTPException(422, "Cannot track removed interval")
    if not 0 <= payload.x <= 1 or not .02 <= payload.y <= .98 or not .04 <= payload.box <= .24:
        raise HTTPException(422, "Invalid target")
    if segment["end"] - segment["start"] > 1200:
        raise HTTPException(422, "Split into segments of 20 minutes or less")
    # A human can reselect the person at a later source-time position,
    # preserving reliable tracking before that point.
    begin = segment["start"] if payload.start_time is None else payload.start_time
    if not math.isfinite(begin) or begin < segment["start"] - .001 or begin > segment["end"] - .25:
        raise HTTPException(422, "Restart time must be inside the selected segment")
    begin = max(segment["start"], begin)
    if begin > segment["start"] + .05 and (
        segment.get("mode") != "follow" or not segment.get("keyframes")
    ):
        raise HTTPException(422, "First track this segment before correcting its suffix")
    path = _directory(project_id) / project["source_name"]

    def work(update):
        keys, warning, gaps = track_panorama(
            path, begin, segment["end"], payload.x, payload.y,
            payload.box, callback=update, include_diagnostics=True
        )
        with PROJECT_LOCK:
            latest = _project(project_id)
            # A saved edit while the tracker was busy invalidates the result.
            _require_revision(latest, payload.expected_revision)
            if payload.segment_index >= len(latest["segments"]):
                raise RuntimeError("Timeline changed during tracking")
            candidate = latest["segments"][payload.segment_index]
            if candidate != segment:
                raise RuntimeError("Selected segment changed during tracking")
            if begin > segment["start"] + .05:
                prefix = [k for k in segment.get("keyframes", [])
                          if k["time"] < begin - .0001]
                # Keep a key just before the correction boundary so the
                # earlier trajectory remains unchanged by interpolation.
                before = max(segment["start"], round(begin - .01, 4))
                if before > segment["start"] and (
                    not prefix or before > prefix[-1]["time"] + .00001
                ):
                    from .core import camera_at
                    prefix.append({"time": before, **camera_at(segment, before)})
                keys = prefix + keys
                previous = [
                    {"start": g["start"], "end": min(g["end"], begin)}
                    for g in segment.get("tracking_gaps", [])
                    if g["start"] < begin and min(g["end"], begin) > g["start"]
                ]
                gaps = previous + gaps
                if previous:
                    warning = ("前半にも追尾できなかった時間帯があります。 " + warning).strip()
            candidate.update(mode="follow", keyframes=keys,
                             tracking_gaps=gaps, tracking_warning=warning)
            normalized = normalize_segments(latest["segments"], latest["duration"])
            _commit_edits(latest, normalized)
        update(100)
    return _job(work)


@app.put("/api/projects/{project_id}/edits")
def save_edits(project_id: str, payload: EditPayload):
    with PROJECT_LOCK:
        project = _project(project_id)
        _require_revision(project, payload.expected_revision)
        try:
            normalized = normalize_segments(payload.segments, project["duration"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _commit_edits(project, normalized)


@app.get("/api/projects/{project_id}/edit-history")
def edit_history(project_id: str):
    with PROJECT_LOCK:
        current = _project(project_id)
        folder = _revision_folder(project_id)
        earlier = []
        for file in sorted(folder.glob("[0-9]*.json.gz"), reverse=True):
            try:
                number = int(file.name.split(".")[0])
                earlier.append({"revision": number, "archived": True,
                                "saved_at": datetime.fromtimestamp(
                                    file.stat().st_mtime, timezone.utc).isoformat()})
            except (ValueError, OSError):
                continue
        return {"current_revision": current["edit_revision"], "revisions": [
            {"revision": current["edit_revision"], "archived": False}
        ] + earlier}


@app.post("/api/projects/{project_id}/restore-revision")
def restore_edit_revision(project_id: str, payload: RestoreRevisionPayload):
    with PROJECT_LOCK:
        current = _project(project_id)
        _require_revision(current, payload.expected_revision)
        if payload.target_revision < 0 or payload.target_revision >= current["edit_revision"]:
            raise HTTPException(422, "Unknown edit revision")
        path = _revision_folder(project_id) / f"{payload.target_revision:010d}.json.gz"
        if not path.is_file():
            raise HTTPException(404, "Edit revision no longer retained")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                checkpoint = json.load(stream)
            if checkpoint.get("revision") != payload.target_revision:
                raise ValueError("Incorrect revision archive")
            normalized = normalize_segments(checkpoint["segments"], current["duration"])
        except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
            raise HTTPException(409, "Archived edit data are invalid") from exc
        result = _commit_edits(current, normalized)
        return result


@app.post("/api/projects/{project_id}/analyze")
def analyze(project_id: str, payload: AnalyzePayload):
    project = _project(project_id)
    if payload.method not in ("silence", "auto_editor"):
        raise HTTPException(422, "Unknown analyzer")
    if not -80 <= payload.noise_db <= -10 or not 1 <= payload.min_seconds <= 60:
        raise HTTPException(422, "Invalid analysis settings")
    directory = _directory(project_id)
    source = directory / project["source_name"]
    def work(update):
        if payload.method == "silence":
            suggestions = silence_suggestions(source, project["duration"], project["has_audio"], payload.noise_db, payload.min_seconds)
        else:
            suggestions = auto_editor_suggestions(source, project["duration"], directory)
        with PROJECT_LOCK:
            current = _project(project_id)
            current["suggestions"] = suggestions
            _save(current)
    return _job(work)


@app.post("/api/projects/{project_id}/apply-suggestions")
def apply(project_id: str, payload: ApplyPayload):
    with PROJECT_LOCK:
        project = _project(project_id)
        _require_revision(project, payload.expected_revision)
        if any(type(i) is not int or i < 0 or i >= len(project["suggestions"]) for i in payload.indices):
            raise HTTPException(422, "Unknown suggestion index")
        try:
            normalized = apply_suggestions(project["segments"], project["suggestions"], payload.indices, project["duration"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _commit_edits(project, normalized)


@app.post("/api/projects/{project_id}/render")
def render_project(project_id: str, payload: RenderPayload):
    project = _project(project_id)
    if payload.size not in ("720p", "1080p"):
        raise HTTPException(422, "Unsupported resolution")
    directory = _directory(project_id)
    source = directory / project["source_name"]
    edits = normalize_segments(project["segments"], project["duration"])
    if not any(s["keep"] for s in edits):
        raise HTTPException(422, "Nothing left to render")
    def work(update):
        output = directory / "export.mp4"
        render(source, output, project["projection"], edits, size=payload.size, has_audio=project["has_audio"], callback=update)
    return _job(work)


@app.get("/api/projects/{project_id}/export")
def export(project_id: str):
    directory = _directory(project_id)
    output = directory / "export.mp4"
    if not output.exists():
        raise HTTPException(404, "Render a video first")
    return FileResponse(output, media_type="video/mp4", filename="movie_modify_export.mp4")
