"""Local snapshot and confirmed-manual-edit HTTP surface for Vistora."""

from __future__ import annotations

import json
import re
import secrets
import socket
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from media_analysis import (
    MediaAnalysisCollection,
    MediaAnalysisRequest,
    MediaAnalysisService,
)
from director import (
    DirectorHistoryQuery,
    DirectorHistoryView,
    DirectorIntegrityError,
    DirectorSessionLedger,
)
from plan_review import (
    PlanDiffRequest,
    PlanReviewEnvelope,
    PlanReviewService,
    load_plan_diff_request,
)
from product_entry import (
    ProductEntryCommand,
    ProductEntryConcurrencyError,
    ProductEntryError,
    ProductEntryIntegrityError,
    ProductionEntryService,
)
from timeline_query import TimelineSnapshot, TimelineSnapshotService
from traceability.store import TraceabilityStore
from core.timeline import SubtitleCue, SubtitleStyle, SubtitleTrackConfig
from subtitles import SubtitleCodecError, export_subtitles, parse_subtitles
from workflow import (
    WorkflowApplicationError,
    WorkflowApplicationService,
    WorkflowHistoryQuery,
    WorkflowIntegrityError,
)

from .manual_edits import (
    ManualEditApplicationService,
    ManualEditValidationError,
)


PREVIEW_API_VERSION = "1.0.0"
STATIC_DIR = Path(__file__).with_name("static")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MEDIA_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".ogv": "video/ogg",
    ".webm": "video/webm",
}
SOURCE_ID_PATTERN = re.compile(r"^source_[0-9a-f]{16}$")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class PreviewConfigurationError(ValueError):
    """Preview server configuration is unsafe or invalid."""


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


@dataclass(frozen=True)
class ResolvedMedia:
    """Allowlisted media metadata without a public filesystem path."""

    path: Path
    content_type: str
    size: int


class MediaResolver:
    """Resolve configured sources only inside explicit allowlisted roots."""

    def __init__(self, roots: Iterable[str | Path] = ()) -> None:
        resolved_roots: list[Path] = []
        for root_value in roots:
            root = Path(root_value).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise PreviewConfigurationError(
                    f"Media root is not a directory: {root_value}"
                )
            if root not in resolved_roots:
                resolved_roots.append(root)
        self._roots = tuple(resolved_roots)

    @property
    def root_count(self) -> int:
        return len(self._roots)

    def resolve(self, configured_source: str) -> ResolvedMedia | None:
        source_path = Path(configured_source).expanduser()
        candidates = (
            (source_path,)
            if source_path.is_absolute()
            else tuple(root / source_path for root in self._roots)
        )
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not any(
                resolved == root or resolved.is_relative_to(root)
                for root in self._roots
            ):
                continue
            content_type = MEDIA_TYPES.get(resolved.suffix.lower())
            if content_type is None or not resolved.is_file():
                continue
            try:
                size = resolved.stat().st_size
            except OSError:
                continue
            return ResolvedMedia(
                path=resolved,
                content_type=content_type,
                size=size,
            )
        return None


class PreviewApplication:
    """Read-only snapshot and safe-media application state."""

    def __init__(
        self,
        snapshot_provider: Callable[[], TimelineSnapshot],
        media_roots: Iterable[str | Path] = (),
        *,
        skill_registry: Mapping[str, Any] | None = None,
        manual_edits_enabled: bool = False,
        analysis_service: MediaAnalysisService | None = None,
        plan_review_request_provider: Callable[
            [], PlanDiffRequest
        ] | None = None,
        workflow_service: WorkflowApplicationService | None = None,
        director_history_provider: Callable[
            [], DirectorHistoryView
        ] | None = None,
        product_entry_service: ProductionEntryService | None = None,
        product_csrf_token: str | None = None,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self.media_resolver = MediaResolver(media_roots)
        self.media_analysis = analysis_service or MediaAnalysisService()
        self._skill_registry = skill_registry or {}
        self._plan_review_request_provider = (
            plan_review_request_provider
        )
        self.workflow = workflow_service
        self._director_history_provider = director_history_provider
        self.product_entry = product_entry_service
        self.product_csrf_token = (
            product_csrf_token or secrets.token_urlsafe(32)
        )
        if manual_edits_enabled and skill_registry is None:
            raise PreviewConfigurationError(
                "Manual editing requires an explicit atomic skill registry"
            )
        self.manual_edits = (
            ManualEditApplicationService(
                self.snapshot,
                self._skill_registry,
            )
            if manual_edits_enabled
            else None
        )

    def snapshot(self) -> TimelineSnapshot:
        snapshot = self._snapshot_provider()
        if not isinstance(snapshot, TimelineSnapshot):
            raise TypeError("Snapshot provider must return TimelineSnapshot")
        return snapshot

    @property
    def plan_review_enabled(self) -> bool:
        return self._plan_review_request_provider is not None

    @staticmethod
    def _source_references(
        snapshot: TimelineSnapshot,
    ) -> dict[str, str | None]:
        references: dict[str, str | None] = {}
        for track in snapshot.tracks:
            for clip in track.clips:
                source_id = clip.source.source_id
                source_value = clip.source.value
                current = references.get(source_id)
                if current is not None and current != source_value:
                    references[source_id] = None
                elif source_id not in references:
                    references[source_id] = source_value
        return references

    def resolve_media(
        self,
        source_id: str,
        snapshot: TimelineSnapshot | None = None,
    ) -> ResolvedMedia | None:
        if SOURCE_ID_PATTERN.fullmatch(source_id) is None:
            return None
        current_snapshot = snapshot or self.snapshot()
        source = self._source_references(current_snapshot).get(source_id)
        if source is None:
            return None
        return self.media_resolver.resolve(source)

    def snapshot_payload(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        media: dict[str, dict[str, Any]] = {}
        for source_id, source in sorted(
            self._source_references(snapshot).items()
        ):
            resolved = (
                None if source is None else self.media_resolver.resolve(source)
            )
            media[source_id] = {
                "available": resolved is not None,
                "url": (
                    f"/media/{source_id}" if resolved is not None else None
                ),
                "content_type": (
                    resolved.content_type if resolved is not None else None
                ),
                "size_bytes": resolved.size if resolved is not None else None,
                "reason": (
                    None
                    if resolved is not None
                    else "not_allowlisted_or_unavailable"
                ),
            }
        return {
            "api_version": PREVIEW_API_VERSION,
            "read_only": True,
            "snapshot": self._browser_safe_snapshot(snapshot),
            "media": media,
            "capabilities": {
                "snapshot_reads": True,
                "media_range_requests": True,
                "media_analysis": True,
                "video_thumbnails": True,
                "audio_waveforms": True,
                "timeline_mutation": False,
                "direct_timeline_mutation": False,
                "agent_execution": False,
                "tool_execution": False,
                "allowlisted_media_roots": self.media_resolver.root_count,
                "manual_draft": True,
                "manual_edit_apply": self.manual_edits is not None,
                "confirmed_manual_dispatch": self.manual_edits is not None,
                "audio_loudness_analysis": self.manual_edits is not None,
                "subtitle_parse": True,
                "subtitle_download": True,
                "plan_review": (
                    self.plan_review_enabled
                ),
                "plan_review_confirmation": False,
                "plan_review_execution": False,
                "workflow_history": self.workflow is not None,
                "workflow_review_persistence": (
                    self.workflow is not None
                    and self.plan_review_enabled
                ),
                "workflow_explicit_confirmation": self.workflow is not None,
                "workflow_confirmed_execution": self.workflow is not None,
                "workflow_reviewed_rollback": self.workflow is not None,
                "director_history": (
                    self._director_history_provider is not None
                ),
                "production_entry": self.product_entry is not None,
            },
        }

    @staticmethod
    def parse_subtitle_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Parse user-selected subtitle text without reading or writing files."""

        content = payload.get("content")
        format_name = payload.get("format", "auto")
        language = payload.get("language", "und")
        if not isinstance(content, str) or not content.strip():
            raise SubtitleCodecError("Subtitle content is required")
        if len(content.encode("utf-8")) > 128 * 1024:
            raise SubtitleCodecError("Subtitle content exceeds 128 KiB")
        if format_name not in {"auto", "srt", "vtt"}:
            raise SubtitleCodecError("Subtitle format must be auto, srt, or vtt")
        if not isinstance(language, str):
            raise SubtitleCodecError("Subtitle language must be text")
        cues = parse_subtitles(content, format_name, language=language)
        return {
            "schema_name": "vistora.subtitle-parse-result",
            "schema_version": "1.0.0",
            "format": format_name,
            "cue_count": len(cues),
            "cues": [cue.model_dump(mode="json") for cue in cues],
            "persisted": False,
        }

    def subtitle_export(
        self,
        *,
        format_name: str,
        track_ids: tuple[str, ...],
    ) -> str:
        """Create a browser download from detached snapshot data only."""

        if format_name not in {"srt", "vtt"}:
            raise SubtitleCodecError("Subtitle format must be srt or vtt")
        snapshot = self.snapshot()
        selected = set(track_ids)
        if len(selected) != len(track_ids):
            raise SubtitleCodecError("Subtitle track IDs must be unique")
        known = {track.track_id for track in snapshot.subtitle_tracks}
        if selected - known:
            raise SubtitleCodecError("Requested subtitle track is unavailable")
        tracks: list[SubtitleTrackConfig] = []
        for track in snapshot.subtitle_tracks:
            if selected and track.track_id not in selected:
                continue
            style = SubtitleStyle(**track.style.model_dump(
                mode="python",
                exclude={"schema_name", "schema_version"},
            ))
            cues = tuple(
                SubtitleCue(
                    cue_id=cue.cue_id,
                    start_seconds=cue.start_seconds,
                    end_seconds=cue.end_seconds,
                    text=cue.text,
                    language=cue.language,
                    speaker=cue.speaker,
                    enabled=cue.enabled,
                    settings=cue.settings,
                    style=(
                        None
                        if cue.style is None
                        else SubtitleStyle(**cue.style.model_dump(
                            mode="python",
                            exclude={"schema_name", "schema_version"},
                        ))
                    ),
                )
                for cue in track.cues
            )
            tracks.append(SubtitleTrackConfig(
                track_id=track.track_id,
                kind=track.kind,
                role=track.role,
                language=track.language,
                order=track.order_index,
                enabled=track.enabled,
                locked=track.locked,
                allow_overlaps=track.allow_overlaps,
                style=style,
                cues=cues,
            ))
        return export_subtitles(tuple(tracks), format_name)

    def product_payload(self) -> dict[str, Any]:
        """Return the path-safe product state plus an ephemeral CSRF token."""

        if self.product_entry is None:
            return {
                "schema_name": "vistora.product-entry-unavailable",
                "schema_version": "1.0.0",
                "state": "unavailable",
                "message": "The production entry service is not configured.",
            }
        return {
            "csrf_token": self.product_csrf_token,
            "view": self.product_entry.view().model_dump(mode="json"),
        }

    def product_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.product_entry is None:
            raise ProductEntryError(
                "The production entry service is not configured"
            )
        command = ProductEntryCommand.model_validate(payload)
        return self.product_entry.command(command).model_dump(mode="json")

    def director_payload(self) -> dict[str, Any]:
        """Return only the browser-safe Director history projection."""

        if self._director_history_provider is None:
            return {
                "schema_name": "vistora.director-history-unavailable",
                "schema_version": "1.0.0",
                "latest_status": "unavailable",
                "message": (
                    "No Director session history was supplied to this preview."
                ),
            }
        history = self._director_history_provider()
        if not isinstance(history, DirectorHistoryView):
            raise TypeError(
                "Director history provider must return DirectorHistoryView"
            )
        return history.model_dump(mode="json")

    def plan_review_payload(self) -> dict[str, Any]:
        """Return a path-redacted review or an explicit availability state."""

        if self._plan_review_request_provider is None:
            return PlanReviewEnvelope(
                review_state="unavailable",
                message=(
                    "No Director plan-review input was supplied to this "
                    "preview."
                ),
            ).model_dump(mode="json")
        try:
            request = self._plan_review_request_provider()
            if not isinstance(request, PlanDiffRequest):
                raise TypeError(
                    "Plan review provider must return PlanDiffRequest"
                )
        except ProductEntryError as exc:
            return PlanReviewEnvelope(
                review_state="unavailable",
                message=str(exc),
            ).model_dump(mode="json")
        except Exception:
            return PlanReviewEnvelope(
                review_state="invalid",
                message=(
                    "The configured plan-review fixture is invalid and was "
                    "not exposed to the browser."
                ),
            ).model_dump(mode="json")
        return PlanReviewService.review(
            request,
            self.snapshot(),
            self._skill_registry,
        ).model_dump(mode="json")

    def workflow_payload(self) -> dict[str, Any]:
        """Return collapsed audit history without raw plans/tool arguments."""

        if self.workflow is None:
            return {
                "schema_name": "vistora.workflow-history-unavailable",
                "schema_version": "1.0.0",
                "state": "unavailable",
                "message": (
                    "Workflow persistence is disabled for external timeline "
                    "documents."
                ),
            }
        snapshot = self.snapshot()
        ledger = self.workflow.store.load(
            None
            if self.workflow.store.path.exists()
            else snapshot.project_id
        )
        return WorkflowHistoryQuery.project(ledger).model_dump(mode="json")

    def workflow_action(
        self,
        route: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.workflow is None:
            raise WorkflowApplicationError(
                "Workflow persistence is unavailable"
            )
        if route == "/api/workflow/reviews":
            if self._plan_review_request_provider is None:
                raise WorkflowApplicationError(
                    "No versioned plan-review input is configured"
                )
            record = self.workflow.record_review(
                self._plan_review_request_provider()
            )
            result = {"review_id": record.review_id, "status": "reviewed"}
        elif route == "/api/workflow/confirmations":
            record = self.workflow.confirm_review(
                str(payload.get("review_id", "")),
                confirmed_by=str(payload.get("confirmed_by", "")),
                decision=payload.get("decision"),
            )
            result = {
                "confirmation_record_id": record.confirmation_record_id,
                "status": record.decision,
            }
        elif route == "/api/workflow/executions":
            record = self.workflow.run_confirmed_execution(
                str(payload.get("confirmation_record_id", ""))
            )
            result = {"run_id": record.run_id, "status": record.status}
        elif route == "/api/workflow/rollbacks/reviews":
            record = self.workflow.propose_rollback(
                str(payload.get("source_run_id", ""))
            )
            result = {
                "review_id": record.review_id,
                "proposal_id": record.proposal.proposal_id,
                "status": "reviewed",
            }
        elif route == "/api/workflow/rollbacks/confirmations":
            record = self.workflow.confirm_rollback(
                str(payload.get("review_id", "")),
                confirmed_by=str(payload.get("confirmed_by", "")),
                decision=payload.get("decision"),
            )
            result = {
                "confirmation_id": record.confirmation_id,
                "status": record.decision,
            }
        elif route == "/api/workflow/rollbacks/runs":
            record = self.workflow.apply_rollback(
                str(payload.get("confirmation_id", ""))
            )
            result = {
                "rollback_run_id": record.rollback_run_id,
                "status": record.status,
            }
        else:
            raise WorkflowApplicationError("Unknown workflow transition")
        return {
            "result": result,
            "history": self.workflow_payload(),
        }

    @staticmethod
    def _browser_safe_snapshot(
        snapshot: TimelineSnapshot,
    ) -> dict[str, Any]:
        """Redact configured paths while preserving snapshot structure."""

        payload = snapshot.model_dump(mode="json")
        for track in payload["tracks"]:
            for clip in track["clips"]:
                source = clip["source"]
                source["reference_type"] = "opaque_preview_reference"
                source["value"] = f"media:{source['source_id']}"
        return payload

    def analysis_payload(
        self,
        preview_mode: str = "applied",
    ) -> dict[str, Any]:
        """Analyze visible video/audio clip ranges without mutating sources."""

        if preview_mode not in {"original", "applied"}:
            raise ValueError("Unknown visual preview mode")

        snapshot = self.snapshot()
        references = self._source_references(snapshot)
        results = []
        for track in snapshot.tracks:
            if track.kind not in {"video", "audio"}:
                continue
            for clip in track.clips:
                request = MediaAnalysisRequest(
                    snapshot_id=snapshot.snapshot_id,
                    source_id=clip.source.source_id,
                    clip_id=clip.clip_id,
                    track_key=track.track_key,
                    media_kind=track.kind,
                    source_start_seconds=clip.trim_in_seconds,
                    source_end_seconds=clip.trim_out_seconds,
                    timeline_start_seconds=clip.timeline_start_seconds,
                    timeline_end_seconds=clip.timeline_end_seconds,
                    reverse=clip.reverse,
                    freeze_frame_source_time_seconds=(
                        clip.freeze_frame_source_time_seconds
                    ),
                    freeze_frame_duration_seconds=(
                        clip.freeze_frame_duration_seconds
                    ),
                    rotate_degrees=clip.rotate_degrees,
                    preview_mode=(
                        preview_mode if track.kind == "video" else "original"
                    ),
                    visual_digest=(
                        clip.visual_digest
                        if track.kind == "video" and preview_mode == "applied"
                        else None
                    ),
                    canvas_width=(
                        snapshot.width
                        if track.kind == "video" and preview_mode == "applied"
                        else None
                    ),
                    canvas_height=(
                        snapshot.height
                        if track.kind == "video" and preview_mode == "applied"
                        else None
                    ),
                    transform=clip.transform.model_dump(mode="python"),
                    color=clip.color.model_dump(mode="python"),
                    visual_automations=tuple(
                        {
                            "automation_id": automation.automation_id,
                            "clip_id": automation.clip_id,
                            "property_path": automation.property_path,
                            "enabled": automation.enabled,
                            "keyframes": tuple(
                                {
                                    "keyframe_id": point.keyframe_id,
                                    "offset_seconds": point.offset_seconds,
                                    "value": point.value,
                                    "interpolation": point.interpolation,
                                }
                                for point in automation.keyframes
                            ),
                        }
                        for automation in clip.visual_automations
                    ) if track.kind == "video" and preview_mode == "applied" else (),
                )
                source = references.get(clip.source.source_id)
                if source is None:
                    result = self.media_analysis.unavailable(request)
                elif Path(source).suffix.lower() not in MEDIA_TYPES:
                    result = self.media_analysis.unavailable(
                        request,
                        status="unsupported",
                        status_code="unsupported_media_type",
                    )
                else:
                    resolved = self.media_resolver.resolve(source)
                    if resolved is None:
                        result = self.media_analysis.unavailable(request)
                    else:
                        result = self.media_analysis.analyze(
                            request,
                            resolved.path,
                            resolved.content_type,
                        )
                results.append(result)
        collection = MediaAnalysisCollection(
            snapshot_id=snapshot.snapshot_id,
            results=tuple(results),
        )
        return collection.model_dump(mode="json")

    def analysis_artifact(
        self,
        analysis_id: str,
        artifact_id: str,
    ):
        return self.media_analysis.get_artifact(
            analysis_id,
            artifact_id,
        )


def _parse_range(value: str, size: int) -> tuple[int, int] | None:
    if not value.startswith("bytes=") or "," in value or size <= 0:
        return None
    start_text, separator, end_text = value[6:].partition("-")
    if not separator:
        return None
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        elif end_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(0, size - suffix_length)
            end = size - 1
        else:
            return None
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _handler_class(
    application: PreviewApplication,
) -> type[BaseHTTPRequestHandler]:
    class PreviewRequestHandler(BaseHTTPRequestHandler):
        server_version = "VistoraPreview/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "media-src 'self'; "
                "connect-src 'self'; "
                "object-src 'none'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'",
            )

        def _send_bytes(
            self,
            status: HTTPStatus,
            content: bytes,
            content_type: str,
            *,
            head_only: bool = False,
            cache_control: str = "no-store",
        ) -> None:
            self.send_response(status)
            self._security_headers()
            self.send_header("Cache-Control", cache_control)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if not head_only:
                self.wfile.write(content)

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, Any],
            *,
            head_only: bool = False,
        ) -> None:
            content = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            self._send_bytes(
                status,
                content,
                "application/json; charset=utf-8",
                head_only=head_only,
            )

        def _send_error_json(
            self,
            status: HTTPStatus,
            code: str,
            message: str,
            *,
            head_only: bool = False,
        ) -> None:
            self._send_json(
                status,
                {"error": {"code": code, "message": message}},
                head_only=head_only,
            )

        def _serve_static(self, route: str, head_only: bool) -> bool:
            asset = STATIC_ROUTES.get(route)
            if asset is None:
                return False
            filename, content_type = asset
            try:
                content = (STATIC_DIR / filename).read_bytes()
            except OSError:
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "static_asset_unavailable",
                    "A required preview asset is unavailable.",
                    head_only=head_only,
                )
                return True
            self._send_bytes(
                HTTPStatus.OK,
                content,
                content_type,
                head_only=head_only,
                cache_control="no-cache",
            )
            return True

        def _serve_snapshot(self, head_only: bool) -> None:
            try:
                payload = application.snapshot_payload()
            except Exception:
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "snapshot_unavailable",
                    "The timeline snapshot could not be loaded.",
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)

        def _serve_subtitle_export(self, head_only: bool) -> None:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            format_name = query.get("format", ["srt"])[0]
            track_ids = tuple(sorted(query.get("track_id", [])))
            try:
                content = application.subtitle_export(
                    format_name=format_name,
                    track_ids=track_ids,
                ).encode("utf-8")
            except SubtitleCodecError as exc:
                self._send_error_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "subtitle_export_rejected",
                    str(exc),
                    head_only=head_only,
                )
                return
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Type",
                "text/vtt; charset=utf-8"
                if format_name == "vtt"
                else "application/x-subrip; charset=utf-8",
            )
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="vistora-subtitles.{format_name}"',
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if not head_only:
                self.wfile.write(content)

        def _serve_analysis(self, head_only: bool) -> None:
            try:
                query = parse_qs(urlsplit(self.path).query)
                mode = query.get("mode", ["applied"])[0]
                payload = application.analysis_payload(mode)
            except Exception:
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "analysis_unavailable",
                    "Media visualization analysis could not be loaded.",
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)

        def _serve_plan_review(self, head_only: bool) -> None:
            try:
                payload = application.plan_review_payload()
            except Exception:
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "plan_review_unavailable",
                    "The plan review could not be loaded safely.",
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)

        def _serve_workflow(self, head_only: bool) -> None:
            try:
                payload = application.workflow_payload()
            except WorkflowIntegrityError:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "workflow_integrity_failed",
                    "The workflow ledger failed integrity validation.",
                    head_only=head_only,
                )
                return
            except Exception:
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "workflow_unavailable",
                    "Workflow history could not be loaded safely.",
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)

        def _serve_director(self, head_only: bool) -> None:
            try:
                payload = application.director_payload()
            except DirectorIntegrityError:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "director_integrity_failed",
                    "The Director session ledger failed integrity validation.",
                    head_only=head_only,
                )
                return
            except Exception:
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "director_history_unavailable",
                    "Director history could not be loaded safely.",
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)

        def _serve_product(self, head_only: bool) -> None:
            try:
                payload = application.product_payload()
            except ProductEntryIntegrityError:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "product_integrity_failed",
                    "The product session failed integrity validation.",
                    head_only=head_only,
                )
                return
            except Exception:
                self._send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "product_entry_unavailable",
                    "The product session could not be loaded safely.",
                    head_only=head_only,
                )
                return
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)

        def _serve_analysis_artifact(
            self,
            analysis_id: str,
            artifact_id: str,
            head_only: bool,
        ) -> None:
            artifact = application.analysis_artifact(
                analysis_id,
                artifact_id,
            )
            if artifact is None:
                self._send_error_json(
                    HTTPStatus.NOT_FOUND,
                    "analysis_artifact_unavailable",
                    "The requested analysis artifact is unavailable.",
                    head_only=head_only,
                )
                return
            self._send_bytes(
                HTTPStatus.OK,
                artifact.content,
                artifact.content_type,
                head_only=head_only,
                cache_control="private, max-age=3600, immutable",
            )

        def _serve_media(self, source_id: str, head_only: bool) -> None:
            try:
                resolved = application.resolve_media(source_id)
            except Exception:
                resolved = None
            if resolved is None:
                self._send_error_json(
                    HTTPStatus.NOT_FOUND,
                    "media_unavailable",
                    "The source is unavailable or outside allowlisted roots.",
                    head_only=head_only,
                )
                return

            start = 0
            end = resolved.size - 1
            status = HTTPStatus.OK
            range_header = self.headers.get("Range")
            if range_header is not None:
                byte_range = _parse_range(range_header, resolved.size)
                if byte_range is None:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self._security_headers()
                    self.send_header("Cache-Control", "no-store")
                    self.send_header(
                        "Content-Range",
                        f"bytes */{resolved.size}",
                    )
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start, end = byte_range
                status = HTTPStatus.PARTIAL_CONTENT

            content_length = max(0, end - start + 1)
            self.send_response(status)
            self._security_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", resolved.content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(content_length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header(
                    "Content-Range",
                    f"bytes {start}-{end}/{resolved.size}",
                )
            self.end_headers()
            if head_only:
                return
            try:
                with resolved.path.open("rb") as media_file:
                    media_file.seek(start)
                    remaining = content_length
                    while remaining:
                        chunk = media_file.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _read(self, head_only: bool) -> None:
            route = unquote(urlsplit(self.path).path)
            if self._serve_static(route, head_only):
                return
            if route == "/api/snapshot":
                self._serve_snapshot(head_only)
                return
            if route == "/api/subtitles/export":
                self._serve_subtitle_export(head_only)
                return
            if route == "/api/analysis":
                self._serve_analysis(head_only)
                return
            if route == "/api/plan-review":
                self._serve_plan_review(head_only)
                return
            if route == "/api/workflow":
                self._serve_workflow(head_only)
                return
            if route == "/api/director":
                self._serve_director(head_only)
                return
            if route == "/api/product":
                self._serve_product(head_only)
                return
            if route.startswith("/analysis/thumbnail/"):
                parts = route.split("/")
                if len(parts) == 5:
                    self._serve_analysis_artifact(
                        parts[3],
                        parts[4],
                        head_only,
                    )
                    return
            if route.startswith("/media/"):
                source_id = route.removeprefix("/media/")
                if "/" not in source_id:
                    self._serve_media(source_id, head_only)
                    return
            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                "not_found",
                "The requested preview route does not exist.",
                head_only=head_only,
            )

        def _read_json_body(self) -> dict[str, Any] | None:
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip() != "application/json":
                self._send_error_json(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "json_required",
                    "Manual edit requests require application/json.",
                )
                return None
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length <= 0:
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "body_required",
                    "A JSON request body is required.",
                )
                return None
            if content_length > 128 * 1024:
                self._send_error_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "body_too_large",
                    "Manual edit request exceeds 128 KiB.",
                )
                return None
            try:
                payload = json.loads(
                    self.rfile.read(content_length).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_json",
                    "Request body must be valid UTF-8 JSON.",
                )
                return None
            if not isinstance(payload, dict):
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "object_required",
                    "Request body must be a JSON object.",
                )
                return None
            return payload

        def _manual_edit(self, route: str) -> None:
            payload = self._read_json_body()
            if payload is None:
                return
            if route == "/api/subtitles/parse":
                try:
                    result = application.parse_subtitle_payload(payload)
                except (SubtitleCodecError, TypeError, ValueError) as exc:
                    self._send_error_json(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        "subtitle_parse_rejected",
                        str(exc),
                    )
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            if application.manual_edits is None:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "manual_edit_disabled",
                    "Manual apply is available only for current workspace state.",
                )
                return
            try:
                if route == "/api/manual-edits/validate":
                    proposal, review = application.manual_edits.review(
                        payload.get("proposal")
                    )
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "persisted": False,
                            "proposal": proposal.model_dump(mode="json"),
                            "review": review.model_dump(mode="json"),
                        },
                    )
                    return
                if route == "/api/manual-edits/apply":
                    result = application.manual_edits.apply(
                        payload.get("proposal"),
                        payload.get("confirmation"),
                    )
                    self._send_json(HTTPStatus.OK, result)
                    return
                if route == "/api/audio/loudness/analyze":
                    result = application.manual_edits.analyze_loudness(payload)
                    self._send_json(HTTPStatus.OK, result)
                    return
            except ManualEditValidationError as exc:
                self._send_error_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_manual_edit",
                    str(exc),
                )
                return
            except (TypeError, ValueError) as exc:
                self._send_error_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "manual_edit_rejected",
                    str(exc),
                )
                return
            except Exception:
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "manual_edit_failed",
                    "The confirmed manual edit could not be applied.",
                )
                return
            self._reject_write()

        def _workflow(self, route: str) -> None:
            payload = self._read_json_body()
            if payload is None:
                return
            try:
                result = application.workflow_action(route, payload)
            except WorkflowApplicationError as exc:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "workflow_transition_rejected",
                    str(exc),
                )
                return
            except WorkflowIntegrityError:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "workflow_integrity_failed",
                    "The workflow ledger failed integrity validation.",
                )
                return
            except (TypeError, ValueError) as exc:
                self._send_error_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_workflow_transition",
                    str(exc),
                )
                return
            except Exception:
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "workflow_transition_failed",
                    "The workflow transition failed and was not reported as "
                    "successful.",
                )
                return
            self._send_json(HTTPStatus.OK, result)

        def _product(self) -> None:
            if application.product_entry is None:
                self._send_error_json(
                    HTTPStatus.NOT_FOUND,
                    "product_entry_unavailable",
                    "The production entry service is not configured.",
                )
                return
            token = self.headers.get("X-Vistora-CSRF", "")
            if not secrets.compare_digest(
                token,
                application.product_csrf_token,
            ):
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "csrf_rejected",
                    "The product action did not include the session token.",
                )
                return
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).hostname not in LOOPBACK_HOSTS:
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "origin_rejected",
                    "Product actions are accepted only from loopback.",
                )
                return
            payload = self._read_json_body()
            if payload is None:
                return
            try:
                result = application.product_action(payload)
            except ProductEntryConcurrencyError as exc:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "product_state_stale",
                    str(exc),
                )
                return
            except ProductEntryIntegrityError:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    "product_integrity_failed",
                    "The product session failed integrity validation.",
                )
                return
            except (ProductEntryError, TypeError, ValueError) as exc:
                self._send_error_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_product_action",
                    str(exc),
                )
                return
            except Exception:
                self._send_error_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "product_action_failed",
                    "The action failed and was not reported as successful.",
                )
                return
            self._send_json(HTTPStatus.OK, result)

        def do_GET(self) -> None:
            self._read(head_only=False)

        def do_HEAD(self) -> None:
            self._read(head_only=True)

        def do_POST(self) -> None:
            route = unquote(urlsplit(self.path).path)
            if route == "/api/product/actions":
                self._product()
                return
            if route in {
                "/api/manual-edits/validate",
                "/api/manual-edits/apply",
                "/api/audio/loudness/analyze",
                "/api/subtitles/parse",
            }:
                self._manual_edit(route)
                return
            if route in {
                "/api/workflow/reviews",
                "/api/workflow/confirmations",
                "/api/workflow/executions",
                "/api/workflow/rollbacks/reviews",
                "/api/workflow/rollbacks/confirmations",
                "/api/workflow/rollbacks/runs",
            }:
                self._workflow(route)
                return
            # Consume a bounded JSON body before closing an unsupported POST;
            # this keeps Windows' HTTP stack from resetting the connection.
            if self.headers.get("Content-Length"):
                if self._read_json_body() is None:
                    return
            self._reject_write()

        def _reject_write(self) -> None:
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self._security_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            content = (
                b'{"error":{"code":"read_only","message":'
                b'"The timeline preview has no write routes."}}'
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_PUT = _reject_write
        do_PATCH = _reject_write
        do_DELETE = _reject_write

    return PreviewRequestHandler


def create_preview_server(
    application: PreviewApplication,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise PreviewConfigurationError(
            "The preview server may bind only to localhost or a loopback IP."
        )
    if not 0 <= port <= 65535:
        raise PreviewConfigurationError("Port must be between 0 and 65535.")
    server_class = (
        _IPv6ThreadingHTTPServer
        if host == "::1"
        else ThreadingHTTPServer
    )
    return server_class((host, port), _handler_class(application))


def _snapshot_provider(
    timeline_path: str | Path | None,
) -> Callable[[], TimelineSnapshot]:
    if timeline_path is None:
        return TimelineSnapshotService.snapshot_current
    path = Path(timeline_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise PreviewConfigurationError(
            f"Timeline path is not a file: {timeline_path}"
        )

    def load_timeline_snapshot() -> TimelineSnapshot:
        with path.open("r", encoding="utf-8") as timeline_file:
            data = json.load(timeline_file)
        return TimelineSnapshotService.snapshot(
            data,
            trace_document=TraceabilityStore.load(path),
        )

    return load_timeline_snapshot


def _plan_review_provider(
    plan_review_path: str | Path | None,
) -> Callable[[], PlanDiffRequest] | None:
    if plan_review_path is None:
        return None
    path = Path(plan_review_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise PreviewConfigurationError(
            f"Plan-review path is not a file: {plan_review_path}"
        )
    try:
        request = load_plan_diff_request(path)
    except Exception as exc:
        raise PreviewConfigurationError(
            "Plan-review fixture is not a valid versioned request"
        ) from exc
    return lambda: request


def _director_history_provider(
    director_history_path: str | Path | None,
) -> Callable[[], DirectorHistoryView] | None:
    if director_history_path is None:
        return None
    path = Path(director_history_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise PreviewConfigurationError(
            f"Director history path is not a file: {director_history_path}"
        )

    def load_history() -> DirectorHistoryView:
        try:
            ledger = DirectorSessionLedger.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise DirectorIntegrityError(
                "Director history fixture failed validation"
            ) from exc
        return DirectorHistoryQuery.project(ledger)

    load_history()
    return load_history


def run_preview_server(
    *,
    timeline_path: str | Path | None = None,
    media_roots: Iterable[str | Path] = (),
    host: str = "127.0.0.1",
    port: int = 8765,
    skill_registry: Mapping[str, Any] | None = None,
    plan_review_path: str | Path | None = None,
    director_history_path: str | Path | None = None,
    product_entry_service: ProductionEntryService | None = None,
    plan_review_request_provider: Callable[
        [], PlanDiffRequest
    ] | None = None,
    director_history_provider: Callable[
        [], DirectorHistoryView
    ] | None = None,
) -> None:
    """Run the blocking local preview server until interrupted."""

    application = PreviewApplication(
        _snapshot_provider(timeline_path),
        media_roots,
        skill_registry=skill_registry,
        manual_edits_enabled=(
            timeline_path is None and skill_registry is not None
        ),
        plan_review_request_provider=(
            plan_review_request_provider
            or _plan_review_provider(plan_review_path)
        ),
        workflow_service=(
            WorkflowApplicationService.for_current_project(skill_registry)
            if timeline_path is None and skill_registry is not None
            else None
        ),
        director_history_provider=(
            director_history_provider
            or _director_history_provider(director_history_path)
        ),
        product_entry_service=product_entry_service,
    )
    server = create_preview_server(application, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    display_host = f"[{bound_host}]" if ":" in bound_host else bound_host
    print(
        f"Vistora snapshot-first timeline preview: "
        f"http://{display_host}:{bound_port}"
    )
    print(
        f"Media roots allowlisted: {application.media_resolver.root_count}. "
        "Press Ctrl+C to stop."
    )
    print(
        "Manual apply: "
        + (
            "enabled through the atomic skill registry."
            if application.manual_edits is not None
            else "disabled for an external timeline document."
        )
    )
    print(
        "Director plan review: "
        + (
            "fixture loaded; review is read-only until explicitly persisted "
            "and confirmed in workflow history."
            if application.plan_review_enabled
            else "unavailable (no fixture supplied)."
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
