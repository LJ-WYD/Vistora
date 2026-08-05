from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_roadmap", ROOT / "scripts" / "validate_roadmap.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def _baseline() -> dict:
    return json.loads((ROOT / "roadmap-status.json").read_text(encoding="utf-8"))


def _write_status(tmp_path: Path, status: dict) -> Path:
    path = tmp_path / "roadmap-status.json"
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _without_active_item(status: dict) -> dict:
    """Make synthetic transition fixtures independent of the live route item."""

    for item in status["items"]:
        if item["status"] == "in_progress":
            item["status"] = "partial"
            if not item["remaining_scope"]:
                item["remaining_scope"] = ["synthetic active scope"]
    return status


def test_authoritative_roadmap_passes() -> None:
    result = VALIDATOR.validate(ROOT / "ROADMAP.md", ROOT / "roadmap-status.json")
    current = _baseline()
    assert result == {
        "digest": VALIDATOR.INITIAL_DEFINITIONS_DIGEST,
        "items": 32,
        "in_progress": [
            item["id"]
            for item in current["items"]
            if item["status"] == "in_progress"
        ],
    }


def test_definition_change_without_digest_and_approval_fails(tmp_path: Path) -> None:
    roadmap = tmp_path / "ROADMAP.md"
    roadmap.write_text(
        (ROOT / "ROADMAP.md").read_text(encoding="utf-8").replace(
            "O1 读取并梳理", "O1 擅自修改并梳理"
        ),
        encoding="utf-8",
    )
    with pytest.raises(VALIDATOR.RoadmapValidationError, match="digest marker"):
        VALIDATOR.validate(roadmap, ROOT / "roadmap-status.json", check_git=False)


def test_cannot_skip_earlier_partial_item(tmp_path: Path) -> None:
    status = _without_active_item(copy.deepcopy(_baseline()))
    status["items"][10]["status"] = "partial"
    status["items"][10]["remaining_scope"] = ["synthetic unfinished scope"]
    status["items"][11]["status"] = "in_progress"  # O12 skips partial O11.
    with pytest.raises(VALIDATOR.RoadmapValidationError, match="skips unfinished"):
        VALIDATOR.validate(ROOT / "ROADMAP.md", _write_status(tmp_path, status), check_git=False)


def test_explicit_user_waiver_allows_audited_skip(tmp_path: Path) -> None:
    status = _without_active_item(copy.deepcopy(_baseline()))
    status["items"][10]["status"] = "partial"
    status["items"][10]["remaining_scope"] = ["synthetic unfinished scope"]
    status["items"][11]["status"] = "in_progress"
    status["execution_waivers"].append(
        {
            "waiver_id": "waiver_test",
            "target_o_id": "O12",
            "reason": "Explicit dependency exception for this test.",
            "approved_by": "user",
            "approval_record": "test approval record",
            "active": True,
        }
    )
    result = VALIDATOR.validate(
        ROOT / "ROADMAP.md", _write_status(tmp_path, status), check_git=False
    )
    assert result["in_progress"] == ["O12"]


def test_complete_requires_remote_commit_and_evidence(tmp_path: Path) -> None:
    status = copy.deepcopy(_baseline())
    item = status["items"][10]
    item.update(
        status="complete",
        commits=[],
        remote_verified=False,
        implementation_paths=[],
        validation_evidence=[],
        remaining_scope=[],
    )
    with pytest.raises(VALIDATOR.RoadmapValidationError, match="without a commit"):
        VALIDATOR.validate(ROOT / "ROADMAP.md", _write_status(tmp_path, status), check_git=False)


def test_unknown_fields_and_duplicate_ids_fail_closed(tmp_path: Path) -> None:
    status = copy.deepcopy(_baseline())
    status["items"][0]["unreviewed_claim"] = True
    with pytest.raises(VALIDATOR.RoadmapValidationError, match="unknown fields"):
        VALIDATOR.validate(ROOT / "ROADMAP.md", _write_status(tmp_path, status), check_git=False)

    status = copy.deepcopy(_baseline())
    status["items"][1]["id"] = "O1"
    with pytest.raises(VALIDATOR.RoadmapValidationError, match="O1-O32"):
        VALIDATOR.validate(ROOT / "ROADMAP.md", _write_status(tmp_path, status), check_git=False)
