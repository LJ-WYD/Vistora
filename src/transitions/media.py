"""Read-only transition media facts with browser-safe failures."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from core import timeline_manager
from core.timeline import ClipConfig
from material_production import MaterialCatalogStore
from timeline_edit import TimelineEditError


def resolve_transition_source(source: str) -> Path:
    if source.startswith("material://"):
        resolved = MaterialCatalogStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ).resolve_uri(source)
        if resolved is None:
            raise TimelineEditError(
                "Catalog material is unavailable, unaccepted, or tampered"
            )
        return Path(resolved)
    candidate = Path(source)
    if not candidate.is_file():
        raise TimelineEditError("Configured transition media is unavailable")
    return candidate


def probe_source_duration(clip: ClipConfig) -> float:
    source = resolve_transition_source(clip.source)
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", os.fspath(source),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise TimelineEditError("Configured transition media cannot be probed")
    try:
        duration = float(json.loads(completed.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TimelineEditError(
            "Configured transition media has no reliable duration"
        ) from exc
    if duration <= 0:
        raise TimelineEditError(
            "Configured transition media has no positive duration"
        )
    return duration


def probe_source_has_audio(clip: ClipConfig) -> bool:
    """Return exact stream availability without exposing the resolved path."""

    source = resolve_transition_source(clip.source)
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "json",
            os.fspath(source),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise TimelineEditError("Configured transition media cannot be probed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise TimelineEditError(
            "Configured transition media facts are invalid"
        ) from exc
    return bool(payload.get("streams"))
