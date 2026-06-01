"""Shared headless ``claude -p`` subprocess runner.

Both the review pipeline (file-reviewer fan-out + integration reviewers) and
the reflection service spawn a Claude sub-agent the same way: write the prompt
to stdin, await stdout under a timeout, surface the JSON envelope intact. This
module owns that helper so neither caller drifts.

The file-reviewer path needs ``--strict-mcp-config`` to suppress MCP servers
(the haiku-class agent would otherwise pay the full opus-class MCP schema cost
per file). Other agents keep MCP enabled because they self-submit via tools.
"""
from __future__ import annotations

import asyncio
from pathlib import Path


_STDERR_EXCERPT_CHARS = 500


async def spawn_claude_agent(
    *,
    agent: str,
    prompt: str,
    project_path: Path,
    max_turns: int | None,
    timeout_s: float,
    suppress_mcp: bool = False,
) -> str:
    """Spawn ``claude -p --agent <agent>`` and return raw stdout.

    When ``suppress_mcp`` is True, ``--strict-mcp-config`` is passed and no
    ``--mcp-config`` files are supplied — this disables every MCP server for
    that invocation. When ``max_turns`` is None, the ``--max-turns`` flag is
    omitted so the agent can run unbounded turns (used by integration
    reviewers and the reflector, which need many MCP round-trips).

    Raises:
        RuntimeError: timeout, non-zero exit, or other subprocess failure.
    """
    argv = _build_argv(agent, suppress_mcp, max_turns)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(project_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await _communicate_with_timeout(
        proc, prompt, agent, timeout_s
    )
    if proc.returncode != 0:
        stderr_excerpt = stderr_bytes.decode(errors="replace")[:_STDERR_EXCERPT_CHARS]
        raise RuntimeError(f"{agent} exit {proc.returncode}: {stderr_excerpt}")
    return stdout_bytes.decode(errors="replace")


def _build_argv(agent: str, suppress_mcp: bool, max_turns: int | None) -> list[str]:
    argv = ["claude", "-p", "--agent", agent]
    if suppress_mcp:
        argv.append("--strict-mcp-config")
    argv.extend(["--output-format", "json"])
    if max_turns is not None:
        argv.extend(["--max-turns", str(max_turns)])
    return argv


async def _communicate_with_timeout(
    proc: asyncio.subprocess.Process,
    prompt: str,
    agent: str,
    timeout_s: float,
) -> tuple[bytes, bytes]:
    try:
        return await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")), timeout=timeout_s
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        try:
            await proc.wait()
        except (ProcessLookupError, OSError):
            pass
        raise RuntimeError(f"{agent} timeout after {timeout_s}s") from exc
