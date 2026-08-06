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
)
from material_production import (
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
    assert registry.reference().registry_revision == 3
    assert by_id["voice_synthesis"].availability == "available"
    assert by_id["video_generation"].availability == "unconfigured"
    serialized = registry.reference().model_dump_json()
    assert str(tmp_path) not in serialized
    assert "workflow.json" not in serialized
    assert "api_key" not in serialized.lower()


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
