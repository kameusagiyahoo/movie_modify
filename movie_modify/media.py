"""Replaceable media adapters: probing, analysis, proxy and final render.

Manufacturer-specific dual-fisheye formats are deliberately not decoded here.
Convert those to equirectangular MP4 with the vendor's tooling first.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from .core import camera_at, merge_intervals, parse_auto_editor_v1


def run(args: list[str], *, timeout: int = 7200) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-2200:] or f"Command failed: {args[0]}")
    return result


def available(name: str) -> bool:
    return shutil.which(name) is not None


def inspect_video(path: Path) -> dict:
    result = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], timeout=180)
    info = json.loads(result.stdout)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("No video stream found")
    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    if not 0 < duration <= 48 * 3600:
        raise ValueError("Unsupported video duration")
    return {"duration": round(duration, 3), "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
            "codec": video.get("codec_name", "unknown")}


def view_filter(yaw: float = 0, pitch: float = 0, fov: float = 90, *, name: str = "") -> str:
    return f"v360{name}=input=equirect:output=flat:yaw={yaw:.3f}:pitch={pitch:.3f}:h_fov={fov:.3f}:v_fov={fov * 9 / 16:.3f}"


def build_filters(projection: str, segment: dict, *, width: int = 1280, height: int = 720) -> str:
    filters = []
    if projection == "equirect":
        filters.append(view_filter(segment["yaw"], segment["pitch"], segment["fov"]))
    filters.extend([f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2", "setsar=1", "fps=30", "format=yuv420p"])
    return ",".join(filters)


def create_proxy(source: Path, dest: Path, projection: str):
    filt = build_filters(projection, {"yaw": 0, "pitch": 0, "fov": 90}, width=960, height=540)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-vf", filt, "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-threads", "2",
         "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dest)], timeout=21600)


def preview_frame(source: Path, time: float, projection: str, yaw: float, pitch: float, fov: float) -> bytes:
    filt = build_filters(projection, {"yaw": yaw, "pitch": pitch, "fov": fov}, width=640, height=360)
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(time),
                           "-i", str(source), "-vf", filt, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                          capture_output=True, timeout=90)
    if proc.returncode or not proc.stdout:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-400:])
    return proc.stdout



def panorama_frame(source: Path, time: float) -> bytes:
    """Unprojected 2:1 360 panorama for touch-to-select targets."""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(time),
                           "-i", str(source), "-vf", "scale=960:480,setsar=1",
                           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                          capture_output=True, timeout=90)
    if proc.returncode or not proc.stdout:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-400:])
    return proc.stdout


def animated_filter(segment: dict, file: Path, width: int, height: int) -> str:
    """Use v360 runtime commands to apply moving camera pose at 5 Hz."""
    start, end = segment["start"], segment["end"]
    commands = []
    for i in range(math.ceil((end - start) * 5) + 1):
        at = min(end, start + i / 5)
        pose = camera_at(segment, at)
        for key, value in (("yaw", pose["yaw"]), ("pitch", pose["pitch"]),
                           ("h_fov", pose["fov"]), ("v_fov", pose["fov"] * 9 / 16)):
            commands.append(f"{at-start:.4f} v360@view {key} {value:.4f};")
    file.write_text("\n".join(commands) + "\n", encoding="utf-8")
    first = camera_at(segment, start)
    return (f"fps=30,sendcmd=f='{file}'," + 
            view_filter(first["yaw"], first["pitch"], first["fov"], name="@view") +
            f",scale={width}:{height}:force_original_aspect_ratio=decrease," +
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")


def silence_suggestions(source: Path, duration: float, has_audio: bool, noise_db: int = -36, min_seconds: float = 3) -> list[dict]:
    if not has_audio:
        return []
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(source), "-vn", "-af",
           f"silencedetect=noise={noise_db}dB:d={min_seconds}", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=21600)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-1200:])
    starts = re.findall(r"silence_start:\s*([0-9.]+)", proc.stderr)
    ends = re.findall(r"silence_end:\s*([0-9.]+)", proc.stderr)
    # Preserve short context on each side rather than deleting entire silences.
    ranges = []
    for i, raw_start in enumerate(starts):
        start = float(raw_start)
        end = float(ends[i]) if i < len(ends) else duration
        if end - start >= min_seconds:
            ranges.append((start + 0.8, end - 0.8))
    return merge_intervals(ranges, duration, min_length=max(0.4, min_seconds - 1.6))


def auto_editor_suggestions(source: Path, duration: float, workspace: Path) -> list[dict]:
    if not available("auto-editor"):
        raise RuntimeError("auto-editor is not installed. Install with: pip install auto-editor")
    dest = workspace / "auto_edit.v1"
    run(["auto-editor", str(source), "--export", "v1", "-o", str(dest)], timeout=21600)
    return parse_auto_editor_v1(json.loads(dest.read_text(encoding="utf-8")), duration)


def render(source: Path, dest: Path, projection: str, segments: list[dict], *, size: str = "720p", has_audio: bool = True, callback=None):
    """Render each kept source range with own camera viewport; concat losslessly.

    Moving 360 camera trajectories are rendered via FFmpeg v360 commands.
    """
    resolution = {"720p": (1280, 720), "1080p": (1920, 1080)}[size]
    kept = [s for s in segments if s["keep"]]
    if not kept:
        raise ValueError("All segments are cut")
    work = dest.parent / "render_parts"
    work.mkdir(parents=True, exist_ok=True)
    parts = []
    try:
        for index, seg in enumerate(kept):
            out = work / f"part_{index:05}.mp4"
            if projection == "equirect" and len(seg.get("keyframes", [])) > 1:
                vf = animated_filter(seg, work / f"commands_{index:05}.txt", *resolution)
            else:
                view = camera_at(seg, seg["start"])
                vf = build_filters(projection, {**seg, **view}, width=resolution[0], height=resolution[1])
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(seg["start"]),
                   "-i", str(source), "-t", str(round(seg["end"] - seg["start"], 3)),
                   "-map", "0:v:0", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "2"]
            if has_audio:
                cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
            else:
                cmd += ["-an"]
            cmd += ["-movflags", "+faststart", str(out)]
            run(cmd, timeout=21600)
            parts.append(out)
            if callback:
                callback(int(90 * (index + 1) / len(kept)))
        concat_file = work / "files.txt"
        concat_file.write_text("".join(f"file '{str(p)}'\n" for p in parts), encoding="utf-8")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(dest)], timeout=21600)
        if callback:
            callback(100)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def create_panorama_proxy(source: Path, dest: Path) -> None:
    """Make an *unprojected* lightweight 2:1 browser video.

    Unlike create_proxy(), this keeps all directions available to the live
    WebGL camera. The source media is never uploaded outside this computer.
    """
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=1280:640:flags=bicubic,setsar=1,fps=24,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
        "-threads", "2", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(dest),
    ], timeout=21600)
