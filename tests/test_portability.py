"""Cross-platform rendering tests: Windows drive/path syntax and POSIX paths."""
import shutil
import subprocess

import pytest

from movie_modify.core import fresh_segment
from movie_modify.media import animated_filter, inspect_video, render


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="FFmpeg is required for integration")
def test_animated_render_with_spaces_and_quotes_in_working_path(tmp_path):
    folder = tmp_path / "Videos O'Hara (family)"
    folder.mkdir()
    source = folder / "original clip.mp4"
    result = folder / "edited result.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x160:rate=10:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(source),
    ], check=True)
    moving = fresh_segment(0, 1.0)
    moving["mode"] = "follow"
    moving["keyframes"] = [
        {"time": 0.0, "yaw": -45, "pitch": 0, "fov": 90},
        {"time": 1.0, "yaw": 65, "pitch": 12, "fov": 85},
    ]
    scenic = fresh_segment(1.0, 2.0)
    scenic["yaw"] = 130
    render(source, result, "equirect", [moving, scenic], size="720p", has_audio=False)
    meta = inspect_video(result)
    assert meta["width"] == 1280 and meta["height"] == 720
    assert 1.8 <= meta["duration"] <= 2.2
    assert result.stat().st_size > 1000


def test_animated_filter_never_embeds_directories_in_filtergraph(tmp_path):
    # ffmpeg -vf filter parsing cannot safely consume raw Windows drive letters.
    filename = tmp_path / "space and 'quote'" / "commands_00001.txt"
    filename.parent.mkdir()
    moving = fresh_segment(0, 1.0)
    moving["keyframes"] = [
        {"time": 0, "yaw": 0, "pitch": 0, "fov": 90},
        {"time": 1, "yaw": 30, "pitch": 0, "fov": 90},
    ]
    vf = animated_filter(moving, filename, 1280, 720)
    assert "sendcmd=f='commands_00001.txt'" in vf
    assert str(filename.parent) not in vf
    assert filename.is_file()


def test_lan_requires_passphrase_even_when_ffmpeg_is_present(monkeypatch, capsys):
    from movie_modify.__main__ import main
    monkeypatch.delenv("MOVIE_MODIFY_TOKEN", raising=False)
    # Simulate FFmpeg discovery without launching a server.
    monkeypatch.setattr("movie_modify.__main__.shutil.which", lambda name: "tool")
    assert main(["--lan"]) == 2
    assert "MOVIE_MODIFY_TOKEN" in capsys.readouterr().err


def test_default_cli_is_loopback(monkeypatch):
    from movie_modify.__main__ import main
    calls = {}
    monkeypatch.setattr("movie_modify.__main__.shutil.which", lambda name: "tool")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.update(kwargs))
    assert main(["--port", "8111"]) == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8111


def test_lan_cli_uses_token_and_host(monkeypatch):
    from movie_modify.__main__ import main
    calls = {}
    monkeypatch.setenv("MOVIE_MODIFY_TOKEN", "a-long-random-password-for-tests")
    monkeypatch.setattr("movie_modify.__main__.shutil.which", lambda name: "tool")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.update(kwargs))
    assert main(["--lan", "--port", "8112"]) == 0
    assert calls["host"] == "0.0.0.0"
