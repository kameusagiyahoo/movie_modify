"""Validate the ChatGPT-authored CodeBoarding architecture data against source.

No external services or LLM calls. This checks structural compatibility with
the documented UnifiedAnalysisJson schema, source locations and relation refs.
It cannot substitute for exercising CodeBoarding's browser viewer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".codeboarding" / "analysis.json"


def test_analysis_uses_official_top_level_shape():
    analysis = json.loads(DATA.read_text(encoding="utf-8"))
    assert set(analysis) == {
        "metadata", "description", "files", "methods_index",
        "components", "components_relations",
    }
    assert analysis["metadata"]["repo_name"] == "movie_modify"
    assert analysis["metadata"]["depth_level"] == 2
    assert len(analysis["components"]) == 8
    assert len(analysis["methods_index"]) >= 100
    assert len(analysis["files"]) >= 15


def test_source_references_and_method_lookup_are_consistent():
    analysis = json.loads(DATA.read_text(encoding="utf-8"))
    methods = analysis["methods_index"]
    for file_name, info in analysis["files"].items():
        actual = ROOT / file_name
        assert actual.is_file(), file_name
        for key in info["method_keys"]:
            assert key in methods
            assert methods[key]["file_path"] == file_name
    for key, method in methods.items():
        assert key == method["file_path"] + "|" + method["qualified_name"]
        contents = (ROOT / method["file_path"]).read_text(encoding="utf-8").splitlines()
        assert 1 <= method["start_line"] <= method["end_line"] <= len(contents)

    components = analysis["components"]
    all_components = {c["component_id"]: c for c in components}
    for comp in components:
        assert comp["can_expand"]
        assert comp["components"]
        for child in comp["components"]:
            all_components[child["component_id"]] = child
    for component in all_components.values():
        assert component["name"] and component["description"]
        assert component["key_entities"]
        for entity in component["key_entities"]:
            file_path = entity["reference_file"]
            assert file_path in analysis["files"]
            assert (file_path + "|" + entity["qualified_name"]) in methods
            assert entity["reference_start_line"] > 0
        for group in component["file_methods"]:
            assert group["file_path"] in analysis["files"]
            assert all(group["file_path"] + "|" + m in methods for m in group["methods"])
    for relation in analysis["components_relations"] + [
        relation for c in components for relation in c["components_relations"]
    ]:
        assert relation["src_id"] in all_components
        assert relation["dst_id"] in all_components
        assert relation["relation"]
        for edge in relation["key_edges"] + relation["all_edges"]:
            assert edge["source"] in methods
            assert edge["target"] in methods


def test_viewer_documentation_and_no_user_video_paths():
    guide = (ROOT / "docs/codeboarding.md").read_text(encoding="utf-8")
    analysis = DATA.read_text(encoding="utf-8")
    assert "app.codeboarding.org/kameusagiyahoo/movie_modify" in guide
    assert "Switch source" in guide
    assert "openai_api_key" not in analysis.lower()
    assert "private_video" not in analysis.lower()
