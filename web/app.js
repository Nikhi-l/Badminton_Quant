/* Baddy frontend: upload, job progress, gallery. Vanilla JS, no build step. */
const $ = (id) => document.getElementById(id);

/* ---------- per-job vision worker selection ---------- */
function currentOptions() {
  return {
    shuttle: $("optShuttle").checked ? "tracknetv3" : "off",
    pose: $("optPose").checked ? "yolo11" : "off",
    coach: $("optCoach").checked,
  };
}

function bindVopt(id) {
  const box = $(id).querySelector("input");
  const sync = () => $(id).classList.toggle("checked", box.checked);
  box.addEventListener("change", sync);
  sync();
}

async function initWorkerOptions() {
  ["voptShuttle", "voptPose", "voptCoach"].forEach(bindVopt);
  try {
    const cap = await (await fetch("/api/capabilities")).json();
    const setAvail = (wrapId, ok, note) => {
      const el = $(wrapId);
      el.classList.toggle("disabled", !ok);
      if (note) el.querySelector(".vopt-s").textContent = note;
      if (!ok) el.querySelector("input").checked = false;
    };
    const sh = cap.shuttle?.tracknetv3 || {};
    setAvail("voptShuttle", sh.available,
      sh.available ? `TrackNetV3 · ${sh.backend === "runpod" ? "GPU" : "on-device"} · locks camera to the shuttle`
                   : "TrackNetV3 · unavailable (no GPU configured)");
    const po = cap.pose?.yolo11 || {};
    setAvail("voptPose", po.available);
    setAvail("voptCoach", cap.coach?.available);
    $("optShuttle").checked = sh.available && cap.defaults?.shuttle === "tracknetv3";
    $("optPose").checked = po.available && cap.defaults?.pose === "yolo11";
    ["voptShuttle", "voptPose", "voptCoach"].forEach(id =>
      $(id).classList.toggle("checked", $(id).querySelector("input").checked));
  } catch { /* capabilities optional; checkboxes stay as-is */ }
}

const STAGE_META = {
  combine:  ["Ordering & joining clips", "🧩"],
  probe:    ["Reading your video", "🔍"],
  proxy:    ["Building analysis proxy", "📉"],
  rallies:  ["Gemini finding rallies", "🧠"],
  vision:   ["Pose + shuttle analysis", "🧬"],
  tracking: ["Tracking the action", "🎯"],
  render:   ["AI virtual camera render", "🎥"],
  validate: ["Quality check (AI reviews frames)", "✅"],
  coach:    ["Gemini coach notes", "C"],
  stitch:   ["Beat-synced stitch", "🎵"],
};

const myJobs = new Set(JSON.parse(localStorage.getItem("baddy_jobs") || "[]"));
let activeTab = "community";
let pollTimer = null;
let galleryItems = [];

/* ---------- upload ---------- */
const drop = $("drop"), fileInput = $("file");
$("browse").onclick = () => fileInput.click();
drop.onclick = (e) => { if (e.target === drop || e.target.closest(".drop-idle")) fileInput.click(); };
fileInput.onchange = () => fileInput.files.length && startUpload([...fileInput.files]);
["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => {
  const fs = [...e.dataTransfer.files];
  if (fs.length) startUpload(fs);
});

async function jfetch(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();
}

async function putChunk(id, index, blob, fileIdx = 0) {
  let delay = 800;
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      return await jfetch(`/api/upload/${id}/chunk/${index}?file=${fileIdx}`, { method: "PUT", body: blob });
    } catch (e) {
      if (attempt === 4) throw e;
      await new Promise(res => setTimeout(res, delay));
      delay *= 2;
    }
  }
}

async function startUpload(files) {
  const totalBytes = files.reduce((s, f) => s + f.size, 0);
  if (totalBytes > 3 * 1024 ** 3) return alert("Keep the total under 3 GB please 🙏");
  showPanel();
  $("jobTitle").textContent = "Uploading";
  $("jobFile").textContent = files.length === 1
    ? `${files[0].name} · ${(totalBytes / 1024 ** 2).toFixed(0)} MB`
    : `${files.length} clips of one game · ${(totalBytes / 1024 ** 2).toFixed(0)} MB · ordered by recording time`;
  $("upbarWrap").style.display = "block";
  $("upbar").style.width = "0%";
  $("jobResult").hidden = true;
  $("jobMsg").textContent = ""; $("jobMsg").classList.remove("err");
  renderStages([]);

  try {
    // Chunked upload: each piece retries on its own, so one network blip
    // doesn't kill a multi-hundred-MB transfer. Multiple clips share one job.
    let jobId = null;
    let sent = 0;
    for (let k = 0; k < files.length; k++) {
      const file = files[k];
      const init = await jfetch("/api/upload/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jobId
          ? { filename: file.name, size: file.size, job: jobId, index: k }
          : { filename: file.name, size: file.size }),
      });
      jobId = init.id;
      const total = Math.ceil(file.size / init.chunk_size);
      for (let i = 0; i < total; i++) {
        await putChunk(jobId, i, file.slice(i * init.chunk_size, (i + 1) * init.chunk_size), k);
        sent = Math.min(sent + init.chunk_size, files.slice(0, k).reduce((s, f) => s + f.size, 0) + Math.min((i + 1) * init.chunk_size, file.size));
        $("upbar").style.width = `${(sent / totalBytes * 100).toFixed(1)}%`;
        $("jobMsg").textContent = `uploading ${files.length > 1 ? `clip ${k + 1}/${files.length} · ` : ""}${(sent / 1024 ** 2).toFixed(0)} / ${(totalBytes / 1024 ** 2).toFixed(0)} MB`;
      }
    }
    await jfetch(`/api/upload/${jobId}/finish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: files.length, options: currentOptions() }),
    });
    myJobs.add(jobId);
    localStorage.setItem("baddy_jobs", JSON.stringify([...myJobs]));
    $("upbarWrap").style.display = "none";
    $("jobMsg").textContent = "";
    $("jobTitle").textContent = "Generating your highlights";
    poll(jobId);
  } catch (e) {
    failJob(`Upload failed: ${e.message} — check your connection and try again`);
  }
}

function showPanel() {
  $("jobPanel").hidden = false;
  $("jobSpin").style.display = "block";
  $("jobPanel").scrollIntoView({ behavior: "smooth", block: "center" });
}
function failJob(msg) {
  $("jobSpin").style.display = "none";
  $("jobMsg").textContent = msg;
  $("jobMsg").classList.add("err");
}

/* ---------- job polling ---------- */
function renderStages(stages) {
  $("stageList").innerHTML = Object.keys(STAGE_META).map(key => {
    const st = (stages.find(s => s.key === key) || {}).state || "pending";
    const [label, icon] = STAGE_META[key];
    const mark = st === "done" ? "✓" : (st === "failed" ? "!" : icon);
    return `<li class="${st}"><span class="dot">${mark}</span>${label}</li>`;
  }).join("");
}

function poll(id) {
  clearInterval(pollTimer);
  const tick = async () => {
    let job;
    try { job = await (await fetch(`/api/jobs/${id}`)).json(); } catch { return; }
    renderStages(job.stages || []);
    $("jobMsg").textContent = jobStatusText(job);
    if (job.status === "done") {
      clearInterval(pollTimer);
      showResult(job);
    } else if (job.status === "failed" || job.status === "error") {
      clearInterval(pollTimer);
      failJob(`Something broke: ${job.error}`);
    }
  };
  tick();
  pollTimer = setInterval(tick, 2500);
}

function genText(job) {
  const pipe = (job.pipeline || "unknown").toUpperCase();
  const elapsed = job.gen_seconds ? `${job.gen_seconds}s` : "";
  const expected = job.expected_gen_seconds ? `target ~${Math.round(job.expected_gen_seconds / 60)}m` : "";
  return [pipe, elapsed, expected].filter(Boolean).join(" · ");
}

function jobStatusText(job) {
  const bits = [];
  if (job.message) bits.push(job.message);
  const meta = genText(job);
  if (meta) bits.push(meta);
  return bits.join(" — ");
}

function showResult(job) {
  $("jobSpin").style.display = "none";
  $("jobTitle").textContent = "Done";
  const r = job.result;
  $("jobResult").hidden = false;
  $("resultVideo").src = r.video;
  $("downloadBtn").href = r.video;
  const u = r.gemini_usage;
  $("resultMeta").innerHTML =
    `${r.duration}s reel · ${r.n_rallies_used} of ${r.n_rallies_found} rallies (longest first)` +
    (job.pipeline ? `<br>${esc(genText(job))}` : "") +
    (r.n_clips > 1 ? `<br>${r.n_clips} clips joined · ordered by ${esc(r.clip_order || "upload order")}` : "") +
    visionSummaryHtml(r.vision, "<br>") +
    coachSummaryHtml(r.coach, "<br>") +
    (u ? `<br>AI cost: ~$${u.est_cost_usd.toFixed(3)} (${((u.prompt_tokens + u.output_tokens) / 1000).toFixed(0)}k tokens, ${u.calls} Gemini calls)` : "") + "<br>" +
    (r.rallies || []).map((x, i) => `R${i + 1}: ${x.dur}s ${x.note ? "— " + esc(x.note) : ""}`).join("<br>");
  $("resultStudio").onclick = () => openStudio({ ...r, id: job.id, filename: job.filename });
  $("resultShare").innerHTML = shareHtml(job.id);
  bindShare($("resultShare"), { ...r, id: job.id });
  loadGallery();
}
$("anotherBtn").onclick = () => { $("jobPanel").hidden = true; fileInput.value = ""; window.scrollTo({ top: 0, behavior: "smooth" }); };

/* ---------- gallery ---------- */
const esc = (s = "") => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtPct = (v) => `${Math.round((Number(v) || 0) * 100)}%`;

function modelSummaryText(models) {
  const m = models || {};
  const bits = [];
  if (m.pose && m.pose.enabled) bits.push("YOLO pose");
  if (m.tracknet && m.tracknet.enabled) bits.push("TrackNet model");
  if (m.racquet && m.racquet.enabled) bits.push("racquet measured");
  else if (m.racquet) bits.push("racquet detector pending");
  return bits.join(" · ");
}

function visionSummaryHtml(vision, sep = " · ") {
  if (!vision) return "";
  const s = (vision || {}).summary || {};
  if (vision.status === "ok") {
    const shuttleEngine = s.shuttle_engine === "tracknetv3" ? " · TrackNetV3" : "";
    const models = modelSummaryText(vision.models);
    return `${sep}Coach engine: ${esc(vision.engine || "runpod")} · players ${fmtPct(s.player_quality)} · shuttle ${fmtPct(s.shuttle_quality)}${shuttleEngine}${s.shuttle_mask ? " · shuttle mask" : ""}${models ? " · " + esc(models) : ""}`;
  }
  if (vision.status === "failed") return `${sep}Coach engine: GPU failed, CPU tracker used`;
  return `${sep}Coach engine: CPU tracker`;
}

function rallyVisionText(vision) {
  if (!vision || vision.status !== "ok") return "";
  const bits = [];
  if ((vision.shuttle_engine || "") === "tracknetv3") bits.push("TrackNetV3");
  if (vision.mask_enabled) bits.push("mask");
  bits.push(`pose ${fmtPct(vision.pose_quality)}`);
  bits.push(`shuttle ${fmtPct(vision.shuttle_quality)}`);
  if (Number(vision.racquet_quality) > 0) bits.push(`racquet ${fmtPct(vision.racquet_quality)}`);
  else if (Number(vision.racquet_candidate_quality) > 0) bits.push(`racquet candidate ${fmtPct(vision.racquet_candidate_quality)}`);
  return bits.join(" · ");
}

function rallyVisionTitle(vision) {
  if (!vision) return "";
  const tracknet = vision.tracknet || {};
  const lines = [
    `Players: ${fmtPct(vision.player_quality)}`,
    `Pose: ${fmtPct(vision.pose_quality)} (${vision.pose_samples || 0} samples)`,
    `Racquet: ${fmtPct(vision.racquet_quality)} (${vision.racquet_samples || 0} samples)`,
    `Racquet candidates: ${fmtPct(vision.racquet_candidate_quality)} (${vision.racquet_candidate_samples || 0} samples)`,
    `Shuttle: ${fmtPct(vision.shuttle_quality)} (${vision.shuttle_samples || 0} samples)`,
  ];
  if ((vision.shuttle_engine || "") === "tracknetv3") {
    lines.push(`TrackNetV3: ${tracknet.status || "ok"}${tracknet.points ? ` · ${tracknet.points} points` : ""}`);
  }
  if (vision.mask_enabled) lines.push("Shuttle mask enabled in render");
  return lines.join("\n");
}

function coachSummaryHtml(coach, sep = " · ") {
  if (!coach) return "";
  const frames = (((coach.evidence || {}).frames) || []).length;
  const evidence = frames ? ` · ${frames} frames` : "";
  const racquet = (((coach.summary || {}).racquet_evidence || {}).mode);
  const racquetText = racquet === "measured" ? " · racquet measured"
    : racquet === "pose_guided_candidate" ? " · racquet candidate"
    : racquet === "frame_context_only" ? " · racquet frame context"
    : "";
  if (coach.status === "ok") {
    return `${sep}Coach notes: ${esc(coach.headline || "ready")} · confidence ${fmtPct(coach.confidence)}${evidence}${racquetText}`;
  }
  if (coach.status === "failed") return `${sep}Coach notes: Gemini failed`;
  if (coach.status === "skipped") return `${sep}Coach notes: ${esc(coach.message || "skipped")}`;
  return "";
}

function timeAgo(ts) {
  const s = (Date.now() / 1000) - ts;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

async function loadGallery() {
  try {
    galleryItems = (await (await fetch("/api/gallery")).json()).items;
    galleryItems.forEach(i => {   // version media URLs so remixed reels bypass cache
      const v = `?v=${Math.floor(i.created_at || 0)}`;
      i.video += v; i.thumb += v;
    });
  } catch { galleryItems = []; }
  renderGallery();
}

function renderGallery() {
  const items = activeTab === "mine" ? galleryItems.filter(i => myJobs.has(i.id)) : galleryItems;
  $("galleryEmpty").hidden = items.length > 0;
  $("grid").innerHTML = items.map(i => `
    <div class="card" data-id="${i.id}">
      <div class="media">
        <img loading="lazy" src="${i.thumb}" alt="">
        <video muted loop playsinline preload="none"></video>
      </div>
      <div class="card-meta">
        <span class="pill">⏱ ${Math.round(i.duration)}s</span>
        <span class="pill">🏸 ${i.n_rallies_used}</span>
        ${i.n_clips > 1 ? `<span class="pill">🧩 ${i.n_clips}</span>` : ""}
        ${i.vision && i.vision.status === "ok" ? `<span class="pill" title="${esc(visionSummaryHtml(i.vision, "").trim())}">🧬 ${fmtPct((i.vision.summary || {}).player_quality)}</span>` : ""}
        ${i.coach && i.coach.status === "ok" ? `<span class="pill" title="${esc(coachSummaryHtml(i.coach, "").trim())}">C ${fmtPct(i.coach.confidence)}</span>` : ""}
        ${i.gemini_usage ? `<span class="pill" title="${(i.gemini_usage.prompt_tokens / 1000).toFixed(0)}k in + ${(i.gemini_usage.output_tokens / 1000).toFixed(1)}k out tokens, ${i.gemini_usage.calls} calls">💳 $${i.gemini_usage.est_cost_usd.toFixed(3)}</span>` : ""}
        <span class="when">${timeAgo(i.created_at)}</span>
      </div>
      <button class="card-studio studio-open">🎬 Open in Studio</button>
    </div>`).join("");

  document.querySelectorAll(".card").forEach(card => {
    const item = galleryItems.find(i => i.id === card.dataset.id);
    const vid = card.querySelector("video");
    card.addEventListener("mouseenter", () => {
      if (!vid.src) vid.src = item.video;
      vid.play().then(() => card.classList.add("playing")).catch(() => {});
    });
    card.addEventListener("mouseleave", () => { vid.pause(); card.classList.remove("playing"); });
    card.addEventListener("click", () => openModal(item));
    card.querySelector(".studio-open").addEventListener("click", (e) => {
      e.stopPropagation();
      openStudio(item);
    });
  });
}

document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  activeTab = t.dataset.tab;
  renderGallery();
});

/* ---------- studio: AI reel editor ---------- */
const studio = {
  item: null,
  mode: "reel",
  raf: 0,
  selectedLayer: "reel",
  zoom: 1,
  dur: 1,
  timelineSegments: [],
  editorState: null,
};
const fmtT = (s) => { s = Math.max(0, s || 0); return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`; };
const styleLabel = (s = "") => s.replace(/[-_]/g, " ").replace(/\b\w/g, c => c.toUpperCase());

function openStudio(item) {
  studio.item = item;
  studio.mode = "reel";
  studio.selectedLayer = "reel";
  studio.zoom = 1;
  studio.editorState = loadEditorState(item);
  $("studio").hidden = false;
  $("studioFile").textContent = [item.filename, item.sport].filter(Boolean).join(" · ");
  $("studioDownload").href = item.video;
  $("stageFrame").style.setProperty("--stage-zoom", studio.zoom);
  $("zoomLabel").textContent = "Fit";
  document.body.style.overflow = "hidden";
  initEdit();
  renderCoachbar(item);
  renderLayerList();
  renderInspector();
  setStudioMode("reel");
  cancelAnimationFrame(studio.raf);
  studioTick();
}

function editorKey(item = studio.item) {
  return `baddy_editor_state_${item && item.id ? item.id : "draft"}`;
}

function defaultEditorState(item) {
  const pool = item.rally_pool || item.rallies || [];
  const order = (item.remix && item.remix.order) || pool.map((_, i) => i + 1);
  return {
    schema: "baddy.editor.v1",
    canvas: { width: 1080, height: 1920, fps: 30, format: "vertical-reel" },
    remix: { order, mirror: !!(item.remix && item.remix.mirror) },
    overlays: {
      shuttle: { enabled: true, style: "ring", size: 54, opacity: 0.92, trail: true },
      pose: { enabled: !!(item.options && item.options.pose === "yolo11"), style: "glow", lineWidth: 3, opacity: 0.82 },
    },
    audio: { bed: "current-stitch", editable: false },
  };
}

function mergeEditorState(base, saved) {
  if (!saved || saved.schema !== "baddy.editor.v1") return base;
  return {
    ...base,
    ...saved,
    canvas: { ...base.canvas, ...(saved.canvas || {}) },
    remix: { ...base.remix, ...(saved.remix || {}) },
    overlays: {
      shuttle: { ...base.overlays.shuttle, ...((saved.overlays || {}).shuttle || {}) },
      pose: { ...base.overlays.pose, ...((saved.overlays || {}).pose || {}) },
    },
    audio: { ...base.audio, ...(saved.audio || {}) },
  };
}

function loadEditorState(item) {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(editorKey(item)) || "null"); } catch {}
  return mergeEditorState(defaultEditorState(item), saved);
}

function saveEditorState() {
  localStorage.setItem(editorKey(), JSON.stringify(studio.editorState));
}

function renderCoachbar(item) {
  const bar = $("coachbar");
  const vision = item.vision;
  const coach = item.coach;
  if (!vision && !coach) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  const s = (vision && vision.summary) || {};
  const parts = [];
  if (coach && coach.status === "ok") {
    const strength = (coach.strengths || [])[0];
    const focus = (coach.work_on || [])[0];
    const frames = (((coach.evidence || {}).frames) || []).length;
    const racquet = (((coach.summary || {}).racquet_evidence || {}).mode);
    parts.push(`<span class="coach-pill ok">Gemini coach</span>`);
    parts.push(`<span class="coach-main">${esc(coach.headline || "Coach notes ready")}</span>`);
    if (frames) parts.push(`<span class="coach-metric">Evidence: measured CV + ${frames} frames</span>`);
    if (racquet === "measured") parts.push(`<span class="coach-metric">Racquet evidence: measured boxes</span>`);
    if (racquet === "pose_guided_candidate") parts.push(`<span class="coach-metric">Racquet evidence: pose-guided candidates</span>`);
    if (racquet === "frame_context_only") parts.push(`<span class="coach-metric">Racquet evidence: frame context only</span>`);
    if (strength) parts.push(`<span class="coach-note">Good: ${esc(strength)}</span>`);
    if (focus) parts.push(`<span class="coach-note">Focus: ${esc(focus)}</span>`);
  } else if (coach && coach.status && coach.status !== "disabled") {
    parts.push(`<span class="coach-pill">Coach notes</span>`);
    parts.push(`<span class="coach-note muted">${esc(coach.message || "not enough measured signal yet")}</span>`);
  }
  if (vision) {
    const models = vision.models || {};
    const modelText = modelSummaryText(models);
    parts.push(`
      <span class="coach-pill ${vision.status === "ok" ? "ok" : ""}">${vision.status === "ok" ? "Runpod vision" : "CPU tracker"}</span>
      <span class="coach-metric">Players ${fmtPct(s.player_quality)}</span>
      <span class="coach-metric">Pose ${fmtPct(s.pose_quality)}</span>
      <span class="coach-metric">Racquet ${fmtPct(s.racquet_quality)}</span>
      ${Number(s.racquet_candidate_quality) > 0 ? `<span class="coach-metric">Racquet candidate ${fmtPct(s.racquet_candidate_quality)}</span>` : ""}
      <span class="coach-metric">Shuttle ${fmtPct(s.shuttle_quality)}${s.shuttle_engine === "tracknetv3" ? " · TrackNetV3" : ""}${s.shuttle_mask ? " · mask on" : ""}</span>
      ${modelText ? `<span class="coach-metric">Models: ${esc(modelText)}</span>` : ""}
      ${models.tracknet && models.tracknet.error ? `<span class="coach-metric warn">TrackNet: ${esc(models.tracknet.error)}</span>` : ""}
      <span class="muted">${esc(vision.message || "")}</span>`);
  }
  if (!parts.length) {
    bar.hidden = true;
    bar.innerHTML = "";
    return;
  }
  bar.hidden = false;
  bar.innerHTML = parts.join("");
}

function setStudioMode(mode) {
  const src = mode === "reel" ? studio.item.video : studio.item.proxy;
  if (!src) {
    $("tpHint").textContent = "source video isn't available for this reel";
    return;
  }
  studio.mode = mode;
  $("modeReel").classList.toggle("active", mode === "reel");
  $("modeSource").classList.toggle("active", mode === "source");
  const v = $("stVideo");
  v.src = src;
  v.onerror = () => { $("tpHint").textContent = "video failed to load — try the other view"; };
  v.play().catch(() => {});
  buildTimeline();
  const hasAll = studio.item.all_rallies && studio.item.all_rallies.length;
  $("tpHint").textContent = mode === "reel"
    ? "Reel preview"
    : hasAll
      ? "Source rally analysis"
      : "Reel rally analysis";
  updateOverlayPreview();
}

function reelSegments() {
  let acc = 0;
  return (studio.item.rallies || []).map((r, i) => {
    const dur = r.clip_dur || r.dur || 0;
    const seg = {
      t0: acc,
      t1: acc + dur,
      label: `R${i + 1}`,
      sub: `${Math.round(r.dur || dur)}s${r.note ? " · " + r.note : ""}`,
      layer: "reel",
      r,
      idx: i + 1,
      sourceStart: Number(r.start ?? r.src_start ?? 0),
      vision: r.vision,
    };
    acc = seg.t1;
    return seg;
  });
}

function buildTimeline() {
  const item = studio.item;
  const lane = $("tlLane"), labels = $("tlLabels"), ruler = $("tlRuler");
  lane.innerHTML = ""; labels.innerHTML = ""; ruler.innerHTML = "";
  const timelineScale = Math.max(0.8, Math.min(1.8, Number($("timelineZoom").value || 100) / 100));
  lane.style.minWidth = `${timelineScale * 100}%`;
  ruler.style.minWidth = `${timelineScale * 100}%`;
  let dur, tracks;
  if (studio.mode === "reel") {
    dur = item.duration || 1;
    const cuts = reelSegments();
    const shuttleOn = studio.editorState.overlays.shuttle.enabled;
    const poseOn = studio.editorState.overlays.pose.enabled;
    tracks = [
      { id: "reel", label: "Reel cuts", count: cuts.length, type: "clip", segs: cuts },
      { id: "shuttle", label: "Shuttle FX", count: shuttleOn ? cuts.length : 0, type: "shuttle",
        segs: shuttleOn ? cuts.map(s => ({ ...s, layer: "shuttle", label: studio.editorState.overlays.shuttle.style, sub: rallyVisionText(s.vision) || "overlay" })) : [] },
      { id: "pose", label: "Pose", count: poseOn ? cuts.length : 0, type: "pose",
        segs: poseOn ? cuts.map(s => ({ ...s, layer: "pose", label: studio.editorState.overlays.pose.style, sub: "skeleton" })) : [] },
      { id: "soundtrack", label: "Soundtrack", count: 1, type: "audio",
        segs: [{ t0: 0, t1: dur, label: "Current bed", sub: "from reel stitch", layer: "soundtrack" }] },
    ];
  } else {
    dur = item.source_duration || 1;
    const list = (item.all_rallies && item.all_rallies.length)
      ? item.all_rallies
      : (item.rallies || []).map(r => ({ ...r, used: true }));
    tracks = [
      { id: "source", label: "Source rallies", count: list.length, type: "source",
        segs: list.map((r, i) => ({ t0: r.start || 0, t1: r.end || (r.start || 0) + (r.dur || 0),
          label: `R${i + 1}`, sub: `${Math.round(r.dur || 0)}s${r.note ? " · " + r.note : ""}`, skip: !r.used, layer: "reel" })) },
      { id: "shuttle", label: "Shuttle FX", count: trackedRallies().length, type: "shuttle",
        segs: trackedRallies().map(s => ({ ...s, layer: "shuttle", label: "Track", sub: rallyVisionText(s.vision) || "source coordinates" })) },
      { id: "pose", label: "Pose", count: poseReadyCount(), type: "pose", segs: [] },
      { id: "soundtrack", label: "Soundtrack", count: 0, type: "audio", segs: [] },
    ];
  }
  studio.dur = dur;
  studio.timelineSegments = tracks.flatMap(t => t.segs.map(s => ({ ...s, type: t.type })));
  $("timelineMeta").textContent = `· ${fmtT(dur)} · ${tracks.length} tracks`;
  const step = dur > 200 ? 30 : dur > 90 ? 15 : dur > 40 ? 10 : 5;
  for (let t = 0; t <= dur; t += step) {
    const el = document.createElement("div");
    el.className = "tick";
    el.style.left = `${t / dur * 100}%`;
    el.textContent = fmtT(t);
    ruler.appendChild(el);
  }
  tracks.forEach(track => {
    labels.insertAdjacentHTML("beforeend", `<div class="track-label">${esc(track.label)} <span>${track.count}</span></div>`);
    const row = document.createElement("div");
    row.className = "lane-row";
    row.dataset.track = track.id;
    lane.appendChild(row);
    track.segs.forEach(s => {
      const el = document.createElement("div");
      el.className = `seg ${track.type}` + (s.skip ? " skip" : "") +
        (s.vision && s.vision.status === "ok" ? " vision-ok" : "") +
        (s.vision && s.vision.mask_enabled ? " mask-on" : "") +
        (s.layer === studio.selectedLayer ? " active-seg" : "");
      el.style.left = `${Math.max(0, s.t0) / dur * 100}%`;
      el.style.width = `${Math.max((s.t1 - s.t0) / dur * 100, 1.4)}%`;
      el.innerHTML = `<b>${esc(s.label)}</b><span>${esc(s.sub || "")}</span>`;
      if (s.vision) el.title = rallyVisionTitle(s.vision);
      el.onclick = (e) => {
        e.stopPropagation();
        selectLayer(s.layer || track.id);
        const v = $("stVideo");
        v.currentTime = Math.min(s.t0 + 0.05, v.duration || dur);
        v.play().catch(() => {});
      };
      row.appendChild(el);
    });
  });
  updateOverlayPreview();
}

function studioTick() {
  if ($("studio").hidden) return;
  const v = $("stVideo");
  const dur = v.duration || studio.dur || 1;
  const timelineScale = Math.max(0.8, Math.min(1.8, Number($("timelineZoom").value || 100) / 100));
  $("tlHead").style.left = `${Math.min(v.currentTime / dur, 1) * timelineScale * 100}%`;
  $("tpTime").textContent = `${fmtT(v.currentTime)} / ${fmtT(dur)}`;
  $("tpPlay").textContent = v.paused ? "▶" : "⏸";
  $("tpScrub").value = String(Math.round(Math.min(v.currentTime / dur, 1) * 1000));
  updateOverlayPreview();
  studio.raf = requestAnimationFrame(studioTick);
}

function trackedRallies() {
  return reelSegments().filter(s => ((s.vision || {}).shuttle_track || []).length);
}

function poseReadyCount() {
  return (studio.item.rallies || []).filter(r => Number(((r.vision || {}).pose_quality) || 0) > 0).length;
}

function renderLayerList() {
  const state = studio.editorState;
  const pool = studio.item.rally_pool || studio.item.rallies || [];
  const included = (studio.edit || []).filter(e => e.on).length || state.remix.order.length;
  const layers = [
    { id: "reel", ico: "▤", title: "Reel cuts", sub: `${included}/${pool.length || included} rallies`, state: "live" },
    { id: "shuttle", ico: "◉", title: "Shuttle FX", sub: `${styleLabel(state.overlays.shuttle.style)} · ${Math.round(state.overlays.shuttle.opacity * 100)}%`, state: state.overlays.shuttle.enabled ? "on" : "off" },
    { id: "pose", ico: "◇", title: "Pose skeleton", sub: `${styleLabel(state.overlays.pose.style)} · ${poseReadyCount()} rallies`, state: state.overlays.pose.enabled ? "on" : "off" },
    { id: "soundtrack", ico: "♪", title: "Soundtrack", sub: "Current stitch bed", state: "fixed" },
  ];
  $("layerList").innerHTML = layers.map(l => `
    <button class="layer-row ${studio.selectedLayer === l.id ? "active" : ""}" data-layer="${l.id}">
      <span class="layer-ico">${l.ico}</span>
      <span><b>${esc(l.title)}</b><span>${esc(l.sub)}</span></span>
      <span class="layer-state">${esc(l.state)}</span>
    </button>`).join("");
  $("layerList").querySelectorAll(".layer-row").forEach(row => {
    row.onclick = () => selectLayer(row.dataset.layer);
  });
}

function selectLayer(layer) {
  studio.selectedLayer = layer;
  renderLayerList();
  renderInspector();
  buildTimeline();
}

function renderInspector() {
  const panel = $("inspectorPanel");
  const state = studio.editorState;
  $("selectedLayerMeta").textContent = styleLabel(studio.selectedLayer);
  if (studio.selectedLayer === "shuttle") {
    const sh = state.overlays.shuttle;
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Shuttle graphic</span><label><input type="checkbox" id="shuttleEnabled" ${sh.enabled ? "checked" : ""}> Visible</label></div>
        <div class="choice-row">
          ${["ring", "fire", "square", "trail"].map(v => `<button class="choice-btn ${sh.style === v ? "active" : ""}" data-shuttle-style="${v}">${styleLabel(v)}</button>`).join("")}
        </div>
        <div class="control-row"><label>Size</label><input type="range" id="shuttleSize" min="34" max="82" value="${sh.size}"></div>
        <div class="control-row"><label>Opacity</label><input type="range" id="shuttleOpacity" min="35" max="100" value="${Math.round(sh.opacity * 100)}"></div>
        <div class="control-row"><label>Trail</label><input type="checkbox" id="shuttleTrail" ${sh.trail ? "checked" : ""}></div>
      </div>
      ${qualityMetrics()}`;
    $("shuttleEnabled").onchange = (e) => { sh.enabled = e.target.checked; stateChanged(); };
    $("shuttleSize").oninput = (e) => { sh.size = Number(e.target.value); stateChanged(false); };
    $("shuttleOpacity").oninput = (e) => { sh.opacity = Number(e.target.value) / 100; stateChanged(false); };
    $("shuttleTrail").onchange = (e) => { sh.trail = e.target.checked; stateChanged(); };
    panel.querySelectorAll("[data-shuttle-style]").forEach(btn => btn.onclick = () => {
      sh.style = btn.dataset.shuttleStyle;
      stateChanged();
    });
  } else if (studio.selectedLayer === "pose") {
    const po = state.overlays.pose;
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Pose skeleton</span><label><input type="checkbox" id="poseEnabled" ${po.enabled ? "checked" : ""}> Visible</label></div>
        <div class="choice-row">
          ${["glow", "minimal", "heat", "velocity"].map(v => `<button class="choice-btn ${po.style === v ? "active" : ""}" data-pose-style="${v}">${styleLabel(v)}</button>`).join("")}
        </div>
        <div class="control-row"><label>Line width</label><input type="range" id="poseWidth" min="2" max="8" value="${po.lineWidth}"></div>
        <div class="control-row"><label>Opacity</label><input type="range" id="poseOpacity" min="25" max="100" value="${Math.round(po.opacity * 100)}"></div>
      </div>
      ${qualityMetrics()}`;
    $("poseEnabled").onchange = (e) => { po.enabled = e.target.checked; stateChanged(); };
    $("poseWidth").oninput = (e) => { po.lineWidth = Number(e.target.value); stateChanged(false); };
    $("poseOpacity").oninput = (e) => { po.opacity = Number(e.target.value) / 100; stateChanged(false); };
    panel.querySelectorAll("[data-pose-style]").forEach(btn => btn.onclick = () => {
      po.style = btn.dataset.poseStyle;
      stateChanged();
    });
  } else if (studio.selectedLayer === "soundtrack") {
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Soundtrack</span><span>Fixed</span></div>
        <div class="control-row"><label>Source</label><span>Current stitched reel bed</span></div>
        <div class="control-row"><label>Edit path</label><span>Future render contract</span></div>
      </div>
      <div class="control-group"><div class="control-title"><span>Export target</span><span>MP4</span></div><div class="control-row"><label>Codec</label><span>H.264</span></div><div class="control-row"><label>Aspect</label><span>9:16</span></div></div>`;
  } else {
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Composition</span><span>${fmtT(studio.item.duration || 0)}</span></div>
        <div class="metric-list">
          <div class="metric"><b>${studio.item.n_rallies_used || 0}</b><span>used rallies</span></div>
          <div class="metric"><b>${studio.item.n_rallies_found || 0}</b><span>found rallies</span></div>
          <div class="metric"><b>${fmtPct(((studio.item.vision || {}).summary || {}).shuttle_quality)}</b><span>shuttle</span></div>
          <div class="metric"><b>${fmtPct(((studio.item.vision || {}).summary || {}).pose_quality)}</b><span>pose</span></div>
        </div>
      </div>
      <div class="control-group">
        <div class="control-title"><span>Render controls</span><span>Remix</span></div>
        <div class="control-row"><label>Mirror</label><input type="checkbox" id="inspectMirror" ${state.remix.mirror ? "checked" : ""}></div>
        <div class="control-row"><label>Selected order</label><span>${state.remix.order.join(", ")}</span></div>
      </div>`;
    $("inspectMirror").onchange = (e) => {
      state.remix.mirror = e.target.checked;
      $("mirrorChk").checked = state.remix.mirror;
      $("stVideo").classList.toggle("stVideo-mirror", state.remix.mirror);
      stateChanged();
    };
  }
}

function qualityMetrics() {
  const summary = ((studio.item.vision || {}).summary) || {};
  return `<div class="control-group">
    <div class="control-title"><span>AI signal</span><span>${esc((studio.item.vision || {}).backend || "local")}</span></div>
    <div class="metric-list">
      <div class="metric"><b>${fmtPct(summary.shuttle_quality)}</b><span>shuttle</span></div>
      <div class="metric"><b>${fmtPct(summary.pose_quality)}</b><span>pose</span></div>
      <div class="metric"><b>${fmtPct(summary.player_quality)}</b><span>players</span></div>
      <div class="metric"><b>${fmtPct(summary.racquet_quality)}</b><span>racquet</span></div>
    </div>
  </div>`;
}

function stateChanged(save = true) {
  studio.editorState.remix.mirror = $("mirrorChk").checked;
  renderLayerList();
  renderInspector();
  buildTimeline();
  updateOverlayPreview();
  if (save) saveEditorState();
}

function videoFitPoint(x, y) {
  const frame = $("stageFrame");
  const v = $("stVideo");
  const fw = frame.clientWidth || 1, fh = frame.clientHeight || 1;
  const vw = v.videoWidth || 9, vh = v.videoHeight || 16;
  const frameAspect = fw / fh, videoAspect = vw / vh;
  let w = fw, h = fh, ox = 0, oy = 0;
  if (videoAspect > frameAspect) {
    h = fw / videoAspect; oy = (fh - h) / 2;
  } else {
    w = fh * videoAspect; ox = (fw - w) / 2;
  }
  return { left: (ox + x * w) / fw * 100, top: (oy + y * h) / fh * 100 };
}

function nearestTrackPoint(track, t) {
  if (!track || !track.length) return null;
  let best = null, delta = Infinity;
  track.forEach(p => {
    const d = Math.abs(Number(p.t || 0) - t);
    if (d < delta) { best = p; delta = d; }
  });
  return delta <= 0.55 ? best : null;
}

function currentShuttlePoint() {
  const v = $("stVideo");
  if (!studio.item || !v.duration) return null;
  if (studio.mode === "source") {
    for (const seg of reelSegments()) {
      const p = nearestTrackPoint(((seg.vision || {}).shuttle_track || []), v.currentTime);
      if (p) return p;
    }
    return null;
  }
  const seg = reelSegments().find(s => v.currentTime >= s.t0 && v.currentTime <= s.t1);
  if (!seg) return null;
  const sourceT = seg.sourceStart + (v.currentTime - seg.t0);
  return nearestTrackPoint(((seg.vision || {}).shuttle_track || []), sourceT);
}

function updateOverlayPreview() {
  const wrap = $("aiOverlays");
  const state = studio.editorState;
  if (!wrap || !state) return;
  const parts = [];
  const p = currentShuttlePoint();
  let pos = p ? videoFitPoint(Number(p.x || 0.58), Number(p.y || 0.31)) : { left: 58, top: 31 };
  const sh = state.overlays.shuttle;
  if (sh.enabled) {
    const trail = sh.trail ? `<div class="shuttle-trail" style="left:${Math.max(3, pos.left - 30)}%;top:${Math.min(92, pos.top + 10)}%"></div>` : "";
    parts.push(`${trail}<div class="shuttle-mark ${esc(sh.style)}" style="left:${pos.left}%;top:${pos.top}%;width:${sh.size}px;height:${sh.size}px;margin-left:${-sh.size / 2}px;margin-top:${-sh.size / 2}px;--overlay-opacity:${sh.opacity}"></div>`);
  }
  const po = state.overlays.pose;
  if (po.enabled) {
    parts.push(`<div class="pose-figure ${esc(po.style)}" style="opacity:${po.opacity};--pose-width:${po.lineWidth}px"><span class="head"></span><span class="torso"></span><span class="arm-a"></span><span class="arm-b"></span><span class="leg-a"></span><span class="leg-b"></span></div>`);
  }
  wrap.innerHTML = parts.join("");
}

/* ---------- studio edit mode: pick / reorder / mirror / rebuild ---------- */
function initEdit() {
  // Edit against the full pool of rendered rallies; mark which are currently in.
  const pool = studio.item.rally_pool || studio.item.rallies || [];
  const current = new Set(studio.editorState.remix.order || pool.map((_, i) => i + 1));
  const inOrder = studio.editorState.remix.order || [];
  const seq = [...inOrder, ...pool.map((_, i) => i + 1).filter(i => !current.has(i) || !inOrder.includes(i))]
    .filter((v, i, a) => a.indexOf(v) === i);
  studio.edit = seq.map(idx => ({ idx, on: current.has(idx), r: pool[idx - 1] })).filter(e => e.r);
  $("mirrorChk").checked = !!studio.editorState.remix.mirror;
  $("stVideo").classList.remove("stVideo-mirror");
  renderEditChips();
}

function renderEditChips() {
  const wrap = $("editChips");
  wrap.innerHTML = "";
  studio.edit.forEach((e, pos) => {
    const chip = document.createElement("div");
    chip.className = "echip" + (e.on ? "" : " off");
    chip.innerHTML = `<span class="mv" data-mv="-1">‹</span>
      <b title="click to include/exclude">R${e.idx} · ${Math.round(e.r.dur || 0)}s</b>
      <span class="mv" data-mv="1">›</span>`;
    chip.querySelector("b").onclick = () => {
      e.on = !e.on;
      studio.editorState.remix.order = studio.edit.filter(x => x.on).map(x => x.idx);
      renderEditChips(); stateChanged();
    };
    chip.querySelectorAll(".mv").forEach(mv => mv.onclick = (ev) => {
      ev.stopPropagation();
      const to = pos + parseInt(mv.dataset.mv, 10);
      if (to < 0 || to >= studio.edit.length) return;
      [studio.edit[pos], studio.edit[to]] = [studio.edit[to], studio.edit[pos]];
      studio.editorState.remix.order = studio.edit.filter(x => x.on).map(x => x.idx);
      renderEditChips(); stateChanged();
    });
    wrap.appendChild(chip);
  });
}

async function rebuildReel() {
  const order = studio.edit.filter(e => e.on).map(e => e.idx);
  if (!order.length) { $("editMsg").textContent = "keep at least one rally"; return; }
  const mirror = $("mirrorChk").checked;
  studio.editorState.remix = { order, mirror };
  saveEditorState();
  $("rebuildBtn").disabled = true;
  $("editMsg").textContent = mirror ? "rendering mirrored reel..." : "rendering reel...";
  try {
    await jfetch(`/api/jobs/${studio.item.id}/remix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rallies: order, mirror }),
    });
    clearInterval(studio.remixTimer);
    const timer = studio.remixTimer = setInterval(async () => {
      const job = await jfetch(`/api/jobs/${studio.item.id}`);
      if (job.status === "done" && job.result) {
        clearInterval(timer);
        const bust = `?r=${Date.now()}`;
        studio.item = { ...job.result, id: job.id, filename: job.filename,
                        video: job.result.video + bust, thumb: job.result.thumb + bust };
        $("rebuildBtn").disabled = false;
        $("editMsg").textContent = mirror
          ? "rendered with mirror"
          : "rendered from selected rallies";
        $("stVideo").classList.remove("stVideo-mirror");
        studio.editorState = loadEditorState(studio.item);
        initEdit();
        renderCoachbar(studio.item);
        renderLayerList();
        renderInspector();
        setStudioMode("reel");
        loadGallery();
      } else if (job.status === "error") {
        clearInterval(timer);
        $("rebuildBtn").disabled = false;
        $("editMsg").textContent = "rebuild failed — original reel kept";
      } else {
        $("editMsg").textContent = `rebuilding… (${job.message || job.stage})`;
      }
    }, 3000);
  } catch (e) {
    $("rebuildBtn").disabled = false;
    $("editMsg").textContent = "rebuild failed: " + e.message;
  }
}

$("rebuildBtn").onclick = rebuildReel;
$("mirrorChk").onchange = () => {
  studio.editorState.remix.mirror = $("mirrorChk").checked;
  $("stVideo").classList.toggle("stVideo-mirror", studio.editorState.remix.mirror);
  $("editMsg").textContent = studio.editorState.remix.mirror ? "mirror preview enabled" : "";
  stateChanged();
};
$("speedToggle").querySelectorAll("button").forEach(b => b.onclick = () => {
  $("speedToggle").querySelectorAll("button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $("stVideo").playbackRate = parseFloat(b.dataset.rate);
});
$("zoomOut").onclick = () => {
  studio.zoom = Math.max(0.68, Math.round((studio.zoom - 0.08) * 100) / 100);
  $("stageFrame").style.setProperty("--stage-zoom", studio.zoom);
  $("zoomLabel").textContent = `${Math.round(studio.zoom * 100)}%`;
};
$("zoomIn").onclick = () => {
  studio.zoom = Math.min(1.24, Math.round((studio.zoom + 0.08) * 100) / 100);
  $("stageFrame").style.setProperty("--stage-zoom", studio.zoom);
  $("zoomLabel").textContent = `${Math.round(studio.zoom * 100)}%`;
};
$("timelineZoom").oninput = () => buildTimeline();
$("tpScrub").oninput = () => {
  const v = $("stVideo");
  const dur = v.duration || studio.dur || 1;
  v.currentTime = Number($("tpScrub").value) / 1000 * dur;
};
document.addEventListener("keydown", (e) => {
  if ($("studio").hidden || !$("modal").hidden) return;
  if (["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(e.target.tagName)) return;
  const v = $("stVideo");
  if (e.code === "Space") { e.preventDefault(); v.paused ? v.play().catch(() => {}) : v.pause(); }
  if (e.key === "ArrowRight") v.currentTime = Math.min(v.currentTime + 5, v.duration || 0);
  if (e.key === "ArrowLeft") v.currentTime = Math.max(v.currentTime - 5, 0);
});

function closeStudio() {
  cancelAnimationFrame(studio.raf);
  clearInterval(studio.remixTimer);
  const v = $("stVideo");
  v.pause(); v.removeAttribute("src"); v.load();
  v.classList.remove("stVideo-mirror");
  v.playbackRate = 1;
  $("aiOverlays").innerHTML = "";
  $("studio").hidden = true;
  document.body.style.overflow = "";
}

$("studioX").onclick = closeStudio;
$("modeReel").onclick = () => setStudioMode("reel");
$("modeSource").onclick = () => setStudioMode("source");
$("tpPlay").onclick = () => { const v = $("stVideo"); v.paused ? v.play().catch(() => {}) : v.pause(); };
$("tl").onclick = (e) => {
  const r = $("tl").getBoundingClientRect();
  const v = $("stVideo");
  const d = v.duration || studio.dur;
  if (d) v.currentTime = (e.clientX - r.left) / r.width * d;
};

/* ---------- share ---------- */
function shareHtml(id) {
  return `<div class="share-row">
    <button class="share-b" data-share="native">📤 Share</button>
    <a class="share-b" data-share="wa" target="_blank" rel="noopener">WhatsApp</a>
    <a class="share-b" data-share="x" target="_blank" rel="noopener">𝕏</a>
    <a class="share-b" data-share="tg" target="_blank" rel="noopener">Telegram</a>
    <button class="share-b" data-share="copy">🔗 Copy link</button>
  </div>`;
}

function bindShare(container, item) {
  const url = `${location.origin}/?reel=${item.id}`;
  const text = `My AI-generated ${item.sport || "sports"} highlight reel 🏸⚡`;
  const wa = container.querySelector('[data-share="wa"]');
  const x = container.querySelector('[data-share="x"]');
  const tg = container.querySelector('[data-share="tg"]');
  if (wa) wa.href = `https://wa.me/?text=${encodeURIComponent(text + " " + url)}`;
  if (x) x.href = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;
  if (tg) tg.href = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
  const nat = container.querySelector('[data-share="native"]');
  if (nat) nat.onclick = async () => {
    try { await navigator.share({ title: "Baddy", text, url }); }
    catch (e) { /* user dismissed or unsupported */ }
  };
  const cp = container.querySelector('[data-share="copy"]');
  if (cp) cp.onclick = async () => {
    await navigator.clipboard.writeText(url);
    cp.textContent = "✓ Copied";
    setTimeout(() => { cp.textContent = "🔗 Copy link"; }, 1500);
  };
}

/* ---------- modal ---------- */
let modalItem = null;
function openModal(item) {
  modalItem = item;
  $("modal").hidden = false;
  $("modalVideo").src = item.video;
  $("modalMeta").innerHTML =
    `<span class="pill">⏱ ${Math.round(item.duration)}s</span>` +
    `<span class="pill">🏸 ${item.n_rallies_used} of ${item.n_rallies_found} rallies</span>` +
    `<span>${timeAgo(item.created_at)}</span>` +
    `<a class="btn" href="${item.video}" download="baddy-reel.mp4">Download</a>` +
    shareHtml(item.id);
  bindShare($("modalMeta"), item);
  document.body.style.overflow = "hidden";
}
const closeModal = () => {
  $("modal").hidden = true;
  $("modalVideo").pause();
  $("modalVideo").src = "";
  document.body.style.overflow = "";
};
$("modalX").onclick = closeModal;
$("modal").onclick = (e) => { if (e.target === $("modal")) closeModal(); };
$("modalStudio").onclick = () => { const it = modalItem; closeModal(); if (it) openStudio(it); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeModal(); closeStudio(); }
});

initWorkerOptions();
loadGallery().then(() => {
  const rid = new URLSearchParams(location.search).get("reel");
  if (rid) {
    const item = galleryItems.find(i => i.id === rid);
    if (item) {
      document.getElementById("gallery").scrollIntoView();
      openModal(item);
    }
  }
});
