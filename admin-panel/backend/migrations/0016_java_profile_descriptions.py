"""Update Java system profiles with agent setup instructions for jdtls + JDK discovery.

The required JDK version depends on the installed jdtls version. The setup agent
must detect this at install time and adapt — older devices may need JDK 17 while
newer devices need JDK 21+.

Approximate jdtls -> required JDK matrix (verify by running `jdtls --validate-java-version`
or by parsing `jdtls`'s startup error if present):

  jdtls < 1.28.0   -> JDK 11+
  jdtls 1.28-1.37  -> JDK 17+
  jdtls >= 1.38    -> JDK 21+

When in doubt, run jdtls once with the candidate JAVA_HOME — it will report the
exact minimum requirement in its error output (e.g. "jdtls requires at least Java 21").
"""
from yoyo import step


def apply_step(conn):
    cursor = conn.cursor()

    description = (
        "Java build verification. "
        "LSP setup uses jdtls and requires a matching JDK. "
        "Step 1: detect installed jdtls version with `jdtls --help` or by inspecting "
        "the brew formula (`brew info jdtls`). "
        "Step 2: pick the matching JDK using this matrix — "
        "jdtls < 1.28: JDK 11+; "
        "jdtls 1.28-1.37: JDK 17+; "
        "jdtls >= 1.38 (current brew releases): JDK 21+. "
        "Step 3: discover the JDK path. "
        "macOS: `/usr/libexec/java_home -v <major>` (e.g. `-v 21`). "
        "Linux: `find /usr/lib/jvm -maxdepth 1 -name '*<major>*' -type d 2>/dev/null | head -1`. "
        "If the required JDK is missing, install it. "
        "macOS: `brew install --cask zulu@<major>` (e.g. `zulu@21`). "
        "Linux: `sudo apt-get install -y openjdk-<major>-jdk` (or distro equivalent). "
        "Step 4: confirm the choice — run jdtls once with the candidate JAVA_HOME; "
        "if it errors with `jdtls requires at least Java N`, switch to JDK N and retry. "
        "Step 5: call `workspace_update_verification_profile` with: "
        "lsp_command='bash', lsp_args='[\"-c\", \"JAVA_HOME=<resolved_path> exec jdtls --jvm-arg=-Xmx1G\"]' "
        "(replace <resolved_path> with the actual JDK path). "
        "Troubleshooting: if the LSP later fails to initialize with "
        "`LSP server closed stdout before responding to initialize`, jdtls's per-project "
        "workspace cache is likely corrupt. Wipe it and retry — the cache lives at "
        "`~/Library/Caches/jdtls/jdtls-<hash>/` (macOS) or `~/.cache/jdtls/jdtls-<hash>/` (Linux), "
        "where `<hash>` is derived from the project working directory."
    )

    cursor.execute(
        "UPDATE verification_profiles SET description = ? WHERE name = 'Java (Gradle)' AND origin = 'system'",
        (description,)
    )
    cursor.execute(
        "UPDATE verification_profiles SET description = ? WHERE name = 'Java (Maven)' AND origin = 'system'",
        (description,)
    )


step(apply_step)
