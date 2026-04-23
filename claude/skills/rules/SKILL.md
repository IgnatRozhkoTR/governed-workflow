---
name: rules
description: Manage project rules (.claude/rules/*.md with glob-based auto-loading). Use when authoring, editing, or deleting rule files via MCP, or when explaining how rule loading works to the user.
---

# Rules Skill

Project rules are markdown files with YAML frontmatter that Claude Code auto-loads when the file paths you edit match the rule's `paths` globs. Rules live at `<project>/.claude/rules/<name>.md` and are shared across every worktree of the project.

## File format

Each rule is a single markdown file:

```markdown
---
name: coding-standards
description: Short human summary used in the admin panel listing.
paths:
  - "**/*.java"
  - "**/*.py"
---

# Coding Standards

...rule body...
```

Three frontmatter fields, all required:
- `name` — lowercase, `[a-z0-9][a-z0-9-_]{0,62}`; must match the filename stem.
- `description` — one-liner shown in the admin panel.
- `paths` — YAML list of glob patterns (gitignore/minimatch-style). A rule auto-applies whenever the current file path matches any glob.

## Default vs user rules

Five rule names are reserved defaults shipped with the admin panel:

- `coding-standards`
- `java-conventions`
- `research-principles`
- `test-standards`
- `validation-pipeline`

Defaults are **immutable** through the MCP tools and the admin panel — they cannot be overwritten, updated, or deleted. Any other rule is a user rule, fully editable. User rules are git-ignored by default (`claude/rules/.gitignore` handles the exceptions for the defaults).

## MCP tools

| Tool | What it does |
|------|--------------|
| `rule_list(project)` | Returns every rule in a project with `{name, description, paths, source}`. |
| `rule_get(project, name)` | Returns one rule with full body. |
| `rule_create(project, name, description, paths, body)` | Creates a new user rule file. Errors `already_exists`, `default_immutable`, `invalid_name`. |
| `rule_update(project, name, description?, paths?, body?)` | Partial update — any omitted field stays unchanged. Errors `not_found`, `default_immutable`. |
| `rule_delete(project, name)` | Deletes a user rule. Errors `not_found`, `default_immutable`. |

The `project` argument accepts a project id or name — whichever the admin panel has registered.

## When to reach for a rule

Pick a rule over an inline agent instruction when:
- The guidance should apply to *any* agent editing matching files, not just one.
- The guidance is about file content (conventions, patterns, what-not-to-do) — not about agent behavior or workflow.
- You want the user to be able to edit it in the admin panel without touching prompts.

Do NOT use rules for:
- Agent-specific workflow steps — those belong in the agent's own prompt.
- Hard policy (e.g., "never push to main") — keep those in `CLAUDE.md` or hooks.
- One-off guidance for a single task — use the task description.

## Authoring checklist

Before creating or updating a rule:
1. Pick a precise `paths` list. Broader globs pull the rule into more contexts; keep the scope honest.
2. Keep the body focused. One rule = one topic. Split if you need "and" to describe it.
3. Avoid duplicating a default — if a default covers the topic, extend it by asking the user to modify it, don't shadow it.
4. Write the body in imperative voice ("Use X", "Don't Y"). No preamble, no meta-commentary.

## Admin panel

The Rules card lives in the Configuration tab, directly below Git Rules. List view shows name, description, paths, and source badge. "New rule" opens a form. Defaults are visible but read-only.
