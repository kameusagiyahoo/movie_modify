from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/yomiyasu"


def test_skill_files_exist():
    assert (SKILL / "SKILL.md").is_file()
    assert (SKILL / "LICENSE").is_file()
    assert (SKILL / "UNICODE-LICENSE.txt").is_file()
    assert (SKILL / "references/audience.md").is_file()
    for name in ("markdown_visibility.py", "yomiyasu_lint.py",
                 "yomiyasu_diff.py", "yomiyasu_check.py"):
        assert (SKILL / "scripts" / name).is_file()


def test_skill_is_not_runtime_dependency():
    assert "yomiyasu" not in (ROOT / "requirements.txt").read_text()
