# Shard OCR — Scale-Aware ROI

We locate the five left-rail tiles (Mystery, Ancient, Void, Primal, Sacred) by **template matching** on the shard icons, across multiple scales. Number ROIs are derived as **percentages** of the tile bounding box, making the OCR resolution-agnostic.

## Templates
Path: `modules/achievements/assets/ocr/icons/`
Files: `mystery.png`, `ancient.png`, `void.png`, `primal.png`, `sacred.png`
> Tight crops of the icon art only (no numbers).

If templates are missing or too few hits (<3), the system **falls back to legacy equal-height ROIs** so testing never blocks.

## Debug
`!ocrdebug` (RBAC + `ENABLE_OCR_DEBUG`): attaches `debug_left_rail.png` overlay marking number ROIs on the full screenshot.
