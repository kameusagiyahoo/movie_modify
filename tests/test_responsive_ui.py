"""The same editor must be usable on phones and desktop browsers."""
from pathlib import Path

from fastapi.testclient import TestClient

from movie_modify.server import app

ROOT = Path(__file__).resolve().parents[1]


def test_responsive_editor_assets_are_local():
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert '/assets/responsive_ui.css' in page.text
        assert '/assets/responsive_ui.js' in page.text
        for asset, mime in [
            ("responsive_ui.css", "text/css"),
            ("responsive_ui.js", "text/javascript"),
        ]:
            result = client.get("/assets/" + asset)
            assert result.status_code == 200
            assert result.headers["content-type"].startswith(mime)
        assert "https://" not in client.get("/assets/responsive_ui.js").text


def test_shared_editor_controls_and_layout_hooks():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "web/responsive_ui.js").read_text(encoding="utf-8")
    css = (ROOT / "web/responsive_ui.css").read_text(encoding="utf-8")
    assert "MovieModifyUI?.mount(p)" in html
    assert "MovieModifyUI?.decorate(current)" in html
    assert "grid-template-columns" in css
    assert "@media(max-width:900px)" in css
    for feature in [
        'data-command="split"', 'data-command="scenery"',
        'data-command="toggle"', 'data-command="save"',
        "changeZoom", "switchTab", "timelinePlayhead",
    ]:
        assert feature in js
    # Both UI layouts operate on the same underlying timeline, not separate EDLs.
    assert 'project.segments' not in css
    assert "createElement" in js
