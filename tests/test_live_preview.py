"""Regression tests for the on-demand 2:1 panorama preview."""
import importlib
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from movie_modify.media import inspect_video


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
def test_panorama_preview_from_existing_project(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_MODIFY_DATA", str(tmp_path / "data"))
    import movie_modify.server as server
    importlib.reload(server)

    sample = tmp_path / "panorama.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=480x240:rate=12:duration=1.5",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(sample),
    ], check=True)

    with TestClient(server.app) as client:
        with sample.open("rb") as inp:
            response = client.post(
                "/api/projects",
                files={"file": ("sample.mp4", inp, "video/mp4")},
                data={"projection": "equirect"},
            )
        assert response.status_code == 200, response.text
        pid = response.json()["project"]["id"]
        assert client.get(f"/api/projects/{pid}/preview360").status_code == 409
        start = client.post(f"/api/projects/{pid}/prepare-preview360")
        assert start.status_code == 200, start.text
        assert "job_id" in start.json() or start.json().get("ready") is True
        if not start.json().get("ready"):
            end = time.monotonic() + 70
            while time.monotonic() < end:
                status = client.get(f"/api/jobs/{start.json()['job_id']}").json()
                if status["state"] in ("done", "failed"):
                    assert status["state"] == "done", status
                    break
                time.sleep(0.2)
            else:
                pytest.fail("Panorama proxy generation timed out")
        result = client.get(f"/api/projects/{pid}/preview360")
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("video/mp4")
        meta = inspect_video(tmp_path / "data" / pid / "proxy360.mp4")
        assert (meta["width"], meta["height"]) == (1280, 640)
        repeated = client.post(f"/api/projects/{pid}/prepare-preview360")
        assert repeated.json() == {"ready": True}
        script = client.get("/assets/live_preview.js")
        assert script.status_code == 200
        assert "LivePanoramaPreview" in script.text
