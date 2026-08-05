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
        "materials_confirmed": ("plan_material_production",),
        "production_plan_ready": (
            "confirm_production_plan",
            "reject_production_plan",
            "withdraw_production_plan",
        ),
        "production_plan_confirmed": (),
        "production_plan_unsupported": ("plan_material_production",),
        "material_production_running": (
            "poll_material_production",
            "cancel_material_job",
        ),
        "material_awaiting_review": (
            "accept_material_artifact",
            "reject_material_artifact",
        ),
        "material_production_partial": ("retry_material_job",),
        "material_production_failed": ("retry_material_job",),
        "material_production_succeeded": ("return_to_director",),
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
        "production_plan_ready": "material_requirements_ready",
        "production_plan_confirmed": "material_requirements_ready",
        "production_plan_unsupported": "material_requirements_ready",
        "material_production_running": "material_requirements_ready",
        "material_awaiting_review": "material_requirements_ready",
        "material_production_partial": "material_requirements_ready",
        "material_production_failed": "material_requirements_ready",
        "material_production_succeeded": "material_requirements_ready",
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
                    "production_plan_ready",
                    "production_plan_confirmed",
                    "production_plan_unsupported",
                    "material_production_running",
                    "material_awaiting_review",
                    "material_production_partial",
                    "material_production_failed",
                    "material_production_succeeded",
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
                    if state
                    in {
                        "materials_confirmed",
                        "production_plan_ready",
                        "production_plan_confirmed",
                        "production_plan_unsupported",
                        "material_production_running",
                        "material_awaiting_review",
                        "material_production_partial",
                        "material_production_failed",
                        "material_production_succeeded",
                    }
                    else []
                ),
            }
            if state
            in {
                "material_reviewed",
                "materials_confirmed",
                "production_plan_ready",
                "production_plan_confirmed",
                "production_plan_unsupported",
                "material_production_running",
                "material_awaiting_review",
                "material_production_partial",
                "material_production_failed",
                "material_production_succeeded",
            }
            else None
        ),
        creation_planning=(
            {
                "state": (
                    "confirmed"
                    if state
                    in {
                        "production_plan_confirmed",
                        "material_production_running",
                        "material_awaiting_review",
                        "material_production_partial",
                        "material_production_failed",
                        "material_production_succeeded",
                    }
                    else "reviewable"
                ),
                "proposals": [
                    {
                        "proposal_id": "production_proposal_visual",
                        "production_plan_id": "production_plan_visual",
                        "plan_version": 1,
                        "plan_digest": "sha256:" + "8" * 64,
                        "review_id": "production_review_visual",
                        "review_digest": "sha256:" + "9" * 64,
                        "material_confirmation_id": (
                            "material_confirmation_visual"
                        ),
                        "tasks": [
                            {
                                "task_id": "production_task_visual",
                                "requirement_item_id": (
                                    "material_need_visual"
                                ),
                                "title": "Produce the hero interaction shot",
                                "method": "generate",
                                "status": (
                                    "planned"
                                    if state.startswith("material_")
                                    else "unsupported"
                                ),
                                "capability_ids": ["video_generation"],
                                "quality_gates": [
                                    "The UI interaction is readable."
                                ],
                                "limitation": (
                                    None
                                    if state.startswith("material_")
                                    else (
                                        "No video-generation adapter is "
                                        "configured."
                                    )
                                ),
                            }
                        ],
                        "warnings": (
                            []
                            if state.startswith("material_")
                            else [
                                "No video-generation adapter is configured."
                            ]
                        ),
                    }
                ],
                "decisions": (
                    [
                        {
                            "confirmation_id": (
                                "production_confirmation_visual"
                            ),
                            "review_id": "production_review_visual",
                            "decision": "confirmed",
                            "confirmed_by": "local_user",
                        }
                    ]
                    if state
                    in {
                        "production_plan_confirmed",
                        "material_production_running",
                        "material_awaiting_review",
                        "material_production_partial",
                        "material_production_failed",
                        "material_production_succeeded",
                    }
                    else []
                ),
            }
            if state
            in {
                "production_plan_ready",
                "production_plan_confirmed",
                "material_production_running",
                "material_awaiting_review",
                "material_production_partial",
                "material_production_failed",
                "material_production_succeeded",
            }
            else None
        ),
        material_production=(
            {
                "state": {
                    "material_production_running": "running",
                    "material_awaiting_review": "awaiting_review",
                    "material_production_partial": "partial",
                    "material_production_failed": "failed",
                    "material_production_succeeded": "succeeded",
                }[state],
                "ledger_revision": 6,
                "catalog_revision": (
                    1 if state == "material_production_succeeded" else 0
                ),
                "capabilities": [
                    {
                        "capability_id": "user_material_request",
                        "adapter_id": "user_material_request_local",
                        "configured": True,
                        "execution_kind": "human_request",
                        "limitation": None,
                    },
                    {
                        "capability_id": "video_generation",
                        "adapter_id": "unconfigured_video_generation",
                        "configured": False,
                        "execution_kind": "external_provider",
                        "limitation": (
                            "No video-generation provider is configured."
                        ),
                    },
                ],
                "runs": [
                    {
                        "run_id": "production_run_visual",
                        "request_id": "production_request_visual",
                        "production_plan_id": "production_plan_visual",
                        "status": {
                            "material_production_running": "running",
                            "material_awaiting_review": "awaiting_review",
                            "material_production_partial": "partial",
                            "material_production_failed": "failed",
                            "material_production_succeeded": "succeeded",
                        }[state],
                        "message": {
                            "material_production_running": (
                                "The local adapter is processing the task."
                            ),
                            "material_awaiting_review": (
                                "The validated result requires an explicit "
                                "accept or reject decision."
                            ),
                            "material_production_partial": (
                                "The valid result was rejected and may be "
                                "retried without cataloging it."
                            ),
                            "material_production_failed": (
                                "The configured adapter did not produce a "
                                "valid result."
                            ),
                            "material_production_succeeded": (
                                "The accepted material is registered."
                            ),
                        }[state],
                    }
                ],
                "jobs": [
                    {
                        "job_id": "production_job_visual",
                        "run_id": "production_run_visual",
                        "task_id": "production_task_visual",
                        "requirement_item_id": "material_need_visual",
                        "adapter_id": "visual_fixture_adapter",
                        "attempt": 1,
                        "status": {
                            "material_production_running": "running",
                            "material_awaiting_review": "succeeded",
                            "material_production_partial": "succeeded",
                            "material_production_failed": "failed",
                            "material_production_succeeded": "succeeded",
                        }[state],
                        "progress": (
                            0.45
                            if state == "material_production_running"
                            else 1
                        ),
                        "cost_status": "unknown",
                        "cost_value": None,
                        "cost_currency": None,
                        "message": "Browser-safe production status.",
                        "error_code": (
                            "provider_unavailable"
                            if state == "material_production_failed"
                            else None
                        ),
                    }
                ],
                "artifacts": (
                    [
                        {
                            "artifact_id": "artifact_visual",
                            "run_id": "production_run_visual",
                            "job_id": "production_job_visual",
                            "task_id": "production_task_visual",
                            "requirement_item_id": "material_need_visual",
                            "passed": True,
                            "size_bytes": 4096,
                            "mime_type": "video/mp4",
                            "duration_seconds": 6.0,
                            "width": 1080,
                            "height": 1920,
                            "fps": 30.0,
                            "has_audio": False,
                            "issues": [],
                            "decision": (
                                "accepted"
                                if state
                                == "material_production_succeeded"
                                else (
                                    "rejected"
                                    if state
                                    == "material_production_partial"
                                    else None
                                )
                            ),
                        }
                    ]
                    if state
                    in {
                        "material_awaiting_review",
                        "material_production_partial",
                        "material_production_succeeded",
                    }
                    else []
                ),
                "catalog": (
                    [
                        {
                            "material_id": "source_1234567890abcdef",
                            "display_name": "Hero interaction.mp4",
                            "media_kind": "video",
                            "duration_seconds": 6.0,
                            "width": 1080,
                            "height": 1920,
                            "fps": 30.0,
                            "has_audio": False,
                            "origin_kind": "generated",
                            "requirement_item_id": "material_need_visual",
                            "production_task_id": "production_task_visual",
                            "production_run_id": "production_run_visual",
                            "license_status": "unknown",
                            "usage_restrictions": [
                                "Verify usage rights before publishing."
                            ],
                        }
                    ]
                    if state == "material_production_succeeded"
                    else []
                ),
            }
            if state
            in {
                "material_production_running",
                "material_awaiting_review",
                "material_production_partial",
                "material_production_failed",
                "material_production_succeeded",
            }
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
            "production_plan_ready",
            "production_plan_confirmed",
            "production_plan_unsupported",
            "material_production_running",
            "material_awaiting_review",
            "material_production_partial",
            "material_production_failed",
            "material_production_succeeded",
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
