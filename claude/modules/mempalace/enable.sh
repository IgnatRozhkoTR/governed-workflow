#!/usr/bin/env bash
set -e

# 1. Python check
if ! python3 -c "import sys; assert sys.version_info >= (3, 9)" 2>/dev/null; then
  echo "ERROR: Python 3.9+ required" >&2
  exit 1
fi

# 2. pip check
if ! command -v pip3 >/dev/null 2>&1; then
  echo "ERROR: pip3 not found - install pip and retry" >&2
  exit 1
fi

# 3. install
if ! pip3 install --user mempalace 2>err.log; then
  err=$(cat err.log)
  echo "ERROR: pip install failed: $err; see https://github.com/MemPalace/mempalace" >&2
  rm -f err.log
  exit 1
fi
rm -f err.log

# 4. palace dir
mkdir -p "$HOME/.claude/governed-workflow/mempalace"

# 5. success
echo "OK: mempalace installed; restart MCP server to pick up the provider"
