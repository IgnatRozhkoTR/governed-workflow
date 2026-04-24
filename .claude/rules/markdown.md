---
name: markdown
description: Markdown style — CLAUDE.md brevity, README scope, frontmatter for skills/rules, no emojis.
paths:
  - "**/*.md"
---

# Markdown conventions

## File kinds

- **`CLAUDE.md`** — ≤30 lines. High-level only: what lives in this folder, key patterns, pointers to deeper docs. No technical how-to; the reader can discover specifics from the code.
- **`README.md`** — for human readers. This repo has exactly three: root (product overview), `admin-panel/` (install + run + architecture), `claude/` (what ships to workspaces). Don't add more without a clear reason.
- **`SKILL.md`** — skills under `.claude/skills/` or `claude/skills/`. YAML frontmatter required: `name`, `description`.
- **`.claude/rules/*.md`** — auto-applied coding rules. YAML frontmatter required: `name`, `description`, `paths` (list of globs).

## Frontmatter

- Opens and closes with `---` on their own lines.
- Keys are lowercase. List items indented two spaces under their key.
- `description` is one line — used by the model to decide relevance. Be specific.

## Style

- Prefer bullets and tables over prose paragraphs when the content is structural.
- Keep sentences short.
- Headings: match the case style of the surrounding file (the repo is mostly sentence-case headings with a few title-case exceptions; match what's already there).
- Code blocks must tag a language: ` ```python `, ` ```js `, ` ```bash `, ` ```sql `. Never an untagged fence.
- No emojis anywhere.
- No trailer lines (no `Co-Authored-By`, no sign-off footers).

## Don'ts

- Don't create a new Markdown file when an existing one is the right home for the content.
- Don't let CLAUDE.md files grow past 30 lines — split or trim instead.
- Don't duplicate content across READMEs — link from child to parent rather than copy.
