# Codex Templates (pinned to our paths)

## Audit only (no planning, no code)
```bash
codex review \
  --task "Shard Module — Audit (spec vs code, UI flow, emoji usage)" \
  --review-paths "
    cogs/shards/cog.py,
    cogs/shards/ocr.py,
    cogs/shards/__init__.py,
    cogs/common/**,
    adapters/**,
    utils/**,
    assets/emojis/**,
    .github/**,
    README.md
  " \
  --exclude "**/__pycache__/**,**/.venv/**,**/venv/**,**/node_modules/**,tests/**,**/*.png,**/*.jpg,**/*.jpeg" \
  --review-output "REVIEW/MODULE_SHARD/SHARDS_AUDIT.md" \
  --artifacts "REVIEW/MODULE_SHARD/SPEC_DIFF.md,REVIEW/MODULE_SHARD/UI_FLOW_MAP.md,REVIEW/MODULE_SHARD/EMOJI_AUDIT.md,REVIEW/MODULE_SHARD/READY_TO_IMPLEMENT.md" \
  --severity-threshold "low" \
  --review-brief-file - << 'BRIEF'
(paste current snapshot here)
BRIEF
```

## Planning only (no code)
```bash
codex review \
  --task "Shard Module — Planning from Audit (issues JSON  acceptance criteria)" \
  --review-paths "
    REVIEW/MODULE_SHARD/SHARDS_AUDIT.md,
    REVIEW/MODULE_SHARD/SPEC_DIFF.md,
    REVIEW/MODULE_SHARD/UI_FLOW_MAP.md,
    REVIEW/MODULE_SHARD/EMOJI_AUDIT.md,
    REVIEW/MODULE_SHARD/READY_TO_IMPLEMENT.md,
    .github/**,
    README.md
  " \
  --exclude "**/__pycache__/**,**/.venv/**,**/venv/**,**/node_modules/**,tests/**" \
  --review-output "REVIEW/MODULE_SHARD/PLANNING_NOTES.md" \
  --artifacts ".github/issue-batches/shards-planning.json,REVIEW/MODULE_SHARD/ACCEPTANCE_CHECKLIST.md" \
  --severity-threshold "low" \
  --review-brief-file - << 'BRIEF'
(paste planning brief here)
BRIEF
```
