from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.timeline import ClipConfig, TimelineConfig, TrackConfig
from contracts import (
    ManualClipLink,
    ManualClipReference,
    ManualEditProposal,
    ManualTrackManage,
)
from timeline_edit import TimelineEditEngine, TimelineEditError
from timeline_preview.manual_edits import review_manual_edit_proposal
from timeline_query import TimelineSnapshotService


def _clip(
    clip_id: str,
    start: float,
    *,
    source: str = "material.mp4",
    link: str | None = None,
) -> ClipConfig:
    return ClipConfig(
        id=clip_id,
        source=source,
        trim_in=0,
        trim_out=4,
        timeline_start=start,
        link_group_id=link,
    )


def _timeline(*, locked_audio: bool = False) -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "v-main": TrackConfig(
                id="track_video_main",
                kind="video",
                role="primary",
                order=0,
                clips=[
                    _clip("video_linked", 0, link="link_scene"),
                    _clip("video_tail", 4),
                ],
            ),
            "v-overlay": TrackConfig(
                id="track_video_overlay",
                kind="video",
                role="overlay",
                order=1,
                clips=[_clip("overlay_clip", 1)],
            ),
            "a-dialogue": TrackConfig(
                id="track_audio_dialogue",
                kind="audio",
                role="dialogue",
                order=2,
                locked=locked_audio,
                clips=[
                    _clip(
                        "audio_linked",
                        0,
                        source="dialogue.wav",
                        link="link_scene",
                    ),
                    _clip("audio_tail", 4, source="dialogue.wav"),
                ],
            ),
            "a-music": TrackConfig(
                id="track_audio_music",
                kind="audio",
                role="music",
                order=3,
                muted=True,
            ),
        },
    )


def _find(timeline: TimelineConfig, clip_id: str) -> ClipConfig:
    return next(
        clip
        for track in timeline.tracks.values()
        for clip in track.clips
        if clip.id == clip_id
    )


def test_legacy_fixed_tracks_migrate_deterministically() -> None:
    legacy = {
        "width": 640,
        "height": 360,
        "fps": 30,
        "tracks": {
            "video": {"id": "video", "clips": []},
            "audio": {"id": "audio", "clips": []},
        },
    }
    first = TimelineConfig.model_validate(legacy)
    second = TimelineConfig.model_validate_json(json.dumps(legacy))
    assert first == second
    assert first.schema_version == "2.0.0"
    assert first.tracks["video"].kind == "video"
    assert first.tracks["audio"].kind == "audio"
    assert first.tracks["video"].order == 0
    assert first.tracks["audio"].order == 1


def test_snapshot_exposes_detached_ordered_multitrack_state() -> None:
    source = _timeline()
    before = source.model_dump(mode="json")
    snapshot = TimelineSnapshotService.snapshot(source)
    assert snapshot.schema_version == "8.0.0"
    assert [track.track_id for track in snapshot.tracks] == [
        "track_video_main",
        "track_video_overlay",
        "track_audio_dialogue",
        "track_audio_music",
    ]
    assert snapshot.tracks[2].locked is False
    assert snapshot.tracks[3].muted is True
    assert snapshot.tracks[0].clips[0].link_group_id == "link_scene"
    assert source.model_dump(mode="json") == before


def test_linked_split_preserves_properties_and_creates_new_group() -> None:
    ids = iter(("link_right", "audio_right"))
    updated, outcome = TimelineEditEngine(
        _timeline(),
        id_factory=lambda _prefix: next(ids),
    ).split(
        "track_video_main",
        "video_linked",
        2,
        right_clip_id="video_right",
        edit_scope="linked_group",
    )
    video_right = _find(updated, "video_right")
    audio_right = _find(updated, "audio_right")
    assert video_right.trim_in == audio_right.trim_in == 2
    assert video_right.timeline_start == audio_right.timeline_start == 2
    assert video_right.link_group_id == audio_right.link_group_id
    assert video_right.link_group_id != "link_scene"
    assert outcome.track_id == "track_video_main"
    assert set(outcome.consequential_clip_ids) == {
        "audio_linked",
        "audio_right",
    }


def test_current_only_and_linked_move_are_explicit() -> None:
    current, _ = TimelineEditEngine(_timeline()).move(
        "track_video_main",
        "video_linked",
        1,
        ripple=False,
        edit_scope="current_clip",
    )
    assert _find(current, "video_linked").timeline_start == 1
    assert _find(current, "audio_linked").timeline_start == 0

    linked, outcome = TimelineEditEngine(_timeline()).move(
        "track_video_main",
        "video_linked",
        1,
        ripple=False,
        edit_scope="linked_group",
    )
    assert _find(linked, "video_linked").timeline_start == 1
    assert _find(linked, "audio_linked").timeline_start == 1
    assert "audio_linked" in outcome.consequential_clip_ids


def test_linked_ripple_remove_closes_each_affected_track() -> None:
    updated, outcome = TimelineEditEngine(_timeline()).remove(
        "track_video_main",
        "video_linked",
        ripple=True,
        edit_scope="linked_group",
    )
    assert _find(updated, "video_tail").timeline_start == 0
    assert _find(updated, "audio_tail").timeline_start == 0
    assert set(outcome.deleted_clip_ids) == {
        "video_linked",
        "audio_linked",
    }


def test_linked_trim_and_playback_properties_are_explicit() -> None:
    trimmed, trim_outcome = TimelineEditEngine(_timeline()).trim(
        "track_video_main",
        "video_linked",
        0.5,
        3.5,
        ripple=True,
        edit_scope="linked_group",
    )
    assert (_find(trimmed, "video_linked").trim_in, _find(
        trimmed, "video_linked"
    ).trim_out) == (0.5, 3.5)
    assert (_find(trimmed, "audio_linked").trim_in, _find(
        trimmed, "audio_linked"
    ).trim_out) == (0.5, 3.5)
    assert _find(trimmed, "video_tail").timeline_start == 3
    assert _find(trimmed, "audio_tail").timeline_start == 3
    assert "audio_linked" in trim_outcome.consequential_clip_ids

    changed, property_outcome = TimelineEditEngine(_timeline()).set_properties(
        "track_video_main",
        "video_linked",
        speed_factor=2,
        volume=0.5,
        keep_audio=None,
        mute=None,
        rotate=None,
        edit_scope="linked_group",
    )
    assert _find(changed, "video_linked").speed_factor == 2
    assert _find(changed, "audio_linked").speed_factor == 2
    assert _find(changed, "audio_linked").volume == 0.5
    assert "audio_linked" in property_outcome.consequential_clip_ids


def test_insert_uses_explicit_group_and_never_infers_link_membership() -> None:
    inserted = _clip(
        "inserted_video",
        1,
        source="inserted.mp4",
        link="link_inserted",
    )
    updated, outcome = TimelineEditEngine(
        _timeline(),
        id_factory=lambda prefix: f"{prefix}_right",
    ).insert_overwrite(
        "track_video_overlay",
        inserted,
        mode="overwrite",
        edit_scope="linked_group",
    )
    assert _find(updated, "inserted_video").link_group_id == "link_inserted"
    assert not any(
        clip.link_group_id == "link_inserted"
        for track in updated.tracks.values()
        for clip in track.clips
        if clip.id != "inserted_video"
    )
    assert any(
        "separate confirmed request" in warning
        for warning in outcome.warnings
    )

    with pytest.raises(TimelineEditError, match="link_group_id"):
        TimelineEditEngine(_timeline()).insert_overwrite(
            "track_video_overlay",
            _clip("unlinked_insert", 1),
            mode="insert",
            edit_scope="linked_group",
        )


def test_locked_link_member_fails_closed_without_mutation() -> None:
    source = _timeline(locked_audio=True)
    before = source.model_dump(mode="json")
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(source).split(
            "track_video_main",
            "video_linked",
            2,
            edit_scope="linked_group",
        )
    assert source.model_dump(mode="json") == before


def test_track_management_and_explicit_link_unlink() -> None:
    engine = TimelineEditEngine(_timeline())
    updated, outcome = engine.manage_track(
        action="add",
        track_id="track_audio_fx",
        kind="audio",
        role="effects",
        order=4,
        enabled=True,
        muted=False,
        locked=False,
    )
    assert updated.tracks["track_audio_fx"].kind == "audio"
    assert outcome.operation == "manage_track"

    updated, _ = TimelineEditEngine(updated).set_clip_link(
        action="unlink",
        members=(
            ("track_video_main", "video_linked"),
            ("track_audio_dialogue", "audio_linked"),
        ),
        link_group_id=None,
    )
    assert _find(updated, "video_linked").link_group_id is None
    assert _find(updated, "audio_linked").link_group_id is None


def test_multitrack_invariants_reject_duplicate_track_order() -> None:
    payload = _timeline().model_dump(mode="python")
    payload["tracks"]["a-music"]["order"] = 2
    with pytest.raises(ValueError, match="order"):
        TimelineConfig.model_validate(payload)


def test_manual_multitrack_link_and_track_state_are_review_only() -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    proposal = ManualEditProposal(
        proposal_id="manual_multitrack_review",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        edits=(
            ManualClipLink(
                operation_id="manual_unlink_scene",
                action="unlink",
                members=(
                    ManualClipReference(
                        track_key="v-main",
                        track_id="track_video_main",
                        clip_id="video_linked",
                    ),
                    ManualClipReference(
                        track_key="a-dialogue",
                        track_id="track_audio_dialogue",
                        clip_id="audio_linked",
                    ),
                ),
            ),
            ManualTrackManage(
                operation_id="manual_mute_music",
                track_key="a-music",
                track_id="track_audio_music",
                action="update",
                muted=False,
            ),
        ),
    )
    review = review_manual_edit_proposal(snapshot, proposal)
    assert snapshot.tracks[0].clips[0].link_group_id == "link_scene"
    assert {
        (change.target_kind, change.clip_id)
        for change in review.changes
    } == {
        ("clip", "video_linked"),
        ("clip", "audio_linked"),
        ("track", "track_audio_music"),
    }
