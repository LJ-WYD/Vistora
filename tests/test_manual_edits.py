import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from contracts import (  # noqa: E402
    ManualClipRemove,
    ManualClipUpdate,
    ManualEditConfirmationRecord,
    ManualEditProposal,
)
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from skills.video_apply_manual_edits import (  # noqa: E402
    VideoApplyManualEditsSkill,
)
from timeline_preview.manual_edits import (  # noqa: E402
    ManualEditApplicationService,
    ManualEditValidationError,
)
from timeline_query import TimelineSnapshotService  # noqa: E402


FIXED_TIME = datetime(2026, 7, 24, tzinfo=timezone.utc)


def _timeline() -> TimelineConfig:
    return TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[
                    ClipConfig(
                        id="clip_a",
                        source="a.mp4",
                        trim_in=0.0,
                        trim_out=2.0,
                        timeline_start=0.0,
                    ),
                    ClipConfig(
                        id="clip_b",
                        source="b.mp4",
                        trim_in=0.0,
                        trim_out=3.0,
                        timeline_start=2.0,
                    ),
                ],
            ),
            "audio": TrackConfig(id="audio"),
        },
    )


def _proposal(snapshot, *edits) -> ManualEditProposal:
    return ManualEditProposal(
        proposal_id="manual_proposal_demo",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        edits=edits,
        created_at=FIXED_TIME,
    )


def _update(**changes) -> ManualClipUpdate:
    values = {
        "operation_id": "manual_update_b",
        "clip_id": "clip_b",
        "trim_in_seconds": 0.5,
        "trim_out_seconds": 2.5,
        "timeline_start_seconds": 1.0,
        "order_index": 0,
    }
    values.update(changes)
    return ManualClipUpdate(**values)


def _confirmation(
    proposal: ManualEditProposal,
    **changes,
) -> ManualEditConfirmationRecord:
    values = {
        "confirmation_id": "manual_confirmation_demo",
        "proposal": proposal,
        "confirmed_by": "local_user",
        "recorded_at": FIXED_TIME,
    }
    values.update(changes)
    return ManualEditConfirmationRecord.for_proposal(**values)


@pytest.fixture
def isolated_timeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    workspace = tmp_path / "workspace"
    project_file = workspace / "current_timeline.json"
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    timeline_manager.TimelineManager.save_current_timeline(_timeline())
    return project_file


def test_manual_contracts_are_versioned_immutable_and_exactly_confirmed() -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    proposal = _proposal(snapshot, _update())
    confirmation = _confirmation(proposal)

    assert confirmation.confirms(proposal)
    assert proposal.digest().startswith("sha256:")
    assert ManualEditProposal.model_validate_json(
        proposal.model_dump_json()
    ) == proposal
    assert ManualEditConfirmationRecord.model_validate_json(
        confirmation.model_dump_json()
    ) == confirmation

    with pytest.raises(ValidationError, match="frozen"):
        proposal.authored_by = "changed"
    with pytest.raises(ValidationError, match="after trim-in"):
        _update(trim_in_seconds=3.0, trim_out_seconds=2.0)

    changed = proposal.model_copy(
        update={"authored_by": "different_user"}
    )
    assert confirmation.confirms(changed) is False


def test_review_is_structured_and_does_not_write_before_confirmation(
    isolated_timeline: Path,
) -> None:
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = _proposal(snapshot, _update())
    service = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        {"VideoApplyManualEditsSkill": VideoApplyManualEditsSkill()},
    )
    before = isolated_timeline.read_bytes()

    normalized, review = service.review(proposal.model_dump(mode="json"))

    assert normalized == proposal
    assert isolated_timeline.read_bytes() == before
    assert review.proposal_ref.proposal_digest == proposal.digest()
    assert review.changes[0].before["order_index"] == 1
    assert review.changes[0].after["order_index"] == 0
    assert review.changes[0].after["trim_in_seconds"] == 0.5


def test_confirmed_atomic_skill_updates_reorders_removes_and_persists(
    isolated_timeline: Path,
) -> None:
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = _proposal(
        snapshot,
        _update(),
        ManualClipRemove(
            operation_id="manual_remove_a",
            clip_id="clip_a",
        ),
    )
    confirmation = _confirmation(proposal)

    result = VideoApplyManualEditsSkill().execute(
        {
            "proposal": proposal.model_dump(mode="json"),
            "confirmation": confirmation.model_dump(mode="json"),
        }
    )

    persisted = timeline_manager.TimelineManager.get_current_timeline()
    assert result["status"] == "success"
    assert result["proposal_id"] == proposal.proposal_id
    assert result["confirmation_id"] == confirmation.confirmation_id
    assert result["applied_operation_ids"] == [
        "manual_update_b",
        "manual_remove_a",
    ]
    assert [clip.id for clip in persisted.tracks["video"].clips] == [
        "clip_b"
    ]
    assert persisted.tracks["video"].clips[0].trim_in == 0.5
    assert persisted.tracks["video"].clips[0].trim_out == 2.5
    assert persisted.tracks["video"].clips[0].timeline_start == 1.0
    assert not list(isolated_timeline.parent.glob("*.tmp"))


def test_rejected_mismatched_and_stale_proposals_never_write(
    isolated_timeline: Path,
) -> None:
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = _proposal(snapshot, _update())
    rejected = _confirmation(proposal, decision="rejected")
    before = isolated_timeline.read_bytes()
    skill = VideoApplyManualEditsSkill()

    with pytest.raises(ValueError, match="requires confirmation"):
        skill.execute(
            {
                "proposal": proposal.model_dump(mode="json"),
                "confirmation": rejected.model_dump(mode="json"),
            }
        )
    assert isolated_timeline.read_bytes() == before

    changed = timeline_manager.TimelineManager.get_current_timeline()
    changed.width = 1280
    timeline_manager.TimelineManager.save_current_timeline(changed)
    changed_bytes = isolated_timeline.read_bytes()
    with pytest.raises(ValueError, match="stale"):
        skill.execute(
            {
                "proposal": proposal.model_dump(mode="json"),
                "confirmation": _confirmation(proposal).model_dump(
                    mode="json"
                ),
            }
        )
    assert isolated_timeline.read_bytes() == changed_bytes


def test_atomic_save_failure_preserves_original_and_cleans_temp(
    isolated_timeline: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = _proposal(snapshot, _update())
    confirmation = _confirmation(proposal)
    before = isolated_timeline.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(
        "skills.video_apply_manual_edits.os.replace",
        fail_replace,
    )
    with pytest.raises(OSError, match="simulated"):
        VideoApplyManualEditsSkill().execute(
            {
                "proposal": proposal.model_dump(mode="json"),
                "confirmation": confirmation.model_dump(mode="json"),
            }
        )

    assert isolated_timeline.read_bytes() == before
    assert not list(isolated_timeline.parent.glob("*.tmp"))


def test_review_rejects_invalid_target_order_and_unknown_clip() -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    service = ManualEditApplicationService(
        lambda: snapshot,
        {"VideoApplyManualEditsSkill": VideoApplyManualEditsSkill()},
    )
    invalid_order = _proposal(snapshot, _update(order_index=9))
    with pytest.raises(ManualEditValidationError, match="outside"):
        service.review(invalid_order)

    unknown_clip = _proposal(
        snapshot,
        _update(clip_id="clip_unknown"),
    )
    with pytest.raises(ManualEditValidationError, match="exactly one"):
        service.review(unknown_clip)
