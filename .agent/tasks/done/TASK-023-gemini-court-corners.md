# TASK-023: Gemini court-corner refinement fallback

**Status:** done
**Branch:** `feat/TASK-023-gemini-court-corners`
**Base SHA:** `d1860af`
**PRD section:** §16 remediation (review 2026-07-07: "use Gemini to spot the
four edges of the court")

## Goal
When `court.detect_from_video` returns `not_found` or confidence < 0.5, sample
3 proxy frames and ask Gemini (structured output, response_schema with 4
normalized corner points + visibility flags) for the outer court corners;
median-merge with any classical result; store provenance
(`court.source = "cv" | "gemini" | "cv+gemini"`). Reuses `app/pipeline/gemini.py`
usage accounting.

## Acceptance criteria
- [x] Mocked-Gemini unit tests (5): strong CV skips Gemini; noise video rescued
      (source=gemini); weak CV merges midpoint (source=cv+gemini); malformed/
      invisible/off-frame/tiny-quad outputs rejected; no API key = CV-only
- [ ] One real occluded-court video gets corners + homography where CV alone
      failed (record job id + confidence here — needs a real upload post-deploy)

## Risks / rollback
- Cost: 3 image calls per job only on the low-confidence path; usage recorded
  in `gemini_usage`.
- rollback: court stays classical-only (`status: not_found` behavior today).
