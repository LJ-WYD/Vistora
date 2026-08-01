"""Deterministic STEP 18 multi-track/link execution reference."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import EditingAgent  # noqa: E402
from atomic_runtime import build_production_registry  # noqa: E402
from audio_analysis import LoudnessAnalysisRequest, LoudnessAnalysisService  # noqa: E402
from contracts import (  # noqa: E402
    DirectorOperation,
    DirectorPlan,
    MediaTimeRangeLocator,
    SourceEvidenceReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    AppliedLoudnessNormalization,
    ClipConfig,
    TimelineConfig,
    TimelineTransition,
    TrackConfig,
    TransitionParameters,
)
from plan_review import (  # noqa: E402
    PlanDiffRequest,
    PreviewMaterialFact,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import WorkflowApplicationService, WorkflowStore  # noqa: E402


REFERENCE_TIME = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _run(command: list[str]) -> None:
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _fixtures(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    main = root / "main.mp4"
    overlay = root / "overlay.mp4"
    dialogue = root / "dialogue.wav"
    music = root / "music.wav"
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x1d4ed8:s=320x180:r=24:d=4",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=4",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(main),
    ])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0xdc2626:s=160x90:r=24:d=4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(overlay),
    ])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=4",
        str(dialogue),
    ])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4",
        str(music),
    ])
    return {
        "main": main,
        "overlay": overlay,
        "dialogue": dialogue,
        "music": music,
    }


def _metadata(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate",
            "-show_entries", "format=duration,size",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def run_multitrack_reference_workflow() -> dict:
    test_data = ROOT / "tests" / "test_data"
    root = test_data / "multitrack_reference_generated"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        media = _fixtures(root / "media")
        workspace = root / "workspace"
        project_file = workspace / "current_timeline.json"
        output = root / "multitrack_output.mp4"
        subtitle_sidecar = root / "multitrack_output.vtt"
        timeline = TimelineConfig(
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
                        ClipConfig(
                            id="clip_video_main",
                            source=str(media["main"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0,
                            keep_audio=True,
                            link_group_id="link_scene_main",
                        )
                    ],
                ),
                "v-overlay": TrackConfig(
                    id="track_video_overlay",
                    kind="video",
                    role="overlay",
                    order=1,
                    clips=[
                        ClipConfig(
                            id="clip_video_overlay",
                            source=str(media["overlay"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0.5,
                            keep_audio=False,
                        )
                    ],
                ),
                "a-dialogue": TrackConfig(
                    id="track_audio_dialogue",
                    kind="audio",
                    role="dialogue",
                    order=2,
                    clips=[
                        ClipConfig(
                            id="clip_audio_dialogue",
                            source=str(media["dialogue"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0,
                            link_group_id="link_scene_main",
                        )
                    ],
                ),
                "a-music": TrackConfig(
                    id="track_audio_music",
                    kind="audio",
                    role="music",
                    order=3,
                    clips=[
                        ClipConfig(
                            id="clip_audio_music",
                            source=str(media["music"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0,
                            volume=0.15,
                        )
                    ],
                ),
            },
        )
        counter = {"value": 0}

        def identifier(prefix: str) -> str:
            counter["value"] += 1
            return f"{prefix}_{counter['value']:04d}"

        registry = build_production_registry(
            timeline_id_factory=identifier
        )
        with (
            patch.object(
                timeline_manager,
                "WORKSPACE_DIR",
                str(workspace),
            ),
            patch.object(
                timeline_manager,
                "PROJECT_FILE",
                str(project_file),
            ),
        ):
            timeline_manager.TimelineManager.save_current_timeline(timeline)
            original = json.loads(project_file.read_text(encoding="utf-8"))
            snapshot = TimelineSnapshotService.snapshot_current()
            video = next(
                clip
                for track in snapshot.tracks
                for clip in track.clips
                if clip.clip_id == "clip_video_main"
            )
            audio = next(
                clip
                for track in snapshot.tracks
                for clip in track.clips
                if clip.clip_id == "clip_audio_dialogue"
            )
            evidence = (
                SourceEvidenceReference(
                    evidence_id="evidence_video_main",
                    material_id=video.source.source_id,
                    locator=MediaTimeRangeLocator(
                        start_seconds=0,
                        end_seconds=4,
                    ),
                ),
                SourceEvidenceReference(
                    evidence_id="evidence_audio_dialogue",
                    material_id=audio.source.source_id,
                    locator=MediaTimeRangeLocator(
                        start_seconds=0,
                        end_seconds=4,
                    ),
                ),
            )
            loudness = LoudnessAnalysisService().analyze(
                timeline,
                LoudnessAnalysisRequest(
                    track_id="track_audio_dialogue",
                    clip_id="clip_audio_dialogue",
                    target_lufs=-16,
                    max_true_peak_dbfs=-1,
                ),
            )
            loudness_evidence = AppliedLoudnessNormalization(
                analysis_id=loudness.analysis_id,
                analyzed_clip_digest=loudness.analyzed_clip_digest,
                source_sha256=loudness.source_sha256,
                integrated_lufs=loudness.integrated_lufs,
                true_peak_dbfs=loudness.true_peak_dbfs,
                target_lufs=loudness.target_lufs,
                max_true_peak_dbfs=loudness.max_true_peak_dbfs,
                applied_gain_db=loudness.recommended_gain_db,
            )
            operations = (
                DirectorOperation(
                    operation_id="operation_dialogue_loudness",
                    tool_name="AudioSetClipPropertiesSkill",
                    arguments={
                        "track_id": "track_audio_dialogue",
                        "clip_id": "clip_audio_dialogue",
                        "gain_db": loudness.recommended_gain_db,
                        "pan": 0.2,
                        "fade_in_seconds": 0.1,
                        "fade_out_seconds": 0.2,
                        "normalization_evidence": loudness_evidence.model_dump(mode="json"),
                    },
                    rationale="Normalize and place the verified dialogue safely.",
                    expected_effect="Apply analyzed gain, pan, and bounded fades.",
                    evidence_ids=("evidence_audio_dialogue",),
                ),
                DirectorOperation(
                    operation_id="operation_music_mix",
                    tool_name="AudioSetTrackMixSkill",
                    arguments={
                        "track_id": "track_audio_music",
                        "gain_db": -6,
                        "pan": -0.25,
                    },
                    rationale="Place the music under the verified dialogue.",
                    expected_effect="Apply deterministic track gain and pan.",
                ),
                DirectorOperation(
                    operation_id="operation_dialogue_envelope",
                    tool_name="AudioSetVolumeEnvelopeSkill",
                    arguments={
                        "track_id": "track_audio_dialogue",
                        "clip_id": "clip_audio_dialogue",
                        "action": "upsert",
                        "point_id": "envelope_dialogue_mid",
                        "offset_seconds": 1,
                        "gain_db": -3,
                    },
                    rationale="Add one bounded linear dialogue automation point.",
                    expected_effect="Create deterministic clip-local automation.",
                    evidence_ids=("evidence_audio_dialogue",),
                ),
                DirectorOperation(
                    operation_id="operation_music_mute",
                    tool_name="AudioSetClipPropertiesSkill",
                    arguments={
                        "track_id": "track_audio_music",
                        "clip_id": "clip_audio_music",
                        "muted": True,
                    },
                    rationale="Mute the optional music layer for this reference cut.",
                    expected_effect="Exclude only the selected music component.",
                ),
                DirectorOperation(
                    operation_id="operation_linked_split",
                    tool_name="VideoSplitClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_main",
                        "split_at_seconds": 1.5,
                        "right_clip_id": "clip_video_right",
                        "edit_scope": "linked_group",
                    },
                    rationale="Split the verified linked picture and dialogue.",
                    expected_effect="Create aligned linked halves.",
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                ),
                DirectorOperation(
                    operation_id="operation_linked_move",
                    tool_name="VideoMoveClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_main",
                        "timeline_start": 0.25,
                        "ripple": False,
                        "edit_scope": "linked_group",
                    },
                    rationale="Move the linked opening together.",
                    expected_effect="Move both verified linked members.",
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                ),
                DirectorOperation(
                    operation_id="operation_overlay_only",
                    tool_name="VideoMoveClipSkill",
                    arguments={
                        "track_id": "track_video_overlay",
                        "clip_id": "clip_video_overlay",
                        "timeline_start": 0.75,
                        "ripple": False,
                        "edit_scope": "current_clip",
                    },
                    rationale="Adjust only the overlay layer.",
                    expected_effect="Leave linked picture/dialogue unchanged.",
                ),
                DirectorOperation(
                    operation_id="operation_linked_ripple_remove",
                    tool_name="VideoRemoveClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_main",
                        "mode": "ripple",
                        "edit_scope": "linked_group",
                    },
                    rationale="Remove the linked opening from both tracks.",
                    expected_effect="Tombstone both members and ripple safely.",
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                ),
                DirectorOperation(
                    operation_id="operation_transition_source_split",
                    tool_name="VideoSplitClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_right",
                        "split_at_seconds": 2.75,
                        "right_clip_id": "clip_video_transition_right",
                        "edit_scope": "current_clip",
                    },
                    rationale="Create one exact reviewed cut for transition validation.",
                    expected_effect="Create two adjacent source-backed picture segments.",
                    evidence_ids=("evidence_video_main",),
                ),
                DirectorOperation(
                    operation_id="operation_transition_add",
                    tool_name="TimelineAddTransitionSkill",
                    arguments={
                        "transition": TimelineTransition(
                            transition_id="transition_reference_video",
                            track_id="track_video_main",
                            from_clip_id="clip_video_right",
                            to_clip_id="clip_video_transition_right",
                            kind="cross_dissolve",
                            duration_seconds=0.5,
                            alignment="centered",
                            parameters=TransitionParameters(),
                            audio_policy="linked_audio",
                            paired_transition_id="transition_reference_audio",
                        ).model_dump(mode="json"),
                        "paired_transition": TimelineTransition(
                            transition_id="transition_reference_audio",
                            track_id="track_video_main",
                            from_clip_id="clip_video_right",
                            to_clip_id="clip_video_transition_right",
                            kind="audio_equal_power",
                            duration_seconds=0.5,
                            alignment="centered",
                            parameters=TransitionParameters(),
                            paired_transition_id="transition_reference_video",
                        ).model_dump(mode="json"),
                    },
                    rationale="Soften the exact cut with explicitly linked picture and embedded audio.",
                    expected_effect="Create reciprocal first-class video/audio transitions.",
                    evidence_ids=("evidence_video_main",),
                ),
                DirectorOperation(
                    operation_id="operation_overlay_transform",
                    tool_name="VideoSetClipTransformSkill",
                    arguments={
                        "track_id": "track_video_overlay",
                        "clip_id": "clip_video_overlay",
                        "action": "set",
                        "transform": {
                            "position_x": 0.72,
                            "position_y": 0.28,
                            "scale_x": 0.62,
                            "scale_y": 0.72,
                            "rotation_degrees": 8,
                            "opacity": 0.82,
                            "anchor_x": 0.5,
                            "anchor_y": 0.5,
                            "crop_left": 0.04,
                            "crop_right": 0.03,
                            "crop_top": 0.05,
                            "crop_bottom": 0.02,
                            "fit": "contain",
                            "flip_horizontal": True,
                            "flip_vertical": False,
                        },
                    },
                    rationale="Reframe the verified overlay within the SDR canvas.",
                    expected_effect="Apply exact canvas-relative geometry and opacity.",
                ),
                DirectorOperation(
                    operation_id="operation_overlay_color",
                    tool_name="VideoSetClipColorSkill",
                    arguments={
                        "track_id": "track_video_overlay",
                        "clip_id": "clip_video_overlay",
                        "action": "set",
                        "color": {
                            "exposure": 0.2,
                            "contrast": 0.15,
                            "saturation": 0.25,
                            "temperature": 0.12,
                            "tint": -0.08,
                            "highlights": 0.1,
                            "shadows": -0.06,
                            "gamma": 1.05,
                            "sharpen": 0.15,
                            "blur": 0,
                        },
                    },
                    rationale="Apply a bounded deterministic overlay treatment.",
                    expected_effect="Adjust SDR tone and color without raw filter input.",
                ),
                DirectorOperation(
                    operation_id="operation_copy_overlay_visual",
                    tool_name="VideoCopyClipVisualSkill",
                    arguments={
                        "source_track_id": "track_video_overlay",
                        "source_clip_id": "clip_video_overlay",
                        "targets": [
                            {
                                "track_id": "track_video_main",
                                "clip_id": "clip_video_right",
                            }
                        ],
                        "components": "both",
                    },
                    rationale="Exercise an exact, explicit visual-property copy.",
                    expected_effect="Copy only to the named picture clip, never linked audio.",
                ),
                DirectorOperation(
                    operation_id="operation_reset_copied_visual",
                    tool_name="VideoSetClipTransformSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_right",
                        "action": "reset",
                    },
                    rationale="Restore neutral geometry on the explicit copy target.",
                    expected_effect="Reset transform while retaining its copied color treatment.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_track",
                    tool_name="SubtitleManageTrackSkill",
                    arguments={
                        "action": "create",
                        "track_id": "subtitle_reference",
                        "kind": "subtitle",
                        "role": "captions",
                        "language": "en",
                        "order": 0,
                    },
                    rationale="Create a first-class caption lane for the verified cut.",
                    expected_effect="Add one unlocked subtitle track without changing media.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_batch",
                    tool_name="SubtitleEditCueSkill",
                    arguments={
                        "action": "batch_add",
                        "track_id": "subtitle_reference",
                        "cues": [
                            {
                                "cue_id": "cue_reference_intro",
                                "start_seconds": 0.2,
                                "end_seconds": 0.9,
                                "text": "Vistora reference",
                                "language": "en",
                            },
                            {
                                "cue_id": "cue_reference_outro",
                                "start_seconds": 1.1,
                                "end_seconds": 2.2,
                                "text": "Confirmed subtitle flow",
                                "language": "en",
                            },
                        ],
                    },
                    rationale="Add exact reviewed cue timings.",
                    expected_effect="Create two deterministic subtitle cues.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_update",
                    tool_name="SubtitleEditCueSkill",
                    arguments={
                        "action": "update",
                        "track_id": "subtitle_reference",
                        "cue_id": "cue_reference_intro",
                        "text": "Vistora · confirmed reference",
                    },
                    rationale="Use the approved opening caption copy.",
                    expected_effect="Change only the first cue text.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_split",
                    tool_name="SubtitleEditCueSkill",
                    arguments={
                        "action": "split",
                        "track_id": "subtitle_reference",
                        "cue_id": "cue_reference_outro",
                        "split_at_seconds": 1.6,
                        "right_cue_id": "cue_reference_outro_right",
                    },
                    rationale="Exercise exact cue splitting.",
                    expected_effect="Create two adjacent timed subtitle cues.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_merge",
                    tool_name="SubtitleEditCueSkill",
                    arguments={
                        "action": "merge",
                        "track_id": "subtitle_reference",
                        "merge_cue_ids": [
                            "cue_reference_outro",
                            "cue_reference_outro_right",
                        ],
                        "merged_cue_id": "cue_reference_outro",
                    },
                    rationale="Exercise deterministic adjacent cue merging.",
                    expected_effect="Restore one exact outro cue range.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_style",
                    tool_name="SubtitleEditCueSkill",
                    arguments={
                        "action": "set_style",
                        "track_id": "subtitle_reference",
                        "cue_id": "cue_reference_intro",
                        "style": {
                            "font_family": "sans",
                            "fallback_families": ["sans"],
                            "font_size": 34,
                            "color": "#FFFFFFFF",
                            "outline_color": "#000000FF",
                            "background_color": "#00000000",
                            "outline_width": 2,
                            "alignment": "center",
                            "position": "bottom",
                            "safe_margin_x": 0.05,
                            "safe_margin_y": 0.08,
                            "bold": True,
                            "italic": False,
                        },
                    },
                    rationale="Apply one controlled logical-font subtitle style.",
                    expected_effect="Style only the opening cue without accepting a font path.",
                ),
                DirectorOperation(
                    operation_id="operation_subtitle_sidecar",
                    tool_name="SubtitleExportSidecarSkill",
                    arguments={
                        "output_path": str(subtitle_sidecar),
                        "format": "vtt",
                        "track_ids": ["subtitle_reference"],
                    },
                    rationale="Export the reviewed subtitle cues as a sidecar.",
                    expected_effect="Write one deterministic UTF-8 WebVTT artifact.",
                ),
                DirectorOperation(
                    operation_id="operation_export_multitrack",
                    tool_name="VideoExportSkill",
                    arguments={
                        "output_path": str(output),
                        "clear_timeline_after": False,
                        "subtitle_mode": "burn",
                        "subtitle_track_ids": ["subtitle_reference"],
                    },
                    rationale="Render the reviewed layers and audio mix.",
                    expected_effect="Produce one deterministic local export.",
                ),
            )
            plan = DirectorPlan(
                plan_id="plan_multitrack_reference",
                plan_version=1,
                created_at=REFERENCE_TIME,
                objective="Verify confirmed multi-track linked editing.",
                source_evidence=evidence,
                operations=operations,
            )
            proposed = ProposedEditingExecutionPlan.from_director_plan(
                proposal_execution_id="proposal_multitrack_reference",
                project_id=snapshot.project_id,
                director_plan=plan,
            )
            request = PlanDiffRequest(
                request_id="review_multitrack_reference",
                snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
                director_plan=plan,
                proposed_execution=proposed,
                registry_ref=RegistrySchemaReference.from_registry(registry),
                material_facts=tuple(
                    PreviewMaterialFact(
                        material_id=clip.source.source_id,
                        media_kind=track.kind,
                        duration_seconds=4,
                        width=320 if track.kind == "video" else None,
                        height=180 if track.kind == "video" else None,
                        has_audio=(
                            track.kind == "audio"
                            or clip.clip_id == "clip_video_main"
                        ),
                    )
                    for track in snapshot.tracks
                    for clip in track.clips
                ),
            )
            workflow = WorkflowApplicationService(
                store=WorkflowStore.for_project_file(project_file),
                registry=registry,
                id_factory=identifier,
            )
            review = workflow.record_review(request)
            confirmation = workflow.confirm_review(
                review.review_id,
                confirmed_by="reference_user",
                decision="confirmed",
            )
            agent = EditingAgent(workflow, id_factory=identifier)
            report = agent.execute(
                agent.prepare_execution(
                    request_id="editing_multitrack_reference",
                    confirmation_record_id=(
                        confirmation.confirmation_record_id
                    ),
                )
            )
            if report.status != "succeeded":
                raise AssertionError(report.model_dump(mode="json"))
            metadata = _metadata(output)
            trace = TraceabilityStore.load(project_file)
            subtitle_relations = tuple(
                relation
                for confirmed_trace in trace.confirmed_traces
                for relation in confirmed_trace.relations
                if relation.entity.entity_kind
                in {"subtitle_track", "subtitle_cue"}
            )
            visual_relations = tuple(
                relation
                for confirmed_trace in trace.confirmed_traces
                for relation in confirmed_trace.relations
                if confirmed_trace.request.tool_name in {
                    "VideoSetClipTransformSkill",
                    "VideoSetClipColorSkill",
                    "VideoCopyClipVisualSkill",
                }
            )
            transition_relations = tuple(
                relation
                for confirmed_trace in trace.confirmed_traces
                for relation in confirmed_trace.relations
                if relation.entity.entity_kind == "transition"
            )
            if not any(
                relation.relation_type == "creates"
                for relation in subtitle_relations
            ):
                raise AssertionError("Subtitle creation provenance was not recorded")
            if not any(
                relation.relation_type == "deletes"
                for relation in subtitle_relations
            ):
                raise AssertionError("Subtitle merge tombstone was not recorded")
            current = TimelineSnapshotService.snapshot_current()
            rollback_review = workflow.propose_rollback(report.run_id)
            rollback_confirmation = workflow.confirm_rollback(
                rollback_review.review_id,
                confirmed_by="reference_user",
                decision="confirmed",
            )
            rollback = workflow.apply_rollback(
                rollback_confirmation.confirmation_id
            )
            restored = json.loads(project_file.read_text(encoding="utf-8"))
            if restored != original:
                raise AssertionError("Rollback did not restore the timeline")
            return {
                "review_digest": review.diff.digest(),
                "review_change_count": len(review.diff.changes),
                "execution_status": report.status,
                "step_count": len(report.steps),
                "trace_count": len(trace.confirmed_traces),
                "subtitle_trace_count": len(subtitle_relations),
                "visual_trace_count": len(visual_relations),
                "transition_trace_count": len(transition_relations),
                "subtitle_tombstone_count": sum(
                    relation.relation_type == "deletes"
                    for relation in subtitle_relations
                ),
                "current_track_count": current.track_count,
                "current_video_clip_count": current.video_clip_count,
                "current_audio_clip_count": current.audio_clip_count,
                "current_subtitle_track_count": current.subtitle_track_count,
                "current_subtitle_cue_count": current.subtitle_cue_count,
                "current_transition_count": current.transition_count,
                "rollback_status": rollback.status,
                "subtitle_sidecar": subtitle_sidecar.read_text(encoding="utf-8"),
                "loudness_analysis_id": loudness.analysis_id,
                "loudness_gain_db": loudness.recommended_gain_db,
                "output": metadata,
            }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    print(
        json.dumps(
            run_multitrack_reference_workflow(),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
