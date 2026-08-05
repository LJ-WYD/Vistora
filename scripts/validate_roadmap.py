"""Validate the immutable original Vistora O1-O32 roadmap and its status ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_NAME = "vistora.roadmap-status"
SCHEMA_VERSION = "1.0.0"
INITIAL_DEFINITIONS_DIGEST = (
    "sha256:143850f88a50bf6b43137723cff42c4f1f9132b2a12cceda369c659db5c5d618"
)
VALID_STATUSES = {"complete", "partial", "missing", "in_progress", "blocked"}
TOP_LEVEL_KEYS = {
    "schema_name",
    "schema_version",
    "roadmap_id",
    "roadmap_digest",
    "definitions_source",
    "updated_at",
    "change_requests",
    "execution_waivers",
    "v1_limit_acceptances",
    "items",
}
ITEM_KEYS = {
    "id",
    "original_summary",
    "status",
    "commits",
    "remote_verified",
    "implementation_paths",
    "validation_evidence",
    "remaining_scope",
}
DEFINITION_RE = re.compile(r"^- (O\d+) (.+)$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
BATCH_RE = re.compile(r"^BATCH-[A-Za-z0-9-]+$")


class RoadmapValidationError(ValueError):
    """Raised when roadmap governance invariants do not hold."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RoadmapValidationError(message)


def load_definitions(roadmap_path: Path) -> list[dict[str, str]]:
    text = roadmap_path.read_text(encoding="utf-8")
    definitions = []
    for line in text.splitlines():
        match = DEFINITION_RE.fullmatch(line)
        if match:
            definitions.append({"id": match.group(1), "definition": match.group(2)})
    expected_ids = [f"O{index}" for index in range(1, 33)]
    _require([entry["id"] for entry in definitions] == expected_ids, "ROADMAP.md must define O1-O32 exactly once and in order")
    _require(not re.search(r"\bSTEP\s*\d+\b", text, flags=re.IGNORECASE), "internal STEP numbering must not appear in ROADMAP.md")
    for entry in definitions:
        _require("BATCH-" not in entry["definition"], f"{entry['id']} definition is polluted by an internal batch identifier")
    return definitions


def definitions_digest(definitions: list[dict[str, str]]) -> str:
    canonical = json.dumps(
        definitions,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _validate_definition_authority(
    roadmap_text: str,
    status: dict[str, Any],
    digest: str,
) -> None:
    _require(f"Definitions digest: `{digest}`" in roadmap_text, "ROADMAP.md digest marker does not match its definitions")
    _require(status["roadmap_digest"] == digest, "roadmap-status.json digest does not match ROADMAP.md")
    if digest != INITIAL_DEFINITIONS_DIGEST:
        approved = [
            request
            for request in status["change_requests"]
            if request.get("approved_definition_digest") == digest
            and request.get("approved_by") == "user"
            and request.get("reason")
            and request.get("approval_record")
        ]
        _require(bool(approved), "changed definitions require a user-approved change_request bound to the new digest")
    else:
        _require(
            any(
                request.get("approved_definition_digest") == digest
                and request.get("approved_by") == "user"
                and request.get("reason")
                and request.get("approval_record")
                for request in status["change_requests"]
            ),
            "the authoritative import requires its user approval record",
        )


def _git_commit_exists(repository: Path, commit: str) -> bool:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={repository.as_posix()}", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repository,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _git_commit_is_on_remote_main(repository: Path, commit: str) -> bool:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository.as_posix()}",
            "merge-base",
            "--is-ancestor",
            commit,
            "refs/remotes/origin/main",
        ],
        cwd=repository,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def validate(
    roadmap_path: Path,
    status_path: Path,
    *,
    check_git: bool = True,
) -> dict[str, Any]:
    roadmap_path = roadmap_path.resolve()
    status_path = status_path.resolve()
    repository = roadmap_path.parent
    definitions = load_definitions(roadmap_path)
    digest = definitions_digest(definitions)
    status = json.loads(status_path.read_text(encoding="utf-8"))

    _require(set(status) == TOP_LEVEL_KEYS, "roadmap-status.json has missing or unknown top-level fields")
    _require(status["schema_name"] == SCHEMA_NAME, "unexpected roadmap status schema")
    _require(status["schema_version"] == SCHEMA_VERSION, "unsupported roadmap status schema version")
    _require(status["definitions_source"] == roadmap_path.name, "definitions_source must name ROADMAP.md")
    _require(isinstance(status["change_requests"], list), "change_requests must be a list")
    _require(isinstance(status["execution_waivers"], list), "execution_waivers must be a list")
    _require(isinstance(status["v1_limit_acceptances"], list), "v1_limit_acceptances must be a list")
    _validate_definition_authority(roadmap_path.read_text(encoding="utf-8"), status, digest)

    items = status["items"]
    expected_ids = [f"O{index}" for index in range(1, 33)]
    _require(isinstance(items, list), "items must be a list")
    _require([item.get("id") for item in items] == expected_ids, "status items must be O1-O32 exactly once and in order")
    in_progress = [item for item in items if item.get("status") == "in_progress"]
    _require(len(in_progress) <= 1, "at most one original O item may be in_progress")

    for item in items:
        item_id = item.get("id", "unknown")
        _require(set(item) == ITEM_KEYS, f"{item_id} has missing or unknown fields")
        _require(item["status"] in VALID_STATUSES, f"{item_id} has invalid status {item['status']!r}")
        _require(isinstance(item["original_summary"], str) and item["original_summary"].strip(), f"{item_id} requires an original_summary")
        for field in ("commits", "implementation_paths", "validation_evidence", "remaining_scope"):
            _require(isinstance(item[field], list), f"{item_id}.{field} must be a list")
        for commit in item["commits"]:
            _require(bool(COMMIT_RE.fullmatch(commit)), f"{item_id} commit must be a full lowercase SHA")
            if check_git:
                _require(_git_commit_exists(repository, commit), f"{item_id} references a commit absent from local history: {commit}")
                if item["remote_verified"] is True:
                    _require(
                        _git_commit_is_on_remote_main(repository, commit),
                        f"{item_id} references a commit not reachable from origin/main: {commit}",
                    )
        if item["status"] == "complete":
            _require(bool(item["commits"]), f"{item_id} cannot be complete without a commit")
            _require(item["remote_verified"] is True, f"{item_id} cannot be complete without remote verification")
            _require(bool(item["implementation_paths"]), f"{item_id} cannot be complete without implementation paths")
            _require(bool(item["validation_evidence"]), f"{item_id} cannot be complete without validation evidence")
            _require(not item["remaining_scope"], f"{item_id} cannot be complete with remaining scope")
            for field in ("implementation_paths", "validation_evidence"):
                for relative_path in item[field]:
                    _require(
                        (repository / relative_path).exists(),
                        f"{item_id} {field} path does not exist: {relative_path}",
                    )
        elif item["status"] in {"partial", "missing", "blocked"}:
            _require(bool(item["remaining_scope"]), f"{item_id} {item['status']} status requires remaining_scope")

    if in_progress:
        active = in_progress[0]
        active_index = int(active["id"][1:])
        earlier_unfinished = [
            item["id"]
            for item in items[: active_index - 1]
            if item["status"] in {"partial", "missing", "blocked"}
        ]
        if earlier_unfinished:
            approved_waiver = any(
                waiver.get("active") is True
                and waiver.get("target_o_id") == active["id"]
                and waiver.get("approved_by") == "user"
                and waiver.get("reason")
                and waiver.get("approval_record")
                for waiver in status["execution_waivers"]
            )
            _require(approved_waiver, f"{active['id']} skips unfinished earlier items {earlier_unfinished} without an active user waiver")

    for waiver in status["execution_waivers"]:
        _require(waiver.get("target_o_id") in expected_ids, "execution waiver targets an unknown O item")
    for batch_id in status.get("internal_batches", []):
        _require(bool(BATCH_RE.fullmatch(batch_id)), f"invalid internal batch identifier: {batch_id}")
    return {"digest": digest, "items": len(items), "in_progress": [item["id"] for item in in_progress]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roadmap", type=Path, default=Path("ROADMAP.md"))
    parser.add_argument("--status", type=Path, default=Path("roadmap-status.json"))
    parser.add_argument("--no-git", action="store_true", help="skip local commit existence checks")
    args = parser.parse_args()
    try:
        result = validate(args.roadmap, args.status, check_git=not args.no_git)
    except (OSError, json.JSONDecodeError, RoadmapValidationError) as exc:
        print(f"roadmap validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "valid", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
