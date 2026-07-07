# TASK-026: Schools platform P0 — auth, tenancy, role dashboards

**Status:** queued
**Branch:** `feat/TASK-026-schools-p0` (not started)
**Base SHA:** TBD (after TASK-021/022 merge)
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

## Acceptance criteria
- [ ] Migrations additive + guarded (PRAGMA checks); fresh DB and upgraded DB
      both boot → unit tests
- [ ] Auth: register school → invite coach → student joins with code; wrong
      role cannot access another school's jobs → API tests
- [ ] Existing anonymous upload path unchanged with the flag off

## Risks / rollback
- Session/auth code is security-sensitive: argon2 + secure/HttpOnly/SameSite
  cookies + CSRF token on mutating forms; no secrets in repo.
- rollback: feature flag off restores today's anonymous app.
