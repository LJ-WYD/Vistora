"""Local-only browser fixture for Director history display states."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from core.timeline import TimelineConfig  # noqa: E402
from director import DirectorHistoryView  # noqa: E402
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402


def _history(state: str, project_id: str) -> DirectorHistoryView:
    reasons = {
        "needs_materials": [
            "No observed source materials are available to ground a plan."
        ],
        "needs_clarification": [
            "Missing creative brief fields: audience, pacing."
        ],
        "materials_incomplete": [
            "Observed picture is available, but the required dialogue source is missing."
        ],
        "proposal_ready": [
            "Required constraints, observed materials, and evidence are present."
        ],
        "model_error": [
            "The reasoning response failed strict schema validation."
        ],
    }
    material_ids = (
        ["source_1111111111111111"]
        if state in {"proposal_ready", "materials_incomplete"}
        else []
    )
    evidence_ids = (
        ["evidence_visual_source"]
        if state in {"proposal_ready", "materials_incomplete"}
        else []
    )
    error = (
        {
            "schema_version": "1.0.0",
            "code": "director_schema_rejected",
            "message": "Malformed structured output was rejected.",
            "retryable": False,
            "recovery_action": "Retry with a valid Director adapter.",
        }
        if state == "model_error"
        else None
    )
    latest_status = state
    readiness = (
        "ready_to_plan" if state == "proposal_ready" else state
    )
    proposals = (
        (
            {
                "proposal_id": "director_proposal_visual",
                "plan_id": "director_plan_visual",
                "plan_version": 1,
                "plan_digest": "sha256:" + ("4" * 64),
                "review_state": "current",
                "review_status": "ready",
                "diff_digest": "sha256:" + ("5" * 64),
            },
        )
        if state == "proposal_ready"
        else ()
    )
    return DirectorHistoryView(
        session_id="session_director_visual",
        project_id=project_id,
        ledger_revision=1,
        integrity_digest="sha256:" + ("1" * 64),
        latest_status=latest_status,
        latest_brief={
            "brief_version": 1,
            "content_digest": "sha256:" + ("2" * 64),
            "readiness": readiness,
            "readiness_reasons": reasons[state],
            "objective": "Create a grounded product launch cut.",
            "audience": (
                "Existing users" if state == "proposal_ready" else None
            ),
            "platform": "Product landing page",
            "target_duration_seconds": 15.0,
            "style": "Clean and restrained",
            "narrative": "One concise source-led arc",
            "pacing": (
                "Steady" if state == "proposal_ready" else None
            ),
            "must_haves": ["Use only observed material"],
            "must_not_haves": ["No invented claims"],
            "delivery_requirements": ["H.264 MP4"],
            "material_ids": material_ids,
            "evidence_ids": evidence_ids,
            "assumptions": [],
            "unresolved_questions": (
                ["Who is the audience?", "What pacing is preferred?"]
                if state == "needs_clarification"
                else []
            ),
            "acceptance_criteria": (
                ["15 second duration", "No unobserved footage"]
                if state == "proposal_ready"
                else []
            ),
            "material_state": (
                {
                    "schema_version": "1.0.0",
                    "schema_name": "vistora.director-material-state",
                    "assessment_id": "material_state_visual",
                    "snapshot_ref": {
                        "schema_name": "vistora.timeline-snapshot-reference",
                        "schema_version": "11.0.0",
                        "project_id": project_id,
                        "revision": 0,
                        "snapshot_id": "snapshot_visual",
                        "timeline_digest": "sha256:" + ("6" * 64),
                    },
                    "brief_content_digest": "sha256:" + ("2" * 64),
                    "material_facts_digest": "sha256:" + ("7" * 64),
                    "state": "materials_incomplete",
                    "observed_material_ids": ["source_1111111111111111"],
                    "unavailable_material_ids": ["source_2222222222222222"],
                    "selected_material_ids": ["source_1111111111111111"],
                    "missing_evidence_material_ids": [],
                    "reasons": reasons[state],
                }
                if state == "materials_incomplete"
                else None
            ),
        },
        turns=(
            {
                "turn_id": "turn_director_visual_001",
                "turn_index": 1,
                "status": latest_status,
                "assistant_message": (
                    "The proposal is ready for separate user review."
                    if state == "proposal_ready"
                    else "The Director stopped without applying any changes."
                ),
                "clarification_questions": (
                    ["Who is the audience?", "What pacing is preferred?"]
                    if state == "needs_clarification"
                    else []
                ),
                "brief_version": 1,
                "context_digest": "sha256:" + ("3" * 64),
                "error": error,
                "withdrawn_proposal_id": None,
            },
        ),
        proposals=proposals,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state",
        required=True,
        choices=(
            "needs_materials",
            "needs_clarification",
            "materials_incomplete",
            "proposal_ready",
            "model_error",
        ),
    )
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()
    snapshot = TimelineSnapshotService.snapshot(TimelineConfig())
    history = _history(args.state, snapshot.project_id)
    application = PreviewApplication(
        lambda: snapshot,
        director_history_provider=lambda: history,
    )
    server = create_preview_server(application, port=args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
