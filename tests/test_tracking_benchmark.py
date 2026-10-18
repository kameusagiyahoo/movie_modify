"""Synthetic benchmark correctness, result persistence, and local HTTP workflow."""
from __future__ import annotations

import importlib
import json
import math
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from movie_modify.benchmark import (
    CASES, evaluate, generate_case, position, predicted_pose,
    run_suite, wrap_angle,
)


def test_360_seam_is_shortest_distance_and_interpolates():
    assert wrap_angle(359) == -1
    keys = [
        {"time": 0.0, "yaw": 175, "pitch": 0},
        {"time": 1.0, "yaw": -175, "pitch": 10},
    ]
    mid = predicted_pose(keys, .5)
    assert abs(abs(mid[0])-180) < .0001
    assert mid[1] == 5
    truth = [{"time": .5, "x": 0.0, "y": .5, "visible": True}]
    metrics = evaluate(truth, keys, [], elapsed=1, duration=1, fps=4)
    assert metrics["success_rate_visible"] == 1
    assert metrics["mean_center_error_deg"] == 5


def test_visibility_masks_occlusion_but_flags_false_lock():
    keys = [{"time": 0, "yaw": -90, "pitch": 0},
            {"time": 1, "yaw": -90, "pitch": 0}]
    truth = [
        {"time": 0.0, "x": .25, "y": .5, "visible": True},
        {"time": .25, "x": .25, "y": .5, "visible": False},
        {"time": .5, "x": .25, "y": .5, "visible": False},
        {"time": .75, "x": .25, "y": .5, "visible": True},
    ]
    out = evaluate(truth, keys, [{"start": .25, "end": .5}],
                   elapsed=.5, duration=1, fps=4)
    assert out["visible_samples"] == 2
    assert out["occluded_samples"] == 2
    assert out["success_rate_visible"] == 1
    assert out["false_tracking_fraction_occluded"] == .5
    assert out["untrusted_seconds"] == .25
    assert out["reacquisition_latency_s"] == 0


def test_case_truth_deterministic_and_has_occlusion():
    for case in CASES:
        initial = [position(case, i, 20) for i in range(20)]
        assert initial == [position(case, i, 20) for i in range(20)]
    seam = [position("seam", i, 20)[0] for i in range(20)]
    assert any(abs(a-b) > .8 for a,b in zip(seam,seam[1:]))
    assert any(not position("occlusion", i, 20)[2] for i in range(20))
    with pytest.raises(ValueError):
        position("not-a-case", 0, 20)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required")
def test_generate_synthetic_source_and_ground_truth(tmp_path):
    samples = generate_case(tmp_path / "seam.mp4", "seam", 103, fps=2, duration=2)
    assert len(samples) == 4
    assert samples[0]["visible"]
    assert (tmp_path / "seam.mp4").stat().st_size > 1000
    assert samples[-1]["time"] == 1.5


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe") and
         __import__("importlib").util.find_spec("cv2") and
         __import__("importlib").util.find_spec("numpy")),
    reason="OpenCV, NumPy, FFmpeg needed",
)
def test_real_tracker_smoke_on_synthetic_video(tmp_path):
    report = run_suite(tmp_path / "reports", cases=["steady"], seed=103, fps=2, duration=2)
    assert report["schema"] == "movie-modify-benchmark/v1"
    assert report["summary"]["case_count"] == 1
    metrics = report["cases"][0]["metrics"]
    assert metrics["samples"] == 4
    assert metrics["visible_samples"] == 4
    assert 0 <= metrics["success_rate_visible"] <= 1
    assert math.isfinite(metrics["mean_center_error_deg"])
    assert metrics["process_fps"] > 0
    assert json.loads((tmp_path/"reports"/(report["id"]+".json")).read_text())["id"] == report["id"]


def test_benchmark_api_job_and_readback(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIE_MODIFY_DATA", str(tmp_path / "data"))
    import movie_modify.server as server
    importlib.reload(server)

    def fake_suite(directory, *, cases, seed, fps, duration, callback):
        callback(100)
        directory.mkdir(parents=True, exist_ok=True)
        entry = {
            "id": "e"*32, "schema": "movie-modify-benchmark/v1",
            "created_at": "2026-10-18T10:00:00+00:00",
            "tracker_version": "test-only",
            "configuration": {"seed": seed, "fps": fps, "duration": duration,
                              "cases": cases},
            "summary": {"case_count": len(cases), "mean_success_rate_visible": .5,
                        "mean_center_error_deg": 4, "total_wall_time_s": 1},
            "cases": [],
        }
        (directory / (entry["id"]+".json")).write_text(json.dumps(entry), encoding="utf-8")
        return entry

    monkeypatch.setattr(server, "run_benchmark_suite", fake_suite)
    monkeypatch.setattr(server, "available", lambda command: True)
    monkeypatch.setattr(server.importlib.util, "find_spec", lambda name: object())
    with TestClient(server.app) as client:
        assert client.get("/api/benchmarks").json() == []
        bad = client.post("/api/benchmarks/run", json={"cases": ["unknown"]})
        assert bad.status_code == 422
        started = client.post("/api/benchmarks/run",json={"cases": ["seam"], "fps": 4, "duration": 5})
        assert started.status_code == 200,started.text
        job = started.json()["job_id"]
        for _ in range(200):
            progress = client.get("/api/jobs/"+job).json()
            if progress["state"] != "queued" and progress["state"] != "running":
                break
            time.sleep(.03)
        assert progress["state"] == "done",progress
        listing = client.get("/api/benchmarks").json()
        assert listing[0]["summary"]["case_count"] == 1
        assert listing[0]["id"] == "e"*32
        single = client.get("/api/benchmarks/"+"e"*32)
        assert single.status_code == 200
        assert single.json()["configuration"]["cases"] == ["seam"]
        assert client.get("/api/benchmarks/../../etc/passwd").status_code != 200
        assert client.get("/api/benchmarks/"+"x"*32).status_code == 404


def test_ui_has_run_and_comparison_controls():
    app = (Path(__file__).resolve().parents[1] / "web/index.html").read_text(encoding="utf-8")
    assert 'id="benchmarkPanel"' in app
    assert 'id="benchmarkRun"' in app
    assert 'id="benchmarkChoice"' in app
    assert "startSyntheticBenchmark" in app
    assert "showBenchmarkReport" in app
    assert "mean_success_rate_visible" in app
