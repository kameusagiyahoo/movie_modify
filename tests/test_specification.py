"""Guardrails for the canonical specification and source links."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "SPECIFICATION.md"


def test_canonical_spec_contains_architecture_modes_and_traceability():
    content = SPEC_PATH.read_text(encoding="utf-8")
    for heading in [
        "目的と設計原則",
        "提供モードと対応範囲",
        "システム全体アーキテクチャ",
        "機能要求・実装ステータス",
        "UI/UX仕様",
        "ユーザー操作フロー",
        "共通編集データ",
        "動画処理・追尾・書き出し",
        "ローカルAPI仕様",
        "実行環境・インストール・運用",
        "安全性・プライバシー・データ保全",
        "品質・テスト・制約",
        "未実装事項と優先ロードマップ",
        "実装ファイル・関連資料・文書管理",
    ]:
        assert heading in content
    fence = chr(96) * 3
    assert content.count(fence + "mermaid") >= 3
    assert fence + "json" in content
    for id in ["F-01", "F-10", "F-15", "F-23", "AC-01", "AC-10", "R-01", "R-11"]:
        assert id in content
    for limitation in ["未実装", "Pages", "Windows", "Linux", "iPhone", "MOVIE_MODIFY_TOKEN"]:
        assert limitation in content


def test_relative_source_references_are_not_broken():
    content = SPEC_PATH.read_text(encoding="utf-8")
    targets = re.findall(r"\[[^\]]+\]\(([^)#\s]+)(?:#[^\)]*)?\)", content)
    local_paths = [target for target in targets if not target.startswith(("http://", "https://", "mailto:"))]
    assert len(local_paths) >= 15
    for target in local_paths:
        assert (SPEC_PATH.parent / target).is_file(), target


def test_spec_is_prominent_in_readme_and_pages_ui():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pages = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "docs/SPECIFICATION.md" in "\n".join(readme.splitlines()[:8])
    assert "docs/SPECIFICATION.md" in pages
