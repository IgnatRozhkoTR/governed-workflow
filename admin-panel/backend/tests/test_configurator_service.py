"""Tests for services.configurator_service.

A Configurator chain renders project-level config files from DB state.
SkillConfigurator templates SKILL.md, AgentFilesConfigurator mirrors the
canonical agent set into each active worktree, and StopHookConfigurator
backfills the Stop hook into pre-existing worktree settings files.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from core.db import get_db
from services.configurator_service import (
    AgentFilesConfigurator,
    Configurator,
    ConfiguratorChain,
    SkillConfigurator,
    StopHookConfigurator,
    _rendered,
)


SKILL_TEMPLATE_REL = SkillConfigurator.TEMPLATE_REL_PATH
SKILL_OUTPUT_REL = SkillConfigurator.OUTPUT_REL_PATH
SAMPLE_TEMPLATE = (
    "---\nname: governed-workflow\ndescription: x\n---\n\n"
    "# Top heading\n\nPreamble.\n\n{{PHASES}}\n\nFooter.\n"
)
SAMPLE_TEMPLATE_WITH_MAP = (
    "---\nname: governed-workflow\ndescription: x\n---\n\n"
    "# Top heading\n\n## Phase Map\n\n{{PHASE_MAP}}\n\n{{PHASES}}\n"
)


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture
def default_template(tmp_path):
    """Point ``SkillConfigurator.DEFAULT_TEMPLATE_PATH`` at a temp SAMPLE_TEMPLATE.

    The configurator always renders from the engine default; tests patch that
    path rather than seeding a (now-ignored) project-local template.
    """
    template = tmp_path / "default-skills" / "governed-workflow" / "SKILL.md.template"
    template.parent.mkdir(parents=True)
    template.write_text(SAMPLE_TEMPLATE)
    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", template):
        yield template


@pytest.fixture
def default_template_with_map(tmp_path):
    """Point the engine template at a temp SAMPLE_TEMPLATE_WITH_MAP for Phase Map tests."""
    template = tmp_path / "default-skills-map" / "governed-workflow" / "SKILL.md.template"
    template.parent.mkdir(parents=True)
    template.write_text(SAMPLE_TEMPLATE_WITH_MAP)
    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", template):
        yield template


@pytest.fixture
def project_root(tmp_path, default_template):
    """Temp project directory that exists on disk (template comes from the engine default)."""
    root = tmp_path / "proj"
    root.mkdir()
    return root


@pytest.fixture
def project_row(db, project_root):
    """Insert a project row pointed at ``project_root`` and return its id."""
    project_id = "configurator-test-project"
    db.execute(
        "INSERT INTO projects (id, name, path, registered) VALUES (?, ?, ?, ?)",
        (project_id, "Configurator Test", str(project_root), datetime.now().isoformat()),
    )
    db.commit()
    return project_id


def _insert_worktree(db, project_id: str, branch: str, working_dir: Path, status: str = "active") -> int:
    cur = db.execute(
        "INSERT INTO workspaces (project_id, branch, sanitized_branch, working_dir, "
        "created, status, phase, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, ?, '0', '{}', 'develop')",
        (project_id, branch, branch.replace("/", "-"), str(working_dir),
         datetime.now().isoformat(), status),
    )
    db.commit()
    return cur.lastrowid


# ── SkillConfigurator: template discovery ──────────────────────────────────────


def test_engine_template_missing_logs_warning_and_writes_nothing(
    db, project_row, tmp_path, caplog
):
    """When the engine template does not exist, the configurator skips."""
    empty_root = tmp_path / "no-template"
    empty_root.mkdir()
    missing_default = tmp_path / "no-default" / "SKILL.md.template"

    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", missing_default), \
         caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        results = SkillConfigurator().configure(db, project_row, empty_root)

    assert not (empty_root / SKILL_OUTPUT_REL).exists()
    assert any("template missing" in r.getMessage() for r in caplog.records)
    assert results == [{"target": "SKILL.md", "action": "skipped", "reason": "template missing"}]


def test_renders_from_engine_template_ignoring_stale_project_local_copy(
    db, project_row, tmp_path, default_template
):
    """A stale project-local template is ignored; rendering uses the engine default."""
    root = tmp_path / "with-stale-local"
    (root / SKILL_TEMPLATE_REL).parent.mkdir(parents=True)
    (root / SKILL_TEMPLATE_REL).write_text("# Stale local copy\n\n{{PHASES}}\n")

    results = SkillConfigurator().configure(db, project_row, root)

    body = (root / SKILL_OUTPUT_REL).read_text()
    assert "{{PHASES}}" not in body
    assert "Preamble." in body and "Footer." in body
    assert "Stale local copy" not in body
    assert all(r["action"] == "rendered" for r in results)


def test_engine_template_lacking_placeholder_logs_warning_and_writes_nothing(
    db, project_row, tmp_path, caplog
):
    """An engine template without the {{PHASES}} marker leaves the output untouched."""
    root = tmp_path / "no-placeholder"
    root.mkdir()
    bad_template = tmp_path / "bad-default" / "SKILL.md.template"
    bad_template.parent.mkdir(parents=True)
    bad_template.write_text("# No placeholder here\n")

    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", bad_template), \
         caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        SkillConfigurator().configure(db, project_row, root)

    assert not (root / SKILL_OUTPUT_REL).exists()
    assert any("placeholder" in r.getMessage() for r in caplog.records)


# ── SkillConfigurator: module override template ────────────────────────────────


def _make_module_with_skill_template_override(root: Path, module_id: str, template_content: str) -> Path:
    mod_dir = root / module_id
    mod_dir.mkdir(parents=True)
    (mod_dir / "SKILL.md").write_text(f"---\nname: {module_id}\n---\n")
    override_dir = mod_dir / "override" / "skills" / "governed-workflow"
    override_dir.mkdir(parents=True)
    (override_dir / "SKILL.md.template").write_text(template_content)
    return mod_dir


def test_enabled_module_template_override_used_when_present(
    db, project_row, project_root, tmp_path, default_template, caplog
):
    modules_root = tmp_path / "modules"
    override_template = (
        "---\nname: governed-workflow\ndescription: x\n---\n\n"
        "# Module Override Heading\n\nPreamble.\n\n{{PHASES}}\n\nFooter.\n"
    )
    _make_module_with_skill_template_override(modules_root, "mod-a", override_template)
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        ("mod-a", "2024-01-01T00:00:00"),
    )
    db.commit()

    with patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]), \
         caplog.at_level(logging.DEBUG, logger="services.configurator_service"):
        SkillConfigurator().configure(db, project_row, project_root)

    body = (project_root / SKILL_OUTPUT_REL).read_text()
    assert "# Module Override Heading" in body
    assert any("module override template" in r.getMessage() for r in caplog.records)


def test_disabled_module_template_override_reverts_to_engine_default(
    db, project_row, project_root, tmp_path, default_template
):
    """Disabling the module and re-rendering falls back to the engine default template."""
    modules_root = tmp_path / "modules"
    override_template = (
        "---\nname: governed-workflow\ndescription: x\n---\n\n"
        "# Module Override Heading\n\nPreamble.\n\n{{PHASES}}\n\nFooter.\n"
    )
    _make_module_with_skill_template_override(modules_root, "mod-a", override_template)
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        ("mod-a", "2024-01-01T00:00:00"),
    )
    db.commit()

    with patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        SkillConfigurator().configure(db, project_row, project_root)
    assert "# Module Override Heading" in (project_root / SKILL_OUTPUT_REL).read_text()

    db.execute("DELETE FROM modules_enabled WHERE module_id = ?", ("mod-a",))
    db.commit()

    with patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        SkillConfigurator().configure(db, project_row, project_root)

    body = (project_root / SKILL_OUTPUT_REL).read_text()
    assert "# Module Override Heading" not in body
    assert "Preamble." in body and "Footer." in body


def test_last_enabled_module_template_override_wins_on_collision(
    db, project_row, project_root, tmp_path, default_template
):
    modules_root = tmp_path / "modules"
    first_template = (
        "---\nname: governed-workflow\ndescription: x\n---\n\n# From First Module\n\n{{PHASES}}\n"
    )
    second_template = (
        "---\nname: governed-workflow\ndescription: x\n---\n\n# From Second Module\n\n{{PHASES}}\n"
    )
    _make_module_with_skill_template_override(modules_root, "mod-first", first_template)
    _make_module_with_skill_template_override(modules_root, "mod-second", second_template)
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        ("mod-first", "2024-01-01T00:00:00"),
    )
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        ("mod-second", "2024-01-02T00:00:00"),
    )
    db.commit()

    with patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        SkillConfigurator().configure(db, project_row, project_root)

    body = (project_root / SKILL_OUTPUT_REL).read_text()
    assert "# From Second Module" in body
    assert "# From First Module" not in body


def test_missing_project_path_skips_root_but_still_renders_worktrees(
    db, project_row, project_root, tmp_path, caplog
):
    """A deleted project root is skipped (not recreated); active worktrees still render."""
    deleted_root = tmp_path / "deleted-proj"
    wt = tmp_path / "wt-live"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/live", wt, status="active")

    with caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        results = SkillConfigurator().configure(db, project_row, deleted_root)

    assert not deleted_root.exists()
    assert (wt / SKILL_OUTPUT_REL).exists()
    root_target = str(deleted_root / SKILL_OUTPUT_REL)
    assert {"target": root_target, "action": "skipped", "reason": "project path missing"} in results
    assert any("project path" in r.getMessage() and "missing" in r.getMessage()
               for r in caplog.records)


# ── SkillConfigurator: rendering ───────────────────────────────────────────────


def test_renders_skill_md_to_project_path_when_no_worktrees(db, project_row, project_root):
    """With zero active worktrees only the project-level SKILL.md is written."""
    SkillConfigurator().configure(db, project_row, project_root)

    project_skill = project_root / SKILL_OUTPUT_REL
    assert project_skill.exists()
    content = project_skill.read_text()
    assert "{{PHASES}}" not in content
    assert "Preamble." in content and "Footer." in content


def test_renders_skill_md_to_every_active_worktree(db, project_row, project_root, tmp_path):
    """An active worktree receives its own copy of the rendered SKILL.md.

    A second worktree (still active) and an archived worktree exercise both
    "multiple active" and "non-active skipped" branches.
    """
    wt_a = tmp_path / "wt-a"
    wt_b = tmp_path / "wt-b"
    wt_archived = tmp_path / "wt-archived"
    for d in (wt_a, wt_b, wt_archived):
        d.mkdir()

    _insert_worktree(db, project_row, "feature/a", wt_a, status="active")
    _insert_worktree(db, project_row, "feature/b", wt_b, status="active")
    _insert_worktree(db, project_row, "feature/old", wt_archived, status="archived")

    SkillConfigurator().configure(db, project_row, project_root)

    project_skill_content = (project_root / SKILL_OUTPUT_REL).read_text()
    assert (wt_a / SKILL_OUTPUT_REL).read_text() == project_skill_content
    assert (wt_b / SKILL_OUTPUT_REL).read_text() == project_skill_content
    assert not (wt_archived / SKILL_OUTPUT_REL).exists()


def test_rendered_block_joins_phase_descriptions_with_separator(db, project_row, project_root):
    """Phase blocks appear joined by the expected horizontal-rule separator."""
    SkillConfigurator().configure(db, project_row, project_root)

    body = (project_root / SKILL_OUTPUT_REL).read_text()

    # Pull descriptions from the resolver and confirm both presence and ordering.
    from advance.phases import get_phase
    from services import phase_resolver

    phase_ids = phase_resolver.resolve_for_project(db, project_row, include_templated=True)
    blocks = []
    for pid in phase_ids:
        phase = get_phase(pid)
        if phase is None:
            continue
        text = phase.description_for_skill().strip()
        if text:
            blocks.append(text)
    expected = "\n\n---\n\n".join(blocks)

    assert expected in body, "rendered SKILL.md is missing the joined phase block"


def test_configure_is_idempotent(db, project_row, project_root):
    """Running configure twice produces byte-identical output."""
    SkillConfigurator().configure(db, project_row, project_root)
    first = (project_root / SKILL_OUTPUT_REL).read_text()

    SkillConfigurator().configure(db, project_row, project_root)
    second = (project_root / SKILL_OUTPUT_REL).read_text()

    assert first == second


def test_phase_map_placeholder_is_replaced_with_markdown_table(
    db, project_row, tmp_path, default_template_with_map
):
    """The {{PHASE_MAP}} placeholder is replaced with a Markdown table for enabled phases."""
    root = tmp_path / "with-map"
    root.mkdir()

    SkillConfigurator().configure(db, project_row, root)

    body = (root / SKILL_OUTPUT_REL).read_text()
    assert "{{PHASE_MAP}}" not in body
    assert "| Phase | Name | What happens | Edits | Commits | Push | Gate |" in body
    assert "| `0` | Init |" in body
    assert "| `1.4` | Preparation Review |" in body and "USER" in body
    # 4.1 is the only basic-mode phase where edits and commits are both ON.
    assert "| `4.1` | Address Fix" in body
    # The push column flips ON only at phase 6.
    assert "| `6` | Done |" in body


def test_phase_map_includes_templated_execution_rows(
    db, project_row, tmp_path, default_template_with_map
):
    """The templated 3.x.K execution rows render in the Phase Map, 3.x.3 as a USER gate."""
    root = tmp_path / "with-exec-map"
    root.mkdir()

    SkillConfigurator().configure(db, project_row, root)

    body = (root / SKILL_OUTPUT_REL).read_text()
    for k in range(5):
        assert f"| `3.x.{k}` |" in body, f"3.x.{k} execution row missing from Phase Map"
    gate_row = next(line for line in body.splitlines() if line.startswith("| `3.x.3` |"))
    assert "USER" in gate_row


def test_phases_block_includes_execution_descriptions(db, project_row, project_root):
    """The {{PHASES}} block carries the templated 3.N.K execution descriptions."""
    SkillConfigurator().configure(db, project_row, project_root)

    body = (project_root / SKILL_OUTPUT_REL).read_text()
    assert "## 3.N.0 Implementation" in body
    assert "## 3.N.3 Code Review (USER GATE)" in body
    assert "## 3.N.4 Commit" in body


def test_phase_map_omits_phases_disabled_at_project_scope(
    db, project_row, tmp_path, default_template_with_map
):
    """A project-level toggle drops the phase row from the rendered Phase Map."""
    from services.phase_settings import set_scope_settings

    root = tmp_path / "with-map-toggle"
    root.mkdir()

    set_scope_settings(db, "project", project_row, {"1.1": False})
    db.commit()

    SkillConfigurator().configure(db, project_row, root)

    body = (root / SKILL_OUTPUT_REL).read_text()
    assert "| `1.1` |" not in body
    assert "| `1.0` |" in body


def test_disabled_phase_is_absent_from_rendered_skill(db, project_row, project_root):
    """A project-level scope override that disables a phase removes it from SKILL.md."""
    from services.phase_settings import set_scope_settings

    # 1.1 is enabled in the basic mode by default; turn it off at the project scope.
    set_scope_settings(db, "project", project_row, {"1.1": False})
    db.commit()

    SkillConfigurator().configure(db, project_row, project_root)

    body = (project_root / SKILL_OUTPUT_REL).read_text()
    assert "## 1.1 Research" not in body
    # Sanity: an unrelated phase is still present.
    assert "## 1.0 Assessment" in body


_PHASE_MAP_HEADER = "| Phase | Name | What happens | Edits | Commits | Push | Gate |"
_MAP_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|")
_BODY_HEADING_RE = re.compile(r"^##\s+(?:Phase\s+)?(\d+(?:\.[\dNx]+)*)\b", re.MULTILINE)
_PHASE_REF_RE = re.compile(r"(?<![\w.])(\d+\.(?:\d+|[Nx])(?:\.(?:\d+|[Nx]))?)(?![\w.])")
_EXECUTION_REF_RE = re.compile(r"^3\.(?:\d+|[Nx])(?:\.(\d+|[Nx]))?$")

_TOGGLE_CASES = {
    # The four render variants of the untouched default phase set.
    "default": None,
    # Phase sets observed on real projects, where scope toggles dropped the
    # research, impact-analysis, validation and post-review-fix phases.
    "research-and-review-off": ["0", "1.0", "2.0", "3.x.0", "3.x.4", "4.2", "5.1", "5.2", "6"],
    # An arbitrary mid-sequence drop that no workflow mode would ever produce.
    "mid-sequence-drop": ["0", "1.0", "1.3", "1.4", "3.x.0", "3.x.1", "3.x.3", "3.x.4", "4.0", "4.2", "5.1", "6"],
    # Drops each phase that another phase's own summary or prose used to name.
    "referenced-phases-off": ["0", "1.1", "1.2", "2.0", "3.x.1", "3.x.2", "3.x.4", "4.1", "5.2", "6"],
}


def _canonical_phase_ref(ref: str) -> str:
    """Fold a rendered phase reference onto the id the resolver uses.

    Body sections label execution phases ``3.N.K`` and the Phase Map labels
    them ``3.x.K``; concrete plan items (``3.1.0``) belong to the same family.
    All three collapse to ``3.x.K``, and a bare sub-phase id (``3.1``) to
    ``3.x``.
    """
    match = _EXECUTION_REF_RE.match(ref)
    if not match:
        return ref
    step = match.group(1)
    return "3.x" if step is None else f"3.x.{step}"


def _phase_map_ids(rendered: str) -> set:
    """Phase ids that have a row in the rendered Phase Map table."""
    lines = rendered.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(_PHASE_MAP_HEADER))
    ids = set()
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        match = _MAP_ROW_RE.match(line)
        if match:
            ids.add(_canonical_phase_ref(match.group(1)))
    return ids


def _body_section_ids(rendered: str) -> set:
    """Phase ids that have a body section heading in the rendered skill."""
    return {_canonical_phase_ref(pid) for pid in _BODY_HEADING_RE.findall(rendered)}


def _referenced_phase_ids(rendered: str) -> set:
    """Every dotted phase id mentioned anywhere in the rendered skill."""
    return {_canonical_phase_ref(ref) for ref in _PHASE_REF_RE.findall(rendered)}


def _renderable_phase_ids(phase_ids: list) -> set:
    """The enabled set, plus the bare execution-family id its members imply."""
    allowed = set(phase_ids)
    if any(pid.startswith("3.x.") for pid in phase_ids):
        allowed.add("3.x")
    return allowed


def _default_phase_ids() -> list:
    """Resolve the clean-default phase set with no scope overrides applied."""
    from services import phase_resolver

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE phase_settings "
        "(scope_type TEXT, scope_id TEXT, phase_id TEXT, enabled INTEGER)"
    )
    try:
        return phase_resolver.resolve_for_project(conn, None, include_templated=True)
    finally:
        conn.close()


def _render_case(case: str, workflow_mode: str, simple_planning: bool):
    phase_ids = _TOGGLE_CASES[case] or _default_phase_ids()
    template = SkillConfigurator.DEFAULT_TEMPLATE_PATH.read_text()
    rendered = SkillConfigurator.render(
        template, phase_ids, simple_planning=simple_planning, workflow_mode=workflow_mode
    )
    return phase_ids, rendered


@pytest.mark.parametrize("case", sorted(_TOGGLE_CASES))
@pytest.mark.parametrize("workflow_mode", ["standard", "fast"])
@pytest.mark.parametrize("simple_planning", [False, True])
def test_rendered_skill_never_references_a_disabled_phase(case, workflow_mode, simple_planning):
    """No phase id outside the enabled set survives anywhere in the output.

    Phases are toggled per device/project/workspace scope, which is an axis
    the template's mode conditionals cannot see. Any hardcoded successor or
    transition reference therefore goes stale the moment a project turns that
    phase off, and mis-instructs the orchestrator at runtime. The document
    declares which phases exist and leaves routing to the backend, so every
    phase id it mentions must be one of its own enabled phases.
    """
    phase_ids, rendered = _render_case(case, workflow_mode, simple_planning)

    dangling = _referenced_phase_ids(rendered) - _renderable_phase_ids(phase_ids)

    assert not dangling, f"rendered skill references disabled phases: {sorted(dangling)}"


@pytest.mark.parametrize("case", sorted(_TOGGLE_CASES))
@pytest.mark.parametrize("workflow_mode", ["standard", "fast"])
@pytest.mark.parametrize("simple_planning", [False, True])
def test_phase_map_and_body_sections_cover_the_same_phases(case, workflow_mode, simple_planning):
    """Every phase with a body section has a Phase Map row and vice versa.

    The table and the body are built by two separate skip predicates
    (``short_description`` vs ``description_for_skill``). If they ever
    disagree, a phase is documented in one view and invisible in the other.
    """
    phase_ids, rendered = _render_case(case, workflow_mode, simple_planning)

    assert _phase_map_ids(rendered) == _body_section_ids(rendered)
    assert _phase_map_ids(rendered) == set(phase_ids)


def test_progress_documentation_states_no_phase_transitions():
    """The progress section names no successor phase.

    It used to tabulate rows like ``| 1.0 -> 1.1 | "1.0" |``, which named a
    phase that any project could switch off. Each phase section now carries
    its own progress requirement instead.
    """
    _, rendered = _render_case("default", "standard", False)

    section = rendered.split("## Progress Documentation", 1)[1]
    assert "→" not in section
    assert not _PHASE_REF_RE.findall(section)


def test_declarative_module_phase_appears_in_rendered_skill(
    db, project_row, tmp_path, default_template_with_map
):
    """A DeclarativePhase registered into PHASE_REGISTRY renders into SKILL.md.

    Regression guard: when WorkModes was removed, the resolver started reading
    from PHASE_REGISTRY directly, so module-contributed phases must flow
    through to the rendered SKILL.md (both the phase block and the Phase Map)
    without any extra wiring.
    """
    from advance.phases import PHASE_REGISTRY, register_phase
    from advance.phases.declarative import DeclarativePhase

    root = tmp_path / "with-module-phase"
    root.mkdir()

    manifest = {
        "id": "4.5",
        "name": "Module Phase",
        "description_for_skill": "## 4.5 Module Phase\n\nDeclarative module-contributed phase body.",
        "short_description": "Module-contributed step",
    }
    register_phase(DeclarativePhase(manifest))
    try:
        SkillConfigurator().configure(db, project_row, root)
        body = (root / SKILL_OUTPUT_REL).read_text()
        assert "## 4.5 Module Phase" in body
        assert "| `4.5` | Module Phase |" in body
    finally:
        PHASE_REGISTRY.pop("4.5", None)


# ── ConfiguratorChain ──────────────────────────────────────────────────────────


def test_default_chain_includes_skill_configurator():
    chain = ConfiguratorChain.default()
    assert any(isinstance(c, SkillConfigurator) for c in chain._configurators)


def test_default_chain_includes_agent_and_stop_hook_configurators():
    chain = ConfiguratorChain.default()
    assert any(isinstance(c, AgentFilesConfigurator) for c in chain._configurators)
    assert any(isinstance(c, StopHookConfigurator) for c in chain._configurators)


# ── AgentFilesConfigurator ─────────────────────────────────────────────────────


@pytest.fixture
def agent_source(tmp_path):
    src = tmp_path / "agents-src"
    src.mkdir()
    (src / "file-reviewer.md").write_text("---\nname: file-reviewer\n---\nbody\n")
    (src / "architecture-reviewer.md").write_text("---\nname: architecture-reviewer\n---\nbody\n")
    (src / "correctness-reviewer.md").write_text("---\nname: correctness-reviewer\n---\nbody\n")
    return src


def test_agent_files_configurator_copies_files_into_each_worktree(
    db, project_row, agent_source, tmp_path
):
    wt_a = tmp_path / "wt-a"
    wt_b = tmp_path / "wt-b"
    wt_a.mkdir(); wt_b.mkdir()
    _insert_worktree(db, project_row, "feature/a", wt_a, status="active")
    _insert_worktree(db, project_row, "feature/b", wt_b, status="active")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source):
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    for wt in (wt_a, wt_b):
        agents_dir = wt / ".claude" / "agents"
        assert (agents_dir / "file-reviewer.md").exists()
        assert (agents_dir / "architecture-reviewer.md").exists()
        assert (agents_dir / "correctness-reviewer.md").exists()


def test_agent_files_configurator_removes_stale_agents_in_worktree(
    db, project_row, agent_source, tmp_path
):
    """A worktree with an old logic-reviewer.md should have it deleted on sync."""
    wt = tmp_path / "wt"
    wt.mkdir()
    stale_dir = wt / ".claude" / "agents"
    stale_dir.mkdir(parents=True)
    (stale_dir / "logic-reviewer.md").write_text("old\n")
    (stale_dir / "security-reviewer.md").write_text("old\n")
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source):
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    assert not (stale_dir / "logic-reviewer.md").exists()
    assert not (stale_dir / "security-reviewer.md").exists()
    assert (stale_dir / "file-reviewer.md").exists()


def test_agent_files_configurator_skips_archived_worktrees(
    db, project_row, agent_source, tmp_path
):
    wt_archived = tmp_path / "archived"
    wt_archived.mkdir()
    _insert_worktree(db, project_row, "feature/old", wt_archived, status="archived")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source):
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    assert not (wt_archived / ".claude" / "agents").exists()


def test_agent_files_configurator_skips_when_source_missing(
    db, project_row, tmp_path, caplog
):
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")
    missing_src = tmp_path / "does-not-exist"

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", missing_src), \
         caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    assert not (wt / ".claude" / "agents").exists()
    assert any("source" in r.getMessage() and "missing" in r.getMessage()
               for r in caplog.records)


def test_agent_files_configurator_is_idempotent(
    db, project_row, agent_source, tmp_path
):
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source):
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    agents = sorted((wt / ".claude" / "agents").glob("*.md"))
    assert [a.name for a in agents] == [
        "architecture-reviewer.md",
        "correctness-reviewer.md",
        "file-reviewer.md",
    ]


# ── AgentFilesConfigurator: module overrides + project-local precedence ────────


def _enable_module(db, module_id: str, enabled_at: str) -> None:
    db.execute(
        "INSERT INTO modules_enabled (module_id, enabled_at) VALUES (?, ?)",
        (module_id, enabled_at),
    )
    db.commit()


def _make_module_with_agent_override(root: Path, module_id: str, filename: str, content: str) -> Path:
    mod_dir = root / module_id
    mod_dir.mkdir(parents=True)
    (mod_dir / "SKILL.md").write_text(f"---\nname: {module_id}\n---\n")
    override_dir = mod_dir / "override" / "agents"
    override_dir.mkdir(parents=True)
    (override_dir / filename).write_text(content)
    return mod_dir


def test_agent_files_configurator_applies_enabled_module_override(
    db, project_row, agent_source, tmp_path
):
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    modules_root = tmp_path / "modules"
    _make_module_with_agent_override(modules_root, "mod-a", "file-reviewer.md", "# Overridden by mod-a")
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source), \
         patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        AgentFilesConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    agents_dir = wt / ".claude" / "agents"
    assert (agents_dir / "file-reviewer.md").read_text() == "# Overridden by mod-a"
    assert "architecture-reviewer" in (agents_dir / "architecture-reviewer.md").read_text()


def test_agent_files_configurator_project_local_file_survives_rerender(
    db, project_row, agent_source, tmp_path
):
    """A project-local agents file overlays defaults and survives repeated re-renders.

    Regression guard: previously the configurator only ever mirrored the repo
    default set, so a project-local customization was clobbered on every run.
    """
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    project_root = tmp_path / "proj"
    project_agents_dir = project_root / ".claude" / "agents"
    project_agents_dir.mkdir(parents=True)
    (project_agents_dir / "custom.md").write_text("# Project custom agent")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source):
        AgentFilesConfigurator().configure(db, project_row, project_root)
        AgentFilesConfigurator().configure(db, project_row, project_root)

    agents_dir = wt / ".claude" / "agents"
    assert (agents_dir / "custom.md").read_text() == "# Project custom agent"
    assert (agents_dir / "file-reviewer.md").exists()


def test_agent_files_configurator_project_local_wins_over_module_override(
    db, project_row, agent_source, tmp_path
):
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    modules_root = tmp_path / "modules"
    _make_module_with_agent_override(modules_root, "mod-a", "file-reviewer.md", "# From module override")
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")

    project_root = tmp_path / "proj"
    project_agents_dir = project_root / ".claude" / "agents"
    project_agents_dir.mkdir(parents=True)
    (project_agents_dir / "file-reviewer.md").write_text("# Project always wins")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source), \
         patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        AgentFilesConfigurator().configure(db, project_row, project_root)

    agents_dir = wt / ".claude" / "agents"
    assert (agents_dir / "file-reviewer.md").read_text() == "# Project always wins"


def test_agent_files_configurator_override_removed_after_module_disabled(
    db, project_row, agent_source, tmp_path
):
    """Disabling a module and re-rendering restores the repo-default agent file."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    modules_root = tmp_path / "modules"
    _make_module_with_agent_override(modules_root, "mod-a", "file-reviewer.md", "# Overridden by mod-a")
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")
    project_root = tmp_path / "proj"

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source), \
         patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        AgentFilesConfigurator().configure(db, project_row, project_root)

    agents_dir = wt / ".claude" / "agents"
    assert (agents_dir / "file-reviewer.md").read_text() == "# Overridden by mod-a"

    db.execute("DELETE FROM modules_enabled WHERE module_id = ?", ("mod-a",))
    db.commit()

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source), \
         patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        AgentFilesConfigurator().configure(db, project_row, project_root)

    assert (agents_dir / "file-reviewer.md").read_text() == "---\nname: file-reviewer\n---\nbody\n"


def test_agent_files_configurator_stale_deletion_preserves_override_and_project_files(
    db, project_row, agent_source, tmp_path
):
    """Only files absent from the full composed set (defaults + overrides + project)
    are treated as stale; override-sourced and project-sourced files are kept."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    modules_root = tmp_path / "modules"
    _make_module_with_agent_override(modules_root, "mod-a", "module-only-agent.md", "# Module-only agent")
    _enable_module(db, "mod-a", "2024-01-01T00:00:00")

    project_root = tmp_path / "proj"
    project_agents_dir = project_root / ".claude" / "agents"
    project_agents_dir.mkdir(parents=True)
    (project_agents_dir / "project-only-agent.md").write_text("# Project-only agent")

    stale_dir = wt / ".claude" / "agents"
    stale_dir.mkdir(parents=True)
    (stale_dir / "retired-agent.md").write_text("old\n")

    with patch("services.configurator_service.DEFAULT_AGENTS_DIR", agent_source), \
         patch("services.configurator_service._MODULE_OVERRIDE_ROOTS", [modules_root]):
        AgentFilesConfigurator().configure(db, project_row, project_root)

    agents_dir = wt / ".claude" / "agents"
    assert not (agents_dir / "retired-agent.md").exists()
    assert (agents_dir / "module-only-agent.md").exists()
    assert (agents_dir / "project-only-agent.md").exists()
    assert (agents_dir / "file-reviewer.md").exists()


# ── StopHookConfigurator ───────────────────────────────────────────────────────


def _settings_with_hooks(extra_hooks: dict | None = None) -> dict:
    return {"hooks": extra_hooks or {}}


def test_stop_hook_configurator_adds_entry_when_absent(
    db, project_row, tmp_path
):
    wt = tmp_path / "wt"
    wt.mkdir()
    settings_path = wt / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(_settings_with_hooks()))
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    StopHookConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    body = json.loads(settings_path.read_text())
    stop_entries = body["hooks"]["Stop"]
    assert len(stop_entries) == 1
    cmd = stop_entries[0]["hooks"][0]["command"]
    assert "stop-advance-action.py" in cmd


def test_stop_hook_configurator_skips_when_settings_missing(
    db, project_row, tmp_path
):
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    StopHookConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    assert not (wt / ".claude" / "settings.json").exists()


def test_stop_hook_configurator_preserves_existing_hooks(
    db, project_row, tmp_path
):
    wt = tmp_path / "wt"
    wt.mkdir()
    settings_path = wt / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    existing = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": "echo other-stop"}]}
            ],
        }
    }
    settings_path.write_text(json.dumps(existing))
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    StopHookConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    body = json.loads(settings_path.read_text())
    assert body["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]
    stop_commands = [
        h["command"]
        for entry in body["hooks"]["Stop"]
        for h in entry["hooks"]
    ]
    assert "echo other-stop" in stop_commands
    assert any("stop-advance-action.py" in c for c in stop_commands)


def test_stop_hook_configurator_is_idempotent(db, project_row, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    settings_path = wt / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(_settings_with_hooks()))
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    StopHookConfigurator().configure(db, project_row, tmp_path / "irrelevant")
    first = settings_path.read_text()
    StopHookConfigurator().configure(db, project_row, tmp_path / "irrelevant")
    second = settings_path.read_text()

    assert first == second
    body = json.loads(second)
    assert len(body["hooks"]["Stop"]) == 1


def test_stop_hook_configurator_handles_invalid_json(
    db, project_row, tmp_path, caplog
):
    wt = tmp_path / "wt"
    wt.mkdir()
    settings_path = wt / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{not valid json")
    _insert_worktree(db, project_row, "feature/x", wt, status="active")

    with caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        StopHookConfigurator().configure(db, project_row, tmp_path / "irrelevant")

    assert "{not valid json" == settings_path.read_text()
    assert any("invalid JSON" in r.getMessage() for r in caplog.records)


def test_chain_continues_when_a_configurator_raises(db, project_row, project_root, caplog):
    """A raising configurator is logged, reported as failed, and does not stop the chain."""
    calls: list[str] = []

    class _Boom(Configurator):
        def configure(self, db, project_id, project_path):
            calls.append("boom")
            raise RuntimeError("intentional failure")

    class _Recorder(Configurator):
        def configure(self, db, project_id, project_path):
            calls.append("recorder")
            return [_rendered("recorder-target")]

    chain = ConfiguratorChain([_Boom(), _Recorder()])
    with caplog.at_level(logging.ERROR, logger="services.configurator_service"):
        results = chain.run(db, project_row, project_root)

    assert calls == ["boom", "recorder"]
    assert any("Configurator _Boom failed" in r.getMessage() for r in caplog.records)
    assert {"target": "_Boom", "action": "failed", "reason": "intentional failure"} in results
    assert {"target": "recorder-target", "action": "rendered", "reason": None} in results


def test_chain_run_executes_configurators_in_order(db, project_row, project_root):
    """Configurators are invoked in declared order and their results aggregate."""
    order: list[str] = []

    class _A(Configurator):
        def configure(self, db, project_id, project_path):
            order.append("a")
            return [_rendered("a")]

    class _B(Configurator):
        def configure(self, db, project_id, project_path):
            order.append("b")
            return [_rendered("b")]

    chain = ConfiguratorChain([_A(), _B()])
    results = chain.run(db, project_row, project_root)
    assert order == ["a", "b"]
    assert [r["target"] for r in results] == ["a", "b"]


def test_chain_run_accepts_project_path_as_plain_string(db, project_row, project_root, tmp_path):
    """Regression: route handlers pass ``project["path"]`` (a plain str sqlite3.Row column),
    not a Path. SkillConfigurator.configure must coerce it instead of crashing on
    ``str / str`` when building the project-root render target.
    """
    wt = tmp_path / "wt-str-path"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/str-path", wt, status="active")

    results = ConfiguratorChain.default().run(db, project_row, str(project_root))

    assert all(r["action"] != "failed" for r in results)
    assert (project_root / SKILL_OUTPUT_REL).exists()
    assert (wt / SKILL_OUTPUT_REL).exists()


def test_chain_run_returns_skipped_entries_for_missing_targets(db, project_row, tmp_path):
    """A skipped target surfaces as a non-rendered entry callers can attach as a warning."""
    empty_root = tmp_path / "skip-root"
    empty_root.mkdir()
    missing_default = tmp_path / "no-default" / "SKILL.md.template"
    missing_agents = tmp_path / "no-agents"

    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", missing_default), \
         patch("services.configurator_service.DEFAULT_AGENTS_DIR", missing_agents):
        results = ConfiguratorChain([SkillConfigurator(), AgentFilesConfigurator()]).run(
            db, project_row, empty_root
        )

    skipped = [r for r in results if r["action"] == "skipped"]
    assert {r["reason"] for r in skipped} == {"template missing", "source directory missing"}


def test_atomic_write_leaves_no_tmp_files(db, project_row, project_root, tmp_path):
    """Rendering leaves no ``.tmp`` siblings behind in any written directory."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _insert_worktree(db, project_row, "feature/atomic", wt, status="active")

    SkillConfigurator().configure(db, project_row, project_root)
    SkillConfigurator().configure(db, project_row, project_root)

    leftovers = list((project_root / ".claude" / "skills" / "governed-workflow").glob("*.tmp"))
    leftovers += list((wt / ".claude" / "skills" / "governed-workflow").glob("*.tmp"))
    assert leftovers == []
