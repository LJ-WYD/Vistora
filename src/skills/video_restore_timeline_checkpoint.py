"""Atomic timeline-state restore used only by a confirmed rollback run."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from core import timeline_manager
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService
from workflow.models import RollbackConfirmationRecord, RollbackProposal

from .base import BaseSkill


class VideoRestoreTimelineCheckpointInput(BaseModel):
    """Exact reviewed rollback payload; no media files are removed/restored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: RollbackProposal
    confirmation: RollbackConfirmationRecord

    @model_validator(mode="after")
    def rollback_is_exactly_confirmed(
        self,
    ) -> VideoRestoreTimelineCheckpointInput:
        if not self.confirmation.confirms(self.proposal):
            raise ValueError(
                "Timeline restore requires an exact confirmed rollback proposal"
            )
        return self


class VideoRestoreTimelineCheckpointSkill(BaseSkill):
    """Replace current timeline JSON with one integrity-checked checkpoint."""

    name = "VideoRestoreTimelineCheckpointSkill"
    description = (
        "Restore only Vistora timeline/project state from an exact reviewed "
        "and confirmed workflow checkpoint. External exports and generated "
        "media are intentionally not deleted or reversed."
    )
    input_model = VideoRestoreTimelineCheckpointInput

    @staticmethod
    def _write_atomic(project_file: Path, text: str) -> None:
        project_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = project_file.parent / (
            f".{project_file.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open(
                "x",
                encoding="utf-8",
                newline="\n",
            ) as output:
                output.write(text)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, project_file)
        finally:
            temporary.unlink(missing_ok=True)

    def run(
        self,
        params: VideoRestoreTimelineCheckpointInput,
    ) -> dict[str, Any]:
        proposal = params.proposal
        project_file = Path(timeline_manager.PROJECT_FILE)
        current = TimelineSnapshotService.snapshot_current()
        current_ref = TimelineSnapshotReference.from_snapshot(current)
        if current_ref != proposal.current_checkpoint.snapshot_ref:
            raise ValueError(
                "Current timeline drifted after rollback review; regenerate "
                "the rollback proposal"
            )

        prior_exists = project_file.exists()
        prior_bytes = project_file.read_bytes() if prior_exists else None
        timeline_text = (
            proposal.target_checkpoint.timeline_document.timeline
            .model_dump_json(indent=2)
        )
        try:
            self._write_atomic(project_file, timeline_text)
            restored = TimelineSnapshotService.snapshot_current()
            restored_ref = TimelineSnapshotReference.from_snapshot(restored)
            target = proposal.target_checkpoint.snapshot_ref
            if (
                restored_ref.timeline_digest != target.timeline_digest
                or restored_ref.snapshot_id != target.snapshot_id
                or restored_ref.project_id != target.project_id
            ):
                raise RuntimeError(
                    "Restored timeline does not match checkpoint integrity"
                )
        except Exception:
            if prior_exists and prior_bytes is not None:
                self._write_atomic(
                    project_file,
                    prior_bytes.decode("utf-8"),
                )
            else:
                project_file.unlink(missing_ok=True)
            raise

        return {
            "status": "success",
            "restored_checkpoint_id": (
                proposal.target_checkpoint.checkpoint_id
            ),
            "timeline_digest": restored_ref.timeline_digest,
            "external_artifacts_changed": False,
        }
