"""Point the Kotlin (Gradle) profile's lsp_command at the direct-JVM launcher.

The cask's native kotlin-lsp launcher (bin/intellij-server) freezes at dyld
load on some machines and never answers stdio. claude/tools/kotlin-lsp-launcher.py
invokes the bundled JBR java directly with the same arguments, sidestepping
the frozen native binary. The admin panel's LSP spawn path already resolves a
``{tools_dir}`` placeholder in lsp_command (see services/lsp_service.py), so
this migration repoints the system Kotlin profile at the launcher script.
lsp_args (the ``{lsp_cache_dir}`` -D args and ``--stdio``) are untouched --
they flow through unchanged into the launcher's argv contract.

Idempotent in both directions: only rewrites when the current value is
exactly the previous default, so a user-customized ``lsp_command`` value is
never clobbered by either the forward or backward migration (same style as
migration 0051).
"""
from yoyo import step

_OLD_COMMAND = "kotlin-lsp"
_NEW_COMMAND = "{tools_dir}/kotlin-lsp-launcher.py"


def apply_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE verification_profiles SET lsp_command = ? "
        "WHERE name = 'Kotlin (Gradle)' AND origin = 'system' AND lsp_command = ?",
        (_NEW_COMMAND, _OLD_COMMAND),
    )


def rollback_step(conn):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE verification_profiles SET lsp_command = ? "
        "WHERE name = 'Kotlin (Gradle)' AND origin = 'system' AND lsp_command = ?",
        (_OLD_COMMAND, _NEW_COMMAND),
    )


step(apply_step, rollback_step)
