"""R-10: durable EDL history, safe revision restoration, no media duplication."""
from __future__ import annotations

import gzip
import importlib
import json

from fastapi.testclient import TestClient

from movie_modify.core import fresh_segment


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIE_MODIFY_DATA", str(tmp_path))
    import movie_modify.server as server
    importlib.reload(server)
    pid = "b" * 32
    folder = tmp_path / pid
    folder.mkdir()
    project = {
        "id":pid, "name":"vacation.mp4", "projection":"flat",
        "duration":10.0, "source_name":"original.mp4",
        "width":320, "height":240, "has_audio":False, "codec":"h264",
        "segments":[fresh_segment(0,10)], "suggestions":[],
        "proxy_ready":True, "edit_revision":0
    }
    (folder / "project.json").write_text(json.dumps(project), encoding="utf-8")
    return server, pid, folder


def test_history_survives_restart_and_restores_with_fresh_revision(tmp_path, monkeypatch):
    server, pid, folder = _setup(tmp_path, monkeypatch)
    url = f"/api/projects/{pid}"
    with TestClient(server.app) as client:
        original=client.get(url).json()["segments"]
        first=[dict(original[0], yaw=35)]
        r=client.put(url+"/edits",json={"segments":first,"expected_revision":0})
        assert r.status_code == 200, r.text
        second=[dict(r.json()["segments"][0], keep=False)]
        r2=client.put(url+"/edits",json={"segments":second,"expected_revision":1})
        assert r2.status_code == 200, r2.text
        assert r2.json()["edit_revision"] == 2
        history=client.get(url+"/edit-history").json()
        assert [v["revision"] for v in history["revisions"]] == [2,1,0]
        assert (folder/"edit_history"/"0000000000.json.gz").exists()
        with gzip.open(folder/"edit_history"/"0000000000.json.gz","rt",encoding="utf-8") as inp:
            assert json.load(inp)["segments"] == original

        # Wrong baseline must not overwrite a newer user's work.
        stale=client.post(url+"/restore-revision",json={
            "target_revision":0,"expected_revision":1})
        assert stale.status_code == 409
        restored=client.post(url+"/restore-revision",json={
            "target_revision":0,"expected_revision":2})
        assert restored.status_code == 200, restored.text
        assert restored.json()["edit_revision"] == 3
        assert restored.json()["segments"] == original
        assert (folder/"edit_history"/"0000000002.json.gz").is_file()
        assert client.get(url).json()["edit_revision"] == 3

    # Durable JSON.gz files remain accessible to a new server instance.
    importlib.reload(server)
    with TestClient(server.app) as new_client:
        history=new_client.get(url+"/edit-history").json()
        assert [v["revision"] for v in history["revisions"]] == [3,2,1,0]
        assert not list((folder/"edit_history").glob("*.mp4"))


def test_history_keeps_last_30_previous_states(tmp_path, monkeypatch):
    server, pid, folder = _setup(tmp_path, monkeypatch)
    url=f"/api/projects/{pid}"
    with TestClient(server.app) as client:
        rev=0
        for index in range(35):
            payload={"segments":[dict(fresh_segment(0,10), yaw=float(index+1))],
                     "expected_revision":rev}
            result=client.put(url+"/edits",json=payload)
            assert result.status_code == 200, result.text
            rev=result.json()["edit_revision"]
        assert rev == 35
        history=client.get(url+"/edit-history").json()
        assert len(history["revisions"]) == 31  # 30 old + current
        assert history["revisions"][-1]["revision"] == 5
        missing=client.post(url+"/restore-revision",json={
            "target_revision":0,"expected_revision":35})
        assert missing.status_code == 404
