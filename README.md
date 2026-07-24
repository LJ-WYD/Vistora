# Vistora

Vistora is an early-stage, agent-driven video editing prototype. It represents edits as a declarative timeline and applies them through small, schema-validated editing skills backed by MoviePy and FFmpeg.

The current public baseline contains the editing runtime and two architecture chapters. Generated media, local workspaces, model weights, credentials, and machine-specific investigation scripts are intentionally excluded.

## Architecture

- The agent layer translates an editing request into calls to registered skills.
- Each skill validates its input with a Pydantic model and performs one bounded editing operation.
- `TimelineManager` persists the active declarative timeline in the local workspace.
- `TimelineRenderer` is responsible for producing media from that timeline.
- `TimelineSnapshotService` exposes detached, immutable read models for inspection without changing timeline or media state.

The intended architecture keeps creative planning separate from execution: a Director Agent produces a structured plan for user confirmation, an Editing Agent validates and executes that confirmed plan, and only atomic tools mutate timeline or media state. The current implementation is a prototype and does not yet implement every part of that target contract.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the implemented runtime, binding responsibility contracts, compatibility exceptions, and current-to-target gap register.

## Requirements

- Python 3.10 or newer
- FFmpeg and `ffprobe` available on `PATH`
- An OpenAI-compatible endpoint only when using interactive chat

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` in `.env` for the interactive agent. Never commit `.env`.

## Usage

List the registered atomic skills and their schemas:

```powershell
python src/main.py list-skills
```

Start the interactive editing agent:

```powershell
python src/main.py chat
```

Render a declarative timeline:

```powershell
python src/main.py render --config path\to\timeline.json --output output\result.mp4
```

Run one skill directly:

```powershell
python src/main.py run-skill --name VideoClearTimelineSkill --params "{}"
```

Read the current timeline without changing it:

```python
from timeline_query import TimelineSnapshotService

snapshot = TimelineSnapshotService.snapshot_current()
print(snapshot.model_dump_json(indent=2))
```

The `vistora.timeline-snapshot` output is versioned and deterministic. It includes project/revision identity, configured tracks and clips, source references, declared timing, and aggregate duration/count fields. The service accepts a current `TimelineConfig`, legacy timeline JSON, or a versioned `TimelineProjectDocument`. It does not probe media, save state, render, or expose mutable source models. Add `src` to `PYTHONPATH` when invoking this library directly from the repository root.

## Validation

The integration validation creates its own synthetic source clip and generated outputs under `tests/test_data/`:

```powershell
python tests/run_validation.py
```

Run the deterministic contract-to-atomic-tool reference workflow:

```powershell
python -m pytest -q tests/test_reference_workflow.py
```

This reference is a test harness; it does not implement production Director or Editing Agents.

Generated validation media and local runtime state are ignored by Git.

## Project status

Vistora is pre-alpha. Interfaces, schemas, rendering behavior, and hardware acceleration support may change. Review generated timelines and outputs before relying on them.

## Naming and compatibility

The product and public repository are named Vistora. Existing checkouts may still use an `AetherEdit` directory name; the directory name is not part of the runtime contract and does not need to be changed.

This naming release intentionally keeps existing Python module paths, `OperatorAgent`, and atomic skill identifiers such as `VideoAddClipSkill` unchanged. They are technical compatibility surfaces or domain terms rather than public product branding.

## Security and privacy

Treat source footage, generated proxies, timeline files, and model credentials as sensitive. Keep them in ignored local directories, inspect changes before committing, and avoid sharing `.env` or runtime workspaces.

## License

No open-source license has been selected for this repository yet. The source is publicly visible, but no reuse license is granted.
