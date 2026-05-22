"""Integration tests: phase-settings saves invoke the configurator chain.

Sub-phase 3.1: project- and workspace-level phase-settings mutations must
re-render SKILL.md. Device-level updates are intentionally NOT covered —
they touch every project's render and the existing code path does not run
the configurator there.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_project_phase_settings_put_invokes_configurator(client, project):
    """PUTing project-scope phase settings runs the chain once with project metadata."""
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/projects/{project['id']}/phase-settings",
            json={"settings": {"1.1": False}},
        )

    assert response.status_code == 200
    chain_instance.run.assert_called_once()
    args, _ = chain_instance.run.call_args
    # (db, project_id, project_path)
    assert args[1] == project["id"]
    assert args[2] == Path(project["path"])


def test_workspace_phase_settings_put_invokes_configurator(client, workspace, project):
    """PUTing workspace-scope phase settings runs the chain once for the parent project."""
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/ws/{workspace['project_id']}/{workspace['branch']}/phase-settings",
            json={"settings": {"1.1": False}},
        )

    assert response.status_code == 200
    chain_instance.run.assert_called_once()
    args, _ = chain_instance.run.call_args
    assert args[1] == project["id"]
    assert args[2] == Path(project["path"])


def test_project_phase_settings_put_succeeds_when_configurator_raises(client, project):
    """Configurator failure must NOT 500 the request — settings should still persist."""
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.side_effect = RuntimeError("boom")
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/projects/{project['id']}/phase-settings",
            json={"settings": {"1.1": False}},
        )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    # Confirm the settings reached the DB even though the chain raised.
    get_resp = client.get(f"/api/projects/{project['id']}/phase-settings")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["settings"]["1.1"] is False


def test_workspace_phase_settings_put_succeeds_when_configurator_raises(client, workspace):
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.side_effect = RuntimeError("boom")
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/ws/{workspace['project_id']}/{workspace['branch']}/phase-settings",
            json={"settings": {"1.1": False}},
        )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_invalid_project_settings_payload_does_not_invoke_chain(client, project):
    """Body-validation errors short-circuit before the configurator runs."""
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/projects/{project['id']}/phase-settings",
            json={"settings": "not a dict"},
        )

    assert response.status_code == 400
    chain_instance.run.assert_not_called()


def test_invalid_workspace_settings_payload_does_not_invoke_chain(client, workspace):
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/ws/{workspace['project_id']}/{workspace['branch']}/phase-settings",
            json={"settings": {"1.1": "not-a-bool"}},
        )

    assert response.status_code == 400
    chain_instance.run.assert_not_called()
