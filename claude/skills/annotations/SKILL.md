---
name: annotations
description: Attach short explanatory notes to line ranges of code (non-obvious decisions, trade-offs, business reasons) via the annotation MCP tools, instead of explanatory code comments. Use when writing non-obvious code or when asked to "annotate the changes".
user_invocable: false
---

# Annotations Skill

An annotation is a short note attached to a line range of a file in the workspace. The admin panel and the VS Code extension show it as grey italic text at the end of the line, expandable to the full text. Reviewers read annotations for context.

Annotations replace explanatory code comments under the no-comments rule: the code stays self-documenting, and the WHY lives next to it without becoming part of the diff.

Annotations are not review comments: they have no replies, no resolution, and never block a gate.

## Tools

- `workspace_list_annotations(file_path?, repo?)` — check what already exists before adding anything. With `file_path`, each annotation is resolved against the file's current content; `stale: true` means its lines changed beyond recognition.
- `workspace_annotate(file_path, line_start, line_end, text, repo?, author)` — pass your agent role as `author`. Lines are 1-based and inclusive and must exist in the current working-tree file, so annotate after the code is written.
- `workspace_update_annotation(id, text?, line_start?, line_end?)` — change the text, or move a stale annotation to where its code now lives.
- `workspace_delete_annotation(id)` — remove an annotation whose code was deleted or rewritten.

Pass `repo` (the attached repo's rel_path) only in multi-repo workspaces.

## When to annotate

- Non-obvious decisions: why this approach and not the obvious one.
- Trade-offs that were accepted deliberately, such as performance against simplicity or a known limitation.
- Business reasons and requirements that the code cannot express.
- Anything a reviewer would ask "why?" about.
- When asked to "annotate the changes": go through the changed lines of the diff and annotate the ones above. Skip the self-explanatory ones.

## When not to annotate

- Restating what the code does. If the code needs that, rename or extract instead.
- TODOs or planned work.
- Review findings or defects. Those go to review threads.
- Obvious code, boilerplate, or generated files.

## How to write

- 1 to 3 sentences, markdown allowed. Lead with the reason.
- Prefer one annotation on a range (the whole method or block) over many single-line notes.
- Update an existing annotation instead of adding a second one to the same lines.
- When you change annotated code, update the annotation or delete it if it no longer applies. Re-anchor stale ones with `workspace_update_annotation`.
- The first sentence is shown as a one-line plain-text preview inline next to the code, and markdown syntax is not rendered there. Start with a plain, self-contained sentence that makes sense alone.
- Keep markdown light: an occasional `code` span or short list in the rest is fine, since the expanded view renders it. No headings, no tables.
