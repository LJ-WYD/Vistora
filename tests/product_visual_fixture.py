"""Serve deterministic product-entry UI states for browser verification."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from product_entry import ProductEntryView  # noqa: E402
from timeline_preview import (  # noqa: E402
    PreviewApplication,
    create_preview_server,
)
from timeline_query import TimelineSnapshotService  # noqa: E402


class StaticProduct:
    def __init__(self, view):
        self._view = view

    def view(self):
        return self._view


def _view(state: str) -> ProductEntryView:
    allowed = {
        "dialogue": ("director_turn",),
        "needs_clarification": ("director_turn",),
        "proposal_ready": ("director_turn", "persist_review"),
        "material_requirements_ready": (
            "director_turn",
            "persist_material_review",
        ),
        "material_reviewed": (
            "confirm_materials",
            "reject_materials",
            "withdraw_materials",
        ),
        "materials_confirmed": (),
        "confirmed": ("execute",),
        "succeeded": ("rollback_review",),
        "error": ("director_turn",),
    }[state]
    director_status = {
        "dialogue": "empty",
        "needs_clarification": "needs_clarification",
        "proposal_ready": "proposal_ready",
        "material_requirements_ready": "material_requirements_ready",
        "material_reviewed": "material_requirements_ready",
        "materials_confirmed": "material_requirements_ready",
        "confirmed": "proposal_ready",
        "succeeded": "proposal_ready",
        "error": "model_error",
    }[state]
    return ProductEntryView(
        session_id="session_visual_product",
        project_id="project_visual_product",
        revision=3 if state != "dialogue" else 0,
        state=state,
        director={
            "latest_status": director_status,
            "proposals": (
                [
                    {
                        "proposal_id": "proposal_visual_product",
                        "plan_id": "plan_visual_product",
                        "plan_version": 1,
                        "plan_digest": "sha256:" + "1" * 64,
                        "review_state": "current",
                        "review_status": "ready",
                        "diff_digest": "sha256:" + "2" * 64,
                    }
                ]
                if state not in {"dialogue", "needs_clarification", "error"}
                else []
            ),
            "material_requirements": (
                [
                    {
                        "proposal_id": "material_proposal_visual",
                        "plan_id": "material_plan_visual",
                        "plan_version": 1,
                        "plan_digest": "sha256:" + "6" * 64,
                        "review_id": "material_review_visual",
                        "review_digest": "sha256:" + "7" * 64,
                        "brief_version": 1,
                        "item_count": 1,
                        "items": [
                            {
                                "item_id": "material_need_visual",
                                "asset_type": "video_shot",
                                "purpose": "Show the product interaction.",
                                "narrative_position": "Proof beat.",
                                "priority": "required",
                                "acceptance_criteria": [
                                    "The UI interaction is readable."
                                ],
                            }
                        ],
                    }
                ]
                if state
                in {
                    "material_requirements_ready",
                    "material_reviewed",
                    "materials_confirmed",
                }
                else []
            ),
        },
        review=None,
        workflow={
            "state": "active" if state not in {"dialogue", "error"} else "empty",
            "reviews": (
                [{"review_id": "review_visual_product"}]
                if state in {"confirmed", "succeeded"}
                else []
            ),
            "confirmations": (
                [
                    {
                        "confirmation_record_id": "confirmation_visual_product",
                        "decision": "confirmed",
                    }
                ]
                if state in {"confirmed", "succeeded"}
                else []
            ),
            "executions": (
                [{"run_id": "run_visual_product", "status": "succeeded"}]
                if state == "succeeded"
                else []
            ),
            "rollback_reviews": [],
            "rollback_confirmations": [],
        },
        material_requirements=(
            {
                "state": (
                    "reviewable"
                    if state == "material_reviewed"
                    else "confirmed"
                ),
                "proposals": [
                    {
                        "proposal_id": "material_proposal_visual",
                        "plan_id": "material_plan_visual",
                        "plan_version": 1,
                        "plan_digest": "sha256:" + "6" * 64,
                        "review_id": "material_review_visual",
                        "review_digest": "sha256:" + "7" * 64,
                        "brief_version": 1,
                        "items": [
                            {
                                "item_id": "material_need_visual",
                                "asset_type": "video_shot",
                                "purpose": "Show the product interaction.",
                                "narrative_position": "Proof beat.",
                                "priority": "required",
                                "acceptance_criteria": [
                                    "The UI interaction is readable."
                                ],
                            }
                        ],
                    }
                ],
                "decisions": (
                    [
                        {
                            "confirmation_id": (
                                "material_confirmation_visual"
                            ),
                            "review_id": "material_review_visual",
                            "decision": "confirmed",
                            "confirmed_by": "local_user",
                        }
                    ]
                    if state == "materials_confirmed"
                    else []
                ),
            }
            if state in {"material_reviewed", "materials_confirmed"}
            else None
        ),
        latest_result={"status": state},
        allowed_actions=allowed,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state",
        choices=[
            "dialogue",
            "needs_clarification",
            "proposal_ready",
            "material_requirements_ready",
            "material_reviewed",
            "materials_confirmed",
            "confirmed",
            "succeeded",
            "error",
        ],
        default="dialogue",
    )
    parser.add_argument("--port", type=int, default=8772)
    args = parser.parse_args()
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        product_entry_service=StaticProduct(_view(args.state)),
        product_csrf_token="visual_csrf_token",
    )
    server = create_preview_server(application, port=args.port)
    print(f"Product visual fixture: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
