"""Read-only staged-artifact validation before catalog acceptance."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from creation_planning import MaterialProductionTask

from .models import ArtifactCandidate, ArtifactValidation


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class ArtifactValidator:
    def __init__(
        self,
        staging_root: str | Path,
        *,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
        max_size_bytes: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        self.staging_root = Path(staging_root)
        self.clock = clock
        self.id_factory = id_factory
        self.max_size_bytes = max_size_bytes

    def resolve(self, candidate: ArtifactCandidate) -> Path:
        root = self.staging_root.resolve()
        target = (
            root / candidate.staging_relative_path
        ).resolve()
        if root not in target.parents:
            raise ValueError("Artifact path escapes isolated staging")
        return target

    def validate(
        self,
        candidate: ArtifactCandidate,
        *,
        run_id: str,
        job_id: str,
        task: MaterialProductionTask,
    ) -> ArtifactValidation:
        issues = []
        if (
            candidate.job_id != job_id
            or candidate.task_id != task.task_id
            or candidate.requirement_item_id != task.requirement_item_id
        ):
            return self._failed(
                candidate,
                run_id,
                ("Artifact linkage does not match the submitted task.",),
            )
        target = self.resolve(candidate)
        if not target.is_file():
            return self._failed(
                candidate,
                run_id,
                ("Staged artifact is missing.",),
            )
        size = target.stat().st_size
        if size <= 0:
            issues.append("Staged artifact is empty.")
        if size > self.max_size_bytes:
            issues.append("Staged artifact exceeds the configured size limit.")
        mime_type = (
            mimetypes.guess_type(target.name)[0]
            or "application/octet-stream"
        )
        if mime_type != task.delivery.mime_type:
            issues.append(
                "Artifact MIME type does not match the production plan."
            )
        if candidate.claimed_mime_type != task.delivery.mime_type:
            issues.append(
                "Adapter MIME claim does not match the production plan."
            )
        expected_suffix = task.delivery.container_or_extension.lower()
        if not expected_suffix.startswith("."):
            expected_suffix = "." + expected_suffix
        if target.suffix.lower() != expected_suffix:
            issues.append(
                "Artifact file extension does not match the production plan."
            )
        hasher = hashlib.sha256()
        with target.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
        sha256 = "sha256:" + hasher.hexdigest()
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    (
                        "stream=codec_type,codec_name,width,height,"
                        "r_frame_rate"
                    ),
                    "-show_entries",
                    "format=format_name,duration,size",
                    "-of",
                    "json",
                    str(target),
                ],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(probe.stdout)
        except Exception:
            return self._failed(
                candidate,
                run_id,
                (*issues, "ffprobe could not decode the staged artifact."),
            )
        streams = payload.get("streams", [])
        videos = [
            stream
            for stream in streams
            if stream.get("codec_type") == "video"
        ]
        audios = [
            stream
            for stream in streams
            if stream.get("codec_type") == "audio"
        ]
        video = videos[0] if videos else {}
        audio = audios[0] if audios else {}
        duration = float(payload.get("format", {}).get("duration", 0) or 0)
        width = int(video.get("width", 0) or 0) or None
        height = int(video.get("height", 0) or 0) or None
        fps = self._fps(video.get("r_frame_rate")) if video else None
        if task.delivery.media_kind == "video" and len(videos) != 1:
            issues.append("Video delivery requires exactly one video stream.")
        if task.delivery.media_kind == "audio" and not audios:
            issues.append("Audio delivery requires an audio stream.")
        if (
            task.duration_seconds is not None
            and abs(duration - task.duration_seconds) > 0.2
        ):
            issues.append("Artifact duration is outside plan tolerance.")
        if task.width is not None and width != task.width:
            issues.append("Artifact width does not match the production plan.")
        if task.height is not None and height != task.height:
            issues.append("Artifact height does not match the production plan.")
        if (
            task.fps is not None
            and (fps is None or abs(fps - task.fps) > 0.01)
        ):
            issues.append("Artifact frame rate does not match the plan.")
        if issues:
            return self._failed(candidate, run_id, tuple(issues))
        return ArtifactValidation(
            validation_id=self.id_factory("artifact_validation"),
            artifact_id=candidate.artifact_id,
            run_id=run_id,
            job_id=candidate.job_id,
            task_id=candidate.task_id,
            requirement_item_id=candidate.requirement_item_id,
            passed=True,
            sha256=sha256,
            size_bytes=size,
            mime_type=mime_type,
            container=payload.get("format", {}).get("format_name"),
            video_codec=video.get("codec_name"),
            audio_codec=audio.get("codec_name"),
            duration_seconds=duration or None,
            width=width,
            height=height,
            fps=fps,
            has_audio=bool(audios),
            validated_at=self.clock(),
        )

    def _failed(self, candidate, run_id, issues):
        return ArtifactValidation(
            validation_id=self.id_factory("artifact_validation"),
            artifact_id=candidate.artifact_id,
            run_id=run_id,
            job_id=candidate.job_id,
            task_id=candidate.task_id,
            requirement_item_id=candidate.requirement_item_id,
            passed=False,
            issues=tuple(dict.fromkeys(issues)),
            validated_at=self.clock(),
        )

    @staticmethod
    def _fps(value):
        if not value:
            return None
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return (
            float(numerator) / denominator_value
            if denominator_value
            else None
        )
