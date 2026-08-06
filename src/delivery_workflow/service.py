"""O32 read/compile/finalize delivery application boundary."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from contracts import DirectorOperation, DirectorPlan
from delivery_qc import DeliveryQCRequest, DeliveryQCService, QCSubtitleCueEvidence
from subtitle_alignment import SubtitleSyncQCInput, SubtitleSyncQCService
from director import digest_json
from plan_review import (
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshotReference

from .models import (
    DeliveryManifest, DeliveryManifestItem, DeliveryPlan,
    ProjectVersionChange, ProjectVersionComparison, ProjectVersionReference,
)


class DeliveryWorkflowError(ValueError):
    pass


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


class DeliveryWorkflowService:
    def __init__(self, *, destinations, clock=lambda: datetime.now(timezone.utc)):
        self.destinations = {key: Path(value).resolve(strict=True) for key, value in destinations.items()}
        if any(not value.is_dir() for value in self.destinations.values()):
            raise DeliveryWorkflowError("Delivery destinations must be existing directories")
        self.clock = clock

    @staticmethod
    def project_version(snapshot, *, version_id):
        return ProjectVersionReference(
            version_id=version_id, project_id=snapshot.project_id,
            project_revision=snapshot.revision, snapshot_id=snapshot.snapshot_id,
            timeline_digest=snapshot.timeline_digest, width=snapshot.width,
            height=snapshot.height, fps=snapshot.fps, track_count=snapshot.track_count,
            clip_count=snapshot.clip_count, subtitle_cue_count=snapshot.subtitle_cue_count,
            transition_count=snapshot.transition_count,
        )

    @staticmethod
    def compare(before, after, *, comparison_id, before_version_id, after_version_id):
        before_ref = DeliveryWorkflowService.project_version(before, version_id=before_version_id)
        after_ref = DeliveryWorkflowService.project_version(after, version_id=after_version_id)
        if before.project_id != after.project_id:
            raise DeliveryWorkflowError("Project version comparison crosses project")
        def entities(snapshot):
            values = {("project_settings", "project_settings"): {"width": snapshot.width, "height": snapshot.height, "fps": snapshot.fps}}
            for track in snapshot.tracks:
                values[("track", track.track_id)] = track.model_dump(mode="json", exclude={"clips"})
                for clip in track.clips:
                    values[("clip", clip.clip_id)] = clip.model_dump(mode="json")
            for track in snapshot.subtitle_tracks:
                values[("track", track.track_id)] = track.model_dump(mode="json", exclude={"cues"})
                for cue in track.cues:
                    values[("cue", cue.cue_id)] = cue.model_dump(mode="json")
            for transition in snapshot.transitions:
                values[("transition", transition.transition_id)] = transition.model_dump(mode="json")
            return values
        left, right = entities(before), entities(after)
        changes = []
        for kind, entity_id in sorted(set(left) | set(right)):
            a, b = left.get((kind, entity_id)), right.get((kind, entity_id))
            if a == b:
                continue
            change_kind = "added" if a is None else "removed" if b is None else "modified"
            changes.append(ProjectVersionChange(
                change_id=f"version_change_{digest_json([kind, entity_id, change_kind])[7:31]}",
                entity_kind=kind, entity_id=entity_id, change_kind=change_kind,
                before_digest=digest_json(a) if a is not None else None,
                after_digest=digest_json(b) if b is not None else None,
            ))
        values = dict(
            comparison_id=comparison_id, before=before_ref, after=after_ref,
            changes=tuple(changes),
            added=sum(item.change_kind == "added" for item in changes),
            removed=sum(item.change_kind == "removed" for item in changes),
            modified=sum(item.change_kind == "modified" for item in changes),
        )
        shell = ProjectVersionComparison.model_construct(**values, comparison_digest="sha256:" + "0" * 64)
        return ProjectVersionComparison(**values, comparison_digest=digest_json(shell.model_dump(mode="json", exclude={"comparison_digest"})))

    def _paths(self, plan):
        root = self.destinations.get(plan.destination_id)
        if root is None:
            raise DeliveryWorkflowError("Delivery destination is not configured")
        paths = {}
        for variant in plan.variants:
            path = (root / variant.filename).resolve()
            if root not in path.parents or path.parent != root:
                raise DeliveryWorkflowError("Delivery filename escapes the destination")
            paths[variant.variant_id] = path
        return paths

    def compile_director_plan(self, plan: DeliveryPlan):
        paths = self._paths(plan)
        operation = DirectorOperation(
            operation_id=f"delivery_operation_{plan.delivery_plan_id}",
            tool_name="VideoExportVariantsSkill",
            arguments={
                "export_set_id": plan.delivery_plan_id,
                "variants": [{
                    "variant_id": variant.variant_id,
                    "output_path": str(paths[variant.variant_id]),
                    "width": variant.width, "height": variant.height, "fps": variant.fps,
                } for variant in plan.variants],
                "subtitle_mode": plan.preferences.subtitle_mode,
                "subtitle_track_ids": list(plan.subtitle_track_ids),
                "subtitle_sync_policy": (
                    "require_aligned" if plan.subtitle_alignment_report is not None
                    else "auto"
                ),
                "output_policy": "create_new",
            },
            rationale=f"Deliver exact project version {plan.project.version_id} under brand pack {plan.brand.brand_pack_id} and preference profile {plan.preferences.preference_id}.",
            expected_effect="Create the reviewed multi-spec delivery set without changing timeline state.",
        )
        return DirectorPlan(
            plan_id=f"director_{plan.delivery_plan_id}", plan_version=plan.version,
            created_at=self.clock(), objective="Render the reviewed multi-spec delivery package.",
            operations=(operation,), outputs=tuple(item.filename for item in plan.variants),
            risks=("Each finished output must pass its bound O31 QC profile.",),
        )

    def review_request(self, plan, snapshot, registry, *, request_id):
        current = self.project_version(snapshot, version_id=plan.project.version_id)
        if current != plan.project:
            raise DeliveryWorkflowError(
                "Delivery project revision changed; regenerate the plan"
            )
        director_plan = self.compile_director_plan(plan)
        return PlanDiffRequest(
            request_id=request_id,
            snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
            director_plan=director_plan,
            proposed_execution=ProposedEditingExecutionPlan.from_director_plan(
                proposal_execution_id=f"proposal_{plan.delivery_plan_id}",
                project_id=snapshot.project_id,
                director_plan=director_plan,
            ),
            registry_ref=RegistrySchemaReference.from_registry(registry),
        )

    def finalize(self, plan, *, confirmation_id, execution_id, atomic_result, timeline=None):
        if atomic_result.status != "success" or atomic_result.tool_name != "VideoExportVariantsSkill" or atomic_result.execution_id != execution_id:
            raise DeliveryWorkflowError("Delivery execution result is failed or mismatched")
        paths = self._paths(plan)
        result_items = {item["variant_id"]: item for item in atomic_result.payload.get("outputs", [])}
        items = []
        for variant in plan.variants:
            path = paths[variant.variant_id]
            if not path.is_file() or variant.variant_id not in result_items:
                raise DeliveryWorkflowError("Delivery output is missing from the exact execution result")
            content_digest = _digest_file(path)
            reported = result_items[variant.variant_id]
            if reported.get("sha256") != content_digest or reported.get("size_bytes") != path.stat().st_size:
                raise DeliveryWorkflowError("Delivery output digest or size drifted")
            layout_items = reported.get("subtitle_layout", [])
            if not isinstance(layout_items, list):
                raise DeliveryWorkflowError("Delivery subtitle layout evidence is malformed")
            if plan.subtitle_track_ids and not layout_items:
                raise DeliveryWorkflowError("Delivery subtitle layout evidence is missing")
            subtitle_cues = []
            for layout in layout_items:
                if not isinstance(layout, dict) or layout.get("safe_area_status") != "passed":
                    raise DeliveryWorkflowError("Delivery subtitle layout did not pass the renderer safe-area gate")
                subtitle_cues.append(QCSubtitleCueEvidence(
                    cue_id=f"{layout['track_id']}:{layout['cue_id']}",
                    start_seconds=layout["start_seconds"],
                    end_seconds=layout["end_seconds"],
                    text=layout["rendered_text"],
                    safe_area_status="passed",
                ))
            subtitle_cues = tuple(sorted(subtitle_cues, key=lambda item: item.cue_id))
            subtitle_sync = None
            if plan.subtitle_alignment_report is not None:
                if timeline is None:
                    raise DeliveryWorkflowError("Sync-gated delivery requires the exact confirmed timeline")
                subtitle_sync = SubtitleSyncQCService().analyze(
                    timeline,
                    SubtitleSyncQCInput(
                        report=plan.subtitle_alignment_report,
                        track_id=plan.subtitle_track_ids[0],
                        cue_id_prefix=plan.subtitle_cue_id_prefix,
                        rendered_media_path=str(path),
                        expected_rendered_sha256=content_digest.removeprefix("sha256:"),
                    ),
                )
                if subtitle_sync.status != "passed":
                    raise DeliveryWorkflowError("Finished delivery failed subtitle synchronization QC")
            qc = DeliveryQCService(allowlisted_roots=(path.parent,)).analyze(
                DeliveryQCRequest(
                    request_id=f"qc_request_{plan.delivery_plan_id}_{variant.variant_id}",
                    project_id=plan.project.project_id,
                    project_revision=plan.project.project_revision,
                    asset_id=f"delivery_asset_{plan.delivery_plan_id}_{variant.variant_id}",
                    expected_content_digest=content_digest,
                    profile=variant.qc_profile,
                    subtitle_cues=subtitle_cues,
                    subtitle_sync_evidence=subtitle_sync,
                ), source_path=path,
            )
            items.append(DeliveryManifestItem(
                variant_id=variant.variant_id, filename=variant.filename,
                width=variant.width, height=variant.height, fps=variant.fps,
                size_bytes=path.stat().st_size, content_digest=content_digest,
                qc_report_id=qc.report_id, qc_report_digest=qc.report_digest,
                qc_status=qc.status,
            ))
        statuses = {item.qc_status for item in items}
        status = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "succeeded"
        return DeliveryManifest.create(
            manifest_id=f"delivery_manifest_{plan.delivery_plan_id}",
            delivery_plan_id=plan.delivery_plan_id, delivery_plan_digest=plan.plan_digest,
            project=plan.project, confirmation_id=confirmation_id,
            execution_id=execution_id, status=status, items=tuple(items),
            limitations=("Existing output files are never overwritten.",),
        )

    @staticmethod
    def public_view(ledger):
        return {
            "schema_name": "vistora.delivery-workflow-view",
            "schema_version": "1.0.0",
            "project_id": ledger.project_id,
            "revision": ledger.revision,
            "status": (
                ledger.manifests[-1].status if ledger.manifests
                else "planned" if ledger.plans else "not_planned"
            ),
            "plans": tuple({
                "delivery_plan_id": item.delivery_plan_id,
                "version": item.version,
                "project_version_id": item.project.version_id,
                "project_revision": item.project.project_revision,
                "brand_pack_id": item.brand.brand_pack_id,
                "brand_version": item.brand.version,
                "preference_id": item.preferences.preference_id,
                "preference_version": item.preferences.version,
                "variant_ids": tuple(variant.variant_id for variant in item.variants),
                "plan_digest": item.plan_digest,
            } for item in ledger.plans),
            "manifests": tuple({
                "manifest_id": item.manifest_id,
                "delivery_plan_id": item.delivery_plan_id,
                "status": item.status,
                "confirmation_id": item.confirmation_id,
                "execution_id": item.execution_id,
                "items": tuple({
                    "variant_id": output.variant_id,
                    "filename": output.filename,
                    "width": output.width,
                    "height": output.height,
                    "fps": output.fps,
                    "size_bytes": output.size_bytes,
                    "content_digest": output.content_digest,
                    "qc_status": output.qc_status,
                    "qc_report_id": output.qc_report_id,
                } for output in item.items),
                "manifest_digest": item.manifest_digest,
                "limitations": item.limitations,
            } for item in ledger.manifests),
            "message": (
                "Delivery history is append-only; output files are create-new and QC-bound."
                if ledger.revision else
                "No multi-spec delivery plan has been reviewed in this project."
            ),
        }
