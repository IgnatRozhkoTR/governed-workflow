"""Integration tests: workspace creation invokes the configurator chain.

Sub-phase 3.1: every mutator endpoint that can change the rendered phase set
must re-run the SkillConfigurator. ``create_workspace`` triggers it after
``_register_workspace`` so SKILL.md is regenerated for the new worktree.
"""

from unittest.mock import MagicMock, patch

import pytest


def test_create_workspace_invokes_configurator(client, project):
    """A successful workspace POST runs the configurator chain once."""
    with patch("routes.workspaces.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.return_value = []
        MockChain.default.return_value = chain_instance

        response = client.post(
            f"/api/projects/{project['id']}/workspaces",
            json={"branch": "feature/trigger-cfg", "source": "develop", "worktree": True},
        )

    assert response.status_code == 201
    chain_instance.run.assert_called_once()
    args, _ = chain_instance.run.call_args
    # signature: (db, project_id, project_path)
    assert args[1] == project["id"]
    assert str(args[2]) == project["path"]


def test_create_workspace_succeeds_when_configurator_raises(client, project):
    """Configurator failure must NOT propagate to a 500."""
    with patch("routes.workspaces.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.side_effect = RuntimeError("simulated configurator boom")
        MockChain.default.return_value = chain_instance

        response = client.post(
            f"/api/projects/{project['id']}/workspaces",
            json={"branch": "feature/trigger-fail", "source": "develop", "worktree": True},
        )

    assert response.status_code == 201
    chain_instance.run.assert_called_once()


def test_create_workspace_does_not_invoke_chain_when_branch_missing(client, project):
    """Validation failures short-circuit before the configurator is consulted."""
    with patch("routes.workspaces.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.return_value = []
        MockChain.default.return_value = chain_instance

        response = client.post(
            f"/api/projects/{project['id']}/workspaces",
            json={"source": "develop"},
        )

    assert response.status_code == 400
    chain_instance.run.assert_not_called()


def test_create_workspace_does_not_invoke_chain_for_duplicate_branch(client, project):
    """Duplicate-branch (409) short-circuits before the configurator runs."""
    first = client.post(
        f"/api/projects/{project['id']}/workspaces",
        json={"branch": "feature/dup-cfg", "source": "develop", "worktree": True},
    )
    assert first.status_code == 201

    with patch("routes.workspaces.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.return_value = []
        MockChain.default.return_value = chain_instance

        second = client.post(
            f"/api/projects/{project['id']}/workspaces",
            json={"branch": "feature/dup-cfg", "source": "develop", "worktree": True},
        )

    assert second.status_code == 409
    chain_instance.run.assert_not_called()
