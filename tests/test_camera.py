"""Regression tests for 360 camera keyframes; no OpenCV dependency required."""
import subprocess

import pytest

from movie_modify.core import (
    apply_suggestions, camera_at, fresh_segment, normalize_segments, slice_segment,
)
from movie_modify.media import panorama_frame, render


def moving_segment():
    s = fresh_segment(0, 3)
    s["mode"] = "follow"
    s["keyframes"] = [
        {"time": 0, "yaw": 170, "pitch": 0, "fov": 90},
        {"time": 3, "yaw": -170, "pitch": 20, "fov": 70},
    ]
    return s


def test_360_seam_shortest_rotation():
    view = camera_at(moving_segment(), 1.5)
    assert abs(abs(view["yaw"]) - 180) < 1e-7
    assert view["pitch"] == 10 and view["fov"] == 80


def test_cut_and_split_preserve_tracking():
    s = moving_segment()
    left = slice_segment(s, 0, 1)
    right = slice_segment(s, 1, 3)
    assert camera_at(left, 1) == camera_at(right, 1)
    assert normalize_segments([left, right], 3)[1]["mode"] == "follow"
    cuts = apply_suggestions([s], [{"start": 1, "end": 2}], [0], 3)
    assert [x["keep"] for x in cuts] == [True, False, True]
    assert camera_at(cuts[0], 1) == camera_at(cuts[1], 1)


def test_reject_invalid_keyframes():
    s = moving_segment()
    s["keyframes"][1]["time"] = 10
    with pytest.raises(ValueError):
        normalize_segments([s], 3)


def test_panorama_and_animated_ffmpeg_render(tmp_path):
    src = tmp_path / "panorama.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","testsrc2=size=640x320:rate=10:duration=3",
                    "-c:v","libx264","-preset","ultrafast",str(src)],check=True)
    assert len(panorama_frame(src, 0.5)) > 100
    s = fresh_segment(0,3)
    s["keyframes"] = [
        {"time":0,"yaw":0,"pitch":0,"fov":90},
        {"time":3,"yaw":100,"pitch":0,"fov":90},
    ]
    dst = tmp_path / "output.mp4"
    render(src, dst, "equirect", [s], size="720p", has_audio=False)
    assert dst.stat().st_size > 1000
    seconds = float(subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nw=1:nk=1",str(dst)],text=True).strip())
    assert 2.9 <= seconds <= 3.2
