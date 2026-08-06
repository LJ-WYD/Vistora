"""HyperFrames provider routing, rendering, and path-safety tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from creation_planning import (
    DeliveryFileSpecification,
    MaterialProductionTask,
    ProductionEstimate,
    PromptSpecification,
    ReproducibilityParameter,
)
from material_production import (
    HYPERFRAMES_WORKFLOW_PARAMETER,
    PROVIDER_ADAPTER_PARAMETER,
    HyperFramesMaterialProductionAdapter,
    HyperFramesProviderConfig,
    ProductionJobRequest,
    build_creation_capability_reference,
    build_material_production_registry,
    load_hyperframes_provider_config,
)


NOW = datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)


class FakeRunner:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def render(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("synthetic render failure")
        kwargs["output_path"].write_bytes(b"synthetic-mp4")


def _config(tmp_path: Path) -> HyperFramesProviderConfig:
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("window.gsap={};", encoding="utf-8")
    return HyperFramesProviderConfig.model_validate(
        {
            "runtime_root": str((tmp_path / "runtime").resolve()),
            "gsap_path": str(gsap.resolve()),
            "require_non_system_drive": False,
            "workflows": [
                {
                    "workflow_id": "kinetic_brief",
                    "capability_ids": [
                        "motion_graphics_generation",
                        "video_generation",
                    ],
                    "default_for_capabilities": [
                        "motion_graphics_generation",
                        "video_generation",
                    ],
                    "template_kind": "kinetic_brief",
                }
            ],
        }
    )


def _task(*, provider="hyperframes_local") -> MaterialProductionTask:
    unknown = ProductionEstimate(
        status="unknown",
        rationale="The local render has no metered provider cost.",
    )
    return MaterialProductionTask(
        task_id="task_motion_graphic",
        requirement_item_id="requirement_motion_graphic",
        title="Render a market data card",
        purpose="Create a short deterministic editorial B-roll card.",
        production_method="generate",
        status="planned",
        capability_ids=("motion_graphics_generation",),
        prompt_spec=PromptSpecification(
            subject="Market breadth improves <without invented figures>",
            scene="Dark editorial control room",
            camera="Stable centered layout",
            action="Reveal the headline and supporting context",
            lighting="Cyan and amber accents",
            style="Cinematic financial news graphics",
            negative_constraints=("No fabricated price data",),
        ),
        duration_seconds=4,
        width=1080,
        height=1920,
        fps=30,
        seed=20260806,
        reproducibility_parameters=(
            ReproducibilityParameter(
                name=HYPERFRAMES_WORKFLOW_PARAMETER,
                value="kinetic_brief",
            ),
            ReproducibilityParameter(
                name=PROVIDER_ADAPTER_PARAMETER,
                value=provider,
            ),
        ),
        batch_id="batch_motion_graphic",
        cost_estimate=unknown,
        time_estimate=unknown,
        quality_gates=("The rendered title stays inside the safe area",),
        retry_strategy=("Retry only after validation failure is reviewed",),
        alternative_strategy="Use a static accepted image with timeline motion.",
        delivery=DeliveryFileSpecification(
            media_kind="video",
            container_or_extension="mp4",
            mime_type="video/mp4",
            filename_pattern="motion_{attempt}.mp4",
        ),
    )


def _request(*, provider="hyperframes_local") -> ProductionJobRequest:
    task = _task(provider=provider)
    return ProductionJobRequest(
        job_id="production_job_motion_graphic",
        run_id="production_run_motion_graphic",
        task_id=task.task_id,
        requirement_item_id=task.requirement_item_id,
        adapter_id=provider,
        capability_id="motion_graphics_generation",
        task_spec=task,
        attempt=1,
        idempotency_key="job_key_motion_graphic",
        requested_at=NOW,
    )


def test_config_loads_relative_paths_and_rejects_system_drive(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "vendor").mkdir()
    (config_dir / "vendor" / "gsap.min.js").write_text("gsap", encoding="utf-8")
    payload = _config(tmp_path).model_dump(mode="json")
    payload["runtime_root"] = "runtime"
    payload["gsap_path"] = "vendor/gsap.min.js"
    payload["require_non_system_drive"] = False
    sidecar = config_dir / "project.hyperframes-provider.json"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_hyperframes_provider_config(config_dir / "project.json")
    assert loaded.runtime_root == (config_dir / "runtime").resolve()
    assert loaded.gsap_path == (config_dir / "vendor" / "gsap.min.js").resolve()

    if __import__("os").name == "nt":
        system_root = Path(__import__("os").environ.get("SystemDrive", "C:") + "\\hf")
        payload["runtime_root"] = str(system_root)
        payload["require_non_system_drive"] = True
        with pytest.raises(ValueError, match="system drive"):
            HyperFramesProviderConfig.model_validate(payload)


def test_render_compiles_safe_project_and_returns_staged_video(tmp_path):
    runner = FakeRunner()
    adapter = HyperFramesMaterialProductionAdapter(
        _config(tmp_path),
        asset_resolver=lambda _material_id: None,
        runner=runner,
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    result = adapter.submit(_request(), staging_root=staging)
    assert result.status == "succeeded"
    assert result.artifacts[0].claimed_mime_type == "video/mp4"
    assert len(runner.calls) == 1
    project = runner.calls[0]["project_root"]
    index = (project / "index.html").read_text(encoding="utf-8")
    assert "Market breadth improves &lt;without invented figures&gt;" in index
    assert "http://" not in index and "https://" not in index
    assert (staging / result.artifacts[0].staging_relative_path).is_file()
    assert runner.calls[0]["fps"] == 30


def test_render_is_idempotent_and_does_not_run_twice(tmp_path):
    runner = FakeRunner()
    adapter = HyperFramesMaterialProductionAdapter(
        _config(tmp_path),
        asset_resolver=lambda _material_id: None,
        runner=runner,
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    first = adapter.submit(_request(), staging_root=staging)
    second = adapter.submit(_request(), staging_root=staging)
    assert first.artifacts == second.artifacts
    assert len(runner.calls) == 1


def test_failure_is_truthful_and_returns_no_artifact(tmp_path):
    adapter = HyperFramesMaterialProductionAdapter(
        _config(tmp_path),
        asset_resolver=lambda _material_id: None,
        runner=FakeRunner(fail=True),
        clock=lambda: NOW,
    )
    result = adapter.submit(_request(), staging_root=tmp_path / "staging")
    assert result.status == "failed"
    assert result.error_code == "hyperframes_render_failed"
    assert result.artifacts == ()


def test_explicit_provider_routing_avoids_ambiguous_video_adapter(tmp_path):
    registry = build_material_production_registry(
        hyperframes_config=_config(tmp_path),
        registry_revision=4,
    )
    selected = registry.select(
        "motion_graphics_generation",
        task_spec=_task(),
    )
    assert selected.capability().adapter_id == "hyperframes_local"
    assert registry.select(
        "motion_graphics_generation",
        task_spec=_task(provider="comfyui_local"),
    ) is None
    public = build_creation_capability_reference(registry)
    by_id = {item.capability_id: item for item in public.capabilities}
    assert by_id["motion_graphics_generation"].availability == "available"
    assert by_id["image_to_video_generation"].availability == "unconfigured"


def test_cancel_removes_only_owned_runtime_job(tmp_path):
    adapter = HyperFramesMaterialProductionAdapter(
        _config(tmp_path),
        asset_resolver=lambda _material_id: None,
        runner=FakeRunner(),
        clock=lambda: NOW,
    )
    request = _request()
    result = adapter.submit(request, staging_root=tmp_path / "staging")
    provider_ref = result.provider_opaque_ref
    owned = _config(tmp_path).runtime_root / "jobs" / provider_ref
    assert owned.is_dir()
    cancelled = adapter.cancel(request, provider_opaque_ref=provider_ref)
    assert cancelled.status == "cancelled"
    assert not owned.exists()


def test_real_hyperframes_cli_smoke_when_configured(tmp_path):
    config_path = os.environ.get("VISTORA_HYPERFRAMES_SMOKE_CONFIG")
    if not config_path:
        pytest.skip("Set VISTORA_HYPERFRAMES_SMOKE_CONFIG for the real CLI smoke")
    config = HyperFramesProviderConfig.model_validate_json(
        Path(config_path).read_text(encoding="utf-8")
    )
    adapter = HyperFramesMaterialProductionAdapter(
        config,
        asset_resolver=lambda _material_id: None,
        clock=lambda: NOW,
    )
    result = adapter.submit(_request(), staging_root=tmp_path / "staging")
    assert result.status == "succeeded", result.model_dump(mode="json")
    output = tmp_path / "staging" / result.artifacts[0].staging_relative_path
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = json.loads(probe.stdout)
    assert payload["streams"][0]["codec_name"] == "h264"
    assert payload["streams"][0]["width"] == 1080
    assert payload["streams"][0]["height"] == 1920
    assert 3.9 <= float(payload["format"]["duration"]) <= 4.1
