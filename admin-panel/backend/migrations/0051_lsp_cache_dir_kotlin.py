"""Point the Kotlin (Gradle) profile's kotlin-lsp at a persistent cache dir.

kotlin-lsp does a full Gradle import + indexing on every ``initialize`` call
unless its IntelliJ config/system dirs are pinned to a stable location (see
the JetBrains-documented ``idea.config.path`` / ``idea.system.path`` system
properties in the server's own ``bin/idea.properties``). The admin panel's
LSP spawn path now substitutes ``{lsp_cache_dir}`` in any profile's
``lsp_args`` with a persistent per-instance directory before launch, so this
migration opts the system Kotlin profile into that mechanism.

Idempotent in both directions: only rewrites when the current value is
exactly the previous default, so a user-customized ``lsp_args`` value is
never clobbered by either the forward or backward migration.
"""
from yoyo import step

_OLD_ARGS = '["--stdio"]'
_NEW_ARGS = (
    '["-Didea.config.path={lsp_cache_dir}/config", '
    '"-Didea.system.path={lsp_cache_dir}/system", "--stdio"]'
)


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE verification_profiles SET lsp_args = ? "
        "WHERE name = 'Kotlin (Gradle)' AND origin = 'system' AND lsp_args = ?",
        (_NEW_ARGS, _OLD_ARGS),
    )


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE verification_profiles SET lsp_args = ? "
        "WHERE name = 'Kotlin (Gradle)' AND origin = 'system' AND lsp_args = ?",
        (_OLD_ARGS, _NEW_ARGS),
    )


step(apply_step, rollback_step)
