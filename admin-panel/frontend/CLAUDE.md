# frontend

Frontend for the admin panel. Vanilla JS SPA — no framework.

## Structure

- `admin.html` — the only HTML file (single-page app).
- `css/` — modular stylesheets.
- `js/` — vanilla JS modules (one per feature area).
- `i18n/` — frontend translation bundles.
- `img/` — static assets.

## Patterns

- Global state variables: `LOCK_DATA`, `PLAN_DATA`, `RESEARCH_DATA`, `DIFF_DATA`, `COMMENTS`.
- DOM preservation via Idiomorph on re-renders (preserves scroll, focus, contenteditable state).
- Cross-module communication via the `EventBus` pattern (`js/event-bus.js`).
- Comments are keyed by `scope:target` in memory.
- All backend calls go through `js/api.js`; no direct `fetch` elsewhere.
