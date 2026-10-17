import json
import pytest
from movie_modify.core import fresh_segment, normalize_segments, apply_suggestions, merge_intervals, parse_auto_editor_v1
from movie_modify.media import build_filters


def test_segments_reject_overlap():
    with pytest.raises(ValueError):
        normalize_segments([fresh_segment(0, 4), fresh_segment(3, 8)], 10)


def test_segments_reject_invalid_angle_and_nonfinite():
    with pytest.raises(ValueError):
        normalize_segments([{**fresh_segment(0, 5), "yaw": 999}], 10)
    with pytest.raises(ValueError):
        normalize_segments([{**fresh_segment(0, 5), "fov": float("nan")}], 10)


def test_suggestions_preserve_other_parts_and_view():
    segments = [{**fresh_segment(0, 12), "yaw": 77}]
    cuts = [{"start": 3, "end": 6}]
    out = apply_suggestions(segments, cuts, [0], 12)
    assert [(x["start"], x["end"], x["keep"]) for x in out] == [(0, 3, True), (3, 6, False), (6, 12, True)]
    assert all(x["yaw"] == 77 for x in out)


def test_merge_and_auto_editor():
    assert len(merge_intervals([(2, 5), (5, 7), (20, 22)], 30)) == 2
    assert parse_auto_editor_v1({"version":"1","timebase":"30/1","chunks":[[0,90,1],[90,180,0]]}, 10)[0]["start"] == 3


def test_360_render_filter():
    vf = build_filters("equirect", {"yaw": 45, "pitch": -4, "fov": 95})
    assert "v360=" in vf and "yaw=45.000" in vf
    assert "v360=" not in build_filters("flat", {})
