"""Frozen O32 project-version, brand, preference and delivery contracts."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from director import digest_json
from delivery_qc import DeliveryQCProfile
from subtitle_alignment import SubtitleAlignmentReport


StableId = Annotated[str, Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class DeliveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Literal["1.0.0"] = "1.0.0"

    def digest(self):
        return digest_json(self.model_dump(mode="json"))


class BrandStylePack(DeliveryModel):
    schema_name: Literal["vistora.brand-style-pack"] = "vistora.brand-style-pack"
    brand_pack_id: StableId
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    colors: tuple[str, ...] = Field(min_length=1, max_length=16)
    logical_fonts: tuple[Literal["monospace", "sans", "serif"], ...] = ("sans",)
    logo_material_ids: tuple[StableId, ...] = ()
    tone_keywords: tuple[str, ...] = Field(min_length=1, max_length=20)
    prohibited_uses: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def name_is_browser_safe(cls, value):
        if re.search(r"(?:[A-Za-z]:\\|file://|/(?:Users|home)/)", value):
            raise ValueError("Brand display text cannot contain a filesystem path")
        return value

    @field_validator("tone_keywords", "prohibited_uses")
    @classmethod
    def guidance_is_browser_safe(cls, value):
        if any(re.search(r"(?:[A-Za-z]:\\|file://|/(?:Users|home)/)", item) for item in value):
            raise ValueError("Brand guidance cannot contain a filesystem path")
        return value

    @field_validator("colors")
    @classmethod
    def colors_are_safe(cls, value):
        normalized = tuple(item.upper() for item in value)
        if normalized != tuple(sorted(set(normalized))) or any(not __import__("re").fullmatch(r"#[0-9A-F]{6}", item) for item in normalized):
            raise ValueError("Brand colors must be ordered unique #RRGGBB values")
        return normalized

    @model_validator(mode="after")
    def ordered(self):
        for value, label in ((self.logical_fonts, "fonts"), (self.logo_material_ids, "logos"), (self.tone_keywords, "tone keywords"), (self.prohibited_uses, "prohibited uses")):
            if value != tuple(sorted(set(value))):
                raise ValueError(f"Brand {label} must be unique and ordered")
        return self


class UserPreferenceProfile(DeliveryModel):
    schema_name: Literal["vistora.user-preference-profile"] = "vistora.user-preference-profile"
    preference_id: StableId
    version: int = Field(ge=1)
    user_id: StableId
    default_variant_ids: tuple[StableId, ...] = Field(min_length=1, max_length=8)
    subtitle_mode: Literal["none", "burn"] = "none"
    target_lufs: float = Field(default=-14, ge=-36, le=-5, allow_inf_nan=False)
    filename_prefix: str = Field(default="vistora", min_length=1, max_length=48, pattern=r"^[A-Za-z0-9._-]+$")
    preserve_existing_outputs: Literal[True] = True

    @model_validator(mode="after")
    def ordered(self):
        if self.default_variant_ids != tuple(sorted(set(self.default_variant_ids))):
            raise ValueError("Preference variants must be unique and ordered")
        return self


class ProjectVersionReference(DeliveryModel):
    schema_name: Literal["vistora.project-version-reference"] = "vistora.project-version-reference"
    version_id: StableId
    project_id: StableId
    project_revision: int = Field(ge=1)
    snapshot_id: StableId
    timeline_digest: Digest
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0, allow_inf_nan=False)
    track_count: int = Field(ge=0)
    clip_count: int = Field(ge=0)
    subtitle_cue_count: int = Field(ge=0)
    transition_count: int = Field(ge=0)


class ProjectVersionChange(DeliveryModel):
    schema_name: Literal["vistora.project-version-change"] = "vistora.project-version-change"
    change_id: StableId
    entity_kind: Literal["project_settings", "track", "clip", "cue", "transition"]
    entity_id: StableId
    change_kind: Literal["added", "removed", "modified"]
    before_digest: Digest | None = None
    after_digest: Digest | None = None


class ProjectVersionComparison(DeliveryModel):
    schema_name: Literal["vistora.project-version-comparison"] = "vistora.project-version-comparison"
    comparison_id: StableId
    before: ProjectVersionReference
    after: ProjectVersionReference
    changes: tuple[ProjectVersionChange, ...]
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    modified: int = Field(ge=0)
    comparison_digest: Digest

    @model_validator(mode="after")
    def exact(self):
        if self.before.project_id != self.after.project_id:
            raise ValueError("Project version comparison crosses project")
        keys = [(item.entity_kind, item.entity_id) for item in self.changes]
        if keys != sorted(set(keys)):
            raise ValueError("Project version changes are ambiguous")
        counts = {kind: sum(item.change_kind == kind for item in self.changes) for kind in ("added", "removed", "modified")}
        if (self.added, self.removed, self.modified) != (counts["added"], counts["removed"], counts["modified"]):
            raise ValueError("Project version comparison counts mismatched")
        payload = self.model_dump(mode="json", exclude={"comparison_digest"})
        if self.comparison_digest != digest_json(payload):
            raise ValueError("Project version comparison digest mismatched")
        return self


class DeliveryVariantSpecification(DeliveryModel):
    schema_name: Literal["vistora.delivery-variant-specification"] = "vistora.delivery-variant-specification"
    variant_id: StableId
    filename: str = Field(min_length=5, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.mp4$")
    width: int = Field(ge=16, le=8192, multiple_of=2)
    height: int = Field(ge=16, le=8192, multiple_of=2)
    fps: float = Field(ge=1, le=120, allow_inf_nan=False)
    qc_profile: DeliveryQCProfile


class DeliveryPlan(DeliveryModel):
    schema_name: Literal["vistora.delivery-plan"] = "vistora.delivery-plan"
    delivery_plan_id: StableId
    version: int = Field(ge=1)
    project: ProjectVersionReference
    destination_id: StableId
    brand: BrandStylePack
    preferences: UserPreferenceProfile
    variants: tuple[DeliveryVariantSpecification, ...] = Field(min_length=2, max_length=8)
    subtitle_track_ids: tuple[StableId, ...] = ()
    subtitle_alignment_report: SubtitleAlignmentReport | None = None
    subtitle_cue_id_prefix: str | None = Field(
        default=None, min_length=3, max_length=100,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    plan_digest: Digest

    @classmethod
    def create(cls, **values):
        shell = cls.model_construct(**values, plan_digest="sha256:" + "0" * 64)
        return cls(**values, plan_digest=digest_json(shell.model_dump(mode="json", exclude={"plan_digest"})))

    @model_validator(mode="after")
    def exact(self):
        ids = [item.variant_id for item in self.variants]
        names = [item.filename.lower() for item in self.variants]
        if ids != sorted(set(ids)) or len(names) != len(set(names)):
            raise ValueError("Delivery variants must have ordered IDs and unique filenames")
        if not set(self.preferences.default_variant_ids).issubset(ids):
            raise ValueError("Delivery preferences reference an absent variant")
        if self.subtitle_track_ids != tuple(sorted(set(self.subtitle_track_ids))):
            raise ValueError("Delivery subtitle tracks must be unique and ordered")
        captioned_delivery = bool(self.subtitle_track_ids)
        requires_sync = all(item.qc_profile.require_subtitle_sync for item in self.variants)
        if captioned_delivery and (
            self.subtitle_alignment_report is None
            or self.subtitle_cue_id_prefix is None
            or not requires_sync
            or self.preferences.subtitle_mode != "burn"
        ):
            raise ValueError(
                "Captioned delivery requires burned aligned captions, their immutable report, and sync QC on every variant"
            )
        if not captioned_delivery and self.subtitle_alignment_report is not None:
            raise ValueError("Subtitle alignment evidence requires an explicit caption track")
        if self.subtitle_alignment_report is not None and self.subtitle_cue_id_prefix is None:
            raise ValueError("Aligned delivery requires a deterministic cue ID prefix")
        payload = self.model_dump(mode="json", exclude={"plan_digest"})
        if self.plan_digest != digest_json(payload):
            raise ValueError("Delivery plan digest mismatched")
        return self


class DeliveryManifestItem(DeliveryModel):
    schema_name: Literal["vistora.delivery-manifest-item"] = "vistora.delivery-manifest-item"
    variant_id: StableId
    filename: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0, allow_inf_nan=False)
    size_bytes: int = Field(gt=0)
    content_digest: Digest
    qc_report_id: StableId
    qc_report_digest: Digest
    qc_status: Literal["passed", "warning", "failed"]


class DeliveryManifest(DeliveryModel):
    schema_name: Literal["vistora.delivery-manifest"] = "vistora.delivery-manifest"
    manifest_id: StableId
    delivery_plan_id: StableId
    delivery_plan_digest: Digest
    project: ProjectVersionReference
    confirmation_id: StableId
    execution_id: StableId
    status: Literal["succeeded", "warning", "failed"]
    items: tuple[DeliveryManifestItem, ...]
    limitations: tuple[str, ...] = ()
    manifest_digest: Digest

    @classmethod
    def create(cls, **values):
        shell = cls.model_construct(**values, manifest_digest="sha256:" + "0" * 64)
        return cls(**values, manifest_digest=digest_json(shell.model_dump(mode="json", exclude={"manifest_digest"})))

    @model_validator(mode="after")
    def exact(self):
        ids = [item.variant_id for item in self.items]
        if ids != sorted(set(ids)):
            raise ValueError("Delivery manifest variants are ambiguous")
        statuses = {item.qc_status for item in self.items}
        expected = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "succeeded"
        if self.status != expected:
            raise ValueError("Delivery manifest aggregate status mismatched")
        payload = self.model_dump(mode="json", exclude={"manifest_digest"})
        if self.manifest_digest != digest_json(payload):
            raise ValueError("Delivery manifest digest mismatched")
        return self


class DeliveryLedger(DeliveryModel):
    schema_name: Literal["vistora.delivery-ledger"] = "vistora.delivery-ledger"
    project_id: StableId
    revision: int = Field(ge=0)
    plans: tuple[DeliveryPlan, ...] = ()
    manifests: tuple[DeliveryManifest, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, project_id):
        return cls(project_id=project_id, revision=0, integrity_digest=digest_json({"plans": [], "manifests": []}))

    @model_validator(mode="after")
    def exact(self):
        if self.revision != len(self.plans) + len(self.manifests):
            raise ValueError("Delivery ledger revision mismatched")
        plan_ids = [item.delivery_plan_id for item in self.plans]
        manifest_ids = [item.manifest_id for item in self.manifests]
        if plan_ids != list(dict.fromkeys(plan_ids)) or manifest_ids != list(dict.fromkeys(manifest_ids)):
            raise ValueError("Delivery ledger duplicates IDs")
        plans = {item.delivery_plan_id: item for item in self.plans}
        for manifest in self.manifests:
            plan = plans.get(manifest.delivery_plan_id)
            if plan is None or manifest.delivery_plan_digest != plan.plan_digest or manifest.project != plan.project:
                raise ValueError("Delivery manifest is not bound to an exact plan")
        payload = {"plans": [item.plan_digest for item in self.plans], "manifests": [item.manifest_digest for item in self.manifests]}
        if self.integrity_digest != digest_json(payload):
            raise ValueError("Delivery ledger integrity mismatched")
        return self
