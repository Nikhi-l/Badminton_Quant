/* Baddy 3D rally replay (TASK-025b/c). Self-contained software-3D canvas
renderer — court + net + reconstructed shuttle trajectory + player marionettes
+ racket lines — driven by the Studio transport. No build step, no three.js:
line rendering with our own perspective projection is ~200 lines and keeps the
layer weightless.

Contract with app.js: the panel lives in #replay3d, app.js calls
replay3D.render(ctx) from the studio tick when the layer is enabled. The SIM
state is quantized to the reconstruction fps (rally_3d.fps, 10–12) per the
review requirement ("keep it at low fps"); the canvas only repaints when the
sim bucket, camera, or size changes. */
/* global $, studio, trackContext, courtOf, interpPoseFrame, courtProject, reelSegments */

const replay3D = (() => {
  const CW = 6.1, CL = 13.4, NET_H = 1.55;
  const orbit = { az: -1.35, el: 0.42, dist: 16, tx: CW / 2, ty: CL / 2, tz: 0.6 };
  const PRESETS = {
    broadcast: { az: -1.35, el: 0.42, dist: 16 },
    side: { az: 0.0, el: 0.18, dist: 13 },
    top: { az: -1.5708, el: 1.35, dist: 15 },
  };
  let canvas = null, g = null, lastKey = "";

  /* ---------- camera ---------- */
  function camBasis() {
    const ce = Math.cos(orbit.el), se = Math.sin(orbit.el);
    const ca = Math.cos(orbit.az), sa = Math.sin(orbit.az);
    const eye = [orbit.tx + orbit.dist * ce * ca,
                 orbit.ty + orbit.dist * ce * sa,
                 orbit.tz + orbit.dist * se];
    const fwd = norm3([orbit.tx - eye[0], orbit.ty - eye[1], orbit.tz - eye[2]]);
    let right = norm3(cross(fwd, [0, 0, 1]));
    if (!isFinite(right[0])) right = [1, 0, 0];
    const down = cross(fwd, right);   // image y grows downward
    return { eye, fwd, right, down };
  }
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm3 = (v) => { const n = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / n, v[1] / n, v[2] / n]; };

  function project(b, p) {
    const d = [p[0] - b.eye[0], p[1] - b.eye[1], p[2] - b.eye[2]];
    const z = d[0] * b.fwd[0] + d[1] * b.fwd[1] + d[2] * b.fwd[2];
    if (z < 0.25) return null;
    const x = d[0] * b.right[0] + d[1] * b.right[1] + d[2] * b.right[2];
    const y = d[0] * b.down[0] + d[1] * b.down[1] + d[2] * b.down[2];
    const f = canvas.height * 1.25;
    return [canvas.width / 2 + f * x / z, canvas.height / 2 + f * y / z];
  }

  function line(b, p1, p2, style, width = 1, dash = null) {
    const a = project(b, p1), c = project(b, p2);
    if (!a || !c) return;
    g.strokeStyle = style;
    g.lineWidth = width;
    g.setLineDash(dash || []);
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(c[0], c[1]); g.stroke();
    g.setLineDash([]);
  }

  function dot(b, p, r, fill) {
    const a = project(b, p);
    if (!a) return;
    g.fillStyle = fill;
    g.beginPath(); g.arc(a[0], a[1], r, 0, Math.PI * 2); g.fill();
  }

  /* ---------- scene data ---------- */
  function rally3dFor(ctx) {
    if (!ctx || !ctx.seg) return null;
    const r3 = ctx.seg.r && ctx.seg.r.rally_3d;
    return (r3 && r3.status === "ok" && Array.isArray(r3.shots)) ? r3 : null;
  }

  function anyRally3d() {
    return (reelSegments() || []).some(s => s.r && s.r.rally_3d && s.r.rally_3d.status === "ok");
  }

  // Legacy results (pre-handedness-normalization courts) store shuttle samples
  // in an x-mirrored court frame (rally_3d.mirrored_frame); marionettes project
  // through the stored homography, so un-mirror the shuttle here or the two
  // render on opposite sides of the court (TASK-032).
  const sampleX = (r3, x) => (r3 && r3.mirrored_frame ? CW - x : x);

  function shuttleAt(r3, t) {
    for (const shot of r3.shots) {
      if (t < shot.t0 - 0.05 || t > shot.t1 + 0.05) continue;
      const s = shot.samples;
      if (!s || !s.length) continue;
      let i = 0;
      while (i + 1 < s.length && s[i + 1].t <= t) i++;
      const a = s[i], b = s[Math.min(i + 1, s.length - 1)];
      const k = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 0;
      const L = (u, v) => u + (v - u) * k;
      return { p: [sampleX(r3, L(a.x, b.x)), L(a.y, b.y), L(a.z, b.z)], shot };
    }
    return null;
  }

  // Marionette: feet anchored on the court plane via the homography; the 2D
  // keypoints become a camera-facing billboard scaled to a 1.7m standing height.
  function marionettes(ctx, b) {
    const c = courtOf();
    if (!c || !c.homography) return [];
    const pose = typeof currentPose === "function" ? currentPose(ctx) : null;
    if (!pose || !pose.people) return [];
    const out = [];
    for (const person of pose.people) {
      const kp = person.keypoints || [];
      const good = kp.filter(p => Number(p.confidence || 0) >= 0.12);
      if (good.length < 6) continue;
      const ys = good.map(p => p.y), xs = good.map(p => p.x);
      const y0 = Math.min(...ys), y1 = Math.max(...ys);
      const foot2d = { x: (xs.reduce((s, v) => s + v, 0) / xs.length), y: y1 };
      const ground = courtProject(c.homography, foot2d.x, foot2d.y);
      if (!ground || ground.u < -2 || ground.u > CW + 2 || ground.v < -2 || ground.v > CL + 2) continue;
      const spanN = Math.max(y1 - y0, 1e-3);
      const scale = 1.62 / spanN;             // ankles ≈ head-top × standing height
      // billboard axes: camera right (ground-projected) and world up
      const rx = norm3([b.right[0], b.right[1], 0]);
      const pts = kp.map(p => {
        if (Number(p.confidence || 0) < 0.12) return null;
        const dx = (p.x - foot2d.x) * scale * 1.35;   // slight widen: image x is foreshortened
        const dz = (y1 - p.y) * scale;
        return [ground.u + rx[0] * dx, ground.v + rx[1] * dx, Math.max(0, dz)];
      });
      out.push({ id: Number(person.id || 0), pts, ground });
    }
    return out;
  }

  const P_COLORS = ["#46e3ff", "#ff7ac6", "#ffd166", "#b388ff"];
  const LIMBS = [[5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
                 [11, 13], [13, 15], [12, 14], [14, 16]];

  /* ---------- drawing ---------- */
  function drawCourt(b) {
    const H = (m1, m2, w, s) => line(b, [m1[0], m1[1], 0], [m2[0], m2[1], 0], s || "rgba(255,255,255,.55)", w || 1.2);
    // floor glow
    g.fillStyle = "rgba(183,245,66,.045)";
    const poly = [[0, 0, 0], [CW, 0, 0], [CW, CL, 0], [0, CL, 0]].map(p => project(b, p));
    if (poly.every(Boolean)) {
      g.beginPath(); g.moveTo(poly[0][0], poly[0][1]);
      poly.slice(1).forEach(p => g.lineTo(p[0], p[1])); g.closePath(); g.fill();
    }
    H([0, 0], [CW, 0], 1.6); H([0, CL], [CW, CL], 1.6);
    H([0, 0], [0, CL], 1.6); H([CW, 0], [CW, CL], 1.6);
    const soft = "rgba(255,255,255,.28)";
    H([0.46, 0], [0.46, CL], 1, soft); H([CW - 0.46, 0], [CW - 0.46, CL], 1, soft);
    H([0, 0.76], [CW, 0.76], 1, soft); H([0, CL - 0.76], [CW, CL - 0.76], 1, soft);
    H([0, CL / 2 - 1.98], [CW, CL / 2 - 1.98], 1, soft);
    H([0, CL / 2 + 1.98], [CW, CL / 2 + 1.98], 1, soft);
    H([CW / 2, 0], [CW / 2, CL / 2 - 1.98], 1, soft);
    H([CW / 2, CL / 2 + 1.98], [CW / 2, CL], 1, soft);
    // net
    const netC = "rgba(70,227,255,.85)";
    line(b, [0, CL / 2, 0], [0, CL / 2, NET_H], netC, 1.6);
    line(b, [CW, CL / 2, 0], [CW, CL / 2, NET_H], netC, 1.6);
    line(b, [0, CL / 2, NET_H], [CW, CL / 2, NET_H], netC, 2);
    line(b, [0, CL / 2, NET_H - 0.76], [CW, CL / 2, NET_H - 0.76], "rgba(70,227,255,.3)", 1);
    for (let x = 0; x <= CW + 1e-6; x += CW / 10) {
      line(b, [x, CL / 2, NET_H - 0.76], [x, CL / 2, NET_H], "rgba(70,227,255,.22)", 0.8);
    }
  }

  function drawShuttle(b, r3, t) {
    // trajectory ribbon: full current shot faint + recent trail bright.
    // (A duplicated break used to fire on every future sample regardless of
    // isCur, so the documented current-shot preview never drew — TASK-032.)
    const cur = shuttleAt(r3, t);
    for (const shot of r3.shots) {
      const s = shot.samples || [];
      const isCur = cur && cur.shot === shot;
      for (let i = 0; i + 1 < s.length; i++) {
        const future = s[i + 1].t > t;
        if (future && !isCur) break;
        const age = t - s[i + 1].t;
        const o = !isCur ? 0.07 : (future ? 0.12 : Math.max(0.12, 0.7 - age * 0.5));
        line(b, [sampleX(r3, s[i].x), s[i].y, s[i].z],
             [sampleX(r3, s[i + 1].x), s[i + 1].y, s[i + 1].z],
             `rgba(183,245,66,${o.toFixed(3)})`, isCur ? 2 : 1);
      }
    }
    if (cur) {
      dot(b, cur.p, 4.5, "#eaffd0");
      dot(b, [cur.p[0], cur.p[1], 0], 2.5, "rgba(0,0,0,.35)");   // ground shadow
      g.fillStyle = "rgba(234,255,208,.85)";
      g.font = "600 10px Inter, sans-serif";
      const sp = project(b, cur.p);
      if (sp) g.fillText(`${cur.shot.speed_kmh} km/h`, sp[0] + 8, sp[1] - 8);
    }
  }

  function drawPlayers(b, people) {
    for (const person of people) {
      const color = P_COLORS[person.id % 4];
      dot(b, [person.ground.u, person.ground.v, 0.02], 3, `${color}55`);
      for (const [i, j] of LIMBS) {
        if (!person.pts[i] || !person.pts[j]) continue;
        line(b, person.pts[i], person.pts[j], color, 1.6);
      }
      if (person.pts[0]) dot(b, person.pts[0], 3, color);   // head
      // racket line: wrist extended along elbow→wrist, 0.65m
      for (const [el, wr] of [[7, 9], [8, 10]]) {
        const e = person.pts[el], w = person.pts[wr];
        if (!e || !w) continue;
        const d = norm3([w[0] - e[0], w[1] - e[1], w[2] - e[2]]);
        line(b, w, [w[0] + d[0] * 0.65, w[1] + d[1] * 0.65, w[2] + d[2] * 0.65],
             "rgba(255,255,255,.6)", 1.2);
      }
    }
  }

  /* ---------- main render (low-fps sim, cheap repaint gate) ---------- */
  function render(ctx) {
    const panel = $("replay3d");
    if (!panel || panel.hidden) return;
    if (!canvas) init(panel);
    const r3 = rally3dFor(ctx);
    const fps = (r3 && r3.fps) || 12;
    // Resize BEFORE the repaint memo — the old order computed the key from the
    // stale canvas dims and early-returned, leaving a stretched canvas after a
    // panel resize while paused (TASK-032).
    const rect = panel.getBoundingClientRect();
    if (canvas.width !== Math.round(rect.width) || canvas.height !== Math.max(120, Math.round(rect.height - 30))) {
      canvas.width = Math.round(rect.width);
      canvas.height = Math.max(120, Math.round(rect.height - 30));
    }
    // Physics stays on the low-fps sim clock (review requirement), but the
    // canvas repaints on a 30 Hz bucket so marionettes and the shuttle dot
    // interpolate smoothly between sim samples instead of stepping (TASK-032;
    // the visual lerp RALLY_3D_RECONSTRUCTION.md always specified).
    const bucket = ctx ? Math.round(ctx.sourceT * 30) : -1;
    const key = `${bucket}|${orbit.az.toFixed(3)}|${orbit.el.toFixed(3)}|${orbit.dist.toFixed(2)}|${canvas.width}x${canvas.height}|${r3 ? 1 : 0}`;
    if (key === lastKey) return;
    lastKey = key;

    g.clearRect(0, 0, canvas.width, canvas.height);
    const b = camBasis();
    drawCourt(b);
    if (r3) {
      drawShuttle(b, r3, ctx.sourceT);
      drawPlayers(b, marionettes(ctx, b));
      g.fillStyle = "rgba(174,181,198,.8)";
      g.font = "600 10px Inter, sans-serif";
      g.fillText(`${r3.shots.length} shots · sim ${fps}fps`, 10, canvas.height - 8);
    } else {
      drawPlayers(b, marionettes(ctx, b));
      g.fillStyle = "rgba(174,181,198,.8)";
      g.font = "600 10px Inter, sans-serif";
      g.fillText(noReconMessage(ctx), 10, canvas.height - 8);
    }
  }

  // WHY there's no 3D for this rally — the backend now ships a slim status on
  // every rally (TASK-032) instead of silently omitting rally_3d.
  const R3D_REASONS = {
    no_court: "no court geometry — draw the corners in the Court layer",
    no_track: "no TrackNet shuttle track for this rally",
    bad_camera: "camera pose could not be recovered from the court",
    no_fit: "no ballistic fit matched the shuttle track",
    failed: "reconstruction failed",
  };
  function noReconMessage(ctx) {
    const r3 = ctx && ctx.seg && ctx.seg.r && ctx.seg.r.rally_3d;
    const why = r3 && R3D_REASONS[r3.status];
    return why ? `no 3D for this rally: ${why}` : "no 3D reconstruction for this rally";
  }

  /* ---------- setup + interaction ---------- */
  function init(panel) {
    canvas = panel.querySelector("canvas");
    g = canvas.getContext("2d");
    let dragging = false, lx = 0, ly = 0;
    canvas.addEventListener("pointerdown", (e) => {
      dragging = true; lx = e.clientX; ly = e.clientY;
      canvas.setPointerCapture(e.pointerId);
      e.stopPropagation();   // don't pan the Studio canvas underneath
      e.preventDefault();
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      orbit.az -= (e.clientX - lx) * 0.008;
      orbit.el = Math.min(1.45, Math.max(0.05, orbit.el + (e.clientY - ly) * 0.006));
      lx = e.clientX; ly = e.clientY;
      lastKey = "";
      render(typeof trackContext === "function" ? trackContext() : null);
    });
    const up = (e) => { dragging = false; try { canvas.releasePointerCapture(e.pointerId); } catch { /* ignore */ } };
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault(); e.stopPropagation();
      orbit.dist = Math.min(34, Math.max(6, orbit.dist * (e.deltaY > 0 ? 1.08 : 1 / 1.08)));
      lastKey = "";
      render(typeof trackContext === "function" ? trackContext() : null);
    }, { passive: false });
    panel.querySelectorAll("[data-r3d-view]").forEach(btn => {
      btn.onclick = () => {
        Object.assign(orbit, PRESETS[btn.dataset.r3dView] || PRESETS.broadcast);
        lastKey = "";
        render(typeof trackContext === "function" ? trackContext() : null);
      };
    });
  }

  return { render, anyRally3d, invalidate: () => { lastKey = ""; } };
})();
