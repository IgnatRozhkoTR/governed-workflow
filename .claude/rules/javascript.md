---
name: javascript
description: Vanilla JS conventions for admin-panel frontend — no bundler, EventBus, Idiomorph, i18n.
paths:
  - "admin-panel/templates/js/**/*.js"
  - "**/*.js"
---

# JavaScript conventions

## Runtime shape

- Vanilla JS. No framework, no bundler, no TypeScript, no jQuery.
- Scripts are loaded as plain `<script>` tags in `admin.html`. **ES modules are NOT used** — there is no `import` / `export`. Functions and globals attach to the window scope via plain declarations.
- One feature per file under `templates/js/`. The filename mirrors the feature (e.g. `rules.js`, `phase-settings.js`, `lsp-client.js`).

## Declarations

- In newer files, prefer `const` for references that never rebind and `let` otherwise.
- Older files use `var`. When editing an existing file, match the file's prevailing style — don't churn.
- Never leak new globals beyond the established ones below.

## Shared globals (use, don't recreate)

- `AppState`, `LOCK_DATA`, `PLAN_DATA`, `RESEARCH_DATA`, `DIFF_DATA`, `COMMENTS`, `CONTEXT_DATA`.
- Comments are keyed by `scope:target`.

## Patterns

- Cross-module communication via `EventBus.on(event, handler)` and `EventBus.emit(event, payload)` from `event-bus.js`. Don't call sibling modules directly.
- List / container rerenders use `morphInnerHTML(el, html)` (Idiomorph wrapper) to preserve scroll, focus, contenteditable, and form state. Plain `el.innerHTML = ...` only for throwaway DOM.
- Every user-content string inserted into innerHTML goes through `escapeHtml(...)`.
- Every user-facing string goes through `t(key, params)` for i18n. Never hardcode English.
- All backend calls go through `apiGet` / `apiPost` / `apiPut` / `apiDelete` helpers in `api.js`. No raw `fetch` elsewhere.
- Inline `style=` in JS-built HTML is accepted ONLY for content-driven values (dynamic bar widths, computed colors). Static styling belongs in CSS classes.

## Structure

- Keep functions short. Extract named helpers rather than deeply-nested callbacks.
- Event handler wiring happens once at module load. Wire via `saveBtn.onclick = handler`, not by re-attaching on every render.
- Module-scoped state (e.g. `_currentRuleName`) goes in a single `var` / `let` at file top, not embedded in closures.

## Don'ts

- No async/await if the surrounding file uses `.then()` chains, and vice versa — match the file.
- No `console.log` left in committed code. Use the existing logger if one is in play, otherwise remove.
- No third-party dependencies added without a strong reason — this project stays dependency-light on the frontend.
