"""Pages → local studio handoff: same-origin and shared edit JSON.

The remote HTTPS Pages site deliberately never fetches a private HTTP API.
The local FastAPI server serves the same Pages UI at /studio/.
"""
import importlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_studio_assets_served_same_origin():
    import movie_modify.server as server
    with TestClient(server.app) as client:
        redirected=client.get("/studio", follow_redirects=False)
        assert redirected.status_code in (301, 302, 307, 308)
        assert redirected.headers["location"]=="/studio/"
        home=client.get("/studio/")
        assert home.status_code==200
        assert "PCの高機能エンジン" in home.text
        assert './bridge_client.js' in home.text
        for path,mime in [
            ("/studio/pages.js","text/javascript"),
            ("/studio/pages.css","text/css"),
            ("/studio/live_preview.js","text/javascript"),
            ("/studio/bridge_client.js","text/javascript")
        ]:
            asset=client.get(path)
            assert asset.status_code==200,asset.text
            assert asset.headers["content-type"].startswith(mime)


def test_browser_bridge_requires_explicit_consent_and_one_origin():
    root=Path(__file__).resolve().parents[1]
    js=(root/"docs/bridge_client.js").read_text(encoding="utf-8")
    pages=(root/"docs/pages.js").read_text(encoding="utf-8")
    html=(root/"docs/index.html").read_text(encoding="utf-8")
    assert 'window.confirm(message)' in js
    assert 'location.assign(dest)' in js
    assert '"/api/projects"' in js
    assert '"POST",body:data' in js
    assert 'credentials:"same-origin"' in js
    assert "MovieModifyPagesBridge" in pages
    assert "bridgeSync" in html and "bridgeSaveFirst" in html
    assert "localhost:8000" not in js  # no hidden/local auto-connect
    assert "fetch('http://" not in js and 'fetch("http://' not in js


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
def test_native_edl_import_preserves_view_modes(tmp_path,monkeypatch):
    monkeypatch.setenv("MOVIE_MODIFY_DATA",str(tmp_path/"projects"))
    import movie_modify.server as server
    importlib.reload(server)
    sample=tmp_path/"family.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","testsrc2=size=160x80:rate=10:duration=2",
                    "-c:v","libx264","-preset","ultrafast",str(sample)],
                    check=True)
    with TestClient(server.app) as client:
        with sample.open("rb") as fh:
            res=client.post("/api/projects",
                files={"file":("family.mp4",fh,"video/mp4")},
                data={"projection":"equirect"})
        assert res.status_code==200,res.text
        pid=res.json()["project"]["id"]
        deadline=time.monotonic()+70
        while time.monotonic()<deadline:
            state=client.get("/api/jobs/"+res.json()["job_id"]).json()
            if state["state"]=="done":break
            assert state["state"]!="failed",state
            time.sleep(.15)
        else:pytest.fail("proxy generation timeout")
        body={"segments":[
            {"start":0,"end":1,"keep":True,"mode":"follow","yaw":0,"pitch":0,
             "fov":90,"keyframes":[
                {"time":0,"yaw":0,"pitch":0,"fov":90},
                {"time":1,"yaw":70,"pitch":2,"fov":90}]},
            {"start":1,"end":2,"keep":False,"mode":"manual","yaw":120,
             "pitch":0,"fov":90,"keyframes":[]}
        ]}
        body["expected_revision"]=res.json()["project"]["edit_revision"]
        saved=client.put("/api/projects/"+pid+"/edits",json=body)
        assert saved.status_code==200,saved.text
        remote=client.get("/api/projects/"+pid).json()
        assert remote["segments"][0]["mode"]=="follow"
        assert remote["segments"][0]["keyframes"][1]["yaw"]==70
        assert remote["segments"][1]["keep"] is False
        assert remote["segments"][1]["yaw"]==120
