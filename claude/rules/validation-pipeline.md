---
name: validation-pipeline
description: Three-stage validation (compilation, logic, quality) with a logic checklist for reviewers.
paths:
  - "**/*.java"
  - "**/*.kt"
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
---

# Validation Pipeline

## Stages

| Stage | Checks | Severity |
|-------|--------|----------|
| 1. Compilation | Syntax, imports, types | CRITICAL |
| 2. Logic | No placeholders, all paths, error handling | MAJOR |
| 3. Quality | SOLID, clean code, naming | MAJOR |

Logic stage also covers: edge cases, unreachable code, infinite loops (placeholders: see coding-standards).
