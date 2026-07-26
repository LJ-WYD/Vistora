"""Durable append-only persistence for timeline provenance sidecars."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from core import timeline_manager

from .models import (
    ConfirmedAtomicTrace,
    ManualEditTrace,
    TimelineTraceDocument,
)


class TraceabilityStore:
    """Persist provenance beside, but never inside, the legacy timeline JSON."""

    @staticmethod
    def trace_path(project_file: str | Path | None = None) -> Path:
        path = Path(project_file or timeline_manager.PROJECT_FILE)
        return path.with_name(f"{path.stem}.trace.json")

    @classmethod
    def load(
        cls,
        project_file: str | Path | None = None,
    ) -> TimelineTraceDocument:
        path = cls.trace_path(project_file)
        if not path.exists():
            return TimelineTraceDocument()
        return TimelineTraceDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    @classmethod
    def next_sequence(
        cls,
        project_file: str | Path | None = None,
    ) -> int:
        current = cls.load(project_file)
        return len(current.confirmed_traces) + len(current.manual_traces) + 1

    @classmethod
    def append_confirmed(
        cls,
        trace: ConfirmedAtomicTrace,
        project_file: str | Path | None = None,
    ) -> TimelineTraceDocument:
        current = cls.load(project_file)
        expected = len(current.confirmed_traces) + len(current.manual_traces) + 1
        if trace.trace_sequence != expected:
            raise ValueError(
                f"Confirmed trace sequence must be {expected}, received "
                f"{trace.trace_sequence}"
            )
        updated = TimelineTraceDocument.model_validate(
            current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "confirmed_traces": (*current.confirmed_traces, trace),
                }
            ).model_dump(mode="python")
        )
        cls._atomic_save(updated, project_file)
        return updated

    @classmethod
    def append_manual(
        cls,
        trace: ManualEditTrace,
        project_file: str | Path | None = None,
    ) -> TimelineTraceDocument:
        current = cls.load(project_file)
        expected = len(current.confirmed_traces) + len(current.manual_traces) + 1
        if trace.trace_sequence != expected:
            raise ValueError(
                f"Manual trace sequence must be {expected}, received "
                f"{trace.trace_sequence}"
            )
        updated = TimelineTraceDocument.model_validate(
            current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "manual_traces": (*current.manual_traces, trace),
                }
            ).model_dump(mode="python")
        )
        cls._atomic_save(updated, project_file)
        return updated

    @classmethod
    def _atomic_save(
        cls,
        document: TimelineTraceDocument,
        project_file: str | Path | None = None,
    ) -> None:
        path = cls.trace_path(project_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open(
                "x",
                encoding="utf-8",
                newline="\n",
            ) as output:
                output.write(document.model_dump_json(indent=2))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
