"""Strict loopback ComfyUI material-production provider.

The adapter consumes only confirmed ``ProductionJobRequest`` contracts.  A
project-local sidecar maps provider-neutral task fields onto an API-format
ComfyUI workflow.  Absolute paths, workflow JSON, and provider output paths
never enter the public capability registry or product view.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from director import digest_json

from .adapters import (
    PRODUCTION_CAPABILITY_KINDS,
    MaterialProductionAdapter,
    _schema_digest,
)
from .models import (
    AdapterCapability,
    AdapterJobUpdate,
    ArtifactCandidate,
    ProductionJobRequest,
)


COMFYUI_PROVIDER_VERSION = "1.1.0"
COMFYUI_WORKFLOW_PARAMETER = "comfyui_workflow_id"
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{2,127}$")
_MIME_BY_SUFFIX = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".m4a": "audio/mp4",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".ogg": "audio/ogg",
    ".png": "image/png",
    ".wav": "audio/wav",
    ".webm": "video/webm",
    ".webp": "image/webp",
}
_REFERENCE_SUFFIXES = {
    "audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"},
    "image": {".jpeg", ".jpg", ".png", ".webp"},
    "video": {".mov", ".mp4", ".webm"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ComfyUIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ComfyUIWorkflowBinding(ComfyUIModel):
    node_id: str = Field(min_length=1, max_length=64)
    input_name: str = Field(min_length=1, max_length=128)
    source: Literal[
        "prompt_text",
        "prompt_subject",
        "prompt_scene",
        "prompt_action",
        "prompt_camera",
        "prompt_lighting",
        "prompt_style",
        "negative_prompt",
        "width",
        "height",
        "fps",
        "duration_seconds",
        "seed",
        "reference_asset",
        "reproducibility_parameter",
    ]
    reference_index: int | None = Field(default=None, ge=0, le=31)
    reference_kind: Literal["image", "audio", "video"] | None = None
    parameter_name: str | None = Field(default=None, min_length=1, max_length=128)
    required: bool = True

    @model_validator(mode="after")
    def source_shape(self) -> "ComfyUIWorkflowBinding":
        if (self.source == "reference_asset") != (self.reference_index is not None):
            raise ValueError("Reference binding requires exactly one reference index")
        if (self.source == "reference_asset") != (self.reference_kind is not None):
            raise ValueError("Reference binding requires exactly one media kind")
        if (self.source == "reproducibility_parameter") != (
            self.parameter_name is not None
        ):
            raise ValueError("Parameter binding requires exactly one parameter name")
        return self


class ComfyUIWorkflowSpec(ComfyUIModel):
    workflow_id: str = Field(min_length=3, max_length=128, pattern=_ID.pattern)
    capability_ids: tuple[str, ...] = Field(min_length=1)
    workflow_path: Path
    output_node_ids: tuple[str, ...] = Field(min_length=1)
    bindings: tuple[ComfyUIWorkflowBinding, ...] = Field(min_length=1)
    default_for_capabilities: tuple[str, ...] = ()
    unload_models_after: bool = True
    supports_targeted_interrupt: bool = False

    @model_validator(mode="after")
    def workflow_shape(self) -> "ComfyUIWorkflowSpec":
        if (
            tuple(sorted(self.capability_ids)) != self.capability_ids
            or len(self.capability_ids) != len(set(self.capability_ids))
        ):
            raise ValueError("Workflow capabilities must be unique and ordered")
        if len(self.output_node_ids) != len(set(self.output_node_ids)):
            raise ValueError("Workflow output nodes must be unique")
        if (
            tuple(sorted(self.default_for_capabilities))
            != self.default_for_capabilities
            or len(self.default_for_capabilities)
            != len(set(self.default_for_capabilities))
            or not set(self.default_for_capabilities).issubset(self.capability_ids)
        ):
            raise ValueError(
                "Default workflow capabilities must be unique, ordered, and declared"
            )
        targets = [(item.node_id, item.input_name) for item in self.bindings]
        if len(targets) != len(set(targets)):
            raise ValueError("Workflow binding targets must be unique")
        return self


class ComfyUIProviderConfig(ComfyUIModel):
    schema_name: Literal["vistora.comfyui-provider"] = "vistora.comfyui-provider"
    schema_version: Literal["1.0.0"] = "1.0.0"
    base_url: str = "http://127.0.0.1:8188"
    request_timeout_seconds: float = Field(default=15, ge=1, le=120)
    max_upload_bytes: int = Field(default=2_147_483_648, ge=1, le=8_589_934_592)
    max_download_bytes: int = Field(default=4_294_967_296, ge=1, le=17_179_869_184)
    workflows: tuple[ComfyUIWorkflowSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def provider_shape(self) -> "ComfyUIProviderConfig":
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("ComfyUI provider must use a credential-free loopback URL")
        ids = [item.workflow_id for item in self.workflows]
        if len(ids) != len(set(ids)):
            raise ValueError("ComfyUI workflow ID is duplicated")
        capabilities = [
            capability
            for workflow in self.workflows
            for capability in workflow.capability_ids
        ]
        unsupported = set(capabilities) - set(PRODUCTION_CAPABILITY_KINDS)
        if unsupported or set(capabilities).intersection(
            {"manual_import", "user_material_request"}
        ):
            raise ValueError("ComfyUI workflow declares an unsupported capability")
        for capability in set(capabilities):
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
                    "Multiple ComfyUI workflows require exactly one default"
                )
        return self


def provider_config_path(project_file: str | Path) -> Path:
    explicit = os.environ.get("VISTORA_COMFYUI_CONFIG")
    if explicit:
        return Path(explicit)
    project = Path(project_file)
    return project.with_name(f"{project.stem}.comfyui-provider.json")


def load_comfyui_provider_config(
    project_file: str | Path,
) -> ComfyUIProviderConfig | None:
    path = provider_config_path(project_file)
    if not path.is_file():
        return None
    try:
        config = ComfyUIProviderConfig.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        workflows = tuple(
            workflow.model_copy(
                update={
                    "workflow_path": (
                        workflow.workflow_path
                        if workflow.workflow_path.is_absolute()
                        else (path.parent / workflow.workflow_path).resolve()
                    )
                }
            )
            for workflow in config.workflows
        )
        return config.model_copy(update={"workflows": workflows})
    except (OSError, ValueError) as exc:
        raise ValueError("ComfyUI provider configuration is invalid") from exc


class ComfyUITransport(Protocol):
    def health(self) -> None: ...

    def upload(self, source: Path, *, subfolder: str) -> str: ...

    def submit(self, prompt: dict[str, Any], *, prompt_id: str) -> str: ...

    def history(self, prompt_id: str) -> dict[str, Any]: ...

    def queue(self) -> dict[str, Any]: ...

    def delete_queued(self, prompt_id: str) -> None: ...

    def interrupt(self, prompt_id: str) -> None: ...

    def unload_models(self) -> None: ...

    def download(self, descriptor: dict[str, str], target: Path) -> None: ...


class ComfyUIHTTPTransport:
    """Small stdlib HTTP client restricted to the configured loopback server."""

    def __init__(self, config: ComfyUIProviderConfig) -> None:
        self.base_url = config.base_url.rstrip("/")
        parsed = urlparse(config.base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.timeout = config.request_timeout_seconds
        self.max_upload_bytes = config.max_upload_bytes
        self.max_download_bytes = config.max_download_bytes

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> bytes:
        data = body
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type is not None:
            headers["Content-Type"] = content_type
        request = Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read(16 * 1024 * 1024)
        except HTTPError as exc:
            raise RuntimeError(f"ComfyUI HTTP status {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("ComfyUI request failed") from exc

    def _json(self, method: str, path: str, payload=None) -> dict[str, Any]:
        raw = self._request(method, path, payload=payload)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ComfyUI returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError("ComfyUI returned an invalid response shape")
        return value

    def health(self) -> None:
        self._json("GET", "/prompt")

    def upload(self, source: Path, *, subfolder: str) -> str:
        size = source.stat().st_size
        if size <= 0 or size > self.max_upload_bytes:
            raise RuntimeError("ComfyUI upload size is outside the configured limit")
        boundary = "vistora" + uuid.uuid4().hex
        name = source.name.replace('"', "_")
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
        fields = (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="type"\r\n\r\ninput'
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="subfolder"\r\n\r\n{subfolder}'
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue'
            f"\r\n--{boundary}--\r\n"
        ).encode("utf-8")
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=self.timeout,
        )
        try:
            connection.putrequest("POST", "/upload/image")
            connection.putheader(
                "Content-Type",
                f"multipart/form-data; boundary={boundary}",
            )
            connection.putheader("Content-Length", len(prefix) + size + len(fields))
            connection.putheader("Accept", "application/json")
            connection.endheaders()
            connection.send(prefix)
            with source.open("rb") as uploaded:
                while True:
                    chunk = uploaded.read(1024 * 1024)
                    if not chunk:
                        break
                    connection.send(chunk)
            connection.send(fields)
            response = connection.getresponse()
            raw = response.read(16 * 1024 * 1024)
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"ComfyUI HTTP status {response.status}")
        except (OSError, HTTPError, TimeoutError) as exc:
            raise RuntimeError("ComfyUI upload failed") from exc
        finally:
            connection.close()
        try:
            response = json.loads(raw.decode("utf-8"))
            filename = response["name"]
            returned_subfolder = response.get("subfolder", "")
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ComfyUI upload response is invalid") from exc
        if Path(filename).name != filename or ".." in Path(returned_subfolder).parts:
            raise RuntimeError("ComfyUI upload response is unsafe")
        return "/".join(part for part in (returned_subfolder, filename) if part)

    def submit(self, prompt: dict[str, Any], *, prompt_id: str) -> str:
        response = self._json(
            "POST",
            "/prompt",
            {
                "prompt": prompt,
                "prompt_id": prompt_id,
                "client_id": "vistora-material-production",
                "extra_data": {"comfy_usage_source": "vistora"},
            },
        )
        returned = response.get("prompt_id")
        if returned != prompt_id:
            raise RuntimeError("ComfyUI prompt identity mismatched")
        return returned

    def history(self, prompt_id: str) -> dict[str, Any]:
        return self._json("GET", f"/history/{quote(prompt_id, safe='')}")

    def queue(self) -> dict[str, Any]:
        return self._json("GET", "/queue")

    def delete_queued(self, prompt_id: str) -> None:
        self._request("POST", "/queue", payload={"delete": [prompt_id]})

    def interrupt(self, prompt_id: str) -> None:
        self._request("POST", "/interrupt", payload={"prompt_id": prompt_id})

    def unload_models(self) -> None:
        self._request(
            "POST",
            "/free",
            payload={"unload_models": True, "free_memory": True},
        )

    def download(self, descriptor: dict[str, str], target: Path) -> None:
        query = urlencode(
            {
                "filename": descriptor["filename"],
                "subfolder": descriptor.get("subfolder", ""),
                "type": descriptor.get("type", "output"),
            }
        )
        request = Request(self.base_url + "/view?" + query, method="GET")
        target.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            with urlopen(request, timeout=self.timeout) as response, target.open("xb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        raise RuntimeError("ComfyUI output exceeds the configured limit")
                    output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if total <= 0:
            target.unlink(missing_ok=True)
            raise RuntimeError("ComfyUI output is empty")


class ComfyUIMaterialProductionAdapter(MaterialProductionAdapter):
    """Maps confirmed Vistora tasks onto configured ComfyUI API workflows."""

    def __init__(
        self,
        config: ComfyUIProviderConfig,
        *,
        asset_resolver: Callable[[str], Path | None],
        transport: ComfyUITransport | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.config = config
        self.asset_resolver = asset_resolver
        self.transport = transport or ComfyUIHTTPTransport(config)
        self.clock = clock
        self._workflows: dict[
            str, dict[str, tuple[ComfyUIWorkflowSpec, dict[str, Any]]]
        ] = {}
        self._default_workflows: dict[str, str] = {}
        workflow_digests = []
        for spec in config.workflows:
            workflow = self._load_workflow(spec)
            public_spec = spec.model_dump(
                mode="json",
                exclude={"workflow_path"},
            )
            workflow_digest = digest_json({"spec": public_spec, "workflow": workflow})
            workflow_digests.append(workflow_digest)
            for capability_id in spec.capability_ids:
                self._workflows.setdefault(capability_id, {})[spec.workflow_id] = (
                    spec,
                    workflow,
                )
                if capability_id in spec.default_for_capabilities:
                    self._default_workflows[capability_id] = spec.workflow_id
        for capability_id, choices in self._workflows.items():
            if len(choices) == 1:
                self._default_workflows.setdefault(
                    capability_id,
                    next(iter(choices)),
                )
        self.workflow_digest = digest_json(workflow_digests)
        self._unloaded: set[str] = set()

    @staticmethod
    def _load_workflow(spec: ComfyUIWorkflowSpec) -> dict[str, Any]:
        try:
            raw = spec.workflow_path.read_bytes()
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("ComfyUI workflow is too large")
            workflow = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ComfyUI workflow cannot be loaded") from exc
        if not isinstance(workflow, dict) or not workflow:
            raise ValueError("ComfyUI workflow must use API JSON format")
        for node_id, node in workflow.items():
            if (
                not isinstance(node_id, str)
                or not isinstance(node, dict)
                or not isinstance(node.get("class_type"), str)
                or not isinstance(node.get("inputs"), dict)
            ):
                raise ValueError("ComfyUI workflow contains an invalid node")
        for node_id in spec.output_node_ids:
            if node_id not in workflow:
                raise ValueError("ComfyUI output node is missing")
        for binding in spec.bindings:
            node = workflow.get(binding.node_id)
            if node is None or binding.input_name not in node["inputs"]:
                raise ValueError("ComfyUI binding target is missing")
        return workflow

    def capability(self) -> AdapterCapability:
        ids = tuple(sorted(self._workflows))
        return AdapterCapability(
            adapter_id="comfyui_local",
            adapter_version=f"{COMFYUI_PROVIDER_VERSION}+{self.workflow_digest[7:19]}",
            capability_ids=ids,
            configured=True,
            execution_kind="external_provider",
            max_concurrency=1,
            limitation=None,
            input_schema_digest=digest_json(
                {
                    "job": ProductionJobRequest.model_json_schema(),
                    "workflow_digest": self.workflow_digest,
                }
            ),
            result_schema_digest=_schema_digest(AdapterJobUpdate),
        )

    def _workflow_choice(
        self,
        request: ProductionJobRequest,
    ) -> tuple[ComfyUIWorkflowSpec, dict[str, Any]]:
        choices = self._workflows.get(request.capability_id)
        if not choices:
            raise ValueError("ComfyUI capability is unavailable")
        requested = None
        if request.task_spec is not None:
            parameters = {
                item.name: item.value
                for item in request.task_spec.reproducibility_parameters
            }
            requested = parameters.get(COMFYUI_WORKFLOW_PARAMETER)
        if requested is not None and not isinstance(requested, str):
            raise ValueError("ComfyUI workflow selector must be a workflow ID")
        workflow_id = requested or self._default_workflows.get(request.capability_id)
        selected = choices.get(workflow_id or "")
        if selected is None:
            raise ValueError("Requested ComfyUI workflow is unavailable")
        return selected

    def _prompt_id(self, request: ProductionJobRequest, workflow_id: str) -> str:
        identity = f"vistora:{request.idempotency_key}"
        if len(self._workflows.get(request.capability_id, {})) > 1:
            identity += f":{workflow_id}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    @staticmethod
    def _provider_ref(prompt_id: str) -> str:
        return "comfyui_" + uuid.UUID(prompt_id).hex

    @staticmethod
    def _prompt_from_ref(provider_opaque_ref: str) -> str:
        if not provider_opaque_ref.startswith("comfyui_"):
            raise ValueError("ComfyUI provider reference is invalid")
        return str(uuid.UUID(hex=provider_opaque_ref.removeprefix("comfyui_")))

    @staticmethod
    def _prompt_text(request: ProductionJobRequest) -> str | None:
        prompt = request.task_spec.prompt_spec if request.task_spec else None
        if prompt is None:
            return None
        return ". ".join(
            value.rstrip(". ")
            for value in (
                prompt.subject,
                prompt.scene,
                prompt.action,
                prompt.camera,
                prompt.lighting,
                prompt.style,
            )
            if value
        ) + "."

    @staticmethod
    def _negative_prompt(request: ProductionJobRequest) -> str | None:
        prompt = request.task_spec.prompt_spec if request.task_spec else None
        return ", ".join(prompt.negative_constraints) if prompt else None

    def _binding_value(
        self,
        binding: ComfyUIWorkflowBinding,
        request: ProductionJobRequest,
        *,
        upload_subfolder: str,
    ) -> Any:
        task = request.task_spec
        if task is None:
            raise ValueError("Confirmed production task details are unavailable")
        values = {
            "prompt_text": self._prompt_text(request),
            "negative_prompt": self._negative_prompt(request),
            "prompt_subject": task.prompt_spec.subject if task.prompt_spec else None,
            "prompt_scene": task.prompt_spec.scene if task.prompt_spec else None,
            "prompt_action": task.prompt_spec.action if task.prompt_spec else None,
            "prompt_camera": task.prompt_spec.camera if task.prompt_spec else None,
            "prompt_lighting": task.prompt_spec.lighting if task.prompt_spec else None,
            "prompt_style": task.prompt_spec.style if task.prompt_spec else None,
            "width": task.width,
            "height": task.height,
            "fps": task.fps,
            "duration_seconds": task.duration_seconds,
            "seed": task.seed,
        }
        if binding.source in values:
            value = values[binding.source]
        elif binding.source == "reproducibility_parameter":
            by_name = {item.name: item.value for item in task.reproducibility_parameters}
            value = by_name.get(binding.parameter_name or "")
        else:
            index = binding.reference_index or 0
            if index >= len(task.reference_asset_ids):
                value = None
            else:
                material_id = task.reference_asset_ids[index]
                source = self.asset_resolver(material_id)
                if source is None or not source.is_file():
                    value = None
                else:
                    if source.suffix.lower() not in _REFERENCE_SUFFIXES[
                        binding.reference_kind or "image"
                    ]:
                        raise ValueError(
                            "ComfyUI reference media kind does not match the binding"
                        )
                    value = self.transport.upload(source, subfolder=upload_subfolder)
        if value is None and binding.required:
            raise ValueError("A required ComfyUI workflow input is unavailable")
        return value

    def _prepare_prompt(
        self,
        request: ProductionJobRequest,
        spec: ComfyUIWorkflowSpec,
        workflow: dict[str, Any],
        *,
        prompt_id: str,
    ) -> dict[str, Any]:
        prepared = copy.deepcopy(workflow)
        subfolder = f"vistora/{prompt_id}"
        for binding in spec.bindings:
            value = self._binding_value(
                binding,
                request,
                upload_subfolder=subfolder,
            )
            if value is not None:
                prepared[binding.node_id]["inputs"][binding.input_name] = value
        prefix = f"vistora/{prompt_id}/{spec.workflow_id}"
        for node_id in spec.output_node_ids:
            inputs = prepared[node_id]["inputs"]
            if "filename_prefix" in inputs:
                inputs["filename_prefix"] = prefix
        return prepared

    @staticmethod
    def _queue_state(queue: dict[str, Any], prompt_id: str) -> str | None:
        for item in queue.get("queue_running", ()):
            if isinstance(item, (list, tuple)) and len(item) > 1 and item[1] == prompt_id:
                return "running"
        for item in queue.get("queue_pending", ()):
            if isinstance(item, (list, tuple)) and len(item) > 1 and item[1] == prompt_id:
                return "submitted"
        return None

    @staticmethod
    def _queue_has_work(queue: dict[str, Any]) -> bool:
        return bool(queue.get("queue_running") or queue.get("queue_pending"))

    def _queue_wait(
        self,
        request: ProductionJobRequest,
        *,
        provider_ref: str,
    ) -> AdapterJobUpdate:
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_ref,
            status="rate_limited",
            progress=0,
            error_code="comfyui_queue_busy",
            retry_after_seconds=2,
            message=(
                "Local ComfyUI is completing another job before this task "
                "can reserve the single generation slot."
            ),
            updated_at=self.clock(),
        )

    def _unload(self, spec: ComfyUIWorkflowSpec, prompt_id: str) -> None:
        if spec.unload_models_after and prompt_id not in self._unloaded:
            self.transport.unload_models()
            self._unloaded.add(prompt_id)

    def _error(
        self,
        request: ProductionJobRequest,
        *,
        provider_ref: str,
        code: str,
        message: str,
        recovery: bool = False,
    ) -> AdapterJobUpdate:
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_ref,
            status="recovery_required" if recovery else "failed",
            progress=0,
            error_code=code,
            message=message,
            updated_at=self.clock(),
        )

    def submit(self, request, *, staging_root):
        try:
            spec_and_workflow = self._workflow_choice(request)
        except ValueError:
            spec_and_workflow = None
        workflow_id = (
            spec_and_workflow[0].workflow_id
            if spec_and_workflow is not None
            else "unavailable"
        )
        prompt_id = self._prompt_id(request, workflow_id)
        provider_ref = self._provider_ref(prompt_id)
        if spec_and_workflow is None:
            return self._error(
                request,
                provider_ref=provider_ref,
                code="comfyui_capability_unavailable",
                message="The configured ComfyUI provider does not support this task.",
            )
        spec, workflow = spec_and_workflow
        try:
            self.transport.health()
            history = self.transport.history(prompt_id)
            if prompt_id in history:
                return self._poll_history(
                    request,
                    spec=spec,
                    prompt_id=prompt_id,
                    provider_ref=provider_ref,
                    history=history,
                    staging_root=Path(staging_root),
                )
            queue = self.transport.queue()
            state = self._queue_state(queue, prompt_id)
            if state is not None:
                return AdapterJobUpdate(
                    job_id=request.job_id,
                    adapter_id=self.capability().adapter_id,
                    provider_opaque_ref=provider_ref,
                    status=state,
                    progress=0.4 if state == "running" else 0.1,
                    message="The ComfyUI job already exists and remains active.",
                    updated_at=self.clock(),
                )
            if self._queue_has_work(queue):
                return self._queue_wait(request, provider_ref=provider_ref)
            prompt = self._prepare_prompt(
                request,
                spec,
                workflow,
                prompt_id=prompt_id,
            )
        except (OSError, RuntimeError, ValueError):
            return self._error(
                request,
                provider_ref=provider_ref,
                code="comfyui_preflight_failed",
                message="The ComfyUI job could not pass local preflight.",
            )
        try:
            self.transport.submit(prompt, prompt_id=prompt_id)
        except (OSError, RuntimeError, ValueError):
            return self._error(
                request,
                provider_ref=provider_ref,
                code="comfyui_submit_uncertain",
                message="ComfyUI submission ended without a reliable acknowledgement.",
                recovery=True,
            )
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_ref,
            status="submitted",
            progress=0.1,
            message="The confirmed task was submitted to local ComfyUI.",
            updated_at=self.clock(),
        )

    def _poll_history(
        self,
        request: ProductionJobRequest,
        *,
        spec: ComfyUIWorkflowSpec,
        prompt_id: str,
        provider_ref: str,
        history: dict[str, Any],
        staging_root: Path,
    ) -> AdapterJobUpdate:
        record = history.get(prompt_id)
        if not isinstance(record, dict):
            raise RuntimeError("ComfyUI history record is invalid")
        status = record.get("status", {})
        completed = bool(status.get("completed")) if isinstance(status, dict) else False
        status_text = status.get("status_str") if isinstance(status, dict) else None
        if not completed:
            if status_text in {"error", "failed"}:
                try:
                    self._unload(spec, prompt_id)
                except RuntimeError:
                    pass
                return self._error(
                    request,
                    provider_ref=provider_ref,
                    code="comfyui_execution_failed",
                    message="The local ComfyUI workflow failed.",
                )
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id=self.capability().adapter_id,
                provider_opaque_ref=provider_ref,
                status="running",
                progress=0.8,
                message="The local ComfyUI workflow is still running.",
                updated_at=self.clock(),
            )
        outputs = record.get("outputs")
        if not isinstance(outputs, dict):
            return self._error(
                request,
                provider_ref=provider_ref,
                code="comfyui_output_missing",
                message="ComfyUI completed without a supported output.",
            )
        descriptors: list[dict[str, str]] = []
        for node_id in spec.output_node_ids:
            node_output = outputs.get(node_id, {})
            if not isinstance(node_output, dict):
                continue
            for collection in node_output.values():
                if not isinstance(collection, list):
                    continue
                for item in collection:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("filename"), str)
                        and isinstance(item.get("subfolder", ""), str)
                        and isinstance(item.get("type", "output"), str)
                    ):
                        descriptors.append(
                            {
                                "filename": item["filename"],
                                "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output"),
                            }
                        )
        if not descriptors:
            try:
                self._unload(spec, prompt_id)
            except RuntimeError:
                return self._error(
                    request,
                    provider_ref=provider_ref,
                    code="comfyui_model_unload_failed",
                    message="ComfyUI completed but its models could not be unloaded.",
                    recovery=True,
                )
            return self._error(
                request,
                provider_ref=provider_ref,
                code="comfyui_output_missing",
                message="ComfyUI completed without a supported output.",
            )
        descriptors.sort(
            key=lambda item: (
                item.get("type", "output"),
                item.get("subfolder", ""),
                item["filename"],
            )
        )
        artifacts = []
        created: list[Path] = []
        root = staging_root.resolve()
        try:
            for index, descriptor in enumerate(descriptors):
                filename = descriptor["filename"]
                subfolder = descriptor.get("subfolder", "")
                output_type = descriptor.get("type", "output")
                if (
                    Path(filename).name != filename
                    or Path(subfolder).is_absolute()
                    or ".." in Path(subfolder).parts
                    or output_type not in {"input", "output", "temp"}
                ):
                    raise RuntimeError("ComfyUI output filename is unsafe")
                suffix = Path(filename).suffix.lower()
                mime = _MIME_BY_SUFFIX.get(suffix)
                if mime is None:
                    raise RuntimeError("ComfyUI output media type is unsupported")
                token = hashlib.sha256(
                    f"{prompt_id}:{index}:{filename}".encode("utf-8")
                ).hexdigest()[:20]
                relative = Path(request.run_id) / request.job_id / f"output_{token}{suffix}"
                target = (staging_root / relative).resolve()
                if root not in target.parents:
                    raise RuntimeError("ComfyUI staging target is unsafe")
                self.transport.download(descriptor, target)
                created.append(target)
                artifacts.append(
                    ArtifactCandidate(
                        artifact_id=f"artifact_{token}",
                        job_id=request.job_id,
                        task_id=request.task_id,
                        requirement_item_id=request.requirement_item_id,
                        staging_relative_path=relative.as_posix(),
                        claimed_mime_type=mime,
                    )
                )
            self._unload(spec, prompt_id)
        except (OSError, RuntimeError, ValueError):
            for target in created:
                target.unlink(missing_ok=True)
            try:
                self._unload(spec, prompt_id)
            except RuntimeError:
                pass
            return self._error(
                request,
                provider_ref=provider_ref,
                code="comfyui_output_recovery_required",
                message="ComfyUI output retrieval or model unloading was incomplete.",
                recovery=True,
            )
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_ref,
            status="succeeded",
            progress=1,
            artifacts=tuple(artifacts),
            message="ComfyUI output was staged and its models were unloaded.",
            updated_at=self.clock(),
        )

    def poll(self, request, *, provider_opaque_ref, staging_root):
        try:
            spec, _ = self._workflow_choice(request)
            prompt_id = self._prompt_from_ref(provider_opaque_ref)
            expected = self._prompt_id(request, spec.workflow_id)
            if prompt_id != expected:
                raise ValueError("ComfyUI prompt identity mismatched")
            history = self.transport.history(prompt_id)
            if prompt_id in history:
                return self._poll_history(
                    request,
                    spec=spec,
                    prompt_id=prompt_id,
                    provider_ref=provider_opaque_ref,
                    history=history,
                    staging_root=Path(staging_root),
                )
            queue = self.transport.queue()
            state = self._queue_state(queue, prompt_id)
        except (KeyError, OSError, RuntimeError, ValueError):
            return self._error(
                request,
                provider_ref=provider_opaque_ref,
                code="comfyui_poll_uncertain",
                message="The ComfyUI job state could not be verified.",
                recovery=True,
            )
        if state is None:
            if self._queue_has_work(queue):
                return self._queue_wait(
                    request,
                    provider_ref=provider_opaque_ref,
                )
            return self.submit(request, staging_root=staging_root)
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_opaque_ref,
            status=state,
            progress=0.55 if state == "running" else 0.15,
            message="The local ComfyUI workflow remains active.",
            updated_at=self.clock(),
        )

    def cancel(self, request, *, provider_opaque_ref):
        try:
            spec, _ = self._workflow_choice(request)
            prompt_id = self._prompt_from_ref(provider_opaque_ref)
            if prompt_id != self._prompt_id(request, spec.workflow_id):
                raise ValueError("ComfyUI prompt identity mismatched")
            history = self.transport.history(prompt_id)
            if prompt_id in history:
                try:
                    self._unload(spec, prompt_id)
                except RuntimeError:
                    pass
                return self._error(
                    request,
                    provider_ref=provider_opaque_ref,
                    code="comfyui_cancel_after_completion",
                    message="The ComfyUI job already reached a terminal history state.",
                    recovery=True,
                )
            state = self._queue_state(self.transport.queue(), prompt_id)
            if state == "running" and not spec.supports_targeted_interrupt:
                return self._error(
                    request,
                    provider_ref=provider_opaque_ref,
                    code="comfyui_targeted_cancel_unavailable",
                    message="This ComfyUI server cannot safely cancel only the running job.",
                    recovery=True,
                )
            if state == "running":
                self.transport.interrupt(prompt_id)
            self.transport.delete_queued(prompt_id)
            self._unload(spec, prompt_id)
        except (KeyError, OSError, RuntimeError, ValueError):
            return self._error(
                request,
                provider_ref=provider_opaque_ref,
                code="comfyui_cancel_uncertain",
                message="The exact ComfyUI cancellation could not be verified.",
                recovery=True,
            )
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_opaque_ref,
            status="cancelled",
            progress=0,
            message="The exact ComfyUI job was cancelled and its models were unloaded.",
            updated_at=self.clock(),
        )


__all__ = [
    "COMFYUI_PROVIDER_VERSION",
    "COMFYUI_WORKFLOW_PARAMETER",
    "ComfyUIHTTPTransport",
    "ComfyUIMaterialProductionAdapter",
    "ComfyUIProviderConfig",
    "ComfyUITransport",
    "ComfyUIWorkflowBinding",
    "ComfyUIWorkflowSpec",
    "load_comfyui_provider_config",
    "provider_config_path",
]
