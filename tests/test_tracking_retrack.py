"""R-05: gap preservation and guarded suffix re-tracking from user-selected time."""
import importlib
import json
import time

from fastapi.testclient import TestClient

from movie_modify.core import fresh_segment, normalize_segments, slice_segment


def test_gaps_are_retained_when_splitting_360_camera_track():
    part=fresh_segment(0,8)
    part["mode"]="follow"
    part["tracking_gaps"]=[{"start":2,"end":3},{"start":6,"end":7}]
    normalized=normalize_segments([part],8)
    left=slice_segment(normalized[0],0,6.5)
    right=slice_segment(normalized[0],6.5,8)
    assert left["tracking_gaps"]==[{"start":2,"end":3},{"start":6,"end":6.5}]
    assert right["tracking_gaps"]==[{"start":6.5,"end":7}]
    assert normalize_segments([left,right],8)[1]["tracking_gaps"]==[{"start":6.5,"end":7}]


def test_invalid_gap_times_are_rejected():
    part=fresh_segment(0,10)
    for gaps in (
        [{"start":2,"end":1}],
        [{"start":-1,"end":2}],
        [{"start":9,"end":12}],
        [{"start":1,"end":3},{"start":2,"end":4}],
        [{"start":float("nan"),"end":3}],
    ):
        part["tracking_gaps"]=gaps
        try:
            normalize_segments([part],10)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid tracking gaps accepted: "+str(gaps))


def test_manual_partial_retrack_preserves_prefix_and_replaces_gaps(tmp_path,monkeypatch):
    monkeypatch.setenv("MOVIE_MODIFY_DATA",str(tmp_path))
    import movie_modify.server as server
    importlib.reload(server)
    pid="c"*32
    folder=tmp_path/pid
    folder.mkdir()
    segment=fresh_segment(0,4)
    segment["mode"]="follow"
    segment["keyframes"]=[
        {"time":t,"yaw":t*10.0,"pitch":0.0,"fov":90.0}
        for t in (0,1,2,3,4)
    ]
    segment["tracking_gaps"]=[{"start":2.2,"end":2.8}]
    segment["tracking_warning"]="過去に追尾未検出"
    source=folder/"original.mp4"
    source.write_bytes(b"synthetic test never decoded")
    (folder/"project.json").write_text(json.dumps({
        "id":pid,"name":"camera.mp4","projection":"equirect",
        "duration":4.0,"segments":[segment],"edit_revision":0,
        "source_name":source.name,"width":960,"height":480,
        "has_audio":False,"codec":"h264","suggestions":[],"proxy_ready":True
    }),encoding="utf-8")

    # The fake tracker generates a deterministic suffix without needing GPU,
    # source media or an OpenCV installation on the test runner.
    from movie_modify import server as instance
    monkeypatch.setattr(instance.importlib.util,"find_spec",
                        lambda name: object() if name=="cv2" else None)
    def fake_track(source_path,start,end,x,y,box,callback=None,include_diagnostics=False):
        assert start==2.6
        assert end==4.0
        assert include_diagnostics is True
        assert source_path == source
        callback(88)
        return [
            {"time":start,"yaw":-100,"pitch":0,"fov":80},
            {"time":end,"yaw":-90,"pitch":0,"fov":80}
        ],"未検出時間あり",[{"start":3.0,"end":3.2}]
    monkeypatch.setattr(instance,"track_panorama",fake_track)
    url=f"/api/projects/{pid}"
    with TestClient(instance.app) as client:
        refused=client.post(url+"/track",json={
            "segment_index":0,"x":.4,"y":.5,"box":.1,
            "expected_revision":0,"start_time":3.9})
        assert refused.status_code==422
        reply=client.post(url+"/track",json={
            "segment_index":0,"x":.4,"y":.5,"box":.1,
            "expected_revision":0,"start_time":2.6})
        assert reply.status_code==200,reply.text
        job_id=reply.json()["job_id"]
        end_time=time.monotonic()+8
        while time.monotonic()<end_time:
            job=client.get("/api/jobs/"+job_id).json()
            if job["state"] in ("done","failed"):break
            time.sleep(.05)
        assert job["state"]=="done",job
        result=client.get(url).json()
        assert result["edit_revision"]==1
        edited=result["segments"][0]
        assert [k["time"] for k in edited["keyframes"]][:3]==[0,1,2]
        assert edited["keyframes"][-2]["yaw"]==-100
        assert edited["keyframes"][-1]["yaw"]==-90
        assert edited["tracking_gaps"]==[
            {"start":2.2,"end":2.6},{"start":3,"end":3.2}
        ]
        assert "前半にも追尾できなかった" in edited["tracking_warning"]
        # A stale second device may not override the manually corrected data.
        stale=client.post(url+"/track",json={
            "segment_index":0,"x":.4,"y":.5,"box":.1,
            "expected_revision":0})
        assert stale.status_code==409
