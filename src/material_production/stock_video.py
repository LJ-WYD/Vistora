"""Licensed stock-video search and acquisition for confirmed material tasks.

The provider is deliberately narrow: it searches only allowlisted Pexels and
Pixabay APIs, downloads an exact HTTPS candidate into Vistora staging, and
attaches browser-safe licence provenance.  The normal material-production
review, validation and catalog boundaries remain responsible for acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from director import digest_json

from .adapters import MaterialProductionAdapter, _schema_digest
from .models import (
    AdapterCapability,
    AdapterJobUpdate,
    ArtifactCandidate,
    ArtifactSourceProvenance,
    ProductionJobRequest,
)


STOCK_VIDEO_PROVIDER_VERSION = "1.0.0"
STOCK_QUERY_PARAMETER = "stock_query"
STOCK_PROVIDER_PARAMETER = "stock_provider"
STOCK_ASSET_ID_PARAMETER = "stock_asset_id"
STOCK_MAX_CANDIDATES_PARAMETER = "stock_max_candidates"
STOCK_ORIENTATION_PARAMETER = "stock_orientation"
_PROVIDER_HOSTS = {
    "pexels": {
        "api": {"api.pexels.com"},
        "download": {"videos.pexels.com"},
        "page": {"pexels.com", "www.pexels.com"},
    },
    "pixabay": {
        "api": {"pixabay.com"},
        "download": {"cdn.pixabay.com"},
        "page": {"pixabay.com", "www.pixabay.com"},
    },
}
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class StockVideoModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class StockVideoSourceConfig(StockVideoModel):
    provider_id: Literal["pexels", "pixabay"]
    api_key_env: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]+$",
    )
    enabled: bool = True
    priority: int = Field(ge=1, le=20)


class StockVideoProviderConfig(StockVideoModel):
    schema_name: Literal["vistora.stock-video-provider"] = (
        "vistora.stock-video-provider"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    cache_root: Path
    request_timeout_seconds: float = Field(default=30, ge=2, le=120)
    max_download_bytes: int = Field(
        default=536_870_912,
        ge=1_048_576,
        le=4_294_967_296,
    )
    search_cache_hours: int = Field(default=24, ge=1, le=168)
    max_candidates_per_task: int = Field(default=1, ge=1, le=3)
    require_non_system_drive: bool = True
    sources: tuple[StockVideoSourceConfig, ...] = (
        StockVideoSourceConfig(
            provider_id="pexels",
            api_key_env="PEXELS_API_KEY",
            priority=1,
        ),
        StockVideoSourceConfig(
            provider_id="pixabay",
            api_key_env="PIXABAY_API_KEY",
            priority=2,
        ),
    )

    @model_validator(mode="after")
    def config_is_safe(self) -> "StockVideoProviderConfig":
        providers = [item.provider_id for item in self.sources]
        priorities = [item.priority for item in self.sources]
        if len(providers) != len(set(providers)) or len(priorities) != len(
            set(priorities)
        ):
            raise ValueError("Stock-video sources and priorities must be unique")
        if not any(item.enabled for item in self.sources):
            raise ValueError("At least one stock-video source must be enabled")
        if (
            self.require_non_system_drive
            and os.name == "nt"
            and self.cache_root.is_absolute()
            and self.cache_root.drive.casefold()
            == os.environ.get("SystemDrive", "C:").rstrip("\\/").casefold()
        ):
            raise ValueError("Stock-video cache must not use the system drive")
        return self


class StockVideoCandidate(StockVideoModel):
    provider_id: Literal["pexels", "pixabay"]
    provider_asset_id: str = Field(min_length=1, max_length=128)
    source_page_url: str = Field(min_length=8, max_length=2048)
    creator_name: str | None = Field(default=None, min_length=1, max_length=256)
    creator_url: str | None = Field(default=None, min_length=8, max_length=2048)
    download_url: str = Field(min_length=8, max_length=4096)
    mime_type: Literal["video/mp4"] = "video/mp4"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    file_size_bytes: int | None = Field(default=None, gt=0)
    license_name: str = Field(min_length=1, max_length=128)
    license_url: str = Field(min_length=8, max_length=2048)
    attribution_required: bool = False
    attribution_text: str | None = Field(default=None, min_length=1, max_length=512)
    usage_restrictions: tuple[str, ...] = Field(min_length=1)
    retrieved_at: datetime
    candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def candidate_is_exact(self) -> "StockVideoCandidate":
        for value in (
            self.source_page_url,
            self.creator_url,
            self.download_url,
            self.license_url,
        ):
            if value is None:
                continue
            parsed = urlparse(value)
            if parsed.scheme != "https" or parsed.username or parsed.password:
                raise ValueError("Stock-video URLs must be credential-free HTTPS")
        host = (urlparse(self.download_url).hostname or "").casefold()
        if host not in _PROVIDER_HOSTS[self.provider_id]["download"]:
            raise ValueError("Stock-video download host is not allowlisted")
        for value in (self.source_page_url, self.creator_url, self.license_url):
            if value is None:
                continue
            page_host = (urlparse(value).hostname or "").casefold()
            if page_host not in _PROVIDER_HOSTS[self.provider_id]["page"]:
                raise ValueError("Stock-video source page host is not allowlisted")
        if self.attribution_required != (self.attribution_text is not None):
            raise ValueError("Required attribution must include exact text")
        payload = self.model_dump(mode="json", exclude={"candidate_digest"})
        if self.candidate_digest != digest_json(payload):
            raise ValueError("Stock-video candidate digest mismatched")
        return self

    def provenance(self) -> ArtifactSourceProvenance:
        payload = {
            "provider_id": self.provider_id,
            "provider_asset_id": self.provider_asset_id,
            "source_page_url": self.source_page_url,
            "creator_name": self.creator_name,
            "creator_url": self.creator_url,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "attribution_required": self.attribution_required,
            "attribution_text": self.attribution_text,
            "usage_restrictions": self.usage_restrictions,
            "source_file_url_digest": _sha256_text(self.download_url),
            "retrieved_at": self.retrieved_at,
        }
        draft = ArtifactSourceProvenance.model_construct(
            **payload,
            provenance_digest="sha256:" + ("0" * 64),
        )
        digest_payload = draft.model_dump(
            mode="json",
            exclude={"provenance_digest"},
        )
        return ArtifactSourceProvenance(
            **payload,
            provenance_digest=digest_json(digest_payload),
        )


class StockVideoTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]: ...

    def download(
        self,
        url: str,
        *,
        destination: Path,
        timeout: float,
        max_bytes: int,
    ) -> int: ...


class UrllibStockVideoTransport:
    def get_json(self, url, *, headers, timeout):
        request = Request(url, headers={**headers, "User-Agent": "Vistora/1"})
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(8_388_609)
            if len(payload) > 8_388_608:
                raise ValueError("Stock-video API response exceeded the safe limit")
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Stock-video API returned an invalid document")
        return decoded

    def download(self, url, *, destination, timeout, max_bytes):
        request = Request(url, headers={"User-Agent": "Vistora/1"})
        partial = destination.with_suffix(destination.suffix + ".partial")
        total = 0
        try:
            with urlopen(request, timeout=timeout) as response, partial.open("wb") as out:
                content_type = response.headers.get_content_type()
                if content_type not in {"video/mp4", "application/octet-stream"}:
                    raise ValueError("Stock-video download did not return an MP4")
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise ValueError("Stock-video download exceeded the safe limit")
                    out.write(block)
            if total == 0:
                raise ValueError("Stock-video download was empty")
            partial.replace(destination)
            return total
        finally:
            partial.unlink(missing_ok=True)


def provider_config_path(project_file: str | Path) -> Path:
    explicit = os.environ.get("VISTORA_STOCK_VIDEO_CONFIG")
    if explicit:
        return Path(explicit)
    project = Path(project_file)
    return project.with_name(f"{project.stem}.stock-video-provider.json")


def load_stock_video_provider_config(
    project_file: str | Path,
) -> StockVideoProviderConfig | None:
    path = provider_config_path(project_file)
    if path.is_file():
        try:
            config = StockVideoProviderConfig.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            root = (
                config.cache_root
                if config.cache_root.is_absolute()
                else (path.parent / config.cache_root).resolve()
            )
            payload = config.model_dump(mode="python")
            payload["cache_root"] = root
            return StockVideoProviderConfig.model_validate(payload)
        except (OSError, ValueError) as exc:
            raise ValueError("Stock-video provider configuration is invalid") from exc
    if not (os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY")):
        return None
    project = Path(project_file).resolve()
    return StockVideoProviderConfig(
        cache_root=project.parent / "stock-video-cache",
    )


class StockVideoMaterialProductionAdapter(MaterialProductionAdapter):
    """Pexels-first, Pixabay-fallback acquisition behind artifact review."""

    def __init__(
        self,
        config: StockVideoProviderConfig,
        *,
        transport: StockVideoTransport | None = None,
        environment: dict[str, str] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibStockVideoTransport()
        self.environment = environment if environment is not None else os.environ
        self.clock = clock

    def _configured_sources(self) -> tuple[StockVideoSourceConfig, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.config.sources
                    if item.enabled and self.environment.get(item.api_key_env)
                ),
                key=lambda item: item.priority,
            )
        )

    def capability(self) -> AdapterCapability:
        configured = bool(self._configured_sources())
        return AdapterCapability(
            adapter_id="stock_video_library",
            adapter_version=STOCK_VIDEO_PROVIDER_VERSION,
            capability_ids=("asset_search",),
            configured=configured,
            execution_kind="external_provider",
            max_concurrency=2,
            rate_limit_per_minute=3,
            limitation=(
                None
                if configured
                else "Set PEXELS_API_KEY or PIXABAY_API_KEY outside project files."
            ),
            input_schema_digest=_schema_digest(ProductionJobRequest),
            result_schema_digest=_schema_digest(AdapterJobUpdate),
        )

    @staticmethod
    def _parameters(request: ProductionJobRequest) -> dict[str, Any]:
        if request.task_spec is None:
            raise ValueError("Stock-video acquisition requires the confirmed task")
        return {
            item.name: item.value
            for item in request.task_spec.reproducibility_parameters
        }

    def _search(self, source, *, query, orientation, requested_width, requested_height):
        key = self.environment.get(source.api_key_env)
        if not key:
            return ()
        cache_key = digest_json(
            {
                "provider": source.provider_id,
                "query": query,
                "orientation": orientation,
                "width": requested_width,
                "height": requested_height,
                "parser": STOCK_VIDEO_PROVIDER_VERSION,
            }
        )[7:]
        cache_path = self.config.cache_root / "search-cache" / f"{cache_key}.json"
        if cache_path.is_file():
            age = self.clock() - datetime.fromtimestamp(
                cache_path.stat().st_mtime, tz=timezone.utc
            )
            if age <= timedelta(hours=self.config.search_cache_hours):
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                    return tuple(StockVideoCandidate.model_validate(item) for item in payload)
                except (OSError, ValueError):
                    pass
        if source.provider_id == "pexels":
            params = {"query": query, "per_page": 15}
            if orientation != "any":
                params["orientation"] = orientation
            url = "https://api.pexels.com/v1/videos/search?" + urlencode(params)
            document = self.transport.get_json(
                url,
                headers={"Authorization": key},
                timeout=self.config.request_timeout_seconds,
            )
            candidates = self._parse_pexels(document)
        else:
            translated = {"portrait": "vertical", "landscape": "horizontal"}.get(
                orientation, "all"
            )
            params = {
                "key": key,
                "q": query,
                "per_page": 20,
                "safesearch": "true",
                "video_type": "all",
            }
            if translated != "all":
                params["orientation"] = translated
            url = "https://pixabay.com/api/videos/?" + urlencode(params)
            document = self.transport.get_json(
                url,
                headers={},
                timeout=self.config.request_timeout_seconds,
            )
            candidates = self._parse_pixabay(document)
        ranked = tuple(
            sorted(
                candidates,
                key=lambda item: self._rank(
                    item,
                    requested_width=requested_width,
                    requested_height=requested_height,
                ),
            )
        )
        temp = cache_path.with_suffix(".tmp")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(
                json.dumps(
                    [item.model_dump(mode="json") for item in ranked],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temp.replace(cache_path)
        except OSError:
            temp.unlink(missing_ok=True)
        return ranked

    @staticmethod
    def _candidate(payload: dict[str, Any]) -> StockVideoCandidate:
        digest_payload = dict(payload)
        retrieved_at = digest_payload.get("retrieved_at")
        if isinstance(retrieved_at, datetime):
            digest_payload["retrieved_at"] = _json_datetime(retrieved_at)
        digest_payload.setdefault("mime_type", "video/mp4")
        return StockVideoCandidate(
            **payload,
            candidate_digest=digest_json(digest_payload),
        )

    def _parse_pexels(self, document):
        results = []
        for video in document.get("videos", []):
            files = [
                item
                for item in video.get("video_files", [])
                if item.get("file_type") == "video/mp4"
                and item.get("width")
                and item.get("height")
                and item.get("link")
            ]
            if not files:
                continue
            chosen = max(files, key=lambda item: int(item["width"]) * int(item["height"]))
            user = video.get("user") or {}
            payload = {
                "provider_id": "pexels",
                "provider_asset_id": str(video["id"]),
                "source_page_url": str(video["url"]),
                "creator_name": user.get("name") or None,
                "creator_url": user.get("url") or None,
                "download_url": str(chosen["link"]),
                "width": int(chosen["width"]),
                "height": int(chosen["height"]),
                "duration_seconds": float(video["duration"]),
                "file_size_bytes": None,
                "license_name": "Pexels License",
                "license_url": "https://www.pexels.com/license/",
                "attribution_required": False,
                "attribution_text": None,
                "usage_restrictions": (
                    "Do not sell an unaltered copy of the stock video.",
                    "Do not imply endorsement by depicted people or brands.",
                    "Do not redistribute the video on another stock platform.",
                ),
                "retrieved_at": self.clock(),
            }
            results.append(self._candidate(payload))
        return tuple(results)

    def _parse_pixabay(self, document):
        results = []
        for video in document.get("hits", []):
            files = [
                item
                for item in (video.get("videos") or {}).values()
                if isinstance(item, dict)
                and item.get("url")
                and item.get("width")
                and item.get("height")
            ]
            if not files:
                continue
            chosen = max(files, key=lambda item: int(item["width"]) * int(item["height"]))
            creator = str(video.get("user") or "") or None
            creator_url = None
            if creator and video.get("user_id"):
                creator_url = (
                    "https://pixabay.com/users/"
                    + _SAFE_ID.sub("-", creator.casefold()).strip("-")
                    + f"-{int(video['user_id'])}/"
                )
            payload = {
                "provider_id": "pixabay",
                "provider_asset_id": str(video["id"]),
                "source_page_url": str(video["pageURL"]),
                "creator_name": creator,
                "creator_url": creator_url,
                "download_url": str(chosen["url"]),
                "width": int(chosen["width"]),
                "height": int(chosen["height"]),
                "duration_seconds": float(video["duration"]),
                "file_size_bytes": (
                    int(chosen["size"]) if chosen.get("size") else None
                ),
                "license_name": "Pixabay Content License",
                "license_url": "https://pixabay.com/service/license-summary/",
                "attribution_required": False,
                "attribution_text": None,
                "usage_restrictions": (
                    "Do not sell or distribute the stock video on a standalone basis.",
                    "Do not use depicted content in a misleading or unlawful way.",
                    "Do not use recognizable brands as part of a trademark or service mark.",
                ),
                "retrieved_at": self.clock(),
            }
            results.append(self._candidate(payload))
        return tuple(results)

    @staticmethod
    def _rank(candidate, *, requested_width, requested_height):
        target_pixels = (requested_width or 1920) * (requested_height or 1080)
        pixels = candidate.width * candidate.height
        undersized = 1 if pixels < target_pixels else 0
        distance = abs(pixels - target_pixels)
        return (undersized, distance, candidate.provider_asset_id)

    def submit(self, request, *, staging_root):
        opaque = "stock_" + hashlib.sha256(
            f"{request.job_id}:{request.idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        created_targets: list[Path] = []
        target_root: Path | None = None
        try:
            parameters = self._parameters(request)
            task = request.task_spec
            assert task is not None
            query = str(parameters.get(STOCK_QUERY_PARAMETER) or task.title).strip()
            if not query or len(query) > 100:
                raise ValueError("Stock-video search query is missing or too long")
            orientation = str(
                parameters.get(STOCK_ORIENTATION_PARAMETER) or "any"
            )
            if orientation not in {"any", "landscape", "portrait", "square"}:
                raise ValueError("Stock-video orientation is invalid")
            requested_provider = str(
                parameters.get(STOCK_PROVIDER_PARAMETER) or "auto"
            )
            if requested_provider not in {"auto", "pexels", "pixabay"}:
                raise ValueError("Stock-video provider selection is invalid")
            count = int(parameters.get(STOCK_MAX_CANDIDATES_PARAMETER) or 1)
            count = min(count, self.config.max_candidates_per_task)
            if count < 1:
                raise ValueError("Stock-video candidate count is invalid")
            exact_asset = parameters.get(STOCK_ASSET_ID_PARAMETER)
            sources = self._configured_sources()
            if requested_provider != "auto":
                sources = tuple(
                    item for item in sources if item.provider_id == requested_provider
                )
            if not sources:
                raise ValueError("No configured stock-video source is available")
            staging = Path(staging_root).resolve()
            target_root = (staging / request.job_id).resolve()
            if staging not in target_root.parents:
                raise ValueError("Stock-video target escapes staging")
            target_root.mkdir(parents=True, exist_ok=True)
            for source in sources:
                try:
                    candidates = self._search(
                        source,
                        query=query,
                        orientation=orientation,
                        requested_width=task.width,
                        requested_height=task.height,
                    )
                except Exception:
                    continue
                if exact_asset is not None:
                    candidates = tuple(
                        item
                        for item in candidates
                        if item.provider_asset_id == str(exact_asset)
                    )
                if not candidates:
                    continue
                source_targets: list[Path] = []
                try:
                    artifacts = []
                    for candidate in candidates[:count]:
                        safe_asset = _SAFE_ID.sub("_", candidate.provider_asset_id)[:64]
                        target = target_root / f"{candidate.provider_id}-{safe_asset}.mp4"
                        self.transport.download(
                            candidate.download_url,
                            destination=target,
                            timeout=self.config.request_timeout_seconds,
                            max_bytes=self.config.max_download_bytes,
                        )
                        source_targets.append(target)
                        created_targets.append(target)
                        artifact_hash = hashlib.sha256(
                            f"{request.job_id}:{candidate.candidate_digest}".encode("utf-8")
                        ).hexdigest()[:24]
                        artifacts.append(
                            ArtifactCandidate(
                                artifact_id=f"artifact_stock_{artifact_hash}",
                                job_id=request.job_id,
                                task_id=request.task_id,
                                requirement_item_id=request.requirement_item_id,
                                staging_relative_path=target.relative_to(staging).as_posix(),
                                claimed_mime_type="video/mp4",
                                source_provenance=candidate.provenance(),
                            )
                        )
                except Exception:
                    for target in source_targets:
                        target.unlink(missing_ok=True)
                        if target in created_targets:
                            created_targets.remove(target)
                    if requested_provider != "auto":
                        raise
                    continue
                return AdapterJobUpdate(
                    job_id=request.job_id,
                    adapter_id=self.capability().adapter_id,
                    provider_opaque_ref=opaque,
                    status="succeeded",
                    progress=1,
                    artifacts=tuple(artifacts),
                    message=(
                        "Licensed stock-video candidates are ready for validation "
                        "and explicit human review."
                    ),
                    updated_at=self.clock(),
                )
            raise ValueError("No licensed stock-video candidate matched the request")
        except Exception:
            for target in created_targets:
                target.unlink(missing_ok=True)
            if target_root is not None:
                try:
                    target_root.rmdir()
                except OSError:
                    pass
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id=self.capability().adapter_id,
                provider_opaque_ref=opaque,
                status="failed",
                progress=0,
                error_code="stock_video_acquisition_failed",
                message=(
                    "Stock-video acquisition failed safely; no candidate was "
                    "accepted or added to the timeline."
                ),
                updated_at=self.clock(),
            )

    def poll(self, request, *, provider_opaque_ref, staging_root):
        return self.submit(request, staging_root=staging_root)

    def cancel(self, request, *, provider_opaque_ref):
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_opaque_ref,
            status="cancelled",
            progress=0,
            message="The stock-video acquisition request was cancelled.",
            updated_at=self.clock(),
        )
