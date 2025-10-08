# Type Check Report

## Command
`mypy .`

## Result
- **Status:** Failed
- **Summary:** mypy aborted because `core/prefix.py` is discovered twice (`prefix` and `core.prefix`). Consider adding an `__init__.py`, adjusting `MYPYPATH`, or running with `--explicit-package-bases`.

See terminal output chunk `53a2f6` for the traceback.
