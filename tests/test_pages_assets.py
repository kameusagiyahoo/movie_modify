"""Verify GitHub Pages app assets are deployed and local-first."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

def test_static_bundle():
    for file in ("index.html", "pages.css", "pages.js", "live_preview.js", "README.md", ".nojekyll"):
        assert (DOCS / file).is_file()
    assert "./docs/" in (ROOT / "index.html").read_text(encoding="utf-8")
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    for asset in ("./pages.css", "./pages.js", "./live_preview.js"):
        assert asset in html

def test_local_only_and_capability_disclosure():
    script = (DOCS / "pages.js").read_text(encoding="utf-8")
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "URL.createObjectURL(newFile)" in script
    assert "LivePanoramaPreview" in script
    assert "MediaRecorder" in script
    assert "fetch(" not in script
    assert "Auto-Editor" in html
    assert "PC版のみ" in html
