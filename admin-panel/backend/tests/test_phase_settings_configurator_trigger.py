"""Integration tests: phase-settings saves invoke the configurator chain.

Project-level phase-settings mutations re-render their own project; device-level
mutations re-render every registered project because they touch all renders.
Workspace-scope phase-settings routes no longer exist (no callers).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_project_phase_settings_put_invokes_configurator(client, project):
    """PUTing project-scope phase settings runs the chain once with project metadata."""
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.return_value = []
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


def test_device_phase_settings_put_invokes_configurator_per_project(client, project):
    """A device-scope save re-renders every registered project via rerender_all_projects."""
    with patch("services.configurator_service.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.return_value = []
        MockChain.default.return_value = chain_instance

        response = client.put(
            "/api/phase-settings/device",
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


def test_invalid_project_settings_payload_does_not_invoke_chain(client, project):
    """Body-validation errors short-circuit before the configurator runs."""
    with patch("routes.phase_settings.ConfiguratorChain") as MockChain:
        chain_instance = MagicMock()
        chain_instance.run.return_value = []
        MockChain.default.return_value = chain_instance

        response = client.put(
            f"/api/projects/{project['id']}/phase-settings",
            json={"settings": "not a dict"},
        )

    assert response.status_code == 400
    chain_instance.run.assert_not_called()


def test_project_phase_settings_reports_configurator_warnings_when_template_missing(
    client, project, tmp_path
):
    """When no template can be found the response surfaces a skipped warning entry."""
    missing_default = tmp_path / "no-default" / "SKILL.md.template"
    missing_agents = tmp_path / "no-agents"

    with patch("services.configurator_service.SkillConfigurator.DEFAULT_TEMPLATE_PATH", missing_default), \
         patch("services.configurator_service.DEFAULT_AGENTS_DIR", missing_agents):
        response = client.put(
            f"/api/projects/{project['id']}/phase-settings",
            json={"settings": {"1.1": False}},
        )

    assert response.status_code == 200
    warnings = response.get_json()["configurator_warnings"]
    reasons = {w["reason"] for w in warnings}
    assert "template missing" in reasons
