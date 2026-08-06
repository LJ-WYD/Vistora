"""Deterministic local HyperFrames material-production provider.

The HeyGen plugin supplies the authoring and validation rules.  This adapter
turns those rules into a reusable Vistora provider: a confirmed production
task is compiled into a small, path-confined HyperFrames project, validated,
rendered by a pinned CLI, and returned through the normal staging/acceptance
pipeline.  It never writes the timeline or accepts arbitrary shell commands.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from director import digest_json

from .adapters import MaterialProductionAdapter, _schema_digest
from .models import (
    AdapterCapability,
    AdapterJobUpdate,
    ArtifactCandidate,
    ProductionJobRequest,
)


HYPERFRAMES_PROVIDER_VERSION = "1.0.0"
HYPERFRAMES_WORKFLOW_PARAMETER = "hyperframes_workflow_id"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HyperFramesModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class HyperFramesWorkflowSpec(HyperFramesModel):
    workflow_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]{2,127}$",
    )
    capability_ids: tuple[str, ...] = Field(min_length=1)
    default_for_capabilities: tuple[str, ...] = ()
    template_kind: Literal["kinetic_brief"] = "kinetic_brief"
    render_quality: Literal["draft", "standard", "high"] = "standard"
    min_duration_seconds: float = Field(default=2, ge=1, le=30)
    max_duration_seconds: float = Field(default=12, ge=1, le=120)
    allowed_fps: tuple[Literal[24, 30, 60], ...] = (24, 30, 60)

    @model_validator(mode="after")
    def workflow_shape(self) -> "HyperFramesWorkflowSpec":
        if (
            tuple(sorted(self.capability_ids)) != self.capability_ids
            or len(self.capability_ids) != len(set(self.capability_ids))
        ):
            raise ValueError("HyperFrames capabilities must be unique and ordered")
        if (
            tuple(sorted(self.default_for_capabilities))
            != self.default_for_capabilities
            or not set(self.default_for_capabilities).issubset(self.capability_ids)
        ):
            raise ValueError("HyperFrames defaults must be ordered and declared")
        if self.max_duration_seconds < self.min_duration_seconds:
            raise ValueError("HyperFrames duration bounds are reversed")
        if not self.allowed_fps or len(self.allowed_fps) != len(set(self.allowed_fps)):
            raise ValueError("HyperFrames FPS choices must be unique")
        return self


class HyperFramesProviderConfig(HyperFramesModel):
    schema_name: Literal["vistora.hyperframes-provider"] = (
        "vistora.hyperframes-provider"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    runtime_root: Path
    gsap_path: Path
    npx_command: Literal["npx", "npx.cmd"] = "npx.cmd"
    cli_package: str = Field(
        default="hyperframes@0.7.94",
        pattern=r"^hyperframes@[0-9]+\.[0-9]+\.[0-9]+$",
    )
    render_timeout_seconds: int = Field(default=600, ge=30, le=3600)
    require_non_system_drive: bool = True
    workflows: tuple[HyperFramesWorkflowSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def provider_shape(self) -> "HyperFramesProviderConfig":
        if self.require_non_system_drive and os.name == "nt" and self.runtime_root.is_absolute():
            system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
            if self.runtime_root.drive.casefold() == system_drive.casefold():
                raise ValueError("HyperFrames runtime must not use the system drive")
        ids = [item.workflow_id for item in self.workflows]
        if len(ids) != len(set(ids)):
            raise ValueError("HyperFrames workflow ID is duplicated")
        supported = {"motion_graphics_generation", "video_generation"}
        declared = {
            capability
            for workflow in self.workflows
            for capability in workflow.capability_ids
        }
        if not declared or declared - supported:
            raise ValueError("HyperFrames workflow capability is unsupported")
        for capability in declared:
            choices = [
                workflow
                for workflow in self.workflows
                if capability in workflow.capability_ids
            ]
            defaults = [
                workflow
                for workflow in choices
                if capability in workflow.default_for_capabilities
            ]
            if len(choices) > 1 and len(defaults) != 1:
                raise ValueError(
                    "Multiple HyperFrames workflows require exactly one default"
                )
        return self


def provider_config_path(project_file: str | Path) -> Path:
    explicit = os.environ.get("VISTORA_HYPERFRAMES_CONFIG")
    if explicit:
        return Path(explicit)
    project = Path(project_file)
    return project.with_name(f"{project.stem}.hyperframes-provider.json")


def load_hyperframes_provider_config(
    project_file: str | Path,
) -> HyperFramesProviderConfig | None:
    path = provider_config_path(project_file)
    if not path.is_file():
        return None
    try:
        config = HyperFramesProviderConfig.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        payload = config.model_dump(mode="python")
        payload.update(
            runtime_root=(
                config.runtime_root
                if config.runtime_root.is_absolute()
                else (path.parent / config.runtime_root).resolve()
            ),
            gsap_path=(
                config.gsap_path
                if config.gsap_path.is_absolute()
                else (path.parent / config.gsap_path).resolve()
            ),
        )
        return HyperFramesProviderConfig.model_validate(payload)
    except (OSError, ValueError) as exc:
        raise ValueError("HyperFrames provider configuration is invalid") from exc


class HyperFramesRunner(Protocol):
    def render(
        self,
        *,
        project_root: Path,
        output_path: Path,
        fps: int,
        workflow: HyperFramesWorkflowSpec,
        config: HyperFramesProviderConfig,
    ) -> None:
        ...


class HyperFramesCLIRunner:
    """Pinned, argument-list-only CLI runner with its cache rooted on E:."""

    def render(self, *, project_root, output_path, fps, workflow, config) -> None:
        executable = shutil.which(config.npx_command)
        if executable is None:
            raise RuntimeError("The configured HyperFrames npx executable is missing")
        temp_root = config.runtime_root / "temp"
        frame_cache = config.runtime_root / "frame-cache"
        browser_cache = config.runtime_root / "browser-cache"
        for directory in (temp_root, frame_cache, browser_cache):
            directory.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["npm_config_cache"] = str(config.runtime_root / "npm-cache")
        env["HYPERFRAMES_TELEMETRY_DISABLED"] = "1"
        env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = str(frame_cache)
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache / "playwright")
        env["PUPPETEER_CACHE_DIR"] = str(browser_cache / "puppeteer")
        env["TEMP"] = str(temp_root)
        env["TMP"] = str(temp_root)
        prefix = [executable, "--yes", config.cli_package]
        subprocess.run(
            [*prefix, "check"],
            cwd=project_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.render_timeout_seconds,
        )
        subprocess.run(
            [
                *prefix,
                "render",
                "--output",
                str(output_path),
                "--fps",
                str(fps),
                "--quality",
                workflow.render_quality,
                "--strict",
            ],
            cwd=project_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.render_timeout_seconds,
        )


class HyperFramesMaterialProductionAdapter(MaterialProductionAdapter):
    """Renders confirmed short motion-graphics tasks through HyperFrames."""

    def __init__(
        self,
        config: HyperFramesProviderConfig,
        *,
        asset_resolver: Callable[[str], Path | None],
        runner: HyperFramesRunner | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.config = config
        if not config.runtime_root.is_absolute() or not config.gsap_path.is_absolute():
            raise ValueError("Resolved HyperFrames paths must be absolute")
        self.asset_resolver = asset_resolver
        self.runner = runner or HyperFramesCLIRunner()
        self.clock = clock
        self._workflows: dict[str, dict[str, HyperFramesWorkflowSpec]] = {}
        self._defaults: dict[str, str] = {}
        for workflow in config.workflows:
            for capability in workflow.capability_ids:
                self._workflows.setdefault(capability, {})[
                    workflow.workflow_id
                ] = workflow
                if capability in workflow.default_for_capabilities:
                    self._defaults[capability] = workflow.workflow_id
        for capability, choices in self._workflows.items():
            if len(choices) == 1:
                self._defaults.setdefault(capability, next(iter(choices)))
        self.config_digest = digest_json(
            config.model_dump(
                mode="json",
                exclude={"runtime_root", "gsap_path"},
            )
        )

    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            adapter_id="hyperframes_local",
            adapter_version=(
                f"{HYPERFRAMES_PROVIDER_VERSION}+{self.config_digest[7:19]}"
            ),
            capability_ids=tuple(sorted(self._workflows)),
            configured=True,
            execution_kind="external_provider",
            max_concurrency=1,
            input_schema_digest=digest_json(
                {
                    "job": ProductionJobRequest.model_json_schema(),
                    "config": self.config_digest,
                }
            ),
            result_schema_digest=_schema_digest(AdapterJobUpdate),
        )

    def _workflow_choice(self, request: ProductionJobRequest) -> HyperFramesWorkflowSpec:
        choices = self._workflows.get(request.capability_id)
        if not choices:
            raise ValueError("HyperFrames capability is unavailable")
        requested = None
        if request.task_spec is not None:
            parameters = {
                item.name: item.value
                for item in request.task_spec.reproducibility_parameters
            }
            requested = parameters.get(HYPERFRAMES_WORKFLOW_PARAMETER)
        if requested is not None and not isinstance(requested, str):
            raise ValueError("HyperFrames workflow selector must be a workflow ID")
        workflow_id = requested or self._defaults.get(request.capability_id)
        selected = choices.get(workflow_id or "")
        if selected is None:
            raise ValueError("Requested HyperFrames workflow is unavailable")
        return selected

    @staticmethod
    def _provider_ref(request: ProductionJobRequest, workflow_id: str) -> str:
        digest = hashlib.sha256(
            f"{request.idempotency_key}:{workflow_id}".encode("utf-8")
        ).hexdigest()[:24]
        return f"hyperframes_{digest}"

    @staticmethod
    def _safe_text(value: str | None, *, fallback: str, limit: int) -> str:
        text = " ".join((value or fallback).split())[:limit]
        return html.escape(text, quote=True)

    def _source_image(self, request: ProductionJobRequest) -> Path | None:
        task = request.task_spec
        if task is None:
            return None
        for material_id in task.reference_asset_ids:
            source = self.asset_resolver(material_id)
            if source is not None and source.is_file() and source.suffix.lower() in {
                ".jpg", ".jpeg", ".png", ".webp"
            }:
                return source
        return None

    def _write_project(
        self,
        request: ProductionJobRequest,
        *,
        work_root: Path,
        duration: float,
        width: int,
        height: int,
    ) -> None:
        task = request.task_spec
        if task is None or task.prompt_spec is None:
            raise ValueError("HyperFrames generation requires a prompt specification")
        work_root.mkdir(parents=True, exist_ok=True)
        vendor = work_root / "vendor"
        vendor.mkdir(exist_ok=True)
        shutil.copyfile(self.config.gsap_path, vendor / "gsap.min.js")
        source = self._source_image(request)
        background = ""
        if source is not None:
            assets = work_root / "assets"
            assets.mkdir(exist_ok=True)
            copied = assets / f"reference{source.suffix.lower()}"
            shutil.copyfile(source, copied)
            background = (
                '<img class="source" src="./assets/' + copied.name + '" alt="" />'
            )
        prompt = task.prompt_spec
        title = self._safe_text(prompt.subject, fallback=task.title, limit=70)
        body = self._safe_text(
            prompt.action or prompt.scene,
            fallback=task.purpose,
            limit=180,
        )
        kicker = self._safe_text(
            prompt.style or prompt.camera,
            fallback="Vistora motion brief",
            limit=70,
        )
        duration_json = json.dumps(round(duration, 3))
        index = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8" />
<meta name="viewport" content="width={width}, height={height}" />
<title>Vistora Motion Graphic</title>
<script src="./vendor/gsap.min.js"></script>
<style>
@font-face{{font-family:VistoraCJK;src:local("Microsoft YaHei");font-style:normal;font-weight:100 900;font-display:swap}}
*{{box-sizing:border-box}} html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden;background:#050910;color:#f7fbff;font-family:VistoraCJK}}
#root{{position:relative;width:{width}px;height:{height}px;overflow:hidden}}
.clip{{position:absolute;inset:0;width:100%;height:100%;overflow:hidden}}
.fill{{position:absolute;inset:0;width:100%;height:100%;overflow:hidden;background:radial-gradient(circle at 78% 18%,rgba(18,211,255,.22),transparent 32%),#050910}}
.source{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.28;filter:saturate(.75) contrast(1.12)}}
.shade{{position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,9,16,.94),rgba(5,9,16,.62) 62%,rgba(5,9,16,.28))}}
.grid{{position:absolute;inset:0;background-image:linear-gradient(rgba(70,224,255,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(70,224,255,.08) 1px,transparent 1px);background-size:6.4% 11.1%;mask-image:linear-gradient(90deg,#000,transparent 82%)}}
.content{{position:relative;display:flex;flex-direction:column;justify-content:center;width:100%;height:100%;padding:9% 10%;gap:3.2%;z-index:2}}
.kicker{{align-self:flex-start;padding:.55em 1em;border:1px solid #19d8ff;border-radius:999px;color:#69e8ff;font-size:clamp(18px,2.1vw,34px);font-weight:700;letter-spacing:.08em;text-transform:uppercase;background:rgba(0,26,38,.72)}}
.title{{max-width:78%;font-size:clamp(58px,8vw,142px);line-height:1.02;letter-spacing:-.035em;font-weight:900;text-wrap:balance;text-shadow:0 0 34px rgba(25,216,255,.22)}}
.body{{max-width:72%;font-size:clamp(24px,3vw,48px);line-height:1.46;color:#c7d8e6;font-weight:500;text-wrap:balance}}
.meter{{width:min(72%,1050px);height:10px;border-radius:99px;background:rgba(255,255,255,.12);overflow:hidden}}
.meter>i{{display:block;width:100%;height:100%;transform-origin:left;background:linear-gradient(90deg,#19d8ff,#ffbd4a);box-shadow:0 0 24px #19d8ff}}
.orb{{position:absolute;right:8%;bottom:12%;width:18vw;height:18vw;max-width:300px;max-height:300px;border:2px solid rgba(25,216,255,.5);border-radius:50%;box-shadow:inset 0 0 50px rgba(25,216,255,.18),0 0 50px rgba(25,216,255,.12);z-index:1}}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{duration}" data-width="{width}" data-height="{height}">
<section id="motion-card" class="clip" data-start="0" data-duration="{duration}" data-track-index="1">
<div class="fill">{background}<div class="shade"></div><div class="grid"></div><div class="orb"></div>
<main class="content"><div class="kicker">{kicker}</div><div class="title">{title}</div><div class="body">{body}</div><div class="meter"><i></i></div></main></div>
</section>
</div>
<script>
window.__timelines=window.__timelines||{{}};
const tl=gsap.timeline({{paused:true}}),D={duration_json};
tl.from('.kicker',{{x:-70,opacity:0,duration:.55,ease:'expo.out'}},.18)
  .from('.title',{{y:70,opacity:0,scale:.97,duration:.72,ease:'power3.out'}},.32)
  .from('.body',{{y:38,opacity:0,duration:.6,ease:'power2.out'}},.62)
  .from('.meter>i',{{scaleX:0,duration:Math.max(.8,D-1.5),ease:'none'}},.72)
  .from('.orb',{{scale:.55,rotation:-42,opacity:0,duration:.7,ease:'back.out(1.2)'}},.38)
  .to('.orb',{{rotation:28,scale:1.08,duration:Math.max(.6,D-1.48),ease:'sine.inOut'}},1.08)
  .to('.content',{{opacity:0,duration:.42,ease:'power2.in'}},Math.max(1,D-.48));
window.__timelines.main=tl;
</script></body></html>"""
        (work_root / "index.html").write_text(index, encoding="utf-8")
        (work_root / "DESIGN.md").write_text(
            """# Vistora Motion Provider\n\n## Style Prompt\nDark cinematic editorial motion graphics with restrained cyan and amber accents, crisp information hierarchy, and strong safe-area discipline.\n\n## Colors\n- Canvas: #050910\n- Primary: #F7FBFF\n- Cyan accent: #19D8FF\n- Amber accent: #FFBD4A\n- Secondary text: #C7D8E6\n\n## Typography\nMicrosoft YaHei / Noto Sans SC / Arial.\n\n## What NOT to Do\nNo generic blue gradients, no random animation, no edge-clipped text, no unverified factual charts.\n""",
            encoding="utf-8",
        )
        (work_root / "hyperframes.json").write_text(
            json.dumps(
                {
                    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                    "media": {"autoProxy": True},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (work_root / "package.json").write_text(
            json.dumps(
                {
                    "name": f"vistora-{request.job_id.lower().replace(':', '-')}",
                    "private": True,
                    "type": "module",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _result(self, request, provider_ref, relative, message) -> AdapterJobUpdate:
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_ref,
            status="succeeded",
            progress=1,
            artifacts=(
                ArtifactCandidate(
                    artifact_id=f"artifact_{request.job_id}",
                    job_id=request.job_id,
                    task_id=request.task_id,
                    requirement_item_id=request.requirement_item_id,
                    staging_relative_path=relative.as_posix(),
                    claimed_mime_type="video/mp4",
                ),
            ),
            message=message,
            updated_at=self.clock(),
        )

    def _failure(self, request, provider_ref, code, message, *, status="failed"):
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_ref,
            status=status,
            progress=0,
            error_code=code,
            message=message,
            updated_at=self.clock(),
        )

    def submit(self, request, *, staging_root):
        try:
            workflow = self._workflow_choice(request)
        except ValueError:
            return self._failure(
                request,
                f"hyperframes_{request.job_id}",
                "hyperframes_capability_unavailable",
                "The requested HyperFrames workflow is unavailable.",
            )
        provider_ref = self._provider_ref(request, workflow.workflow_id)
        relative = Path(request.run_id) / request.job_id / "hyperframes.mp4"
        staging = Path(staging_root).resolve()
        target = (staging / relative).resolve()
        if staging not in target.parents:
            raise ValueError("HyperFrames target escapes staging")
        if target.is_file() and target.stat().st_size > 0:
            return self._result(
                request,
                provider_ref,
                relative,
                "The existing deterministic HyperFrames render was recovered.",
            )
        task = request.task_spec
        if task is None or task.prompt_spec is None:
            return self._failure(
                request,
                provider_ref,
                "hyperframes_task_invalid",
                "HyperFrames requires a confirmed generated task with a prompt.",
            )
        duration = task.duration_seconds or workflow.min_duration_seconds
        fps = int(round(task.fps or 30))
        width = task.width or 1920
        height = task.height or 1080
        if not workflow.min_duration_seconds <= duration <= workflow.max_duration_seconds:
            return self._failure(
                request,
                provider_ref,
                "hyperframes_duration_unsupported",
                "The requested motion-graphic duration is outside the workflow bounds.",
            )
        if fps not in workflow.allowed_fps:
            return self._failure(
                request,
                provider_ref,
                "hyperframes_fps_unsupported",
                "The requested motion-graphic frame rate is unsupported.",
            )
        if not self.config.gsap_path.is_file():
            return self._failure(
                request,
                provider_ref,
                "hyperframes_runtime_unconfigured",
                "The pinned local HyperFrames/GSAP runtime is unavailable.",
            )
        runtime = self.config.runtime_root.resolve()
        work_root = (runtime / "jobs" / provider_ref).resolve()
        if runtime not in work_root.parents:
            raise ValueError("HyperFrames work directory escapes runtime root")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write_project(
                request,
                work_root=work_root,
                duration=duration,
                width=width,
                height=height,
            )
            self.runner.render(
                project_root=work_root,
                output_path=target,
                fps=fps,
                workflow=workflow,
                config=self.config,
            )
        except subprocess.TimeoutExpired:
            return self._failure(
                request,
                provider_ref,
                "hyperframes_render_timeout",
                "The bounded HyperFrames render timed out.",
                status="timed_out",
            )
        except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError):
            return self._failure(
                request,
                provider_ref,
                "hyperframes_render_failed",
                "The HyperFrames project did not pass validation and rendering.",
            )
        if not target.is_file() or target.stat().st_size <= 0:
            return self._failure(
                request,
                provider_ref,
                "hyperframes_output_missing",
                "HyperFrames finished without a valid rendered file.",
            )
        return self._result(
            request,
            provider_ref,
            relative,
            "The pinned HyperFrames composition passed checks and was rendered.",
        )

    def poll(self, request, *, provider_opaque_ref, staging_root):
        expected = self._provider_ref(
            request,
            self._workflow_choice(request).workflow_id,
        )
        if provider_opaque_ref != expected:
            return self._failure(
                request,
                provider_opaque_ref,
                "hyperframes_job_identity_mismatch",
                "The HyperFrames job identity does not match this request.",
                status="recovery_required",
            )
        return self.submit(request, staging_root=staging_root)

    def cancel(self, request, *, provider_opaque_ref):
        expected = self._provider_ref(
            request,
            self._workflow_choice(request).workflow_id,
        )
        if provider_opaque_ref != expected:
            return self._failure(
                request,
                provider_opaque_ref,
                "hyperframes_job_identity_mismatch",
                "The HyperFrames job identity does not match this request.",
                status="recovery_required",
            )
        work_root = self.config.runtime_root.resolve() / "jobs" / expected
        if work_root.is_dir():
            shutil.rmtree(work_root)
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_opaque_ref,
            status="cancelled",
            progress=0,
            message="The unaccepted HyperFrames working copy was removed.",
            updated_at=self.clock(),
        )


__all__ = [
    "HYPERFRAMES_PROVIDER_VERSION",
    "HYPERFRAMES_WORKFLOW_PARAMETER",
    "HyperFramesCLIRunner",
    "HyperFramesMaterialProductionAdapter",
    "HyperFramesProviderConfig",
    "HyperFramesRunner",
    "HyperFramesWorkflowSpec",
    "load_hyperframes_provider_config",
]
