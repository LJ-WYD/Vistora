"""Licensed stock-video provider regression tests without network access."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from creation_planning import (
    DeliveryFileSpecification,
    MaterialProductionTask,
    ProductionEstimate,
    ReproducibilityParameter,
)
from material_production import (
    ProductionJobRequest,
    MaterialProductionOrchestrator,
    StockVideoMaterialProductionAdapter,
    StockVideoProviderConfig,
    build_material_production_registry,
)


NOW = datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, *, pexels=True, fail_pexels_download=False):
        self.pexels = pexels
        self.fail_pexels_download = fail_pexels_download
        self.json_calls = []
        self.downloads = []

    def get_json(self, url, *, headers, timeout):
        self.json_calls.append((url, headers, timeout))
        if "pexels" in url:
            if not self.pexels:
                raise OSError("synthetic Pexels outage")
            return {
                "videos": [
                    {
                        "id": 314159,
                        "width": 1920,
                        "height": 1080,
                        "duration": 8,
                        "url": "https://www.pexels.com/video/market-314159/",
                        "user": {
                            "name": "Editorial Creator",
                            "url": "https://www.pexels.com/@editorial-creator/",
                        },
                        "video_files": [
                            {
                                "file_type": "video/mp4",
                                "width": 1920,
                                "height": 1080,
                                "link": "https://videos.pexels.com/video-files/314159/market.mp4",
                            }
                        ],
                    }
                ]
            }
        return {
            "hits": [
                {
                    "id": 271828,
                    "pageURL": "https://pixabay.com/videos/market-271828/",
                    "duration": 7,
                    "user": "Market Creator",
                    "user_id": 42,
                    "videos": {
                        "large": {
                            "url": "https://cdn.pixabay.com/video/271828/market.mp4",
                            "width": 1920,
                            "height": 1080,
                            "size": 2048,
                        }
                    },
                }
            ]
        }

    def download(self, url, *, destination, timeout, max_bytes):
        self.downloads.append((url, destination, timeout, max_bytes))
        if self.fail_pexels_download and "pexels" in url:
            raise OSError("synthetic Pexels download outage")
        destination.write_bytes(b"synthetic licensed mp4")
        return destination.stat().st_size


def _config(tmp_path: Path):
    return StockVideoProviderConfig(
        cache_root=tmp_path / "stock-cache",
        require_non_system_drive=False,
    )


def _request(*, provider="auto"):
    unknown = ProductionEstimate(
        status="unknown",
        rationale="The provider has no confirmed billable cost.",
    )
    task = MaterialProductionTask(
        task_id="task_stock_market",
        requirement_item_id="requirement_stock_market",
        title="US stock market trading floor",
        purpose="Acquire licensed supporting footage for a market brief.",
        production_method="library_search",
        status="planned",
        capability_ids=("asset_search",),
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        duration_seconds=8,
        reproducibility_parameters=(
            ReproducibilityParameter(
                name="material_provider_adapter_id",
                value="stock_video_library",
            ),
            ReproducibilityParameter(name="stock_orientation", value="landscape"),
            ReproducibilityParameter(name="stock_provider", value=provider),
            ReproducibilityParameter(
                name="stock_query",
                value="US stock market trading floor",
            ),
        ),
        batch_id="batch_stock_market",
        cost_estimate=unknown,
        time_estimate=unknown,
        quality_gates=("The selected source has verifiable provider terms.",),
        retry_strategy=("Try the fallback licensed library once.",),
        alternative_strategy="Use an explicitly licensed manual import.",
        delivery=DeliveryFileSpecification(
            media_kind="video",
            container_or_extension="mp4",
            mime_type="video/mp4",
            filename_pattern="stock_market_{attempt}.mp4",
        ),
    )
    return ProductionJobRequest(
        job_id="production_job_stock_market",
        run_id="production_run_stock_market",
        task_id=task.task_id,
        requirement_item_id=task.requirement_item_id,
        adapter_id="stock_video_library",
        capability_id="asset_search",
        task_spec=task,
        attempt=1,
        idempotency_key="stock_market_key",
        requested_at=NOW,
    )


def test_pexels_candidate_is_downloaded_with_safe_license_provenance(tmp_path):
    transport = FakeTransport()
    adapter = StockVideoMaterialProductionAdapter(
        _config(tmp_path),
        transport=transport,
        environment={"PEXELS_API_KEY": "secret-pexels"},
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    update = adapter.submit(_request(), staging_root=staging)

    assert update.status == "succeeded"
    assert len(update.artifacts) == 1
    artifact = update.artifacts[0]
    assert (staging / artifact.staging_relative_path).read_bytes()
    assert artifact.source_provenance.provider_id == "pexels"
    assert artifact.source_provenance.license_name == "Pexels License"
    assert artifact.source_provenance.attribution_required is False
    assert "secret-pexels" not in artifact.model_dump_json()
    assert transport.json_calls[0][1] == {"Authorization": "secret-pexels"}
    cached_metadata = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "stock-cache").rglob("*.json")
    )
    assert "secret-pexels" not in cached_metadata


def test_pixabay_is_used_only_after_primary_source_fails(tmp_path):
    transport = FakeTransport(pexels=False)
    adapter = StockVideoMaterialProductionAdapter(
        _config(tmp_path),
        transport=transport,
        environment={
            "PEXELS_API_KEY": "secret-pexels",
            "PIXABAY_API_KEY": "secret-pixabay",
        },
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    update = adapter.submit(_request(), staging_root=staging)

    assert update.status == "succeeded"
    assert update.artifacts[0].source_provenance.provider_id == "pixabay"
    assert len(transport.json_calls) == 2
    assert "secret-pixabay" not in update.model_dump_json()


def test_pixabay_fallback_also_handles_primary_download_failure(tmp_path):
    transport = FakeTransport(fail_pexels_download=True)
    adapter = StockVideoMaterialProductionAdapter(
        _config(tmp_path),
        transport=transport,
        environment={
            "PEXELS_API_KEY": "secret-pexels",
            "PIXABAY_API_KEY": "secret-pixabay",
        },
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    update = adapter.submit(_request(), staging_root=staging)

    assert update.status == "succeeded"
    assert update.artifacts[0].source_provenance.provider_id == "pixabay"
    assert not list(staging.rglob("pexels-*.mp4"))


def test_registry_exposes_configured_asset_search_without_credentials_in_schema(tmp_path):
    config = _config(tmp_path)
    registry = build_material_production_registry(stock_video_config=config)
    adapter = registry.adapters["stock_video_library"]
    adapter.environment = {"PEXELS_API_KEY": "secret-pexels"}

    capability = adapter.capability()

    assert capability.configured is True
    assert capability.capability_ids == ("asset_search",)
    assert "secret-pexels" not in registry.reference().model_dump_json()


def test_unconfigured_provider_fails_closed_without_writing(tmp_path):
    adapter = StockVideoMaterialProductionAdapter(
        _config(tmp_path),
        transport=FakeTransport(),
        environment={},
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    update = adapter.submit(_request(), staging_root=staging)

    assert adapter.capability().configured is False
    assert update.status == "failed"
    assert update.error_code == "stock_video_acquisition_failed"
    assert list(staging.rglob("*")) == []


def test_provider_terms_survive_acceptance_into_catalog_contract(tmp_path):
    adapter = StockVideoMaterialProductionAdapter(
        _config(tmp_path),
        transport=FakeTransport(),
        environment={"PEXELS_API_KEY": "secret-pexels"},
        clock=lambda: NOW,
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    request = _request()
    update = adapter.submit(request, staging_root=staging)
    artifact = update.artifacts[0]
    service = object.__new__(MaterialProductionOrchestrator)
    service.clock = lambda: NOW
    validation = SimpleNamespace(
        sha256="sha256:" + ("1" * 64),
        size_bytes=23,
        mime_type="video/mp4",
        container="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        audio_codec=None,
        duration_seconds=8.0,
        width=1920,
        height=1080,
        fps=30.0,
        has_audio=False,
        requirement_item_id=request.requirement_item_id,
        task_id=request.task_id,
        run_id=request.run_id,
        job_id=request.job_id,
        validation_id="validation_stock_market",
    )
    confirmed = SimpleNamespace(
        proposal=SimpleNamespace(
            plan=SimpleNamespace(
                material_confirmation_ref=SimpleNamespace(
                    requirements_plan_id="requirements_plan_stock_market"
                ),
                production_plan_id="production_plan_stock_market",
            )
        )
    )
    job = SimpleNamespace(
        request=SimpleNamespace(adapter_id="stock_video_library"),
        update=SimpleNamespace(
            cost_status="unknown",
            cost_value=None,
            cost_currency=None,
        ),
    )
    ingest = SimpleNamespace(
        derivatives=(),
        analysis=None,
        tags=(),
        quality_report=None,
    )

    entry = service._catalog_entry(
        validation=validation,
        decision=SimpleNamespace(decision_id="decision_stock_market"),
        artifact=artifact,
        job=job,
        confirmed=confirmed,
        task=request.task_spec,
        ingest_bundle=ingest,
    )

    assert entry.origin_kind == "library"
    assert entry.license_status == "provider_terms"
    assert entry.source_provenance == artifact.source_provenance
    assert entry.usage_restrictions == artifact.source_provenance.usage_restrictions
