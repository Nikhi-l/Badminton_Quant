# TASK-010: Upload double-prompt bug

**Status:** done (2026-06-23) — single-open guard + stopPropagation; verified in preview.
**Branch:** `fix/TASK-010-upload-double-prompt`
**PRD section:** §8 upload flow (bug)

## Symptom
After a reel was generated, starting a new upload prompted the OS file picker
twice ("I select the video but the popup shows again, then it works"); with
Shuttle tracking enabled the retry upload appeared not to start at all.

## Root cause
The "Choose video(s)" button (`#browse`) sits inside `#drop`. A button click
fired `browse.onclick → fileInput.click()` AND bubbled to `drop.onclick`, whose
`e.target.closest(".drop-idle")` was truthy → `fileInput.click()` a second time.
The browser queues the second open, re-showing the picker after the first pick.
The shuttle symptom rode on the same double-trigger (no shuttle-specific upload
code path exists; `currentOptions()` is only read at `finish`).

## Fix (`web/app.js`)
`openFilePicker()` with a `pickerBusy` guard (700ms fallback for cancelled
pickers, cleared on `change`); `browse.onclick` calls `e.stopPropagation()`.
Every path (button, drop zone, rapid double-click) now opens exactly once, and
consecutive intents after a pick still work.

## Verification
- Preview spy on `fileInput.click()`: button→1, drop→1, rapid-double→1, retry
  after change→1 (was 2 on the button path).
- `node --check web/app.js` OK; `./scripts/check.sh` 9 passed.
