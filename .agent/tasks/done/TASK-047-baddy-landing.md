# TASK-047 — Baddy marketing landing with preserved product entry

**Branch:** `feat/TASK-047-landing-page` (merged as PR #4)
**Base SHA:** `00164823fbf3f169d9f4e69d0795adcdaa401991`
**Merge SHA:** `f43ed3f5673c410cdcc43c0d9bd2aff007327272`
**PRD:** §16 remediation — TASK-047
**Source:** owner request 2026-07-24 to deploy the accepted LifeLapse-derived
landing design to `baddyai.com`.

## Goal

Make the dark/neon-green Baddy landing page the public root without replacing
or weakening the existing uploader, processing queue, gallery, and Studio.

## Scope

1. Keep the existing vanilla product page byte-for-byte as `web/create.html`.
2. Serve the React marketing landing at `web/index.html`, with its source in
   `landing/` and its production bundle isolated under `web/landing/`.
3. Point reel and gallery CTAs to `/create.html#create` and
   `/create.html#gallery`.
4. Redirect legacy root hashes (`/#studio/<job>`, `/#preview`, `/#create`,
   `/#gallery`) to `create.html` so shared product links remain valid.
5. Use original Baddy Studio and tracked-rally images; do not ship the retired
   phone mockup or the generated rally image.

## Acceptance criteria

- [x] `/` contains `data-deployment="baddy-landing-v1"` and loads the hashed
      landing JS/CSS.
- [x] `/create.html#create` still exposes the file picker and analysis workers.
- [x] `/create.html#gallery` still exposes the current reel gallery.
- [x] `/#studio/<job>` redirects to `/create.html#studio/<job>`.
- [x] `/api/health`, `/app.html`, `/architecture`, and existing static/API
      routes remain unchanged.
- [x] `./scripts/check.sh` passes.
- [x] Live domain and assets return HTTP 200 after deployment.

## Verification

- `PUBLIC_URL=/landing GENERATE_SOURCEMAP=false CI=true yarn build`
- `./scripts/check.sh`
- Static deployment-contract checks in
  `tests/regression/test_landing_deployment_contract.py`
- Post-deploy HTTP checks for `/`, `/create.html`, hashed assets, and
  `/api/health`
- Rendered desktop/mobile validation when the localhost/browser policy permits

## Live deployment

Deployed from clean `main@f43ed3f` on 2026-07-24 with
`bash deploy/deploy.sh`.

- `baddy.service` and `caddy.service` active; `/api/health` returned
  `{"ok":true}`.
- `/`, `/create.html`, `/app.html`, `/architecture`, and the hashed landing
  assets returned HTTP 200.
- Public, VM, and merged-main hashes matched for `index.html`, `create.html`,
  `app.html`, JS, and CSS.
- Browser QA verified the landing and uploader with no console warnings/errors.
- A legacy `/#studio/adda60dbf93e` link reopened the existing editor at
  `/create.html#studio/adda60dbf93e`, including shuttle and pose layers.
- Production retained all 35 prior jobs (33 done, 2 failed).

## Rollback

Revert the TASK-047 merge commit and run `bash deploy/deploy.sh` from the clean
reverted `main` tree. The deploy excludes `/opt/baddy/data`, so existing jobs
and media are retained.
