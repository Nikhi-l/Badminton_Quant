# Baddy landing page

React source for the public `baddyai.com` landing page.

The existing upload, gallery, and Studio product remains the vanilla client in
`web/create.html`, backed by `web/app.js`, `web/style.css`, and
`web/replay3d.js`.

## Build

```bash
yarn install
PUBLIC_URL=/landing GENERATE_SOURCEMAP=false CI=true yarn build
```

Copy the generated JavaScript and CSS into `web/landing/static/`, update
`web/index.html` to reference the emitted hashes, and copy the three original
Baddy images into `web/assets/`.

The landing CTAs intentionally target:

- `/create.html#create` for reel generation
- `/create.html#gallery` for existing reels

`web/index.html` also redirects legacy `/#studio/<job>` and `/#preview` links
to `create.html` so shared Studio URLs continue to work after the root cutover.

## Production topology

- `/` — React marketing landing
- `/create.html` — uploader, gallery, processing queue, and Studio
- `/app.html` — Baddy Schools
- `/api/*` and `/media/*` — unchanged FastAPI routes
