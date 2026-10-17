"""R-04: bounded, resumable uploads with idempotent retry and finalization."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from movie_modify.uploads import MAX_CHUNK_BYTES, UploadIssue, UploadStore


def test_upload_store_resumes_across_instances(tmp_path):
    store = UploadStore(tmp_path)
    created = store.create("family.mp4", 9, "flat", 12345)
    uid = created["id"]
    assert store.status(uid)["received"] == 0
    assert store.append(uid, 0, b"abc")["received"] == 3
    # ACK lost: byte-identical retry must not duplicate the chunk.
    assert store.append(uid, 0, b"abc")["received"] == 3
    with pytest.raises(UploadIssue) as exc:
        store.append(uid, 0, b"xyz")
    assert exc.value.code == "offset_mismatch"
    assert exc.value.metadata["received"] == 3
    resumed = UploadStore(tmp_path)
    assert resumed.status(uid)["received"] == 3
    resumed.append(uid, 3, b"defghi")
    assert resumed.ready_source(uid)[1].read_bytes() == b"abcdefghi"
    resumed.mark_complete(uid, "a"*32, "b"*32)
    assert resumed.status(uid)["completed"] is True
    assert resumed.status(uid)["project_id"] == "a"*32


def test_rejects_wrong_size_bad_extension_and_overflow(tmp_path):
    store = UploadStore(tmp_path)
    with pytest.raises(UploadIssue):
        store.create("../family.exe", 11, "flat")
    with pytest.raises(UploadIssue):
        store.create("clip.mp4", 0, "flat")
    info = store.create("clip.mp4", 2, "equirect")
    with pytest.raises(UploadIssue) as exc:
        store.append(info["id"], 0, b"abc")
    assert exc.value.code == "upload_overflow"
    assert store.status(info["id"])["received"] == 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
def test_resumable_upload_api_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIE_MODIFY_DATA", str(tmp_path / "server"))
    import movie_modify.server as server
    importlib.reload(server)

    source = tmp_path / "family.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=1.3",
        "-c:v", "libx264", "-preset", "ultrafast",
        str(source),
    ], check=True)
    data = source.read_bytes()
    mid = len(data)//2

    with TestClient(server.app) as client:
        created = client.post("/api/uploads", json={
            "filename": "family.mp4", "size": len(data),
            "projection": "flat", "last_modified": 100,
        })
        assert created.status_code == 200, created.text
        uid = created.json()["id"]
        assert client.post(f"/api/uploads/{uid}/complete").status_code == 409
        first = client.put(f"/api/uploads/{uid}/chunk?offset=0", content=data[:mid])
        assert first.status_code == 200, first.text
        assert first.json()["received"] == mid
        assert client.put(f"/api/uploads/{uid}/chunk?offset=0",
                          content=data[:mid]).json()["received"] == mid
        wrong = client.put(f"/api/uploads/{uid}/chunk?offset=0", content=b"XYZ")
        assert wrong.status_code == 409
        assert wrong.json()["detail"]["received"] == mid

        # Disk-backed status survives a fresh manager (simulates app restart).
        assert UploadStore(server.STORAGE).status(uid)["received"] == mid
        end = client.put(f"/api/uploads/{uid}/chunk?offset={mid}",
                         content=data[mid:])
        assert end.status_code == 200, end.text
        assert end.json()["received"] == len(data)
        done = client.post(f"/api/uploads/{uid}/complete")
        assert done.status_code == 200, done.text
        project_id = done.json()["project"]["id"]
        assert done.json()["project"]["edit_revision"] == 0

        completed_again = client.post(f"/api/uploads/{uid}/complete")
        assert completed_again.status_code == 200
        assert completed_again.json()["project"]["id"] == project_id
        assert client.delete(f"/api/uploads/{uid}").status_code == 409
        assert (server.STORAGE / project_id / "original.mp4").read_bytes() == data

        end_time = time.monotonic() + 80
        while time.monotonic() < end_time:
            job = client.get("/api/jobs/" + done.json()["job_id"]).json()
            if job["state"] in ("done", "failed"):
                assert job["state"] == "done", job
                break
            time.sleep(.2)
        else:
            pytest.fail("FFmpeg proxy transcode timeout")
        assert client.get(f"/api/projects/{project_id}/preview").status_code == 200
