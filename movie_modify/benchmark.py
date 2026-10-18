"""Deterministic, offline synthetic 360-degree tracking benchmark.

The target is a synthetic textured patch, NOT a real person's identity.
Ground truth is known for each generated frame, including occlusion. Camera
centering error, held/lost intervals, and processing rate are evaluated
separately. Inputs are created locally and destroyed after the run.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .tracking import track_panorama

TRACKER_VERSION = "appearance-recovery-v2"
CASES = ("steady", "seam", "occlusion", "lookalike")


def wrap_angle(value: float) -> float:
    return (value + 180) % 360 - 180


def position(case: str, i: int, total: int) -> tuple[float, float, bool]:
    """Normalized target centre and its actual visibility, 0..1 panorama."""
    if case not in CASES or total < 2:
        raise ValueError("Unsupported case or frame count")
    progress = i / (total - 1)
    if case == "steady":
        return .24 + .27 * progress, .52, True
    if case == "seam":
        return (.90 + .23 * progress) % 1, .48, True
    if case == "occlusion":
        return .25 + .38 * progress, .52, not (.37 <= progress <= .62)
    return .22 + .16 * progress, .51, True


def generate_case(path: Path, case: str, seed: int, *, fps: int = 4,
                  duration: float = 5.0) -> list[dict]:
    """Encode an MP4 using only FFmpeg and NumPy; return exact frame labels."""
    import numpy as np

    if case not in CASES or not 2 <= fps <= 10 or not 2 <= duration <= 15:
        raise ValueError("Invalid synthetic benchmark parameters")
    width, height = 480, 240
    nframes = round(fps * duration)
    rng = np.random.default_rng(seed)
    patch = rng.integers(60, 240, (42, 42, 3), dtype=np.uint8)
    patch[3:8, 4:35] = (230, 30, 200)
    bg = np.full((height, width, 3), 22, dtype=np.uint8)
    bg[:, :, 0] += np.arange(width, dtype=np.uint8)[None, :] % 11
    bg[:, :, 1] += np.arange(height, dtype=np.uint8)[:, None] % 13

    def stamp(frame, cx, cy, tile):
        x = round(cx * width) - tile.shape[1] // 2
        y = round(cy * height) - tile.shape[0] // 2
        for col in range(tile.shape[1]):
            yy = max(0, y)
            yend = min(height, y + tile.shape[0])
            if yy < yend:
                frame[yy:yend, (x + col) % width] = tile[yy-y:yend-y, col]

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
           "-pix_fmt", "yuv420p", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    truth = []
    try:
        for i in range(nframes):
            x, y, visible = position(case, i, nframes)
            frame = bg.copy()
            if visible:
                stamp(frame, x, y, patch)
            if case == "lookalike" and i >= nframes // 3:
                stamp(frame, (x + .36) % 1, y, patch)
            truth.append({"time": round(i / fps, 4), "x": x, "y": y,
                          "visible": visible})
            if proc.stdin is None:
                raise RuntimeError("FFmpeg encoder stdin not available")
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.returncode is None:
            message = proc.stderr.read() if proc.stderr else b""
            if proc.wait(timeout=90):
                raise RuntimeError("Synthetic FFmpeg encode failed: " +
                                   message.decode("utf-8", errors="replace")[-800:])
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stderr:
            proc.stderr.close()
    return truth


def predicted_pose(keys: list[dict], seconds: float) -> tuple[float, float]:
    """Interpolate camera keyframes using the shortest 360-degree yaw path."""
    if not keys:
        raise ValueError("Missing tracker samples")
    if seconds <= keys[0]["time"]:
        return keys[0]["yaw"], keys[0]["pitch"]
    for first, second in zip(keys, keys[1:]):
        if seconds <= second["time"]:
            alpha = (seconds - first["time"]) / max(1e-9, second["time"] - first["time"])
            yaw = wrap_angle(first["yaw"] +
                             wrap_angle(second["yaw"] - first["yaw"]) * alpha)
            pitch = first["pitch"] + (second["pitch"] - first["pitch"]) * alpha
            return yaw, pitch
    return keys[-1]["yaw"], keys[-1]["pitch"]


def evaluate(truth: list[dict], keys: list[dict], gaps: list[dict],
             *, elapsed: float, duration: float, fps: int) -> dict:
    """Use visible-target denominator; never claim identity identification.

    A lost interval starts on the first untrusted sample and ends upon
    corroborated reacquisition. Error is an angular camera-center error,
    not IoU or recognition accuracy.
    """
    if not truth or not keys or fps <= 0 or elapsed <= 0:
        raise ValueError("Cannot evaluate empty tracking or invalid timing")
    errors = []
    visible = lost_visible = hidden = false_lock = 0
    samples = []
    for index, sample in enumerate(truth):
        t = sample["time"]
        yaw, pitch = predicted_pose(keys, t)
        real_yaw = (sample["x"] - .5) * 360
        real_pitch = (.5 - sample["y"]) * 180
        delta = math.hypot(wrap_angle(yaw - real_yaw), pitch - real_pitch)
        # The tracker uses frame timestamps at multiples of 1 / fps;
        # a gap's END is the first corroborated sample, not part of loss.
        lost = any(g["start"] - 1e-5 <= t < g["end"] - 1e-5 for g in gaps)
        if sample["visible"]:
            visible += 1
            errors.append(delta)
            if lost:
                lost_visible += 1
        else:
            hidden += 1
            if not lost:
                false_lock += 1
        samples.append({"time": t, "error_deg": round(delta, 3),
                        "visible": sample["visible"], "untrusted": lost})
    sorted_err = sorted(errors)
    p95 = sorted_err[min(len(sorted_err)-1, math.ceil(.95*len(sorted_err))-1)]
    # Recovery latency: how long beyond the FIRST visible sample after a
    # known occlusion it took for the untrusted interval to end.
    reacquisition = None
    if hidden:
        last_hidden = max(i for i, x in enumerate(truth) if not x["visible"])
        first_back = next((i for i in range(last_hidden+1, len(truth))
                           if truth[i]["visible"]), None)
        if first_back is not None:
            first_time = truth[first_back]["time"]
            next_trusted = next((s["time"] for s in samples[first_back:]
                                 if not s["untrusted"]), None)
            if next_trusted is not None:
                reacquisition = round(max(0, next_trusted-first_time), 3)
    good = sum(delta <= 15 for delta in errors)
    return {
        "samples": len(truth), "visible_samples": visible,
        "occluded_samples": hidden, "success_rate_visible": round(good/visible, 4) if visible else None,
        "mean_center_error_deg": round(statistics.mean(errors), 3) if errors else None,
        "median_center_error_deg": round(statistics.median(errors), 3) if errors else None,
        "p95_center_error_deg": round(p95, 3) if errors else None,
        "lost_visible_fraction": round(lost_visible/visible, 4) if visible else None,
        "false_tracking_fraction_occluded": round(false_lock/hidden, 4) if hidden else None,
        "reacquisition_latency_s": reacquisition,
        "untrusted_seconds": round(sum(g["end"]-g["start"] for g in gaps), 3),
        "process_fps": round(len(truth)/elapsed, 2),
        "wall_time_s": round(elapsed, 3),
        "source_seconds": duration, "sample_fps": fps,
        "threshold_deg": 15,
        "sample_diagnostics": samples,
    }


def run_suite(directory: Path, *, cases: list[str] | None = None,
              seed: int = 103, fps: int = 4, duration: float = 5,
              callback=None) -> dict:
    """Run same-version, deterministic synthetic scenarios and persist JSON."""
    selection = list(CASES) if cases is None else list(cases)
    if not selection or len(set(selection)) != len(selection) or any(c not in CASES for c in selection):
        raise ValueError("Unknown/duplicate benchmark scenario")
    if not 2 <= fps <= 10 or not 2 <= duration <= 15 or not 0 <= seed < 2**31:
        raise ValueError("Invalid benchmark configuration")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="mm-benchmark-") as tmp:
        for index, case in enumerate(selection):
            source = Path(tmp) / f"{case}.mp4"
            truth = generate_case(source, case, seed+index, fps=fps, duration=duration)
            first = next(p for p in truth if p["visible"])
            started = time.perf_counter()
            keys, warning, gaps = track_panorama(
                source, 0, duration, first["x"], first["y"],
                box=.10, fps=fps, include_diagnostics=True
            )
            elapsed = max(.000001, time.perf_counter()-started)
            metrics = evaluate(truth, keys, gaps, elapsed=elapsed,
                               duration=duration, fps=fps)
            # Keep report small: detailed samples have no personal data.
            records.append({"case": case, "metrics": metrics,
                            "warning": warning, "gaps": gaps})
            if callback:
                callback(round(100 * (index+1) / len(selection)))
    success = [r["metrics"]["success_rate_visible"] for r in records]
    error = [r["metrics"]["mean_center_error_deg"] for r in records]
    report = {
        "schema": "movie-modify-benchmark/v1",
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tracker_version": TRACKER_VERSION,
        "configuration": {"seed": seed, "cases": selection, "fps": fps,
                          "duration": duration, "threshold_deg": 15},
        "summary": {"case_count": len(records),
                    "mean_success_rate_visible": round(statistics.mean(success), 4),
                    "mean_center_error_deg": round(statistics.mean(error), 3),
                    "total_wall_time_s": round(sum(r["metrics"]["wall_time_s"] for r in records), 3)},
        "cases": records,
        "caveat": "Synthetic patch tracking. Camera-centering metrics cannot establish person identity or real-footage accuracy.",
    }
    output = directory / (report["id"] + ".json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline synthetic 360 tracking benchmark")
    parser.add_argument("--output-dir", type=Path, default=Path("data/benchmarks"))
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--seed", type=int, default=103)
    parser.add_argument("--fps", type=int, default=4)
    parser.add_argument("--duration", type=float, default=5)
    opts = parser.parse_args()
    result = run_suite(opts.output_dir, cases=opts.cases,
                       seed=opts.seed, fps=opts.fps, duration=opts.duration)
    print(json.dumps({"id": result["id"], "summary": result["summary"],
                      "file": str(opts.output_dir / (result["id"] + ".json"))},
                     ensure_ascii=False, indent=2))
