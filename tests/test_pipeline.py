import subprocess
import time

from fastapi.testclient import TestClient


def wait_job(client, job_id, timeout=30):
    until = time.time() + timeout
    while time.time() < until:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["state"] in ("done", "failed"):
            assert status["state"] == "done", status
            return
        time.sleep(.15)
    raise AssertionError("Timed out waiting for media job")


def test_flat_video_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_MODIFY_DATA", str(tmp_path))
    from importlib import reload
    import movie_modify.server as server
    reload(server)
    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=size=160x90:rate=12:duration=2", "-c:v", "libx264",
                    "-preset", "ultrafast", str(source)], check=True)
    with TestClient(server.app) as client:
        with source.open("rb") as stream:
            r = client.post("/api/projects", files={"file": ("demo.mp4", stream, "video/mp4")},
                            data={"projection": "flat"})
        assert r.status_code == 200, r.text
        pid = r.json()["project"]["id"]
        wait_job(client, r.json()["job_id"])
        assert client.get(f"/api/projects/{pid}/preview").status_code == 200
        r = client.post(f"/api/projects/{pid}/render", json={"size": "720p"})
        assert r.status_code == 200, r.text
        wait_job(client, r.json()["job_id"])
        assert client.get(f"/api/projects/{pid}/export").status_code == 200
