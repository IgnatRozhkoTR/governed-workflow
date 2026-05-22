"""Tests for services.configurator_service.

Sub-phase 3.1: a Configurator chain renders project-level config files from
DB state. SkillConfigurator is the only built-in configurator and is
responsible for templating SKILL.md from SKILL.md.template plus every
enabled phase's description_for_skill().
"""

import logging
from datetime import datetime
from pathlib import Path

import pytest

from core.db import get_db
from services.configurator_service import (
    Configurator,
    ConfiguratorChain,
    SkillConfigurator,
)


SKILL_TEMPLATE_REL = SkillConfigurator.TEMPLATE_REL_PATH
SKILL_OUTPUT_REL = SkillConfigurator.OUTPUT_REL_PATH
SAMPLE_TEMPLATE = (
    "---\nname: governed-workflow\ndescription: x\n---\n\n"
    "# Top heading\n\nPreamble.\n\n{{PHASES}}\n\nFooter.\n"
)


@pytest.fixture
def db(clean_db):
    conn = get_db()
    yield conn
    conn.close()


@pytest.fixture
def project_root(tmp_path):
    """Temp project directory with the SKILL.md.template placed at the canonical path."""
    root = tmp_path / "proj"
    (root / SKILL_TEMPLATE_REL).parent.mkdir(parents=True)
    (root / SKILL_TEMPLATE_REL).write_text(SAMPLE_TEMPLATE)
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
        "created, status, phase, scope_json, plan_json, source_branch) "
        "VALUES (?, ?, ?, ?, ?, ?, '0', '{}', '{}', 'develop')",
        (project_id, branch, branch.replace("/", "-"), str(working_dir),
         datetime.now().isoformat(), status),
    )
    db.commit()
    return cur.lastrowid


# ── SkillConfigurator: template discovery ──────────────────────────────────────


def test_template_missing_logs_warning_and_writes_nothing(db, project_row, tmp_path, caplog):
    """When SKILL.md.template is absent, the configurator logs and skips silently."""
    empty_root = tmp_path / "no-template"
    empty_root.mkdir()

    with caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        SkillConfigurator().configure(db, project_row, empty_root)

    assert not (empty_root / SKILL_OUTPUT_REL).exists()
    assert any("template missing" in r.getMessage() for r in caplog.records)


def test_template_lacking_placeholder_logs_warning_and_writes_nothing(
    db, project_row, tmp_path, caplog
):
    """A template without the {{PHASES}} marker is left untouched."""
    root = tmp_path / "no-placeholder"
    (root / SKILL_TEMPLATE_REL).parent.mkdir(parents=True)
    (root / SKILL_TEMPLATE_REL).write_text("# No placeholder here\n")

    with caplog.at_level(logging.WARNING, logger="services.configurator_service"):
        SkillConfigurator().configure(db, project_row, root)

    assert not (root / SKILL_OUTPUT_REL).exists()
    assert any("placeholder" in r.getMessage() for r in caplog.records)


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

    phase_ids = phase_resolver.resolve_for_project(db, project_row)
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


# ── ConfiguratorChain ──────────────────────────────────────────────────────────


def test_default_chain_includes_skill_configurator():
    chain = ConfiguratorChain.default()
    assert any(isinstance(c, SkillConfigurator) for c in chain._configurators)


def test_chain_continues_when_a_configurator_raises(db, project_row, project_root, caplog):
    """A raising configurator is logged but does not stop later configurators."""
    calls: list[str] = []

    class _Boom(Configurator):
        def configure(self, db, project_id, project_path):
            calls.append("boom")
            raise RuntimeError("intentional failure")

    class _Recorder(Configurator):
        def configure(self, db, project_id, project_path):
            calls.append("recorder")

    chain = ConfiguratorChain([_Boom(), _Recorder()])
    with caplog.at_level(logging.ERROR, logger="services.configurator_service"):
        chain.run(db, project_row, project_root)

    assert calls == ["boom", "recorder"]
    assert any("Configurator _Boom failed" in r.getMessage() for r in caplog.records)


def test_chain_run_executes_configurators_in_order(db, project_row, project_root):
    """Configurators are invoked in declared order."""
    order: list[str] = []

    class _A(Configurator):
        def configure(self, db, project_id, project_path):
            order.append("a")

    class _B(Configurator):
        def configure(self, db, project_id, project_path):
            order.append("b")

    chain = ConfiguratorChain([_A(), _B()])
    chain.run(db, project_row, project_root)
    assert order == ["a", "b"]
