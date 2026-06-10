# agents

20 agent definitions — the orchestrator plus 19 sub-agent roles it works with. Each file is a Markdown spec that Claude Code loads as an agent.

## Frontmatter Fields

- `name` — role identifier.
- `description` — when the orchestrator should invoke this role.
- `tools` — minimal tool whitelist. Keep agents tightly scoped.

## Design

- No `<rules>` blocks inside agent bodies — rules auto-apply via path globs in `../rules/*.md` frontmatter.
- Researchers, engineers, validators, and reviewers are separated — engineers never write tests, test engineers never write production code.
- The `plan-advisor` runs as a persistent teammate across the session. Phase 4.0 reviewers work blind with zero implementation context.
