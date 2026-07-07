# TASK-026: Schools platform P0 — auth, tenancy, role dashboards

**Status:** done (P0 — Cycle 14; P1+ phases tracked in the PRD)
**Branch:** `feat/TASK-026-schools-p0` (stacked on `fix/TASK-021-studio-review-fixes`)
**Base SHA:** `12e5842`
**PRD section:** `docs/roadmap/SCHOOL_PLATFORM_PRD.md` (canonical; review
2026-07-07: pivot to a school sports-management platform with student logins,
progress, AI-coach details, highlights, rallies)

## Goal (P0 only)
Identity + ownership under the existing pipeline: `users`/`schools`/
`memberships` tables (additive SQLite migrations per AGENTS.md), session-cookie
auth (argon2), login + school join-code pages in the existing design system,
`school_id`+`uploaded_by` on jobs, school-scoped gallery/queue, role-routed
`/app` shell (admin | coach | student). Anonymous public flow stays behind a
flag until cutover. Student profile/progress/heatmap surfaces are P1/P2 —
see the PRD phases.

## What P0 shipped (this branch)
- `app/db.py`: users / schools / memberships / auth_sessions / job_students
  tables; guarded ALTERs add `jobs.school_id` + `jobs.uploaded_by`.
- `app/auth.py`: stdlib scrypt hashes, HttpOnly+SameSite=Lax session cookies
  (secure over https), join-code generator, role guards.
- API: register-school / login / logout / join / me; `/api/school/overview`
  (roster, join codes — coach code admin-only, school sessions);
  `/api/jobs/{id}/assign` (+unassign) pinning WHICH tracked player (P1/P2) is
  the student; `/api/students/{id}/profile` aggregate (highlights, rallies,
  AI-coach notes, per-session quality, court-space movement distance +
  coverage via the TASK-022 homography). Signed-in uploads own their jobs;
  anonymous flow untouched.
- UI: `web/login.html` (sign in / join with code / create school),
  `web/app.html` + `platform.js/css` — role-routed shell (admin/coach:
  Overview, Sessions w/ assign, Students; student: My progress), student
  profile with stat cards + sparklines, session cards (video, rally chips,
  AI-coach box, movement stats). "Schools" link in the main nav.

## Acceptance criteria
- [x] Migrations additive + guarded (PRAGMA checks); re-running init is
      idempotent → `tests/unit/test_schools_auth.py`
- [x] Auth flows: register school → student joins with code; role scoping
      (student blocked from overview and other students' profiles; jobs
      outside the school 404 on assign) → API tests (4 passing)
- [x] Existing anonymous upload path unchanged → API test
- [x] Browser walkthrough (2026-07-07, local): registered "Sunrise Academy"
      via the login page → student "nia" joined with ST- code via API →
      admin panel showed join codes/roster/sessions, assigned fixture01 +
      uservid3 with a P1 pin → student login rendered My Progress with stat
      cards + sparklines (2 sessions, 7 rallies, 8s longest, 15m court
      distance), session videos, rally note chips, AI-coach box; student
      correctly 403-blocked from /api/school/overview.

## Risks / rollback
- Session/auth code is security-sensitive: argon2 + secure/HttpOnly/SameSite
  cookies + CSRF token on mutating forms; no secrets in repo.
- rollback: feature flag off restores today's anonymous app.
