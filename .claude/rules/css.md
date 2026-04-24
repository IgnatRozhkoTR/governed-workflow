---
name: css
description: CSS conventions — per-feature files, theme tokens, BEM-ish, flat selectors.
paths:
  - "admin-panel/templates/css/**/*.css"
  - "**/*.css"
---

# CSS conventions

## Organization

- One stylesheet per feature or card (e.g. `cards.css`, `phase-settings.css`, `tabs.css`). Keep files modular.
- Theme tokens live in `variables.css` and only there. Add a new token there instead of re-declaring colors/sizes in feature stylesheets.
- Use `/* ═══ BANNER ═══ */` comments only where the file is already structured that way.

## Theme tokens (use these, don't hardcode)

Defined in `variables.css` under `:root`, `[data-theme="dark"]`, and `[data-theme="light"]`:

- Typography: `--font-sans`, `--font-mono`
- Shape: `--radius`, `--radius-sm`, `--transition`, `--shadow-sm`, `--shadow-md`
- Surfaces: `--bg-base`, `--bg-surface`, `--bg-raised`, `--bg-hover`, `--bg-input`
- Borders: `--border`, `--border-active`
- Text: `--text-primary`, `--text-secondary`, `--text-muted`
- Accent: `--accent`, `--accent-text`, `--accent-dim`, `--accent-hover`
- Semantic: `--success`, `--danger`, `--warning`, `--info` (each with `-dim` variant)
- Composite: `--phase-track`, `--phase-fill`, `--card-glow`, `--tab-indicator`, `--scrollbar-*`, `--diff-*`

Always prefer `var(--token)` over a hex literal.

## Naming

- BEM-ish: `.block__element--modifier` (e.g. `phase-settings__badge--user-gate`).
- Keep selectors flat. Avoid 3+ levels of nesting or chained descendant selectors.
- Don't rely on tag specificity (`div.card`) when a class alone suffices.

## Misc

- No `!important` unless overriding a third-party style. Document why with a short comment if used.
- Inline `style=` in HTML/JS only for content-driven values (dynamic widths, computed colors). Static styling goes in a stylesheet.
- Respect dark/light themes — anything color-related must use a token so both themes flow through.
