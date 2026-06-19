"""Blueprint registration."""
from .auth import bp as auth_bp
from .projects import bp as projects_bp
from .workspaces import bp as workspaces_bp
from .state import bp as state_bp
from .comments import bp as comments_bp
from .files import bp as files_bp
from .hooks import bp as hooks_bp
from .hook_api import bp as hook_api_bp
from .context import bp as context_bp
from .criteria import bp as criteria_bp
from .static import bp as static_bp
from .git_config import bp as git_config_bp
from .rules import bp as rules_bp
from .advance import bp as advance_bp
from .terminal_routes import bp as terminal_bp, register_terminal_ws
from .verification import bp as verification_bp
from .modules import bp as modules_bp
from .setup import bp as setup_bp, register_setup_ws
from .lsp import bp as lsp_bp, register_lsp_ws
from .history import bp as history_bp
from .phase_settings import bp as phase_settings_bp
from .advance_modes import bp as advance_modes_bp
from .review_pipeline import bp as review_pipeline_bp
from .proposals import bp as proposals_bp


def register_blueprints(app):
    for bp_module in [auth_bp, projects_bp, workspaces_bp, state_bp, comments_bp, files_bp, hooks_bp, hook_api_bp, context_bp, criteria_bp, static_bp, git_config_bp, rules_bp, advance_bp, terminal_bp, verification_bp, modules_bp, setup_bp, lsp_bp, history_bp, phase_settings_bp, advance_modes_bp, review_pipeline_bp, proposals_bp]:
        app.register_blueprint(bp_module)
    register_terminal_ws(app)
    register_setup_ws(app)
    register_lsp_ws(app)
