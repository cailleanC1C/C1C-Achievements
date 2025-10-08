*** Begin Patch
*** Add File: docs/ENGINEERING.md
# C1C Engineering Contract (Dev Guardrails)

These are the non-negotiables for how we change and ship things.

## Process (always this order)
1. **Analysis first** → Audit-only run (no code changes).
2. **Planning next** → Issues JSON  Acceptance Checklist (no code).
3. **Then patches** → Copy-paste diffs (file path  anchor  unified diff  one-line “why”).

## Canonical locations
- Global docs: `docs/**`
- Architecture Decisions: `docs/ADR/**`
- Module reviews/plans/checklists: `REVIEW/MODULE_*/**`
- Issue batches for Actions: `.github/issue-batches/*.json|yml`
- Workflows: `.github/workflows/*.yml`
- Static assets (e.g., emoji maps): `assets/**`

## Labels (harmonized)
Source of truth is `.github/labels/harmonized.json`. Examples we use:  
`bot:achievements`, `comp:shards`, `feature`, `epic`, `ready`, `blocked`, `P0..P4`, `severity:*`, `infra`, `docs`, `devx`, `config`, `data`, `tests`, `lint`, `typecheck`.

## Patch format requirements
- Provide **unified diffs**.
- Include **exact file path**  short **anchor** (search hint).
- End patch with a **one-line why**.

## Release gate
No feature merges unless the PR contains (or links) a module **ACCEPTANCE_CHECKLIST.md** and Guardrails CI is green.

## Codex templates
Pinned, copy-pasteable Codex commands live in `docs/CODEX_TEMPLATES.md`.
*** End Patch
