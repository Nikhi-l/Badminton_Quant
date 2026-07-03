# TASK-021: AI-analytics repositioning + AI Coach dashboard (report card UI)

**Status:** implemented on branch — awaiting product-owner review before merge/deploy.
**Branch:** `feat/TASK-021-analytics-coach-ui` (off `main` @ 29af265)
**PRD section:** §8 frontend flows (extends), new §8b.

## Goal
Revamp the UI from "highlight generator" to **AI-powered badminton analytics** (tone
researched from stupasports.ai — positioning/tone only, all copy original): the
product is an **AI coach** that saves every session per user and presents a
**report card** — recordings, analytics, coach notes, and the existing highlight
creation.

## Delivered
- **Positioning:** title/meta, nav (My Coach · Gallery · How it works · "Analyze a
  match"), hero "Every session, measured. / Every rally, analyzed.", analytics
  hero-strip (rally detection / shuttle tracking / pose / coach notes), reframed
  chips + How-it-works steps, footer.
- **AI Coach dashboard (#coach)** replaces the queue section: aggregate report
  strip (sessions, rallies analyzed, play analyzed, reels, avg shuttle tracking,
  coach reports) + session history cards (status chips incl. live
  processing/failed, per-session metric pills, Report card + Highlights actions).
  Data = `GET /api/jobs` (mine via localStorage ids) merged with the light
  `GET /api/gallery` items; 4s polling while jobs run. `loadQueue` aliased.
- **Session report card modal:** recording player, 8 metric tiles (rallies
  found/used, longest/avg rally, play analyzed, shuttle/pose/player quality),
  rally-breakdown bar chart (lime = in the reel, tooltips w/ notes), full Gemini
  coach notes (headline, confidence, strengths, work_on, key moments incl. rally
  refs, caveats), actions → Studio (highlight creation) + reel download.
- No backend changes; no new endpoints. Cache-bust v=26.

## Verification
- `node --check` OK; `./scripts/check.sh` 32 passed; no console errors.
- Preview: hero renders; dashboard with 5 mock sessions → 6 aggregate tiles,
  status chips, error on failed; report modal → 8 tiles, 13 bars (5 lime),
  coach columns/moments; "Create highlight clips" closes + routes openStudioById.

## Next / open
- Merge + deploy pending owner approval (visual pivot).
- Later: per-user auth (sessions are localStorage-scoped today), trend charts
  across sessions (needs per-session metrics persisted server-side or N fetches).
