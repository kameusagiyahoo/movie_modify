"""R-05: conservative recovery decisions without user video or paid APIs."""
from __future__ import annotations

import pytest

from movie_modify.tracking import RecoveryState, _match_in_region, _reference_score


def test_low_confidence_freezes_pose_and_counts_loss():
    state = RecoveryState()
    assert state.accepts(.85, .82, csrt=True)
    assert state.advance(True) == "tracked"
    assert not state.accepts(.4, .90, csrt=True)
    assert state.advance(False) == "lost"
    assert state.missed == 1
    assert state.lost_frames == 1
    assert state.max_lost_run == 1
    assert "直前の画角を維持" in state.warning(4)


def test_reacquisition_requires_high_confidence_and_nonambiguous_candidate():
    state = RecoveryState()
    for _ in range(9):
        assert state.advance(False) == "lost"
    assert state.radius(70, 960) > 70
    assert state.radius(70, 960) <= 432

    assert not state.accepts(.78, .98, .25)
    assert not state.accepts(.95, .31, .12)
    assert not state.accepts(.91, .84, .89)
    assert state.rejected_ambiguous == 1
    assert state.accepts(.93, .82, .50)
    assert state.advance(True) == "recovered"
    assert state.missed == 0
    assert state.recovered == 1
    assert state.max_lost_run == 9
    assert state.lost_frames == 9
    assert "再発見1回" in state.warning(4)


def test_nan_never_counts_as_tracked():
    state = RecoveryState()
    assert not state.accepts(float("nan"), .91)
    assert not state.accepts(.91, float("inf"))
    assert state.advance(False) == "lost"


def test_360_seam_search_and_ambiguous_twins():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(103)
    width, height = 120, 60
    pattern = rng.integers(50, 240, size=(12, 16), dtype=np.uint8)
    image = np.zeros((height, width), dtype=np.uint8)
    center_x, center_y = 117, 29
    for col in range(pattern.shape[1]):
        xx = (center_x - pattern.shape[1]//2 + col) % width
        image[center_y-6:center_y+6, xx] = pattern[:, col]
    tiled = np.concatenate((image, image, image), axis=1)
    score = _reference_score(cv2, np, tiled, pattern,
                             center_x, center_y, width, height)
    assert score >= .99
    match = _match_in_region(cv2, np, tiled, pattern,
                            center_x, center_y, 35, width, height)
    assert match is not None
    cx, cy, similarity, _runner = match
    assert min(abs(cx-center_x), width-abs(cx-center_x)) <= 1
    assert abs(cy-center_y) <= 1
    assert similarity >= .99

    # Two truly identical appearances in a search region must be ambiguous.
    second = image.copy()
    for col in range(pattern.shape[1]):
        xx = (57 - pattern.shape[1]//2 + col) % width
        second[center_y-6:center_y+6,xx] = pattern[:, col]
    tiled = np.concatenate((second,second,second),axis=1)
    match = _match_in_region(cv2, np, tiled, pattern,
                            center_x, center_y, 80, width, height)
    assert match is not None
    assert match[2] > .99
    assert match[3] is not None and match[3] > .99
    state=RecoveryState(missed=5)
    assert not state.accepts(match[2], .99, match[3])


def test_adaptive_radius_remains_local_even_after_long_occlusion():
    state = RecoveryState()
    for _ in range(100):
        state.advance(False)
    assert state.radius(190, 960) == 432
    assert state.recovered == 0
    assert state.warning(4).find("最長連続25.0秒") >= 0


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None,
                    reason="FFmpeg required for synthetic tracking video")
def test_tracker_freezes_during_synthetic_occlusion_and_marks_warning(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    import subprocess
    from movie_modify.tracking import track_panorama

    src = tmp_path / "synthetic_360.mp4"
    width, height, fps = 320, 160, 3
    rng = np.random.default_rng(531)
    target = rng.integers(30, 230, size=(32, 32, 3), dtype=np.uint8)
    frames = []
    for i in range(10):
        frame = np.full((height,width,3), 18, dtype=np.uint8)
        if i not in (4,5,6):  # Object is absent for one full second.
            frame[64:96,64:96,:] = target
        frames.append(frame)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "320x160",
        "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
        "-preset", "ultrafast", "-crf", "8", "-pix_fmt", "yuv420p",
        str(src)
    ]
    proc = subprocess.run(command, input=b"".join(f.tobytes() for f in frames),
                          capture_output=True, timeout=30)
    assert proc.returncode == 0, proc.stderr[-500:]
    keyframes, warning, gaps = track_panorama(
        src, 0, 3.2, x=.25, y=.5, box=.10, fps=fps,
        include_diagnostics=True,
    )
    assert len(keyframes) >= 9
    assert keyframes[0]["time"] == 0
    assert keyframes[-1]["time"] == 3.2
    assert all(-180 <= p["yaw"] <= 180 for p in keyframes)
    assert "未検出" in warning and "画角を維持" in warning
    assert gaps, "Occlusion must be reported as inspectable time intervals"
    assert all(0 <= gap["start"] < gap["end"] <= 3.2 for gap in gaps)
    assert any(gap["start"] <= 2.1 and gap["end"] >= 1.3 for gap in gaps)
    # When the object disappears, the viewpoint must not drift to any
    # similarly colored region elsewhere in the panorama.
    assert abs(keyframes[5]["yaw"]-keyframes[4]["yaw"]) < 2
    assert abs(keyframes[6]["yaw"]-keyframes[5]["yaw"]) < 2


def test_fast_teleporting_lookalike_is_rejected_but_seam_crossing_allowed():
    state = RecoveryState()
    width, height = 960, 480
    assert state.plausible_motion(953, 200, 12, 207, width, height)
    assert not state.plausible_motion(953, 200, 400, 207, width, height)
    assert not state.plausible_motion(70, 200, 77, 440, width, height)
    assert state.rejected_jumps == 2
    assert "飛び移り候補の拒否2回" in state.warning(4)


def test_reacquisition_requires_two_consecutive_spatially_consistent_samples():
    state = RecoveryState()
    for _ in range(4):
        state.advance(False)
    # A one-frame lookalike is not sufficient to re-aim the camera.
    assert not state.confirm_reacquisition(955, 240, 960, 480)
    assert state.awaiting_confirmation == 1
    assert state.missed == 4
    # Another plausible match across the seam corroborates a recovery.
    assert state.confirm_reacquisition(8, 244, 960, 480)
    assert state.advance(True) == "recovered"
    assert state.recovered == 1
    assert state.missed == 0
    assert state.pending_location is None


def test_candidate_switch_discards_single_frame_recovery():
    state = RecoveryState(missed=3)
    assert not state.confirm_reacquisition(100, 100, 960, 480)
    # A competing person appears far from the previous proposed position.
    assert not state.confirm_reacquisition(430, 100, 960, 480)
    assert state.pending_count == 1
    assert state.pending_location == (430, 100)
    assert state.confirm_reacquisition(431, 101, 960, 480)
    state.advance(True)
    assert state.recovered == 1
