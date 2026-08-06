"""Read-only FFmpeg/ffprobe finished-media QC for original O31."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from .models import (
    DeliveryMediaProbe,
    DeliveryQCCheck,
    DeliveryQCReport,
    DeliveryQCRequest,
)


class DeliveryQCError(ValueError):
    pass


class DeliveryQCService:
    def __init__(self, *, allowlisted_roots, runner=subprocess.run, cache_size=16):
        self.roots = tuple(Path(item).resolve(strict=True) for item in allowlisted_roots)
        self.runner = runner
        self.cache_size = max(1, min(int(cache_size), 128))
        self._cache = {}

    def _resolve(self, source_path):
        path = Path(source_path).resolve(strict=True)
        if not path.is_file() or not any(path == root or root in path.parents for root in self.roots):
            raise DeliveryQCError("QC source is outside the allowlisted media roots")
        return path

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    def _command(self, arguments):
        try:
            return self.runner(arguments, capture_output=True, text=True, timeout=120)
        except Exception as exc:
            raise DeliveryQCError("Media QC backend failed without a safe diagnostic") from exc

    @staticmethod
    def _rate(value):
        try:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator)
        except (AttributeError, ValueError, ZeroDivisionError):
            return None

    def _probe(self, path):
        result = self._command([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
        ])
        if result.returncode != 0:
            raise DeliveryQCError("Media probe failed")
        try:
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            video = next((item for item in streams if item.get("codec_type") == "video"), None)
            audios = [item for item in streams if item.get("codec_type") == "audio"]
            subtitles = [item for item in streams if item.get("codec_type") == "subtitle"]
            duration = float(payload.get("format", {}).get("duration", 0))
            return DeliveryMediaProbe(
                duration_seconds=max(0, duration),
                width=video.get("width") if video else None,
                height=video.get("height") if video else None,
                frame_rate=self._rate(video.get("avg_frame_rate")) if video else None,
                video_codec=video.get("codec_name") if video else None,
                audio_codecs=tuple(sorted(str(item.get("codec_name")) for item in audios)),
                audio_streams=len(audios),
                subtitle_streams=len(subtitles),
                sample_rates=tuple(sorted(int(item["sample_rate"]) for item in audios if item.get("sample_rate"))),
                channel_counts=tuple(sorted(int(item["channels"]) for item in audios if item.get("channels"))),
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise DeliveryQCError("Media probe returned malformed metadata") from exc

    def _detect(self, path, filter_name):
        result = self._command(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vf", filter_name, "-an", "-f", "null", os.devnull])
        return result.returncode, result.stderr

    def _loudness(self, path, profile):
        result = self._command([
            "ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af",
            f"loudnorm=I={profile.target_lufs}:TP={profile.maximum_true_peak_dbtp}:LRA=7:print_format=json",
            "-f", "null", os.devnull,
        ])
        matches = re.findall(r"\{[^{}]*\}", result.stderr, flags=re.DOTALL)
        for candidate in reversed(matches):
            try:
                payload = json.loads(candidate)
                if "input_i" in payload and "input_tp" in payload:
                    return result.returncode, float(payload["input_i"]), float(payload["input_tp"])
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return result.returncode, None, None

    def analyze(self, request: DeliveryQCRequest, *, source_path):
        path = self._resolve(source_path)
        content_digest = self._sha256(path)
        if content_digest != request.expected_content_digest:
            raise DeliveryQCError("QC source content changed; regenerate the request")
        cache_key = (request.digest(), content_digest)
        if cache_key in self._cache:
            return self._cache[cache_key]
        checks = []
        try:
            probe = self._probe(path)
        except DeliveryQCError:
            probe = None
            checks = [DeliveryQCCheck(
                check_id=check_id,
                status="failed" if check_id == "full_decode" else "not_applicable",
                message="Media metadata is unavailable; this check cannot claim success.",
            ) for check_id in (
                "audio_tracks", "black_frames", "codec", "duration", "frame_size",
                "freeze_frames", "full_decode", "loudness", "subtitles",
                "subtitle_sync",
            )]
            return self._finish(request, content_digest, probe, checks, cache_key)
        profile = request.profile
        duration_ok = probe.duration_seconds >= profile.minimum_duration_seconds and (
            profile.maximum_duration_seconds is None or probe.duration_seconds <= profile.maximum_duration_seconds
        )
        checks.append(DeliveryQCCheck(check_id="duration", status="passed" if duration_ok else "failed", message="Duration is within the confirmed QC range." if duration_ok else "Duration is outside the confirmed QC range.", observed={"seconds": probe.duration_seconds}))
        size_ok = probe.width is not None and probe.height is not None and (
            profile.expected_width is None or probe.width == profile.expected_width
        ) and (profile.expected_height is None or probe.height == profile.expected_height)
        checks.append(DeliveryQCCheck(check_id="frame_size", status="passed" if size_ok else "failed", message="Frame dimensions match the QC profile." if size_ok else "Frame dimensions are missing or mismatched.", observed={"width": probe.width, "height": probe.height, "aspect_ratio": (probe.width / probe.height) if probe.width and probe.height else None}))
        video_ok = probe.video_codec in profile.allowed_video_codecs
        audio_codec_ok = all(codec in profile.allowed_audio_codecs for codec in probe.audio_codecs)
        checks.append(DeliveryQCCheck(check_id="codec", status="passed" if video_ok and audio_codec_ok else "failed", message="Video and audio codecs are allowed." if video_ok and audio_codec_ok else "A media codec is missing or not allowed.", observed={"video": probe.video_codec, "audio": list(probe.audio_codecs)}))
        audio_ok = profile.minimum_audio_streams <= probe.audio_streams <= profile.maximum_audio_streams and (not profile.require_audio or probe.audio_streams > 0)
        checks.append(DeliveryQCCheck(check_id="audio_tracks", status="passed" if audio_ok else "failed", message="Audio stream count matches the QC profile." if audio_ok else "Audio stream count is outside the QC profile.", observed={"count": probe.audio_streams, "sample_rates": list(probe.sample_rates), "channels": list(probe.channel_counts)}))
        black_code, black_log = self._detect(path, f"blackdetect=d={profile.black_duration_threshold_seconds}:pix_th=0.10")
        black_count = len(re.findall(r"black_start:", black_log))
        checks.append(DeliveryQCCheck(check_id="black_frames", status="failed" if black_code else "warning" if black_count else "passed", message="Black-frame intervals were detected." if black_count else "No threshold-length black interval was detected.", observed={"intervals": black_count, "threshold_seconds": profile.black_duration_threshold_seconds}))
        freeze_code, freeze_log = self._detect(path, f"freezedetect=n=-60dB:d={profile.freeze_duration_threshold_seconds}")
        freeze_count = len(re.findall(r"freeze_start:", freeze_log))
        checks.append(DeliveryQCCheck(check_id="freeze_frames", status="failed" if freeze_code else "warning" if freeze_count else "passed", message="Static/freeze intervals were detected." if freeze_count else "No threshold-length freeze interval was detected.", observed={"intervals": freeze_count, "threshold_seconds": profile.freeze_duration_threshold_seconds}))
        if probe.audio_streams:
            loud_code, lufs, peak = self._loudness(path, profile)
            loud_ok = loud_code == 0 and lufs is not None and peak is not None and abs(lufs - profile.target_lufs) <= profile.loudness_tolerance_lu and peak <= profile.maximum_true_peak_dbtp
            checks.append(DeliveryQCCheck(check_id="loudness", status="passed" if loud_ok else "warning" if lufs is not None else "failed", message="Integrated loudness and true peak meet the profile." if loud_ok else "Loudness or true peak needs review.", observed={"integrated_lufs": lufs, "true_peak_dbtp": peak, "target_lufs": profile.target_lufs}))
        else:
            checks.append(DeliveryQCCheck(check_id="loudness", status="failed" if profile.require_audio else "not_applicable", message="No audio stream is available for loudness analysis."))
        cues = sorted(request.subtitle_cues, key=lambda item: (item.start_seconds, item.end_seconds, item.cue_id))
        overlap = any(current.start_seconds < previous.end_seconds for previous, current in zip(cues, cues[1:]))
        unsafe = sum(item.safe_area_status == "failed" for item in cues)
        subtitles_present = bool(cues) or probe.subtitle_streams > 0
        subtitle_ok = (not profile.require_subtitles or subtitles_present) and not overlap and not unsafe
        checks.append(DeliveryQCCheck(check_id="subtitles", status="passed" if subtitle_ok else "failed", message="Subtitle presence, timing and safe-area evidence pass." if subtitle_ok else "Subtitles are missing, overlapping or outside the safe area.", observed={"cue_count": len(cues), "stream_count": probe.subtitle_streams, "overlaps": overlap, "unsafe_cues": unsafe}))
        sync = request.subtitle_sync_evidence
        if sync is None:
            checks.append(DeliveryQCCheck(
                check_id="subtitle_sync",
                status="failed" if profile.require_subtitle_sync else "not_applicable",
                message=(
                    "Passed narration-to-caption synchronization evidence is required."
                    if profile.require_subtitle_sync else
                    "This QC profile does not require narration-to-caption synchronization evidence."
                ),
            ))
        else:
            checks.append(DeliveryQCCheck(
                check_id="subtitle_sync", status="passed" if sync.status == "passed" else "failed",
                message="Narration, timed words, and final audio mux are synchronized." if sync.status == "passed" else "Narration-to-caption synchronization failed.",
                observed={
                    "sync_qc_id": sync.sync_qc_id,
                    "maximum_timeline_error_seconds": sync.maximum_timeline_error_seconds,
                    "audio_mux_offset_seconds": sync.audio_mux_offset_seconds,
                    "audio_correlation": sync.audio_correlation,
                },
            ))
        decode = self._command(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0", "-f", "null", os.devnull])
        checks.append(DeliveryQCCheck(check_id="full_decode", status="passed" if decode.returncode == 0 else "failed", message="Every encoded stream decoded completely." if decode.returncode == 0 else "Complete media decode failed."))
        return self._finish(request, content_digest, probe, checks, cache_key)

    def _finish(self, request, content_digest, probe, checks, cache_key):
        checks = tuple(sorted(checks, key=lambda item: item.check_id))
        statuses = {item.status for item in checks}
        status = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
        report = DeliveryQCReport.create(
            report_id=f"qc_report_{request.digest()[7:31]}",
            request_digest=request.digest(),
            project_id=request.project_id,
            project_revision=request.project_revision,
            asset_id=request.asset_id,
            source_content_digest=content_digest,
            profile_id=request.profile.profile_id,
            status=status,
            probe=probe,
            checks=checks,
            browser_safe=True,
        )
        if len(self._cache) >= self.cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = report
        return report
