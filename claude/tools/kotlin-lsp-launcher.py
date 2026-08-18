#!/usr/bin/env python3
"""Direct-JVM launcher for kotlin-lsp, bypassing the native intellij-server binary.

On some machines the cask's native launcher (bin/intellij-server) freezes at
dyld load and never answers stdio. Invoking the bundled JBR java directly
with the arguments product-info.json describes for the native launcher works
reliably, so the admin panel spawns this script in place of the plain
``kotlin-lsp`` command whenever a matching cask install is found.

Argv contract: any argument starting with ``-D`` is treated as a JVM system
property and placed before ``-cp``; every other argument (e.g. ``--stdio``)
is treated as a program argument and placed after the main class. This lets
the admin panel keep passing ``-Didea.config.path``/``-Didea.system.path``
and ``--stdio`` exactly as it does for the plain ``kotlin-lsp`` command.
"""
import glob
import json
import os
import sys

CASK_GLOB = "/opt/homebrew/Caskroom/kotlin-lsp/*/kotlin-server-*"
PLAIN_COMMAND = "kotlin-lsp"


def _version_sort_key(dist_path):
    version_segment = os.path.basename(dist_path.rstrip("/")).replace("kotlin-server-", "")
    return tuple(
        int(part) if part.isdigit() else part
        for part in version_segment.replace("-", ".").split(".")
    )


def _resolve_dist_dir():
    """Return the kotlin-lsp distribution root to launch, or None to fall back to PATH."""
    env_home = os.environ.get("KOTLIN_LSP_HOME")
    if env_home:
        return env_home.rstrip("/")
    candidates = sorted(glob.glob(CASK_GLOB), key=_version_sort_key)
    return candidates[-1].rstrip("/") if candidates else None


def _load_launch_config(dist_dir):
    with open(os.path.join(dist_dir, "product-info.json")) as f:
        product_info = json.load(f)
    return product_info["launch"][0]


def _classpath(dist_dir, jar_names):
    return ":".join(os.path.join(dist_dir, "lib", name) for name in jar_names)


def _rewrite_app_package_prefix(argument, dist_dir):
    """Rewrite embedded $APP_PACKAGE/[Contents/] refs to the dist root.

    additionalJvmArguments often embeds the placeholder mid-string (e.g.
    ``-Xbootclasspath/a:$APP_PACKAGE/Contents/lib/nio-fs.jar``), not just at
    the start, and no ``Contents/`` directory exists in this distribution
    layout.
    """
    for prefix in ("$APP_PACKAGE/Contents/", "$APP_PACKAGE/"):
        if prefix in argument:
            return argument.replace(prefix, dist_dir + "/")
    return argument


def _read_vmoptions(dist_dir, vmoptions_relpath):
    vmoptions = []
    with open(os.path.join(dist_dir, vmoptions_relpath)) as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                vmoptions.append(stripped)
    vmoptions.append("-Xshare:off")
    return vmoptions


def _split_argv(argv):
    """Split incoming argv into JVM system-property args (-D...) and program args."""
    jvm_args = [arg for arg in argv if arg.startswith("-D")]
    program_args = [arg for arg in argv if not arg.startswith("-D")]
    return jvm_args, program_args


def build_command(dist_dir, extra_argv):
    """Construct the full java argv for launching kotlin-lsp directly, JVM-only."""
    launch = _load_launch_config(dist_dir)
    java_bin = os.path.join(dist_dir, launch["javaExecutablePath"])
    classpath = _classpath(dist_dir, launch["bootClassPathJarNames"])
    additional_args = [
        _rewrite_app_package_prefix(arg, dist_dir) for arg in launch["additionalJvmArguments"]
    ]
    vmoptions = _read_vmoptions(dist_dir, launch["vmOptionsFilePath"])
    jvm_args, program_args = _split_argv(extra_argv)

    return (
        [java_bin]
        + vmoptions
        + additional_args
        + jvm_args
        + ["-cp", classpath, launch["mainClass"]]
        + program_args
    )


def main():
    argv = sys.argv[1:]
    print_cmd = "--print-cmd" in argv
    if print_cmd:
        argv = [arg for arg in argv if arg != "--print-cmd"]

    dist_dir = _resolve_dist_dir()
    if dist_dir is None:
        if print_cmd:
            sys.stderr.write("kotlin-lsp-launcher: no bundled dist found, would exec plain kotlin-lsp\n")
            sys.exit(1)
        os.execvp(PLAIN_COMMAND, [PLAIN_COMMAND] + argv)
        return

    try:
        command = build_command(dist_dir, argv)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"kotlin-lsp-launcher: failed to build command from {dist_dir}: {exc}\n")
        sys.exit(1)

    if print_cmd:
        print(json.dumps(command))
        return

    os.execv(command[0], command)


if __name__ == "__main__":
    main()
