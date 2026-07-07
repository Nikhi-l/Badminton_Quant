# Baddy for Schools — sports management platform PRD (TASK-026)

Source: product direction from the 2026-07-07 review. Reshape Baddy from a
single-page reel generator into a **sports management platform for schools**:
coaches manage squads, every student gets a login and a growth trail (their
matches, rallies, highlights, AI-coach feedback, movement heatmaps), and the
school gets scheduling + oversight. Reference UI: the tournament "Day Planner"
screenshot (matches list → drag onto court/time grid) shared in the review.

## 1. Personas
- **School admin** — owns the school account, invites coaches, sees usage.
- **Coach** — creates cohorts (class/team), uploads session video, assigns
  rallies/highlights to students, reviews AI-coach notes, schedules courts.
- **Student** — logs in, sees their profile: progress charts, highlights,
  match rallies, per-session heatmaps, AI-coach feedback; shares reels.
- **Parent (later)** — read-only progress digest.

## 2. What exists that this reuses
Pipeline (rallies/vision/tracking/court/heatmaps/coach notes), Studio,
gallery, queue, jobs DB. Everything is currently anonymous + single-tenant —
the pivot adds identity, ownership, and structure ABOVE the pipeline, not a
rewrite of it.

## 3. Architecture decisions (proposed)
- **Auth**: session-cookie auth on FastAPI. Email+password with
  argon2 hashing + school join-codes for students (COPPA-friendly: usernames,
  no student email required). Magic-link optional later. Roles:
  `admin | coach | student` on a `memberships` table (user ↔ school ↔ role).
  OAuth (Google Workspace for EDU) is a fast follow, not phase 0.
- **Tenancy**: single DB, `school_id` scoping on every domain row. SQLite
  stays until schools > ~20 or concurrent writes hurt; the additive-migration
  discipline (AGENTS.md) already fits; Postgres is a lift-and-shift later.
- **Data model (additive tables)**:
  `users`, `schools`, `memberships`, `cohorts`, `cohort_members`,
  `sessions_log` (training session → 1..n jobs), `job_owners`
  (job ↔ school/cohort/uploader), `student_clips` (rally/highlight ↔ student,
  assigned by coach or auto via player id), `assessments` (AI-coach snapshot +
  coach comments per student per session), `schedule_slots` (court × time ×
  cohort/match — the Day-Planner grid).
- **Frontend**: keep the no-build vanilla stack; move to multi-page app
  shell: `/login`, `/app` (role-routed dashboard), `/app/student/:id`,
  `/app/cohort/:id`, `/app/schedule`, Studio unchanged as the editor surface.
  Dark Midjourney-style design system carries over.

## 4. Student profile (the core surface)
- Header: name, cohort, sessions attended, streak.
- **Progress**: per-session series of measured signals we already compute —
  shuttle/pose quality, rally count, longest rally, movement distance (from
  court-space foot tracks), court coverage % (heatmap occupancy) — plus coach
  ratings. Sparkline cards, one per metric.
- **Highlights**: reels where this student is tagged (auto: the per-player
  track id chosen at assignment; manual override by coach).
- **Match rallies**: rally list with per-rally vision chips → opens Studio.
- **AI coach**: latest `coach` output (headline, strengths, work-on) with
  history; coach can annotate/approve before students see it.
- **Heatmaps**: per-session court-plane movement maps (already built in
  Studio) aggregated per student.

## 5. Phases
- **P0 — Identity + ownership (TASK-026)**: users/schools/memberships/auth
  pages (login, join-with-code), jobs gain `school_id`+`uploaded_by`, gallery
  and queue become school-scoped. Feature-flagged; baddyai.com anonymous flow
  keeps working until cutover.
- **P1 — Cohorts + student tagging**: cohort CRUD, roster, assign rallies /
  highlights to students (Studio "assign to student" on a player track),
  student dashboard v1 (highlights + rallies + AI coach).
- **P2 — Progress + assessments**: metric aggregation per student/session,
  progress cards, coach assessments, heatmap history.
- **P3 — Scheduling (Day Planner)**: court × time grid, drag matches from a
  list (reference screenshot), conflicts, print/export. Independent of
  video pipeline; can slot anywhere after P0.
- **P4 — Polish/scale**: parent digests, Google SSO, Postgres migration,
  per-school storage quotas, billing.

## 6. Non-goals (now)
Payments, mobile apps, federation/leagues, live streaming, public profiles.

## 7. Open questions (decide at P0 kickoff)
- Student PII policy per school (username-only vs email) → default username+code.
- Storage growth: per-school quota + retention (e.g. keep proxies 90 days).
- Whether the anonymous public gallery remains as a marketing surface (likely
  yes, behind a "showcase" flag with consent).
