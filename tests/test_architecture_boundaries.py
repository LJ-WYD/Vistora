import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
AGENT_DIR = SRC / "agent"

# Agents may inspect read-only context and invoke registered skills, but these
# modules expose timeline/media mutation mechanisms that belong behind tools.
FORBIDDEN_AGENT_IMPORTS = {
    "core.timeline",
    "core.timeline_manager",
    "subprocess",
    "utils.hardware",
    "utils.proxy",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_agents_do_not_import_mutation_engines() -> None:
    violations: dict[str, list[str]] = {}
    for path in sorted(AGENT_DIR.glob("*.py")):
        forbidden = sorted(_imports(path) & FORBIDDEN_AGENT_IMPORTS)
        if forbidden:
            violations[path.name] = forbidden

    assert not violations, (
        "Agent modules must dispatch registered atomic tools instead of "
        f"importing timeline/media mutation engines directly: {violations}"
    )


def test_trace_queries_and_visualization_do_not_import_mutation_engines() -> None:
    read_only_modules = (
        SRC / "traceability" / "query.py",
        SRC / "timeline_preview" / "server.py",
        SRC / "media_analysis" / "service.py",
    )
    forbidden = {
        "core.timeline_manager",
        "skills",
        "skills.video_add_clip",
        "skills.video_modify_clip",
        "skills.video_apply_manual_edits",
    }
    violations = {
        path.relative_to(SRC).as_posix(): sorted(_imports(path) & forbidden)
        for path in read_only_modules
        if _imports(path) & forbidden
    }
    assert not violations, (
        "Read/query/visualization modules must not import timeline mutation "
        f"engines or atomic skill implementations: {violations}"
    )


def test_public_registry_exports_valid_unique_skill_schemas() -> None:
    sys.path.insert(0, str(SRC))
    try:
        import main
        from skills.base import BaseSkill
    finally:
        sys.path.pop(0)

    exported_names: list[str] = []
    for registry_name, skill in main.SKILLS.items():
        assert isinstance(skill, BaseSkill)
        schema = skill.get_schema()
        assert registry_name == skill.name == schema["name"]
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        exported_names.append(schema["name"])

    assert len(exported_names) == len(set(exported_names))
