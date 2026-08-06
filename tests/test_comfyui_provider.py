"""Production ComfyUI Provider contract, lifecycle, and safety tests."""

from __future__ import annotations

import json
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
    COMFYUI_WORKFLOW_PARAMETER,
    ComfyUIMaterialProductionAdapter,
    ComfyUIProviderConfig,
    ProductionJobRequest,
    build_creation_capability_reference,
    build_material_production_registry,
    load_comfyui_provider_config,
)


NOW = datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self):
        self.history_value = {}
        self.queue_value = {"queue_running": [], "queue_pending": []}
        self.submissions = []
        self.uploads = []
        self.downloads = []
        self.deleted = []
        self.interrupted = []
        self.unload_count = 0
        self.healthy = True

    def health(self):
        if not self.healthy:
            raise RuntimeError("offline")

    def upload(self, source, *, subfolder):
        self.uploads.append((source, subfolder))
        return f"{subfolder}/{source.name}"

    def submit(self, prompt, *, prompt_id):
        self.submissions.append((prompt_id, prompt))
        return prompt_id

    def history(self, prompt_id):
        return self.history_value

    def queue(self):
        return self.queue_value

    def delete_queued(self, prompt_id):
        self.deleted.append(prompt_id)

    def interrupt(self, prompt_id):
        self.interrupted.append(prompt_id)

    def unload_models(self):
        self.unload_count += 1

    def download(self, descriptor, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"provider-media")
        self.downloads.append((descriptor, target))


def _workflow(path: Path):
    value = {
        "2": {
            "class_type": "VoiceSynthesis",
            "inputs": {"target_text": "original", "seed": 1},
        },
        "3": {
            "class_type": "LoadAudio",
            "inputs": {"audio": "reference.wav"},
        },
        "6": {
            "class_type": "SaveAudio",
            "inputs": {"filename_prefix": "ComfyUI", "audio": ["2", 0]},
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def _config(path: Path, *, targeted=False):
    _workflow(path)
    return ComfyUIProviderConfig.model_validate(
        {
            "workflows": [
                {
                    "workflow_id": "voice_local",
                    "capability_ids": ["voice_synthesis"],
                    "workflow_path": str(path),
                    "output_node_ids": ["6"],
                    "bindings": [
                        {
                            "node_id": "2",
                            "input_name": "target_text",
                            "source": "prompt_text",
                        },
                        {
                            "node_id": "2",
                            "input_name": "seed",
                            "source": "seed",
                        },
                        {
                            "node_id": "3",
                            "input_name": "audio",
                            "source": "reference_asset",
                            "reference_index": 0,
                            "reference_kind": "audio",
                        },
                    ],
                    "unload_models_after": True,
                    "supports_targeted_interrupt": targeted,
                }
            ]
        }
    )


def _image_workflow(path: Path):
    value = {
        "90": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyUI", "images": ["106", 0]},
        },
        "105": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "original positive", "clip": ["103", 0]},
        },
        "106": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["111", 0], "vae": ["109", 0]},
        },
        "107": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
        },
        "108": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "original negative", "clip": ["103", 0]},
        },
        "111": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "steps": 4,
                "model": ["104", 0],
                "positive": ["105", 0],
                "negative": ["108", 0],
                "latent_image": ["107", 0],
            },
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def _voice_and_image_config(tmp_path: Path):
    voice = tmp_path / "voice workflow.json"
    image = tmp_path / "image workflow.json"
    base = _config(voice).model_dump(mode="json")
    _image_workflow(image)
    base["workflows"].append(
        {
            "workflow_id": "image_local",
            "capability_ids": ["image_generation"],
            "workflow_path": str(image),
            "output_node_ids": ["90"],
            "bindings": [
                {
                    "node_id": "105",
                    "input_name": "text",
                    "source": "prompt_text",
                },
                {
                    "node_id": "108",
                    "input_name": "text",
                    "source": "negative_prompt",
                    "required": False,
                },
                {
                    "node_id": "107",
                    "input_name": "width",
                    "source": "width",
                    "required": False,
                },
                {
                    "node_id": "107",
                    "input_name": "height",
                    "source": "height",
                    "required": False,
                },
                {
                    "node_id": "111",
                    "input_name": "seed",
                    "source": "seed",
                    "required": False,
                },
            ],
            "unload_models_after": True,
            "supports_targeted_interrupt": False,
        }
    )
    return ComfyUIProviderConfig.model_validate(base)


def _multi_image_config(tmp_path: Path):
    base = _voice_and_image_config(tmp_path).model_dump(mode="json")
    fast_path = tmp_path / "fast image workflow.json"
    _image_workflow(fast_path)
    base["workflows"].append(
        {
            **base["workflows"][1],
            "workflow_id": "image_fast",
            "workflow_path": str(fast_path),
            "default_for_capabilities": ["image_generation"],
        }
    )
    return ComfyUIProviderConfig.model_validate(base)


def _task():
    unknown = ProductionEstimate(
        status="unknown",
        rationale="Local generation cost is not monetized.",
    )
    return MaterialProductionTask(
        task_id="task_voice_local",
        requirement_item_id="requirement_voice_local",
        title="Generate confirmed narration",
        purpose="Create one locally generated voice asset.",
        production_method="generate",
        status="planned",
        capability_ids=("voice_synthesis",),
        prompt_spec=PromptSpecification(
            subject="Chinese market narration",
            scene="A clean voice recording",
            camera="Close microphone",
            action="Read the confirmed script",
            lighting="Neutral",
            style="Clear and natural",
            negative_constraints=("No background noise",),
        ),
        reference_asset_ids=("source_1111111111111111",),
        seed=23,
        batch_id="batch_voice_local",
        cost_estimate=unknown,
        time_estimate=unknown,
        quality_gates=("Speech is intelligible",),
        retry_strategy=("Retry only after review",),
        alternative_strategy="Request a manual voice recording.",
        delivery=DeliveryFileSpecification(
            media_kind="audio",
            container_or_extension="flac",
            mime_type="audio/flac",
            filename_pattern="voice_{attempt}.flac",
        ),
    )


def _request():
    task = _task()
    return ProductionJobRequest(
        job_id="production_job_voice_local",
        run_id="production_run_voice_local",
        task_id=task.task_id,
        requirement_item_id=task.requirement_item_id,
        adapter_id="comfyui_local",
        capability_id="voice_synthesis",
        task_spec=task,
        attempt=1,
        idempotency_key="job_key_voice_local",
        requested_at=NOW,
    )


def _image_request(workflow_id=None):
    unknown = ProductionEstimate(
        status="unknown",
        rationale="Local generation cost is not monetized.",
    )
    task = MaterialProductionTask(
        task_id="task_image_local",
        requirement_item_id="requirement_image_local",
        title="Generate a confirmed editorial still",
        purpose="Create one locally generated image asset.",
        production_method="generate",
        status="planned",
        capability_ids=("image_generation",),
        prompt_spec=PromptSpecification(
            subject="A financial news studio",
            scene="A clean vertical editorial backdrop",
            camera="Medium-wide composition",
            action="Display restrained market data graphics",
            lighting="Soft cinematic key light",
            style="Photorealistic and premium",
            negative_constraints=("No distorted text", "No watermark"),
        ),
        width=1080,
        height=1920,
        seed=20260806,
        reproducibility_parameters=(
            (
                ReproducibilityParameter(
                    name=COMFYUI_WORKFLOW_PARAMETER,
                    value=workflow_id,
                ),
            )
            if workflow_id is not None
            else ()
        ),
        batch_id="batch_image_local",
        cost_estimate=unknown,
        time_estimate=unknown,
        quality_gates=("Image decodes and matches the requested aspect ratio",),
        retry_strategy=("Retry only after visual review",),
        alternative_strategy="Request a manually supplied image.",
        delivery=DeliveryFileSpecification(
            media_kind="image",
            container_or_extension="png",
            mime_type="image/png",
            filename_pattern="image_{attempt}.png",
        ),
    )
    return ProductionJobRequest(
        job_id="production_job_image_local",
        run_id="production_run_image_local",
        task_id=task.task_id,
        requirement_item_id=task.requirement_item_id,
        adapter_id="comfyui_local",
        capability_id="image_generation",
        task_spec=task,
        attempt=1,
        idempotency_key="job_key_image_local",
        requested_at=NOW,
    )


def _adapter(tmp_path, *, targeted=False, transport=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    reference = tmp_path / "reference voice.flac"
    reference.write_bytes(b"voice-reference")
    transport = transport or FakeTransport()
    adapter = ComfyUIMaterialProductionAdapter(
        _config(tmp_path / "voice workflow.json", targeted=targeted),
        asset_resolver=lambda material_id: (
            reference if material_id == "source_1111111111111111" else None
        ),
        transport=transport,
        clock=lambda: NOW,
    )
    return adapter, transport


def _prompt_id(update):
    return str(
        __import__("uuid").UUID(
            hex=update.provider_opaque_ref.removeprefix("comfyui_")
        )
    )


def test_loopback_config_is_strict_relative_and_path_private(tmp_path):
    workflow = tmp_path / "workflow.json"
    _workflow(workflow)
    sidecar = tmp_path / "project.timeline.comfyui-provider.json"
    payload = _config(workflow).model_dump(mode="json")
    payload["workflows"][0]["workflow_path"] = "workflow.json"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_comfyui_provider_config(tmp_path / "project.timeline.json")
    assert loaded.workflows[0].workflow_path == workflow.resolve()

    payload["base_url"] = "https://example.com"
    with pytest.raises(ValueError, match="loopback"):
        ComfyUIProviderConfig.model_validate(payload)
    payload["base_url"] = "http://127.0.0.1:8188"
    payload["workflows"].append(dict(payload["workflows"][0]))
    with pytest.raises(ValueError, match="workflow ID"):
        ComfyUIProviderConfig.model_validate(payload)

    duplicate_capability = json.loads(json.dumps(payload["workflows"][0]))
    duplicate_capability["workflow_id"] = "voice_second"
    payload["workflows"] = [payload["workflows"][0], duplicate_capability]
    with pytest.raises(ValueError, match="exactly one default"):
        ComfyUIProviderConfig.model_validate(payload)

    payload["workflows"] = [dict(payload["workflows"][0])]
    payload["workflows"][0]["capability_ids"] = ["manual_import"]
    with pytest.raises(ValueError, match="unsupported capability"):
        ComfyUIProviderConfig.model_validate(payload)


def test_submit_binds_confirmed_task_idempotently_and_never_leaks_paths(tmp_path):
    adapter, transport = _adapter(tmp_path)
    request = _request()
    update = adapter.submit(request, staging_root=tmp_path / "staging")
    assert update.status == "submitted"
    assert len(transport.submissions) == 1
    assert len(transport.uploads) == 1
    prompt_id, prompt = transport.submissions[0]
    assert prompt["2"]["inputs"]["seed"] == 23
    assert "Chinese market narration" in prompt["2"]["inputs"]["target_text"]
    assert prompt["3"]["inputs"]["audio"].startswith(
        f"vistora/{prompt_id}/"
    )
    assert prompt["6"]["inputs"]["filename_prefix"] == (
        f"vistora/{prompt_id}/voice_local"
    )
    serialized = update.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "workflow.json" not in serialized

    transport.queue_value = {
        "queue_running": [],
        "queue_pending": [[1, prompt_id, {}, {}]],
    }
    replay = adapter.submit(request, staging_root=tmp_path / "staging")
    assert replay.status == "submitted"
    assert len(transport.submissions) == 1
    assert len(transport.uploads) == 1


def test_image_generation_binds_prompt_dimensions_seed_and_stages_png(tmp_path):
    transport = FakeTransport()
    adapter = ComfyUIMaterialProductionAdapter(
        _voice_and_image_config(tmp_path),
        asset_resolver=lambda _material_id: None,
        transport=transport,
        clock=lambda: NOW,
    )
    request = _image_request()
    submitted = adapter.submit(request, staging_root=tmp_path / "staging")
    assert submitted.status == "submitted"
    prompt_id, prompt = transport.submissions[0]
    assert prompt["107"]["inputs"]["width"] == 1080
    assert prompt["107"]["inputs"]["height"] == 1920
    assert prompt["111"]["inputs"]["seed"] == 20260806
    assert "financial news studio" in prompt["105"]["inputs"]["text"]
    assert prompt["108"]["inputs"]["text"] == (
        "No distorted text, No watermark"
    )
    assert prompt["90"]["inputs"]["filename_prefix"] == (
        f"vistora/{prompt_id}/image_local"
    )

    transport.history_value = {
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "90": {
                    "images": [
                        {
                            "filename": "generated.png",
                            "subfolder": f"vistora/{prompt_id}",
                            "type": "output",
                        }
                    ]
                }
            },
        }
    }
    result = adapter.poll(
        request,
        provider_opaque_ref=submitted.provider_opaque_ref,
        staging_root=tmp_path / "staging",
    )
    assert result.status == "succeeded"
    assert len(result.artifacts) == 1
    assert result.artifacts[0].claimed_mime_type == "image/png"
    assert transport.unload_count == 1


def test_multiple_image_workflows_use_default_or_exact_confirmed_selector(tmp_path):
    transport = FakeTransport()
    adapter = ComfyUIMaterialProductionAdapter(
        _multi_image_config(tmp_path),
        asset_resolver=lambda _material_id: None,
        transport=transport,
        clock=lambda: NOW,
    )
    default_request = _image_request()
    default_update = adapter.submit(
        default_request,
        staging_root=tmp_path / "staging",
    )
    assert default_update.status == "submitted"
    default_id, default_prompt = transport.submissions[-1]
    assert default_prompt["90"]["inputs"]["filename_prefix"] == (
        f"vistora/{default_id}/image_fast"
    )

    transport.queue_value = {"queue_running": [], "queue_pending": []}
    selected_request = _image_request("image_local").model_copy(
        update={
            "job_id": "production_job_image_selected",
            "idempotency_key": "job_key_image_selected",
        }
    )
    selected_update = adapter.submit(
        selected_request,
        staging_root=tmp_path / "staging",
    )
    assert selected_update.status == "submitted"
    selected_id, selected_prompt = transport.submissions[-1]
    assert selected_prompt["90"]["inputs"]["filename_prefix"] == (
        f"vistora/{selected_id}/image_local"
    )
    assert selected_id != default_id

    unavailable = _image_request("not_configured").model_copy(
        update={
            "job_id": "production_job_image_unavailable",
            "idempotency_key": "job_key_image_unavailable",
        }
    )
    rejected = adapter.submit(unavailable, staging_root=tmp_path / "staging")
    assert rejected.status == "failed"
    assert rejected.error_code == "comfyui_capability_unavailable"


def test_poll_stages_only_declared_outputs_then_unloads_models(tmp_path):
    adapter, transport = _adapter(tmp_path)
    request = _request()
    submitted = adapter.submit(request, staging_root=tmp_path / "staging")
    prompt_id = _prompt_id(submitted)
    transport.history_value = {
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "6": {
                    "audio": [
                        {
                            "filename": "voice.flac",
                            "subfolder": f"vistora/{prompt_id}",
                            "type": "output",
                        }
                    ]
                },
                "999": {
                    "images": [
                        {"filename": "undeclared.png", "type": "output"}
                    ]
                },
            },
        }
    }
    result = adapter.poll(
        request,
        provider_opaque_ref=submitted.provider_opaque_ref,
        staging_root=tmp_path / "staging",
    )
    assert result.status == "succeeded"
    assert len(result.artifacts) == 1
    assert result.artifacts[0].claimed_mime_type == "audio/flac"
    assert (tmp_path / "staging" / result.artifacts[0].staging_relative_path).read_bytes() == b"provider-media"
    assert transport.unload_count == 1
    assert "unloaded" in result.message


def test_single_comfyui_slot_defers_second_job_until_queue_is_empty(tmp_path):
    adapter, transport = _adapter(tmp_path)
    first = _request()
    first_update = adapter.submit(first, staging_root=tmp_path / "staging")
    first_prompt_id = _prompt_id(first_update)
    transport.queue_value = {
        "queue_running": [[1, first_prompt_id, {}, {}]],
        "queue_pending": [],
    }
    second = first.model_copy(
        update={
            "job_id": "production_job_voice_second",
            "idempotency_key": "job_key_voice_second",
        }
    )
    deferred = adapter.submit(second, staging_root=tmp_path / "staging")
    assert deferred.status == "rate_limited"
    assert deferred.error_code == "comfyui_queue_busy"
    assert len(transport.submissions) == 1
    assert len(transport.uploads) == 1

    transport.queue_value = {"queue_running": [], "queue_pending": []}
    resumed = adapter.poll(
        second,
        provider_opaque_ref=deferred.provider_opaque_ref,
        staging_root=tmp_path / "staging",
    )
    assert resumed.status == "submitted"
    assert len(transport.submissions) == 2


def test_output_or_unload_uncertainty_is_recovery_required_and_cleans_staging(
    tmp_path,
):
    class UnloadFails(FakeTransport):
        def unload_models(self):
            raise RuntimeError("cannot unload")

    adapter, transport = _adapter(tmp_path, transport=UnloadFails())
    request = _request()
    submitted = adapter.submit(request, staging_root=tmp_path / "staging")
    prompt_id = _prompt_id(submitted)
    transport.history_value = {
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "6": {
                    "audio": [
                        {"filename": "voice.flac", "type": "output"}
                    ]
                }
            },
        }
    }
    result = adapter.poll(
        request,
        provider_opaque_ref=submitted.provider_opaque_ref,
        staging_root=tmp_path / "staging",
    )
    assert result.status == "recovery_required"
    assert result.error_code == "comfyui_output_recovery_required"
    assert not list((tmp_path / "staging").rglob("*.flac"))


def test_reference_kind_and_provider_output_paths_fail_closed(tmp_path):
    wrong_reference = tmp_path / "reference.png"
    wrong_reference.write_bytes(b"png")
    transport = FakeTransport()
    adapter = ComfyUIMaterialProductionAdapter(
        _config(tmp_path / "workflow.json"),
        asset_resolver=lambda _material_id: wrong_reference,
        transport=transport,
        clock=lambda: NOW,
    )
    request = _request()
    rejected = adapter.submit(request, staging_root=tmp_path / "staging")
    assert rejected.status == "failed"
    assert rejected.error_code == "comfyui_preflight_failed"
    assert transport.submissions == []

    adapter, transport = _adapter(tmp_path / "unsafe")
    submitted = adapter.submit(request, staging_root=tmp_path / "unsafe_staging")
    prompt_id = _prompt_id(submitted)
    transport.history_value = {
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "6": {
                    "audio": [
                        {"filename": "../outside.flac", "type": "output"}
                    ]
                }
            },
        }
    }
    unsafe = adapter.poll(
        request,
        provider_opaque_ref=submitted.provider_opaque_ref,
        staging_root=tmp_path / "unsafe_staging",
    )
    assert unsafe.status == "recovery_required"
    assert not (tmp_path / "outside.flac").exists()
    assert transport.unload_count == 1


def test_cancel_never_globally_interrupts_without_explicit_server_support(tmp_path):
    adapter, transport = _adapter(tmp_path)
    request = _request()
    submitted = adapter.submit(request, staging_root=tmp_path / "staging")
    prompt_id = _prompt_id(submitted)
    transport.queue_value = {
        "queue_running": [[1, prompt_id, {}, {}]],
        "queue_pending": [],
    }
    blocked = adapter.cancel(
        request,
        provider_opaque_ref=submitted.provider_opaque_ref,
    )
    assert blocked.status == "recovery_required"
    assert transport.interrupted == []
    assert transport.deleted == []

    exact, exact_transport = _adapter(tmp_path / "exact", targeted=True)
    exact_request = _request()
    exact_submitted = exact.submit(
        exact_request,
        staging_root=tmp_path / "exact_staging",
    )
    exact_prompt_id = _prompt_id(exact_submitted)
    exact_transport.queue_value = {
        "queue_running": [[1, exact_prompt_id, {}, {}]],
        "queue_pending": [],
    }
    cancelled = exact.cancel(
        exact_request,
        provider_opaque_ref=exact_submitted.provider_opaque_ref,
    )
    assert cancelled.status == "cancelled"
    assert exact_transport.interrupted == [exact_prompt_id]
    assert exact_transport.deleted == [exact_prompt_id]
    assert exact_transport.unload_count == 1


def test_registry_replaces_only_configured_capabilities_without_path_leaks(tmp_path):
    config = _config(tmp_path / "workflow.json")
    registry = build_material_production_registry(
        comfyui_config=config,
        asset_resolver=lambda _material_id: None,
    )
    projected = build_creation_capability_reference(registry)
    by_id = {item.capability_id: item for item in projected.capabilities}
    assert registry.reference().registry_revision == 4
    assert by_id["voice_synthesis"].availability == "available"
    assert by_id["video_generation"].availability == "unconfigured"
    serialized = registry.reference().model_dump_json()
    assert str(tmp_path) not in serialized
    assert "workflow.json" not in serialized
    assert "api_key" not in serialized.lower()


def test_registry_exposes_configured_comfyui_image_generation(tmp_path):
    registry = build_material_production_registry(
        comfyui_config=_voice_and_image_config(tmp_path),
        asset_resolver=lambda _material_id: None,
    )
    projected = build_creation_capability_reference(registry)
    by_id = {item.capability_id: item for item in projected.capabilities}
    assert by_id["image_generation"].availability == "available"
    assert by_id["voice_synthesis"].availability == "available"
    assert by_id["video_generation"].availability == "unconfigured"
    serialized = registry.reference().model_dump_json()
    assert "image workflow.json" not in serialized


def test_wan_image_to_video_binds_integer_controls_and_reference(tmp_path):
    workflow_path = tmp_path / "wan2.2-i2v.json"
    workflow_path.write_text(
        json.dumps(
            {
                "97": {"class_type": "LoadImage", "inputs": {"image": "start.png"}},
                "108": {
                    "class_type": "SaveVideo",
                    "inputs": {"filename_prefix": "video/ComfyUI", "video": ["152", 0]},
                },
                "124": {"class_type": "Prompt", "inputs": {"positive": "old"}},
                "139": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
                "149": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
                "170": {"class_type": "PrimitiveInt", "inputs": {"value": 480}},
                "171": {"class_type": "PrimitiveInt", "inputs": {"value": 832}},
                "172": {"class_type": "PrimitiveInt", "inputs": {"value": 5}},
                "173": {"class_type": "PrimitiveInt", "inputs": {"value": 16}},
            }
        ),
        encoding="utf-8",
    )
    config = ComfyUIProviderConfig.model_validate(
        {
            "workflows": [
                {
                    "workflow_id": "wan_2_2_i2v",
                    "capability_ids": [
                        "image_to_video_generation",
                        "video_generation",
                    ],
                    "workflow_path": str(workflow_path),
                    "output_node_ids": ["108"],
                    "bindings": [
                        {
                            "node_id": "97",
                            "input_name": "image",
                            "source": "reference_asset",
                            "reference_index": 0,
                            "reference_kind": "image",
                        },
                        {"node_id": "124", "input_name": "positive", "source": "prompt_text"},
                        {"node_id": "139", "input_name": "text", "source": "negative_prompt"},
                        {"node_id": "170", "input_name": "value", "source": "width", "value_transform": "integer"},
                        {"node_id": "171", "input_name": "value", "source": "height", "value_transform": "integer"},
                        {"node_id": "172", "input_name": "value", "source": "duration_seconds", "value_transform": "integer"},
                        {"node_id": "173", "input_name": "value", "source": "fps", "value_transform": "integer"},
                        {"node_id": "149", "input_name": "noise_seed", "source": "seed", "value_transform": "integer"},
                    ],
                    "unload_models_after": True,
                }
            ]
        }
    )
    source = tmp_path / "start image.png"
    source.write_bytes(b"image")
    transport = FakeTransport()
    adapter = ComfyUIMaterialProductionAdapter(
        config,
        asset_resolver=lambda _material_id: source,
        transport=transport,
        clock=lambda: NOW,
    )
    unknown = ProductionEstimate(status="unknown", rationale="Local render.")
    task = MaterialProductionTask(
        task_id="task_wan_i2v",
        requirement_item_id="requirement_wan_i2v",
        title="Animate one accepted still",
        purpose="Create a short motion shot from the accepted image.",
        production_method="generate",
        status="planned",
        capability_ids=("image_to_video_generation",),
        prompt_spec=PromptSpecification(
            subject="A presenter",
            scene="A clean editorial studio",
            camera="Slow forward push",
            action="Subtle breathing and a slow camera push",
            lighting="Soft natural key light",
            style="Photorealistic and restrained",
            negative_constraints=("No text",),
        ),
        reference_asset_ids=("source_1111111111111111",),
        duration_seconds=4.6,
        width=480,
        height=832,
        fps=16,
        seed=20260806,
        batch_id="batch_wan_i2v",
        cost_estimate=unknown,
        time_estimate=unknown,
        quality_gates=("The clip decodes",),
        retry_strategy=("Retry after review",),
        alternative_strategy="Use HyperFrames motion on the still.",
        delivery=DeliveryFileSpecification(
            media_kind="video",
            container_or_extension="mp4",
            mime_type="video/mp4",
            filename_pattern="wan_{attempt}.mp4",
        ),
    )
    request = ProductionJobRequest(
        job_id="production_job_wan_i2v",
        run_id="production_run_wan_i2v",
        task_id=task.task_id,
        requirement_item_id=task.requirement_item_id,
        adapter_id="comfyui_local",
        capability_id="image_to_video_generation",
        task_spec=task,
        attempt=1,
        idempotency_key="job_key_wan_i2v",
        requested_at=NOW,
    )
    update = adapter.submit(request, staging_root=tmp_path / "staging")
    assert update.status == "submitted"
    prepared = transport.submissions[0][1]
    assert prepared["97"]["inputs"]["image"].endswith("start image.png")
    assert prepared["170"]["inputs"]["value"] == 480
    assert prepared["171"]["inputs"]["value"] == 832
    assert prepared["172"]["inputs"]["value"] == 5
    assert prepared["173"]["inputs"]["value"] == 16
    assert prepared["149"]["inputs"]["noise_seed"] == 20260806
    serialized = update.model_dump_json()
    assert str(tmp_path) not in serialized


def test_job_task_linkage_and_missing_confirmed_task_fail_closed(tmp_path):
    request = _request()
    payload = request.model_dump(mode="json")
    payload["task_spec"]["task_id"] = "task_other"
    with pytest.raises(ValueError, match="crosses job linkage"):
        ProductionJobRequest.model_validate(payload)
    legacy = request.model_copy(update={"task_spec": None})
    adapter, _ = _adapter(tmp_path)
    result = adapter.submit(legacy, staging_root=tmp_path / "staging")
    assert result.status == "failed"
    assert result.error_code == "comfyui_preflight_failed"
