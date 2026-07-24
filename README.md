# AetherEdit

AetherEdit is an early-stage, agent-driven video editing prototype. It represents edits as a declarative timeline and applies them through small, schema-validated editing skills backed by MoviePy and FFmpeg.

The current public baseline contains the editing runtime and two architecture chapters. Generated media, local workspaces, model weights, credentials, and machine-specific investigation scripts are intentionally excluded.

## Architecture

- The agent layer translates an editing request into calls to registered skills.
- Each skill validates its input with a Pydantic model and performs one bounded editing operation.
- `TimelineManager` owns the in-memory declarative timeline.
- `TimelineRenderer` is responsible for producing media from that timeline.

The intended architecture keeps creative planning separate from execution: a Director Agent produces a structured plan for user confirmation, an Editing Agent validates and executes that confirmed plan, and only atomic tools mutate timeline or media state. The current implementation is a prototype and does not yet implement every part of that target contract.

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

## Validation

The integration validation creates its own synthetic source clip and generated outputs under `tests/test_data/`:

```powershell
python tests/run_validation.py
```

Generated validation media and local runtime state are ignored by Git.

## Project status

AetherEdit is pre-alpha. Interfaces, schemas, rendering behavior, and hardware acceleration support may change. Review generated timelines and outputs before relying on them.

## Security and privacy

Treat source footage, generated proxies, timeline files, and model credentials as sensitive. Keep them in ignored local directories, inspect changes before committing, and avoid sharing `.env` or runtime workspaces.

## License

No open-source license has been selected for this repository yet. The source is publicly visible, but no reuse license is granted.
