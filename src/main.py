"""Vistora command-line and local product composition entry."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone


sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from atomic_runtime import (  # noqa: E402
    AtomicExecutionContext,
    AtomicExecutionGateway,
    build_production_registry,
)
from contracts import AtomicToolRequestEnvelope, PlanReference  # noqa: E402
from core.timeline import TimelineConfig, TimelineRenderer  # noqa: E402


PRODUCTION_REGISTRY = build_production_registry()
# Legacy OperatorAgent and historical tests may still mutate this compatibility
# view. Production entry points consume only PRODUCTION_REGISTRY.
SKILLS = dict(PRODUCTION_REGISTRY)
ATOMIC_GATEWAY = AtomicExecutionGateway(PRODUCTION_REGISTRY)


def list_skills() -> None:
    """Print the stable public production registry and skill descriptors."""

    payload = {
        "schema_name": "vistora.atomic-skill-registry",
        "schema_version": "1.0.0",
        "registry": PRODUCTION_REGISTRY.reference.model_dump(mode="json"),
        "skills": [
            descriptor.model_dump(mode="json")
            for descriptor in PRODUCTION_REGISTRY.public_descriptors()
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def render_timeline(timeline_json_path: str, output_path: str) -> None:
    """Legacy direct-render compatibility command (architecture gap G-06)."""

    with open(timeline_json_path, "r", encoding="utf-8") as source:
        config = TimelineConfig(**json.load(source))
    TimelineRenderer(config).render(output_path)
    print(json.dumps({
        "schema_name": "vistora.cli.render-result",
        "schema_version": "1.0.0",
        "status": "success",
        "output_path": output_path,
    }, indent=2, ensure_ascii=False))


def run_skill(skill_name: str, params_json: str) -> None:
    """Low-level compatibility entry constrained by the atomic gateway."""

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "schema_name": "vistora.cli.atomic-result",
            "schema_version": "1.0.0",
            "status": "error",
            "error": {"code": "invalid_json", "message": str(exc)},
        }, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc

    invocation = uuid.uuid4().hex
    confirmation_id = f"cli_confirmation_{invocation}"
    project_id = "project_cli_compatibility"
    request = AtomicToolRequestEnvelope(
        request_id=f"request_cli_{invocation}",
        execution_id=f"execution_cli_{invocation}",
        project_id=project_id,
        confirmation_id=confirmation_id,
        plan_ref=PlanReference(
            plan_id=f"plan_cli_{invocation}",
            plan_version=1,
            plan_digest="sha256:" + ("0" * 64),
        ),
        step_id=f"step_cli_{invocation}",
        tool_name=skill_name,
        arguments=params,
        requested_at=datetime.now(timezone.utc),
    )
    context = AtomicExecutionContext(
        caller="cli_compatibility",
        registry_ref=PRODUCTION_REGISTRY.reference,
        project_id=project_id,
        confirmation_id=confirmation_id,
        allowed_side_effects=("external", "files", "media", "timeline"),
        idempotency_key=f"idempotency_cli_{invocation}",
        low_level_manual_acknowledged=True,
    )
    result = ATOMIC_GATEWAY.execute(request, context)
    print(json.dumps(
        result.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    ))
    if result.status != "success":
        raise SystemExit(1)


def chat_loop() -> None:
    """Run the explicitly legacy OperatorAgent compatibility loop."""

    from agent.operator_agent import OperatorAgent

    agent = OperatorAgent(SKILLS)
    print(
        "Vistora legacy OperatorAgent compatibility chat. "
        "Use 'studio' for the confirmed production workflow."
    )
    while True:
        try:
            prompt = input("\nUser: ")
            if prompt.strip().lower() in {"exit", "quit", "q"}:
                break
            if prompt.strip():
                print(f"\nAgent:\n{agent.run(prompt)}")
        except (EOFError, KeyboardInterrupt):
            break


def preview_timeline(
    timeline_path: str | None,
    media_roots: list[str],
    host: str,
    port: int,
    plan_review_path: str | None,
    director_history_path: str | None,
) -> None:
    """Start the local snapshot-first timeline UI."""

    from timeline_preview import run_preview_server

    run_preview_server(
        timeline_path=timeline_path,
        media_roots=media_roots,
        host=host,
        port=port,
        skill_registry=PRODUCTION_REGISTRY,
        plan_review_path=plan_review_path,
        director_history_path=director_history_path,
    )


def production_studio(
    media_roots: list[str],
    host: str,
    port: int,
    session_id: str,
) -> None:
    """Start the confirmed Director/material/editing product entry."""

    from product_entry import build_current_product_entry
    from timeline_preview import run_preview_server

    product = build_current_product_entry(
        PRODUCTION_REGISTRY,
        session_id=session_id,
    )
    run_preview_server(
        media_roots=media_roots,
        host=host,
        port=port,
        skill_registry=PRODUCTION_REGISTRY,
        product_entry_service=product,
        plan_review_request_provider=product.latest_review_request,
        director_history_provider=product.director_history,
    )


def _add_server_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--media-root",
        action="append",
        default=[],
        help="Explicit allowlisted local media root; may be repeated.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        choices=["127.0.0.1", "::1", "localhost"],
        help="Loopback interface to bind.",
    )
    parser.add_argument("--port", type=int, default=8765)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vistora local CLI")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "list-skills",
        help="Print the versioned atomic registry and public schemas.",
    )

    render = commands.add_parser(
        "render",
        help="Legacy direct render of a declarative timeline.",
    )
    render.add_argument("--config", required=True)
    render.add_argument("--output", required=True)

    run = commands.add_parser(
        "run-skill",
        help="Low-level manual compatibility dispatch through the gateway.",
    )
    run.add_argument("--name", required=True)
    run.add_argument("--params", required=True)
    commands.add_parser(
        "chat",
        help="Legacy OperatorAgent compatibility chat.",
    )

    preview = commands.add_parser(
        "preview",
        help="Start the local snapshot-first visual timeline.",
    )
    preview.add_argument("--timeline")
    preview.add_argument("--plan-review")
    preview.add_argument("--director-history")
    _add_server_arguments(preview)

    studio = commands.add_parser(
        "studio",
        help="Start the confirmed production product entry.",
    )
    studio.add_argument(
        "--session-id",
        default="session_local_product",
        help="Stable opaque local product session ID.",
    )
    _add_server_arguments(studio)

    args = parser.parse_args()
    if args.command == "list-skills":
        list_skills()
    elif args.command == "render":
        render_timeline(args.config, args.output)
    elif args.command == "run-skill":
        run_skill(args.name, args.params)
    elif args.command == "chat":
        chat_loop()
    elif args.command == "preview":
        preview_timeline(
            args.timeline,
            args.media_root,
            args.host,
            args.port,
            args.plan_review,
            args.director_history,
        )
    elif args.command == "studio":
        production_studio(
            args.media_root,
            args.host,
            args.port,
            args.session_id,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
