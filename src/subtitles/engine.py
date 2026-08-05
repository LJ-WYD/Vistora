"""Deterministic detached subtitle editing and explicit ripple semantics."""

from __future__ import annotations

from collections.abc import Iterable

from core.timeline import SubtitleCue, SubtitleStyle, SubtitleTrackConfig, TimelineConfig

from .models import SubtitleEditCueInput, SubtitleEditOutcome, SubtitleManageTrackInput, SubtitleRipplePolicy


EPSILON = 1e-6


class SubtitleEditError(ValueError):
    pass


class SubtitleEditEngine:
    def __init__(self, timeline: TimelineConfig) -> None:
        self.timeline = timeline.model_copy(deep=True)

    def _find_track(self, track_id: str, *, allow_locked: bool = False) -> tuple[str, SubtitleTrackConfig]:
        matches = [(key, track) for key, track in self.timeline.subtitle_tracks.items() if track.track_id == track_id or key == track_id]
        if len(matches) != 1:
            raise SubtitleEditError(f"subtitle track {track_id!r} must identify exactly one track")
        key, track = matches[0]
        if track.locked and not allow_locked:
            raise SubtitleEditError(f"Subtitle track {track.track_id!r} is locked")
        return key, track

    def _replace_track(self, key: str, track: SubtitleTrackConfig) -> None:
        values = dict(self.timeline.subtitle_tracks)
        values[key] = SubtitleTrackConfig.model_validate(track.model_dump(mode="python"))
        self.timeline.subtitle_tracks = values

    def _finish(self, outcome: SubtitleEditOutcome) -> tuple[TimelineConfig, SubtitleEditOutcome]:
        self.timeline = TimelineConfig.model_validate(self.timeline.model_dump(mode="python"))
        return self.timeline, outcome

    def manage_track(self, params: SubtitleManageTrackInput) -> tuple[TimelineConfig, SubtitleEditOutcome]:
        if params.action == "create":
            if any(track.track_id == params.track_id for track in self.timeline.subtitle_tracks.values()):
                raise SubtitleEditError("Subtitle track ID already exists")
            order = params.order if params.order is not None else max((track.order for track in self.timeline.subtitle_tracks.values()), default=-1) + 1
            if any(track.order == order for track in self.timeline.subtitle_tracks.values()):
                raise SubtitleEditError("Subtitle track order already exists")
            track = SubtitleTrackConfig(
                track_id=params.track_id,
                kind=params.kind or "subtitle",
                role=params.role or "captions",
                language=params.language or "und",
                order=order,
                enabled=True if params.enabled is None else params.enabled,
                locked=False if params.locked is None else params.locked,
                allow_overlaps=False if params.allow_overlaps is None else params.allow_overlaps,
                style=params.style or SubtitleStyle(),
            )
            self.timeline.subtitle_tracks = {**self.timeline.subtitle_tracks, params.track_id: track}
            return self._finish(SubtitleEditOutcome(operation="create_track", track_id=params.track_id, created_track_ids=(params.track_id,)))

        key, track = self._find_track(params.track_id, allow_locked=True)
        if track.locked:
            if params.action != "update" or params.locked is not False or any(
                value is not None
                for value in (
                    params.kind,
                    params.role,
                    params.language,
                    params.order,
                    params.enabled,
                    params.allow_overlaps,
                    params.style,
                )
            ):
                raise SubtitleEditError(
                    "Locked subtitle track accepts only an explicit unlock"
                )
        if params.action == "delete":
            values = dict(self.timeline.subtitle_tracks)
            values.pop(key)
            self.timeline.subtitle_tracks = values
            return self._finish(SubtitleEditOutcome(
                operation="delete_track",
                track_id=track.track_id,
                deleted_track_ids=(track.track_id,),
                deleted_cue_ids=tuple(cue.cue_id for cue in track.cues),
            ))
        values = track.model_dump(mode="python")
        for field in ("kind", "role", "language", "order", "enabled", "locked", "allow_overlaps", "style"):
            value = getattr(params, field)
            if value is not None:
                values[field] = value
        if values == track.model_dump(mode="python"):
            raise SubtitleEditError("Subtitle track update changes no fields")
        if params.order is not None and any(other.track_id != track.track_id and other.order == params.order for other in self.timeline.subtitle_tracks.values()):
            raise SubtitleEditError("Subtitle track order already exists")
        self._replace_track(key, SubtitleTrackConfig.model_validate(values))
        return self._finish(SubtitleEditOutcome(operation="update_track", track_id=track.track_id, modified_track_ids=(track.track_id,)))

    def edit_cues(self, params: SubtitleEditCueInput) -> tuple[TimelineConfig, SubtitleEditOutcome]:
        key, track = self._find_track(params.track_id)
        cues = list(track.cues)
        by_id = {cue.cue_id: cue for cue in cues}
        direct: list[str] = []
        created: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        consequential: list[str] = []

        if params.action in {"add", "batch_add"}:
            for cue in params.cues:
                if cue.cue_id in by_id:
                    raise SubtitleEditError("Subtitle cue ID already exists")
                cues.append(cue)
                by_id[cue.cue_id] = cue
                direct.append(cue.cue_id)
                created.append(cue.cue_id)
        elif params.action == "ripple_shift":
            assert params.anchor_seconds is not None and params.delta_seconds is not None
            shifted: list[SubtitleCue] = []
            for candidate in cues:
                if candidate.start_seconds >= params.anchor_seconds - EPSILON:
                    start = candidate.start_seconds + params.delta_seconds
                    end = candidate.end_seconds + params.delta_seconds
                    if start < -EPSILON:
                        raise SubtitleEditError("Subtitle ripple would move a cue before zero")
                    word_delta = params.delta_seconds
                    shifted.append(candidate.model_copy(update={
                        "start_seconds": max(0.0, start),
                        "end_seconds": end,
                        "words": tuple(
                            word.model_copy(update={
                                "start_seconds": word.start_seconds + word_delta,
                                "end_seconds": word.end_seconds + word_delta,
                            })
                            for word in candidate.words
                        ),
                    }))
                    direct.append(candidate.cue_id)
                    modified.append(candidate.cue_id)
                else:
                    shifted.append(candidate)
            if not direct:
                raise SubtitleEditError("Subtitle ripple matches no cues")
            cues = shifted
        elif params.action == "merge":
            if len(params.merge_cue_ids) != len(set(params.merge_cue_ids)):
                raise SubtitleEditError("Merge cue IDs must be unique")
            missing = set(params.merge_cue_ids) - set(by_id)
            if missing:
                raise SubtitleEditError("Merge references a missing cue")
            ordered = sorted((by_id[cue_id] for cue_id in params.merge_cue_ids), key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id))
            indexes = sorted(cues.index(cue) for cue in ordered)
            if indexes != list(range(indexes[0], indexes[-1] + 1)):
                raise SubtitleEditError("Merge cues must be adjacent in track order")
            merged_id = params.merged_cue_id or ordered[0].cue_id
            if merged_id not in params.merge_cue_ids and merged_id in by_id:
                raise SubtitleEditError("Merged cue ID already exists")
            merged = ordered[0].model_copy(update={
                "cue_id": merged_id,
                "end_seconds": ordered[-1].end_seconds,
                "text": "\n".join(cue.text for cue in ordered),
                "words": tuple(
                    word for cue in ordered for word in cue.words
                ),
            })
            cues = [cue for cue in cues if cue.cue_id not in params.merge_cue_ids]
            cues.append(merged)
            direct.extend(params.merge_cue_ids)
            direct.append(merged_id)
            deleted.extend(cue_id for cue_id in params.merge_cue_ids if cue_id != merged_id)
            modified.append(merged_id)
        else:
            cue_id = params.cue_id
            if cue_id is None or cue_id not in by_id:
                raise SubtitleEditError("Subtitle cue does not exist")
            cue = by_id[cue_id]
            direct.append(cue_id)
            if params.action == "delete":
                cues.remove(cue)
                deleted.append(cue_id)
            elif params.action == "split":
                assert params.split_at_seconds is not None and params.right_cue_id is not None
                if not (cue.start_seconds + EPSILON < params.split_at_seconds < cue.end_seconds - EPSILON):
                    raise SubtitleEditError("Subtitle split point must be inside the cue")
                if params.right_cue_id in by_id:
                    raise SubtitleEditError("Subtitle split output ID already exists")
                if any(
                    word.start_seconds < params.split_at_seconds - EPSILON
                    and word.end_seconds > params.split_at_seconds + EPSILON
                    for word in cue.words
                ):
                    raise SubtitleEditError(
                        "Subtitle split cannot cut through a timed word"
                    )
                left = cue.model_copy(update={
                    "end_seconds": params.split_at_seconds,
                    "words": tuple(
                        word for word in cue.words
                        if word.end_seconds <= params.split_at_seconds + EPSILON
                    ),
                })
                right = cue.model_copy(update={
                    "cue_id": params.right_cue_id,
                    "start_seconds": params.split_at_seconds,
                    "words": tuple(
                        word for word in cue.words
                        if word.start_seconds >= params.split_at_seconds - EPSILON
                    ),
                })
                cues[cues.index(cue)] = left
                cues.append(right)
                direct.append(params.right_cue_id)
                modified.append(cue_id)
                created.append(params.right_cue_id)
            elif params.action == "move":
                assert params.timeline_start_seconds is not None
                duration = cue.end_seconds - cue.start_seconds
                delta = params.timeline_start_seconds - cue.start_seconds
                updated = cue.model_copy(update={
                    "start_seconds": params.timeline_start_seconds,
                    "end_seconds": params.timeline_start_seconds + duration,
                    "words": tuple(
                        word.model_copy(update={
                            "start_seconds": word.start_seconds + delta,
                            "end_seconds": word.end_seconds + delta,
                        })
                        for word in cue.words
                    ),
                })
                cues[cues.index(cue)] = updated
                modified.append(cue_id)
            elif params.action == "trim":
                assert params.start_seconds is not None and params.end_seconds is not None
                if any(
                    (
                        word.start_seconds < params.start_seconds - EPSILON
                        < word.end_seconds
                    )
                    or (
                        word.start_seconds < params.end_seconds - EPSILON
                        < word.end_seconds
                    )
                    for word in cue.words
                ):
                    raise SubtitleEditError(
                        "Subtitle trim cannot cut through a timed word"
                    )
                updated = cue.model_copy(update={
                    "start_seconds": params.start_seconds,
                    "end_seconds": params.end_seconds,
                    "words": tuple(
                        word for word in cue.words
                        if word.start_seconds >= params.start_seconds - EPSILON
                        and word.end_seconds <= params.end_seconds + EPSILON
                    ),
                })
                cues[cues.index(cue)] = updated
                modified.append(cue_id)
            elif params.action == "set_words":
                updated = cue.model_copy(update={"words": params.words or ()})
                if updated == cue:
                    raise SubtitleEditError("Subtitle word update changes no fields")
                cues[cues.index(cue)] = updated
                modified.append(cue_id)
            else:
                updates = {}
                for field, value in (
                    ("text", params.text), ("language", params.language), ("speaker", params.speaker),
                    ("enabled", params.enabled), ("start_seconds", params.start_seconds),
                    ("end_seconds", params.end_seconds), ("style", params.style),
                    ("cue_kind", params.cue_kind), ("words", params.words),
                ):
                    if value is not None:
                        updates[field] = value
                updated = cue.model_copy(update=updates)
                if updated == cue:
                    raise SubtitleEditError("Subtitle cue update changes no fields")
                cues[cues.index(cue)] = updated
                modified.append(cue_id)

        next_track = track.model_copy(update={"cues": tuple(sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id)))})
        try:
            next_track = SubtitleTrackConfig.model_validate(next_track.model_dump(mode="python"))
        except ValueError as exc:
            raise SubtitleEditError(str(exc)) from exc
        self._replace_track(key, next_track)
        return self._finish(SubtitleEditOutcome(
            operation=params.action,
            track_id=track.track_id,
            direct_cue_ids=tuple(dict.fromkeys(direct)),
            consequential_cue_ids=tuple(sorted(set(consequential))),
            created_cue_ids=tuple(dict.fromkeys(created)),
            modified_cue_ids=tuple(sorted(set(modified))),
            deleted_cue_ids=tuple(sorted(set(deleted))),
            modified_track_ids=(track.track_id,),
        ))

    def apply_ripple(self, *, anchor_seconds: float, delta_seconds: float, policy: SubtitleRipplePolicy) -> tuple[str, ...]:
        if policy.mode == "none" or abs(delta_seconds) <= EPSILON:
            return ()
        selected = set(policy.selected_track_ids)
        changed: list[str] = []
        for key, track in sorted(self.timeline.subtitle_tracks.items(), key=lambda item: (item[1].order, item[1].track_id)):
            if policy.mode == "selected_subtitle_tracks" and track.track_id not in selected:
                continue
            if track.locked:
                if policy.mode == "selected_subtitle_tracks" and track.track_id in selected:
                    raise SubtitleEditError(f"Subtitle ripple selected locked track {track.track_id!r}")
                continue
            cues = []
            for cue in track.cues:
                if cue.start_seconds >= anchor_seconds - EPSILON:
                    start = cue.start_seconds + delta_seconds
                    end = cue.end_seconds + delta_seconds
                    if start < -EPSILON:
                        raise SubtitleEditError("Subtitle ripple would move a cue before zero")
                    cues.append(cue.model_copy(update={
                        "start_seconds": max(0.0, start),
                        "end_seconds": end,
                        "words": tuple(
                            word.model_copy(update={
                                "start_seconds": word.start_seconds + delta_seconds,
                                "end_seconds": word.end_seconds + delta_seconds,
                            })
                            for word in cue.words
                        ),
                    }))
                    changed.append(cue.cue_id)
                else:
                    cues.append(cue)
            self._replace_track(key, track.model_copy(update={"cues": tuple(cues)}))
        if policy.mode == "selected_subtitle_tracks":
            known = {track.track_id for track in self.timeline.subtitle_tracks.values()}
            if selected - known:
                raise SubtitleEditError("Subtitle ripple references an unknown track")
        return tuple(sorted(set(changed)))
