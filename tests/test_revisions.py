"""R-03: edited projects use conditional atomic revisions, not last-writer-wins."""
from __future__ import annotations

import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from movie_modify.core import fresh_segment


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIE_MODIFY_DATA", str(tmp_path))
    import movie_modify.server as server
    importlib.reload(server)
    identifier = "a" * 32
    directory = tmp_path / identifier
    directory.mkdir()
    baseline = {
        "id": identifier, "name": "video.mp4", "projection": "flat",
        "source_name": "original.mp4", "duration": 12.0, "width": 320,
        "height": 240, "has_audio": False, "codec": "h264",
        "proxy_ready": True, "suggestions": [
            {"start": 2, "end": 4, "reason": "quiet_audio"},
        ], "segments": [fresh_segment(0, 12)],
    }
    # Simulates a project saved before edit_revision existed.
    (directory / "project.json").write_text(json.dumps(baseline), encoding="utf-8")
    return server, identifier


def test_stale_editor_cannot_overwrite_newer_save(tmp_path, monkeypatch):
    server, pid = _fixture(tmp_path, monkeypatch)
    url = f"/api/projects/{pid}"
    with TestClient(server.app) as client:
        initial = client.get(url).json()
        assert initial["edit_revision"] == 0
        first = [dict(initial["segments"][0], keep=False)]
        result = client.put(url + "/edits", json={"segments": first, "expected_revision": 0})
        assert result.status_code == 200, result.text
        assert result.json()["edit_revision"] == 1

        stale = [dict(initial["segments"][0], yaw=60)]
        response = client.put(url + "/edits", json={"segments": stale, "expected_revision": 0})
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "revision_conflict"
        assert response.json()["detail"]["current_revision"] == 1

        live = client.get(url).json()
        assert live["edit_revision"] == 1
        assert live["segments"][0]["keep"] is False
        assert live["segments"][0]["yaw"] == 0
        # Idempotent repeated saves do not spuriously bump revision.
        again = client.put(url + "/edits",
                           json={"segments": live["segments"], "expected_revision": 1})
        assert again.status_code == 200
        assert again.json()["edit_revision"] == 1


def test_suggestion_edits_also_require_fresh_revision(tmp_path, monkeypatch):
    server, pid = _fixture(tmp_path, monkeypatch)
    with TestClient(server.app) as client:
        url = f"/api/projects/{pid}"
        res = client.post(url + "/apply-suggestions",
                          json={"indices": [0], "expected_revision": 0})
        assert res.status_code == 200, res.text
        assert res.json()["edit_revision"] == 1
        assert any(not x["keep"] for x in res.json()["segments"])
        outdated = client.post(url + "/apply-suggestions",
                               json={"indices": [0], "expected_revision": 0})
        assert outdated.status_code == 409
        assert client.get(url).json()["edit_revision"] == 1
        missing = client.put(url + "/edits", json={"segments": [fresh_segment(0, 12)]})
        assert missing.status_code == 422  # No silent unguarded write.


def test_racing_writes_accept_exactly_one_revision(tmp_path, monkeypatch):
    server, pid = _fixture(tmp_path, monkeypatch)
    url = f"/api/projects/{pid}/edits"
    gate = threading.Barrier(2)

    def writer(yaw):
        with TestClient(server.app) as client:
            gate.wait(timeout=10)
            return client.put(url, json={
                "segments": [dict(fresh_segment(0, 12), yaw=yaw)],
                "expected_revision": 0,
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(writer, [30, -40]))
    assert sorted(results) == [200, 409]
    with TestClient(server.app) as client:
        assert client.get(f"/api/projects/{pid}").json()["edit_revision"] == 1


def test_proxy_metadata_update_preserves_edit_revision(tmp_path, monkeypatch):
    server, pid = _fixture(tmp_path, monkeypatch)
    with server.PROJECT_LOCK:
        project = server._project(pid)
        project["proxy_ready"] = False
        server._save(project)
    assert server._project(pid)["edit_revision"] == 0
