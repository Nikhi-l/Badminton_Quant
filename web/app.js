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

function poseOptionEnabled(opts) {
  const pose = String((opts || {}).pose || "off").toLowerCase();
  return pose && pose !== "off";
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
    const po = cap.pose?.pose || cap.pose?.yolo11 || {};
    setAvail("voptPose", po.available,
      po.available ? `${po.model || "YOLO pose"} · ${po.backend === "runpod" ? "GPU" : "local"} · players & keypoints`
                   : "Pose unavailable");
    setAvail("voptCoach", cap.coach?.available);
    $("optShuttle").checked = sh.available && cap.defaults?.shuttle === "tracknetv3";
    $("optPose").checked = po.available && poseOptionEnabled({ pose: cap.defaults?.pose });
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
// Open the OS file picker exactly once per intent. The "Choose video(s)" button
// lives inside #drop, so a button click ALSO bubbles to drop.onclick — that fired
// fileInput.click() twice and the browser re-opened the picker after the first
// pick (TASK-010: "I select the video but the popup shows again"). The busy guard
// + stopPropagation collapse every path to a single open.
let pickerBusy = false;
function openFilePicker() {
  if (pickerBusy) return;
  pickerBusy = true;
  fileInput.click();
  setTimeout(() => { pickerBusy = false; }, 700); // fallback if the picker is cancelled (no change event)
}
$("browse").onclick = (e) => { e.stopPropagation(); openFilePicker(); };
drop.onclick = (e) => { if (e.target === drop || e.target.closest(".drop-idle")) openFilePicker(); };
fileInput.onchange = () => { pickerBusy = false; if (fileInput.files.length) startUpload([...fileInput.files]); };
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
    loadQueue();   // surface the new job in the queue with live status
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
  loadQueue();
}
$("anotherBtn").onclick = () => { $("jobPanel").hidden = true; fileInput.value = ""; window.scrollTo({ top: 0, behavior: "smooth" }); };

/* ---------- gallery ---------- */
const esc = (s = "") => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtPct = (v) => `${Math.round((Number(v) || 0) * 100)}%`;

function modelSummaryText(models) {
  const m = models || {};
  const bits = [];
  if (m.pose && m.pose.enabled) bits.push(m.pose.model ? `Pose ${m.pose.model}` : "YOLO pose");
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
      openStudioById(item.id);   // fetch the full result (gallery items are light)
    });
  });
}

document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  activeTab = t.dataset.tab;
  renderGallery();
});

/* ---------- TASK-005: job queue (live status of your submissions) ---------- */
let queueTimer = null;

async function loadQueue() {
  try {
    const all = (await (await fetch("/api/jobs")).json()).jobs || [];
    const mine = all.filter(j => myJobs.has(j.id));
    renderQueue(mine);
    const active = mine.some(j => j.status === "queued" || j.status === "processing");
    clearTimeout(queueTimer);
    if (active) queueTimer = setTimeout(loadQueue, 4000);   // live refresh while jobs run
  } catch { /* queue is best-effort */ }
}

function fmtDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  return sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`;
}

function renderQueue(jobs) {
  const sec = $("queueSection"), list = $("queueList");
  if (!jobs.length) { sec.hidden = true; return; }
  sec.hidden = false;
  list.innerHTML = jobs.map(j => {
    const st = j.status || "queued";
    const pipe = (j.pipeline && j.pipeline !== "unknown") ? j.pipeline.toUpperCase() : "";
    const timing = st === "done" && j.gen_seconds != null ? `generated in ${fmtDur(j.gen_seconds)}`
      : st === "processing" ? `running${j.expected_gen_seconds ? ` · ~${fmtDur(j.expected_gen_seconds)}` : ""}`
      : st === "queued" ? "waiting in queue"
      : "did not finish";
    const stageTxt = (st === "processing" && j.stage) ? ` · ${esc(j.stage)}` : "";
    const ic = st === "failed" ? "⚠" : st === "done" ? "✓" : st === "processing" ? "●" : "…";
    return `<div class="q-item q-${st}">
      <div class="q-thumb">${j.thumb ? `<img src="${esc(j.thumb)}" alt="">` : `<span class="q-ic">${ic}</span>`}</div>
      <div class="q-body">
        <div class="q-top"><b>${esc(j.filename || j.id)}</b><span class="q-chip ${st}">${st}</span></div>
        <div class="q-meta">${pipe ? `${esc(pipe)} · ` : ""}${esc(timeAgo(j.submitted_at))}${stageTxt} · ${esc(timing)}</div>
        ${st === "failed" && j.error ? `<div class="q-err">${esc(j.error)}</div>` : ""}
      </div>
      ${st === "done" ? `<button class="btn btn-small q-open" data-qid="${esc(j.id)}">🎬 Studio</button>` : ""}
    </div>`;
  }).join("");
  list.querySelectorAll(".q-open").forEach(b => b.onclick = () => openStudioById(b.dataset.qid));
}

async function openStudioById(id) {
  let item = galleryItems.find(i => i.id === id);
  // Gallery items are light (no per-rally tracking) — fetch the full result so the
  // Studio has rallies + shuttle/player tracks for the overlays.
  if (!item || !Array.isArray(item.rallies)) {
    try {
      const j = await jfetch(`/api/jobs/${id}`);
      if (j && j.result) {
        const versioned = item ? { video: item.video, thumb: item.thumb } : {};
        item = { ...(item || {}), ...j.result, ...versioned, id, filename: (item && item.filename) || j.filename };
      }
    } catch { /* fall through to whatever we have */ }
  }
  if (item) openStudio(item);
}

$("queueRefresh").onclick = () => loadQueue();

/* ---------- studio: AI reel editor ---------- */
const studio = {
  item: null,
  mode: "reel",
  raf: 0,
  selectedLayer: "reel",
  canvas: { x: 0, y: 0, scale: 1 },
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
  resetCanvas();
  _lastCamCenter = _camSmooth = null;
  for (const k of Object.keys(_playerSmooth)) delete _playerSmooth[k];
  studio.editorState = loadEditorState(item);
  $("studio").hidden = false;
  $("studioFile").textContent = [item.filename, item.sport].filter(Boolean).join(" · ");
  $("studioDownload").href = item.video;
  setPreviewAspect("portrait");
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
    framing: { fit: "fit", zoom: 1, x: 0, y: 0 },
    // TASK-014 configurable virtual camera. enabled=false → the auto camera (current
    // behavior). Keyframes are authored against reel time; each picks a follow target
    // (shuttle | player | fixed point) + zoom, interpolated between keyframes.
    camera: { enabled: false, keyframes: [] },
    // Multi-clip canvas composition (Phase 2): clip nodes placed/connected on the
    // canvas. Edges + render + per-edge NL agent are follow-up slices.
    composition: { nodes: [], edges: [] },
    overlays: {
      shuttle: { enabled: true, style: "ring", size: 28, opacity: 0.92, trail: true },
      pose: { enabled: poseOptionEnabled(item.options), style: "glow", lineWidth: 3, opacity: 0.82 },
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
    framing: { ...base.framing, ...(saved.framing || {}) },
    camera: {
      ...base.camera,
      ...(saved.camera || {}),
      keyframes: Array.isArray((saved.camera || {}).keyframes) ? saved.camera.keyframes : base.camera.keyframes,
    },
    overlays: {
      shuttle: (() => {
        const s = { ...base.overlays.shuttle, ...((saved.overlays || {}).shuttle || {}) };
        if (s.size >= 48) s.size = base.overlays.shuttle.size;  // migrate the old big default down
        return s;
      })(),
      pose: { ...base.overlays.pose, ...((saved.overlays || {}).pose || {}) },
    },
    composition: {
      nodes: Array.isArray((saved.composition || {}).nodes) ? saved.composition.nodes : base.composition.nodes,
      edges: Array.isArray((saved.composition || {}).edges) ? saved.composition.edges : base.composition.edges,
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
  studio.mode = mode;
  $("modeReel").classList.toggle("active", mode === "reel");
  $("modeSource").classList.toggle("active", mode === "source");
  $("modeCompose").classList.toggle("active", mode === "compose");
  const compose = mode === "compose";
  $("stageFrame").style.visibility = compose ? "hidden" : "";
  $("canvasNodes").hidden = !compose;
  $("clipLibrary").hidden = !compose;
  if (compose) {
    $("stVideo").pause();
    renderComposeLibrary();
    renderCanvasNodes();
    $("tpHint").textContent = "Compose · multi-clip canvas";
    return;
  }
  $("composeHint").hidden = true;
  const src = mode === "reel" ? studio.item.video : studio.item.proxy;
  if (!src) {
    $("tpHint").textContent = "source video isn't available for this reel";
    return;
  }
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

/* ---------- Compose mode: multi-clip canvas (Phase 2) ---------- */
function compositionState() {
  const st = studio.editorState;
  if (!st.composition) st.composition = { nodes: [], edges: [] };
  return st.composition;
}

// Available clips to drop on the canvas: this game's rallies + your other reels.
function composeLibrary() {
  const item = studio.item, out = [];
  const rallies = item.rally_pool || item.rallies || [];
  rallies.forEach((r, i) => out.push({
    kind: "rally", refId: `${item.id}:r${i}`, src: item.proxy || item.video,
    label: `R${i + 1} · ${Math.round(r.dur || (r.end - r.start) || 0)}s`,
    thumb: item.thumb, t0: r.start || 0, t1: r.end || ((r.start || 0) + (r.dur || 0)),
  }));
  (galleryItems || []).filter(g => g.id !== item.id).slice(0, 12).forEach(g => out.push({
    kind: "reel", refId: g.id, src: g.video, label: (g.filename || "reel").slice(0, 22),
    thumb: g.thumb, t0: 0, t1: g.duration || 0,
  }));
  return out;
}

function renderComposeLibrary() {
  const list = $("clipLibraryList");
  const clips = composeLibrary();
  list.innerHTML = clips.map((c, i) => `
    <button class="lib-clip" data-lib="${i}">
      <span class="lib-thumb"${c.thumb ? ` style="background-image:url('${esc(c.thumb)}')"` : ""}></span>
      <span class="lib-label"><b>${esc(c.label)}</b><span>${esc(c.kind)}</span></span>
    </button>`).join("") || `<div class="muted" style="padding:8px;font-size:11px">No clips yet — generate a few reels first.</div>`;
  list.querySelectorAll("[data-lib]").forEach(b => b.onclick = () => addClipNode(clips[Number(b.dataset.lib)]));
}

let _nodeSeq = 0;
function addClipNode(clip) {
  const comp = compositionState();
  const n = comp.nodes.length;
  comp.nodes.push({
    id: `n${_nodeSeq++}_${comp.nodes.length}`,
    kind: clip.kind, refId: clip.refId, src: clip.src, label: clip.label, thumb: clip.thumb,
    t0: clip.t0, t1: clip.t1,
    x: 40 + (n % 4) * 34, y: 40 + (n % 4) * 28,   // stagger drops
  });
  saveEditorState();
  renderCanvasNodes();
}

function removeClipNode(id) {
  const comp = compositionState();
  comp.nodes = comp.nodes.filter(n => n.id !== id);
  comp.edges = (comp.edges || []).filter(e => e.from !== id && e.to !== id);
  saveEditorState();
  renderCanvasNodes();
}

function renderCanvasNodes() {
  const layer = $("canvasNodes");
  if (!layer) return;
  const comp = compositionState();
  layer.innerHTML = comp.nodes.map(nd => `
    <div class="clip-node" data-node="${esc(nd.id)}" style="left:${nd.x}px;top:${nd.y}px">
      <div class="clip-node-thumb"${nd.thumb ? ` style="background-image:url('${esc(nd.thumb)}')"` : ""}>
        <span class="clip-node-kind">${esc(nd.kind)}</span>
        <button class="clip-node-x" data-del="${esc(nd.id)}" title="Remove">×</button>
      </div>
      <div class="clip-node-label">${esc(nd.label)}</div>
    </div>`).join("");
  layer.querySelectorAll("[data-del]").forEach(b => b.onclick = (e) => { e.stopPropagation(); removeClipNode(b.dataset.del); });
  layer.querySelectorAll(".clip-node").forEach(el => initNodeDrag(el));
  $("composeHint").hidden = comp.nodes.length > 0;
}

// Drag a clip node in canvas space (screen delta / scale = world delta).
function initNodeDrag(el) {
  const id = el.dataset.node;
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".clip-node-x")) return;
    e.stopPropagation();   // don't pan the canvas while dragging a node
    const nd = compositionState().nodes.find(n => n.id === id);
    if (!nd) return;
    const start = { x: e.clientX, y: e.clientY, ox: nd.x, oy: nd.y };
    el.classList.add("dragging");
    const move = (ev) => {
      const s = studio.canvas.scale || 1;
      nd.x = start.ox + (ev.clientX - start.x) / s;
      nd.y = start.oy + (ev.clientY - start.y) / s;
      el.style.left = `${nd.x}px`; el.style.top = `${nd.y}px`;
    };
    const up = (ev) => {
      el.classList.remove("dragging");
      try { el.releasePointerCapture(ev.pointerId); } catch { /* ignore */ }
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      saveEditorState();
    };
    // bind move/up BEFORE capturing — setPointerCapture can throw, and the drag must
    // still work if it does.
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    try { el.setPointerCapture(e.pointerId); } catch { /* ignore */ }
  });
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

// Per-track icon + lane height (px). Drives the variable-height lanes.
const TRACK_META = {
  reel:       { ico: "🎞", h: 56 },
  source:     { ico: "🎬", h: 56 },
  caption:    { ico: "💬", h: 30 },
  camera:     { ico: "🎥", h: 26 },
  shuttle:    { ico: "🏸", h: 28 },
  pose:       { ico: "🦴", h: 28 },
  soundtrack: { ico: "🎵", h: 44 },
};

function captionTextOf(s) {
  const note = (s.r && s.r.note) || s.note || "";
  const t = (note || s.label || "").toString().trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : (s.label || "Rally");
}

// Deterministic pseudo-random 0.18..0.95 so the waveform looks like audio before
// the real peaks load (and as a fallback if decoding fails).
function stylizedPeak(i) {
  const x = Math.sin((i + 1) * 12.9898) * 43758.5453;
  return 0.18 + 0.77 * Math.abs(x - Math.floor(x));
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
      { id: "caption", label: "Captions", type: "caption",
        segs: cuts.map(s => ({ t0: s.t0, t1: s.t1, layer: s.layer || "reel", vision: s.vision, label: captionTextOf(s) })) },
      { id: "camera", label: "Camera", type: "camera", count: cameraLaneCount(), segs: [] },
      { id: "shuttle", label: "Shuttle FX", count: shuttleOn ? cuts.length : 0, type: "shuttle",
        segs: shuttleOn ? cuts.map(s => ({ ...s, layer: "shuttle", label: studio.editorState.overlays.shuttle.style, sub: rallyVisionText(s.vision) || "overlay" })) : [] },
      { id: "pose", label: "Pose", count: poseOn ? cuts.length : 0, type: "pose",
        segs: poseOn ? cuts.map(s => ({ ...s, layer: "pose", label: studio.editorState.overlays.pose.style, sub: "skeleton" })) : [] },
      { id: "soundtrack", label: "Soundtrack", count: 1, type: "audio",
        segs: [{ t0: 0, t1: dur, label: "Music bed", sub: "120 BPM · from stitch", layer: "soundtrack", wave: true }] },
    ];
  } else {
    dur = item.source_duration || 1;
    const list = (item.all_rallies && item.all_rallies.length)
      ? item.all_rallies
      : (item.rallies || []).map(r => ({ ...r, used: true }));
    const srcSegs = list.map((r, i) => ({ t0: r.start || 0, t1: r.end || (r.start || 0) + (r.dur || 0),
      label: `R${i + 1}`, sub: `${Math.round(r.dur || 0)}s${r.note ? " · " + r.note : ""}`, note: r.note, skip: !r.used, layer: "reel" }));
    tracks = [
      { id: "source", label: "Source rallies", count: list.length, type: "clip", segs: srcSegs },
      { id: "caption", label: "Captions", type: "caption",
        segs: srcSegs.filter(s => !s.skip).map(s => ({ t0: s.t0, t1: s.t1, layer: "reel", label: captionTextOf(s) })) },
      { id: "camera", label: "Camera", type: "camera", count: cameraLaneCount(), segs: [] },
      { id: "shuttle", label: "Shuttle FX", count: trackedRallies().length, type: "shuttle",
        segs: trackedRallies().map(s => ({ ...s, layer: "shuttle", label: "Track", sub: rallyVisionText(s.vision) || "source coordinates" })) },
      { id: "pose", label: "Pose", count: studio.editorState.overlays.pose.enabled ? poseReadyCount() : 0, type: "pose", segs: [] },
      { id: "soundtrack", label: "Ambient", count: 0, type: "audio", segs: [] },
    ];
  }
  tracks.forEach(t => { if (t.count == null) t.count = t.segs.length; });
  studio.dur = dur;
  studio.timelineSegments = tracks.flatMap(t => t.segs.map(s => ({ ...s, type: t.type })));
  $("timelineMeta").textContent = `· ${fmtT(dur)} · ${tracks.length} tracks`;

  // ruler: labelled major ticks + unlabelled minor ticks at half-steps
  const step = dur > 200 ? 30 : dur > 90 ? 15 : dur > 40 ? 10 : 5;
  for (let t = 0; t <= dur + 1e-6; t += step / 2) {
    const major = Math.abs(t % step) < 1e-6;
    const el = document.createElement("div");
    el.className = major ? "tick" : "tick minor";
    el.style.left = `${t / dur * 100}%`;
    if (major) el.textContent = fmtT(t);
    ruler.appendChild(el);
  }

  tracks.forEach(track => {
    const meta = TRACK_META[track.id] || { ico: "•", h: 30 };
    const toggleable = (track.id === "shuttle" || track.id === "pose") && studio.editorState.overlays[track.id];
    const on = toggleable ? studio.editorState.overlays[track.id].enabled : null;
    const tail = toggleable
      ? `<span class="tl-sw ${on ? "on" : ""}">${on ? "ON" : "OFF"}</span>`
      : `<span class="tl-n">${track.count}</span>`;
    labels.insertAdjacentHTML("beforeend",
      `<div class="track-label${toggleable ? " tl-toggle" : ""}${toggleable && !on ? " tl-off" : ""}" ` +
      `data-tltoggle="${toggleable ? track.id : ""}" style="height:${meta.h}px">` +
      `<span class="tl-ico">${meta.ico}</span>${esc(track.label)}${tail}</div>`);
    const row = document.createElement("div");
    row.className = "lane-row" + (track.type === "clip" ? " lane-clip"
      : track.type === "audio" ? " lane-wave" : track.type === "caption" ? " lane-cap" : "");
    row.style.height = `${meta.h}px`;
    row.dataset.track = track.id;
    lane.appendChild(row);

    // caption lane: gap markers (trimmed dead time) between consecutive segments
    if (track.type === "caption") {
      const ordered = [...track.segs].sort((a, b) => a.t0 - b.t0);
      for (let i = 0; i < ordered.length - 1; i++) {
        const gap = ordered[i + 1].t0 - ordered[i].t1;
        if (gap <= 0.4) continue;
        const g = document.createElement("div");
        g.className = "gap-mark";
        g.style.left = `${ordered[i].t1 / dur * 100}%`;
        g.style.width = `${gap / dur * 100}%`;
        g.textContent = `${gap.toFixed(1)}s`;
        row.appendChild(g);
      }
    }

    // Source mode: draw the actual shuttle track across the WHOLE video timeline
    // (a trajectory strip: a dot per tracked point at its source time + height).
    if (track.id === "shuttle" && studio.mode === "source") {
      const pts = allShuttlePoints();
      const step = Math.max(1, Math.ceil(pts.length / 600));
      for (let i = 0; i < pts.length; i += step) {
        const pt = pts[i];
        const d = document.createElement("span");
        d.className = "shuttle-dot";
        d.style.left = `${pt.t / dur * 100}%`;
        d.style.top = `${Math.max(6, Math.min(94, pt.y * 100))}%`;
        d.style.opacity = `${0.35 + 0.55 * (pt.confidence || 0.6)}`;
        row.appendChild(d);
      }
    }

    // Source mode: player presence on the Pose lane — a centroid dot per player
    // across the whole timeline, coloured by track id (parity with the shuttle strip).
    if (track.id === "pose" && studio.mode === "source" && studio.editorState.overlays.pose.enabled) {
      const pts = allPosePoints();
      const step = Math.max(1, Math.ceil(pts.length / 600));
      for (let i = 0; i < pts.length; i += step) {
        const pt = pts[i];
        const d = document.createElement("span");
        d.className = `player-dot p${pt.id % 4}`;
        d.style.left = `${pt.t / dur * 100}%`;
        d.style.top = `${Math.max(6, Math.min(94, pt.y * 100))}%`;
        d.style.opacity = `${0.35 + 0.5 * (pt.confidence || 0.6)}`;
        row.appendChild(d);
      }
    }

    // Camera keyframes (reel-time) as clickable diamonds, coloured by target.
    if (track.id === "camera" && studio.mode === "reel" && (studio.editorState.camera || {}).enabled) {
      for (const k of cameraKeyframes()) {
        const m = document.createElement("span");
        m.className = `kf-mark ${esc(k.target || "shuttle")}`;
        m.style.left = `${Math.max(0, Math.min(100, Number(k.t || 0) / dur * 100))}%`;
        m.title = `${fmtT(k.t)} · ${targetLabel(k)}`;
        m.onclick = () => { $("stVideo").currentTime = Number(k.t || 0); if (studio.selectedLayer === "camera") renderInspector(); updateOverlayPreview(); };
        row.appendChild(m);
      }
    }

    track.segs.forEach(s => {
      const el = document.createElement("div");
      el.className = `seg ${track.type}` + (s.skip ? " skip" : "") +
        (s.vision && s.vision.status === "ok" ? " vision-ok" : "") +
        (s.vision && s.vision.mask_enabled ? " mask-on" : "") +
        (s.wave ? " has-wave" : "") +
        (s.layer === studio.selectedLayer ? " active-seg" : "");
      el.style.left = `${Math.max(0, s.t0) / dur * 100}%`;
      el.style.width = `${Math.max((s.t1 - s.t0) / dur * 100, track.type === "caption" ? 0.8 : 1.4)}%`;
      if (track.type === "clip") {
        el.innerHTML = `<div class="film"></div><div class="clip-cap"><b>${esc(s.label)}</b><span>${esc(s.sub || "")}</span></div>`;
        const film = el.querySelector(".film");
        if (item.thumb) film.style.backgroundImage = `url("${item.thumb}")`;
        el._film = film; el._mid = (s.t0 + s.t1) / 2;
      } else if (track.type === "caption") {
        el.innerHTML = `<b>${esc(s.label || "")}</b>`;
      } else if (s.wave) {
        const wrap = document.createElement("div");
        wrap.className = "wave-wrap";
        const n = Math.max(40, Math.round((s.t1 - s.t0) * 4));
        for (let i = 0; i < n; i++) {
          const b = document.createElement("div");
          b.className = "wave-bar";
          b.style.height = `${Math.round(stylizedPeak(i) * 86 + 8)}%`;
          wrap.appendChild(b);
        }
        el.appendChild(wrap);
        el.insertAdjacentHTML("beforeend", `<b>${esc(s.label)}</b><span>${esc(s.sub || "")}</span>`);
        el._wave = wrap;
      } else {
        el.innerHTML = `<b>${esc(s.label)}</b><span>${esc(s.sub || "")}</span>`;
      }
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

  // Lane labels are controls: clicking Shuttle/Pose toggles that overlay.
  labels.querySelectorAll("[data-tltoggle]").forEach(el => {
    const id = el.dataset.tltoggle;
    if (!id) return;
    el.onclick = () => {
      const o = studio.editorState.overlays[id];
      if (o) { o.enabled = !o.enabled; stateChanged(); }
    };
  });

  upgradeFilmstrip();   // real video frames behind the clip lane (best-effort)
  upgradeWaveform();    // real audio peaks for the soundtrack lane (best-effort)
  updateOverlayPreview();
}

// All tracked shuttle points across the video, in SOURCE time, for the source-mode
// full-timeline trajectory strip.
function allShuttlePoints() {
  const out = [];
  for (const seg of reelSegments()) {
    for (const p of ((seg.vision || {}).shuttle_track || [])) {
      out.push({ t: Number(p.t || 0), x: Number(p.x || 0), y: Number(p.y || 0), confidence: Number(p.confidence || 0) });
    }
  }
  return out.sort((a, b) => a.t - b.t);
}

// All tracked player centroids across the video, in SOURCE time, for the source-mode
// Pose-lane presence strip (one point per player box, tagged by track id).
function allPlayerPoints() {
  const out = [];
  for (const seg of reelSegments()) {
    for (const f of ((seg.vision || {}).players_track || [])) {
      for (const b of (f.boxes || [])) {
        out.push({ t: Number(f.t || 0), y: Number(b.y || 0), id: Number(b.id || 0), confidence: Number(b.confidence || 0) });
      }
    }
  }
  return out.sort((a, b) => a.t - b.t);
}

function posePersonCenter(person) {
  const b = person && person.bbox;
  if (b) return { y: Number(b.y || 0), confidence: Number(b.confidence || person.confidence || 0) };
  const pts = ((person || {}).keypoints || []).filter(p => Number(p.confidence || 0) >= 0.05);
  if (!pts.length) return null;
  return {
    y: pts.reduce((s, p) => s + Number(p.y || 0), 0) / pts.length,
    confidence: Number(person.confidence || 0),
  };
}

function allPosePoints() {
  const out = [];
  for (const seg of reelSegments()) {
    const poseTrack = ((seg.vision || {}).pose_track || []);
    for (const f of poseTrack) {
      for (const p of (f.people || [])) {
        const c = posePersonCenter(p);
        if (c) out.push({ t: Number(f.t || 0), y: c.y, id: Number(p.id || 0), confidence: c.confidence });
      }
    }
  }
  return (out.length ? out : allPlayerPoints()).sort((a, b) => a.t - b.t);
}

// Capture a real frame per clip segment from the studio video into its filmstrip
// background. Same-origin video, so the canvas is not tainted. Falls back to the
// reel thumbnail already set on each .film.
let _filmBusy = false;
async function upgradeFilmstrip() {
  if (_filmBusy) return;
  const clips = [...document.querySelectorAll(".seg.clip")]
    .map(seg => ({ film: seg._film, mid: seg._mid })).filter(c => c.film && c.mid != null);
  const v = $("stVideo");
  const src = (v && (v.currentSrc || v.src)) || "";
  if (!clips.length || !src) return;
  _filmBusy = true;
  try {
    const vid = document.createElement("video");
    vid.muted = true; vid.preload = "auto"; vid.crossOrigin = "anonymous"; vid.src = src;
    await new Promise((res, rej) => { vid.onloadeddata = res; vid.onerror = rej; setTimeout(rej, 9000); });
    const cv = document.createElement("canvas"); cv.width = 128; cv.height = 72;
    const ctx = cv.getContext("2d");
    for (const c of clips) {
      try {
        await new Promise((res) => { vid.onseeked = res; vid.currentTime = Math.min(c.mid, (vid.duration || 1) - 0.05); setTimeout(res, 1800); });
        ctx.drawImage(vid, 0, 0, cv.width, cv.height);
        c.film.style.backgroundImage = `url("${cv.toDataURL("image/jpeg", 0.62)}")`;
      } catch (_) { /* keep thumb */ }
    }
  } catch (_) { /* keep thumb fallback */ }
  finally { _filmBusy = false; }
}

// Decode the reel audio and set real waveform bar heights. Cached per source.
let _wavePeaks = null, _wavePeaksSrc = null;
async function upgradeWaveform() {
  const wraps = [...document.querySelectorAll(".wave-wrap")];
  const v = $("stVideo");
  const src = (v && (v.currentSrc || v.src)) || "";
  if (!wraps.length || !src) return;
  try {
    if (!_wavePeaks || _wavePeaksSrc !== src) {
      const buf = await (await fetch(src)).arrayBuffer();
      const AC = window.AudioContext || window.webkitAudioContext;
      const ac = new AC();
      const audio = await ac.decodeAudioData(buf);
      const data = audio.getChannelData(0);
      const N = 600, block = Math.max(1, Math.floor(data.length / N)), peaks = [];
      for (let i = 0; i < N; i++) {
        let m = 0;
        for (let j = 0; j < block; j += 32) { const a = Math.abs(data[i * block + j] || 0); if (a > m) m = a; }
        peaks.push(m);
      }
      const mx = Math.max(...peaks, 1e-3);
      _wavePeaks = peaks.map(p => p / mx); _wavePeaksSrc = src;
      if (ac.close) ac.close();
    }
    wraps.forEach(wrap => {
      const bars = wrap.children, n = bars.length;
      for (let i = 0; i < n; i++) {
        const p = _wavePeaks[Math.floor(i / n * _wavePeaks.length)] || 0;
        bars[i].style.height = `${Math.max(6, Math.round(p * 92))}%`;
      }
    });
  } catch (_) { /* keep stylized fallback */ }
}

function studioTick() {
  if ($("studio").hidden) return;
  const v = $("stVideo");
  const dur = v.duration || studio.dur || 1;
  const timelineScale = Math.max(0.8, Math.min(1.8, Number($("timelineZoom").value || 100) / 100));
  $("tlHead").style.left = `${Math.min(v.currentTime / dur, 1) * timelineScale * 100}%`;
  $("tlHeadTime").textContent = fmtT(v.currentTime);
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
  return (studio.item.rallies || []).filter(r => {
    const v = r.vision || {};
    return Number(v.pose_quality || 0) > 0
      || (Array.isArray(v.pose_track) && v.pose_track.length > 0)
      || (Array.isArray(v.players_track) && v.players_track.length > 0);
  }).length;
}

function renderLayerList() {
  const state = studio.editorState;
  const pool = studio.item.rally_pool || studio.item.rallies || [];
  const included = (studio.edit || []).filter(e => e.on).length || state.remix.order.length;
  const fr = state.framing || { fit: "fit", zoom: 1, x: 0, y: 0 };
  const frEdited = fr.fit !== "fit" || (fr.zoom || 1) !== 1 || fr.x || fr.y;
  const layers = [
    { id: "reel", ico: "▤", title: "Reel cuts", sub: `${included}/${pool.length || included} rallies`, state: "live" },
    { id: "framing", ico: "⛶", title: "Framing", sub: frEdited ? `${fr.fit === "fill" ? "Crop" : "Fit"} · ${Math.round((fr.zoom || 1) * 100)}%` : "Original frame", state: frEdited ? "edited" : "auto" },
    { id: "camera", ico: "◎", title: "Camera", sub: cameraSub(state), state: (state.camera && state.camera.enabled) ? "on" : "auto" },
    { id: "shuttle", ico: "◉", title: "Shuttle FX", sub: `${styleLabel(state.overlays.shuttle.style)} · ${Math.round(state.overlays.shuttle.opacity * 100)}%`, state: state.overlays.shuttle.enabled ? "on" : "off" },
    { id: "pose", ico: "◇", title: "Players & pose", sub: `tracks · ${poseReadyCount()} rallies`, state: state.overlays.pose.enabled ? "on" : "off" },
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
  const stage = $("stageFrame");
  if (stage) stage.style.cursor = layer === "framing" ? "grab" : "";
  renderLayerList();
  renderInspector();
  buildTimeline();
}

function renderInspector() {
  const panel = $("inspectorPanel");
  const state = studio.editorState;
  $("selectedLayerMeta").textContent = styleLabel(studio.selectedLayer);
  if (studio.selectedLayer === "framing") {
    const f = framingState();
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Video framing</span><button class="btn btn-small" id="framingReset">Reset to original</button></div>
        <div class="choice-row">
          <button class="choice-btn ${f.fit === "fit" ? "active" : ""}" data-fit="fit">Original frame</button>
          <button class="choice-btn ${f.fit === "fill" ? "active" : ""}" data-fit="fill">Crop to fill</button>
        </div>
        <div class="control-row"><label>Zoom</label><input type="range" id="framingZoom" min="100" max="300" value="${Math.round((f.zoom || 1) * 100)}"></div>
        <div class="control-row"><label>Pan X</label><input type="range" id="framingX" min="-100" max="100" value="${Math.round((f.x || 0) * 100)}"></div>
        <div class="control-row"><label>Pan Y</label><input type="range" id="framingY" min="-100" max="100" value="${Math.round((f.y || 0) * 100)}"></div>
        <div class="control-hint muted">Drag the preview to reposition the crop. “Reset to original” restores the full video frame.</div>
      </div>`;
    const apply = (save) => { applyFraming(); updateOverlayPreview(); renderLayerList(); if (save) saveEditorState(); };
    panel.querySelectorAll("[data-fit]").forEach(b => b.onclick = () => { f.fit = b.dataset.fit; apply(true); });
    $("framingZoom").oninput = (e) => { f.zoom = Number(e.target.value) / 100; apply(false); };
    $("framingZoom").onchange = () => saveEditorState();
    $("framingX").oninput = (e) => { f.x = Number(e.target.value) / 100; apply(false); };
    $("framingX").onchange = () => saveEditorState();
    $("framingY").oninput = (e) => { f.y = Number(e.target.value) / 100; apply(false); };
    $("framingY").onchange = () => saveEditorState();
    $("framingReset").onclick = () => { studio.editorState.framing = { fit: "fit", zoom: 1, x: 0, y: 0 }; renderInspector(); apply(true); };
  } else if (studio.selectedLayer === "camera") {
    const cam = cameraState();
    ensureKeyframe();
    const a = activeKeyframe();
    const playerIds = [...new Set(currentPlayers().map(b => b.id))].sort((x, y) => x - y);
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Virtual camera</span><label><input type="checkbox" id="camEnabled" ${cam.enabled ? "checked" : ""}> Manual</label></div>
        <div class="control-hint muted">Off = automatic shuttle-follow. On = follow a target you pick, with keyframes to switch target/zoom over time. Overrides the Framing layer while on.</div>
      </div>
      ${cam.enabled && a ? `
      <div class="control-group">
        <div class="control-title"><span>Target at playhead</span><span>${fmtT(cameraTime())}</span></div>
        <div class="choice-row">
          ${["shuttle", "player", "point"].map(t => `<button class="choice-btn ${a.target === t ? "active" : ""}" data-cam-target="${t}">${t === "shuttle" ? "Shuttle" : t === "player" ? "Player" : "Point"}</button>`).join("")}
        </div>
        ${a.target === "player" ? `<div class="choice-row">${(playerIds.length ? playerIds : [0]).map(id => `<button class="choice-btn ${Number(a.targetPlayer || 0) === id ? "active" : ""}" data-cam-player="${id}">P${id + 1}</button>`).join("")}</div>` : ""}
        ${a.target === "point" ? `
          <div class="control-row"><label>Point X</label><input type="range" id="camPointX" min="0" max="100" value="${Math.round((a.point || { x: 0.5 }).x * 100)}"></div>
          <div class="control-row"><label>Point Y</label><input type="range" id="camPointY" min="0" max="100" value="${Math.round((a.point || { y: 0.45 }).y * 100)}"></div>` : ""}
        <div class="control-row"><label>Zoom</label><input type="range" id="camZoom" min="100" max="280" value="${Math.round((a.zoom || 1.4) * 100)}"></div>
        <button class="btn btn-small" id="camAddKf">+ Keyframe at playhead</button>
      </div>
      <div class="control-group">
        <div class="control-title"><span>Keyframes</span><span>${cam.keyframes.length}</span></div>
        <div class="kf-list" id="camKfList">
          ${cameraKeyframes().map((k, i) => `<div class="kf-item ${k === a ? "active" : ""}" data-kf-seek="${k.t}"><span class="kf-t">${fmtT(k.t)}</span><span class="kf-tgt">${targetLabel(k)} · ${Math.round((k.zoom || 1.4) * 100)}%</span><button class="kf-del" data-kf-del="${i}" title="Delete keyframe">✕</button></div>`).join("")}
        </div>
      </div>` : ""}`;
    $("camEnabled").onchange = (e) => { cam.enabled = e.target.checked; _lastCamCenter = _camSmooth = null; ensureKeyframe(); stateChanged(); };
    if (cam.enabled && a) {
      panel.querySelectorAll("[data-cam-target]").forEach(b => b.onclick = () => { a.target = b.dataset.camTarget; _lastCamCenter = _camSmooth = null; stateChanged(); });
      panel.querySelectorAll("[data-cam-player]").forEach(b => b.onclick = () => { a.targetPlayer = Number(b.dataset.camPlayer); _lastCamCenter = _camSmooth = null; stateChanged(); });
      const liveApply = () => { applyFraming(); updateOverlayPreview(); renderLayerList(); };
      if ($("camPointX")) { $("camPointX").oninput = (e) => { a.point = { ...(a.point || {}), x: Number(e.target.value) / 100 }; liveApply(); }; $("camPointX").onchange = () => saveEditorState(); }
      if ($("camPointY")) { $("camPointY").oninput = (e) => { a.point = { ...(a.point || {}), y: Number(e.target.value) / 100 }; liveApply(); }; $("camPointY").onchange = () => saveEditorState(); }
      $("camZoom").oninput = (e) => { a.zoom = Number(e.target.value) / 100; liveApply(); };
      $("camZoom").onchange = () => saveEditorState();
      $("camAddKf").onclick = addKeyframeAtPlayhead;
      panel.querySelectorAll("[data-kf-seek]").forEach(el => el.onclick = (e) => {
        if (e.target.classList.contains("kf-del")) return;
        $("stVideo").currentTime = Number(el.dataset.kfSeek);
        renderInspector(); updateOverlayPreview();
      });
      panel.querySelectorAll("[data-kf-del]").forEach(b => b.onclick = (e) => {
        e.stopPropagation();
        const kf = cameraKeyframes()[Number(b.dataset.kfDel)];
        if (cam.keyframes.length > 1 && kf) { cam.keyframes = cam.keyframes.filter(k => k !== kf); ensureKeyframe(); stateChanged(); }
      });
    }
  } else if (studio.selectedLayer === "shuttle") {
    const sh = state.overlays.shuttle;
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Shuttle graphic</span><label><input type="checkbox" id="shuttleEnabled" ${sh.enabled ? "checked" : ""}> Visible</label></div>
        <div class="choice-row">
          ${["ring", "fire", "square", "trail"].map(v => `<button class="choice-btn ${sh.style === v ? "active" : ""}" data-shuttle-style="${v}">${styleLabel(v)}</button>`).join("")}
        </div>
        <div class="control-row"><label>Size</label><input type="range" id="shuttleSize" min="14" max="64" value="${sh.size}"></div>
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

/* ---------- TASK-014: configurable virtual camera (targets + keyframes) ---------- */
let _lastCamCenter = null;
let _camSmooth = null;      // {x,y,t} temporally-smoothed camera centre
const _playerSmooth = {};   // id -> {x,y,w,h,t} temporally-smoothed player boxes

// Frame-rate-independent exponential smoother for a normalized point/box. Eases the
// kept `state` toward `target` with time constant `tau` seconds (bigger = smoother,
// more lag), but SNAPS (no ease) when the target jumps more than `snap` — i.e. a seek
// or a cut to another rally — so motion glides without sliding across the whole frame.
// Time-based, so it advances correctly even when called several times per RAF frame.
function smoothToward(state, target, keys, tau, snap) {
  const now = (typeof performance !== "undefined" ? performance.now() : Date.now());
  const far = state && Math.hypot(target.x - state.x, target.y - state.y) > snap;
  if (!state || far) { const s = { t: now }; keys.forEach(k => s[k] = target[k]); return s; }
  const dt = Math.max(0, (now - state.t) / 1000);
  const a = 1 - Math.exp(-dt / tau);
  const s = { t: now };
  keys.forEach(k => s[k] = state[k] + (target[k] - state[k]) * a);
  return s;
}

function cameraState() {
  const st = studio.editorState;
  if (!st) return null;
  if (!st.camera) st.camera = { enabled: false, keyframes: [] };
  return st.camera;
}

function cameraKeyframes() {
  const cam = cameraState();
  return cam ? [...cam.keyframes].sort((a, b) => Number(a.t || 0) - Number(b.t || 0)) : [];
}

function cameraTime() {
  const v = $("stVideo");
  return v ? v.currentTime : 0;
}

// The camera plan at reel time t: the active keyframe's target + a zoom interpolated
// toward the next keyframe. Null when there are no keyframes.
function cameraAt(t) {
  const kfs = cameraKeyframes();
  if (!kfs.length) return null;
  let i = 0;
  while (i + 1 < kfs.length && Number(kfs[i + 1].t || 0) <= t) i++;
  const a = kfs[i], b = kfs[i + 1] || null;
  let zoom = Number(a.zoom || 1.4);
  if (b) {
    const span = Number(b.t || 0) - Number(a.t || 0);
    const frac = span > 0 ? Math.max(0, Math.min(1, (t - Number(a.t || 0)) / span)) : 0;
    zoom += (Number(b.zoom || zoom) - zoom) * frac;
  }
  return {
    target: a.target || "shuttle",
    targetPlayer: a.targetPlayer == null ? 0 : a.targetPlayer,
    point: a.point || { x: 0.5, y: 0.45 },
    zoom,
    sinceSwitch: t - Number(a.t || 0),
    prev: i > 0 ? kfs[i - 1] : null,
  };
}

// Resolve a target spec to a normalized centre {x,y}, or null if not trackable now.
function resolveTargetCenter(spec) {
  if (!spec) return null;
  if (spec.target === "point") return { x: Number(spec.point.x), y: Number(spec.point.y) };
  if (spec.target === "player") {
    const boxes = currentPlayers();
    const b = boxes.find(pb => pb.id === spec.targetPlayer) || boxes[0];
    return b ? { x: Number(b.x), y: Number(b.y) } : null;
  }
  const p = currentShuttlePoint();
  return p ? { x: Number(p.x), y: Number(p.y) } : null;
}

// Effective {fit,zoom,x,y} centring the camera target now, or null to fall back to
// manual framing. Holds the last good centre on momentary target loss and cross-fades
// for ~0.4s after a target switch so the camera never teleports.
function evalCameraFraming() {
  const plan = cameraAt(cameraTime());
  if (!plan) return null;
  let center = resolveTargetCenter(plan);
  const BLEND = 0.4;
  if (plan.prev && plan.sinceSwitch < BLEND) {
    const prevCenter = resolveTargetCenter({
      target: plan.prev.target || "shuttle",
      targetPlayer: plan.prev.targetPlayer == null ? 0 : plan.prev.targetPlayer,
      point: plan.prev.point || { x: 0.5, y: 0.45 },
    });
    if (center && prevCenter) {
      const k = plan.sinceSwitch / BLEND;
      center = { x: prevCenter.x + (center.x - prevCenter.x) * k, y: prevCenter.y + (center.y - prevCenter.y) * k };
    }
  }
  if (!center) center = _lastCamCenter;       // hold last good centre on a brief loss
  if (!center) return null;
  _lastCamCenter = center;
  // Temporal smoothing: glide toward the target instead of snapping to each sampled
  // point (kills the jitter from the sparse track). Snaps on a seek / rally cut.
  _camSmooth = smoothToward(_camSmooth, center, ["x", "y"], 0.20, 0.45);
  return centerFraming({ x: _camSmooth.x, y: _camSmooth.y }, plan.zoom);
}

// {fit,zoom,x,y} (manual-framing convention) placing a normalized source point at the
// frame centre under fit="fill" + zoom. Derived from videoFitPoint's geometry so the
// overlays stay aligned with the camera transform.
function centerFraming(center, zoom) {
  const frame = $("stageFrame"), v = $("stVideo");
  const fw = frame.clientWidth || 1, fh = frame.clientHeight || 1;
  const vw = v.videoWidth || 9, vh = v.videoHeight || 16;
  const frameAspect = fw / fh, videoAspect = vw / vh;
  const fitWidth = videoAspect < frameAspect;   // fit="fill" (cover)
  let w = fw, h = fh, ox = 0, oy = 0;
  if (fitWidth) { h = fw / videoAspect; oy = (fh - h) / 2; }
  else { w = fh * videoAspect; ox = (fw - w) / 2; }
  const s = zoom || 1.4, cx = fw / 2, cy = fh / 2;
  const fx = -2 * (ox + center.x * w - cx) * s / fw;
  const fy = -2 * (oy + center.y * h - cy) * s / fh;
  return { fit: "fill", zoom: s, x: Math.max(-1.6, Math.min(1.6, fx)), y: Math.max(-1.6, Math.min(1.6, fy)) };
}

function framingState() {
  const st = studio.editorState;
  if (!st) return { fit: "fit", zoom: 1, x: 0, y: 0 };
  if (!st.framing) st.framing = { fit: "fit", zoom: 1, x: 0, y: 0 };
  if (st.camera && st.camera.enabled) {
    const cam = evalCameraFraming();
    if (cam) return cam;
  }
  return st.framing;
}

/* ---------- camera authoring (layer-rail summary, keyframe editing) ---------- */
function cameraSub(state) {
  const cam = state.camera || {};
  if (!cam.enabled) return "Auto follow";
  const n = (cam.keyframes || []).length;
  const a = activeKeyframe();
  return `${n} keyframe${n === 1 ? "" : "s"} · ${a ? targetLabel(a) : "shuttle"}`;
}

function targetLabel(kf) {
  if (kf.target === "player") return `player ${Number(kf.targetPlayer || 0) + 1}`;
  if (kf.target === "point") return "fixed point";
  return "shuttle";
}

function cameraLaneCount() {
  const cam = cameraState();
  return (cam && cam.enabled) ? cam.keyframes.length : 0;
}

// The keyframe governing the current playhead (latest with t<=now), or null.
function activeKeyframe() {
  const kfs = cameraKeyframes();
  if (!kfs.length) return null;
  const t = cameraTime();
  let active = kfs[0];
  for (const kf of kfs) { if (Number(kf.t || 0) <= t) active = kf; }
  return active;
}

// An enabled camera always has at least one keyframe to follow.
function ensureKeyframe() {
  const cam = cameraState();
  if (cam && cam.enabled && !cam.keyframes.length) {
    cam.keyframes.push({ t: 0, target: "shuttle", targetPlayer: 0, point: { x: 0.5, y: 0.45 }, zoom: 1.4 });
  }
}

function addKeyframeAtPlayhead() {
  const cam = cameraState();
  if (!cam) return;
  const a = activeKeyframe() || { target: "shuttle", targetPlayer: 0, point: { x: 0.5, y: 0.45 }, zoom: 1.4 };
  const t = Math.round(cameraTime() * 100) / 100;
  const kf = {
    t, target: a.target, targetPlayer: a.targetPlayer == null ? 0 : a.targetPlayer,
    point: { ...(a.point || { x: 0.5, y: 0.45 }) }, zoom: a.zoom || 1.4,
  };
  const existing = cam.keyframes.find(k => Math.abs(Number(k.t || 0) - t) < 0.05);
  if (existing) Object.assign(existing, kf); else cam.keyframes.push(kf);
  stateChanged();
}

// Apply the manual framing (fit + zoom + pan) and mirror to the preview video.
function applyFraming() {
  const v = $("stVideo"), st = studio.editorState;
  if (!v || !st) return;
  const f = framingState();
  v.style.objectFit = f.fit === "fill" ? "cover" : "contain";
  const parts = [];
  if (st.remix.mirror) parts.push("scaleX(-1)");
  if ((f.x || 0) || (f.y || 0)) parts.push(`translate(${(f.x || 0) * 50}%, ${(f.y || 0) * 50}%)`);
  if ((f.zoom || 1) !== 1) parts.push(`scale(${f.zoom})`);
  v.style.transformOrigin = "center";
  v.style.transform = parts.join(" ");
}

function videoFitPoint(x, y) {
  const frame = $("stageFrame");
  const v = $("stVideo");
  const fw = frame.clientWidth || 1, fh = frame.clientHeight || 1;
  const vw = v.videoWidth || 9, vh = v.videoHeight || 16;
  const frameAspect = fw / fh, videoAspect = vw / vh;
  const f = framingState();
  // object-fit base box (contain vs cover)
  const fitWidth = (f.fit === "fill") ? (videoAspect < frameAspect) : (videoAspect > frameAspect);
  let w = fw, h = fh, ox = 0, oy = 0;
  if (fitWidth) { h = fw / videoAspect; oy = (fh - h) / 2; }
  else { w = fh * videoAspect; ox = (fw - w) / 2; }
  let px = ox + x * w, py = oy + y * h;
  // element transform: scale about centre, then translate, then mirror (matches applyFraming)
  const s = f.zoom || 1, cx = fw / 2, cy = fh / 2;
  px = (px - cx) * s + cx + (f.x || 0) * 0.5 * fw;
  py = (py - cy) * s + cy + (f.y || 0) * 0.5 * fh;
  if (studio.editorState && studio.editorState.remix.mirror) px = fw - px;
  return { left: px / fw * 100, top: py / fh * 100 };
}

function nearestTrackPoint(track, t, window = 0.55) {
  if (!track || !track.length) return null;
  let best = null, delta = Infinity;
  track.forEach(p => {
    const d = Math.abs(Number(p.t || 0) - t);
    if (d < delta) { best = p; delta = d; }
  });
  return delta <= window ? best : null;
}

// Player boxes ({id,x,y,w,h,confidence}) tracked at the current time, or []. Maps
// the playhead to source time the same way as the shuttle, then takes the nearest
// sampled players_track frame (wider window — player samples are sparser).
function currentPlayers() {
  const v = $("stVideo");
  if (!studio.item || !v.duration) return [];
  const pick = (vision, t) => {
    const fr = nearestTrackPoint((vision || {}).players_track || [], t, 1.0);
    return fr ? (fr.boxes || []) : [];
  };
  if (studio.mode === "source") {
    for (const seg of reelSegments()) {
      const boxes = pick(seg.vision, v.currentTime);
      if (boxes.length) return boxes;
    }
    return [];
  }
  const seg = reelSegments().find(s => v.currentTime >= s.t0 && v.currentTime <= s.t1);
  if (!seg) return [];
  return pick(seg.vision, seg.sourceStart + (v.currentTime - seg.t0));
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

// Player boxes smoothed over time (per id) so the overlay glides instead of snapping
// between sparse samples. Snaps on a big jump (new detection / rally cut).
function smoothedPlayerBoxes() {
  const raw = currentPlayers();
  const live = new Set(raw.map(b => Number(b.id)));
  for (const k of Object.keys(_playerSmooth)) if (!live.has(Number(k))) delete _playerSmooth[k];
  return raw.map(b => {
    const s = smoothToward(_playerSmooth[b.id], { x: +b.x, y: +b.y, w: +b.w, h: +b.h },
                           ["x", "y", "w", "h"], 0.14, 0.35);
    _playerSmooth[b.id] = s;
    return { ...b, x: s.x, y: s.y, w: s.w, h: s.h };
  });
}

// The shuttle's ACTUAL recent trajectory (last `windowSec` of tracked points up to the
// playhead), mapped to screen %, for a real motion trail instead of a fixed bar.
function recentShuttleScreenPoints(windowSec = 0.7) {
  const v = $("stVideo");
  if (!studio.item || !v.duration) return [];
  let track = null, sourceT = null;
  if (studio.mode === "source") {
    for (const seg of reelSegments()) {
      const t = (seg.vision || {}).shuttle_track || [];
      if (nearestTrackPoint(t, v.currentTime)) { track = t; sourceT = v.currentTime; break; }
    }
  } else {
    const seg = reelSegments().find(s => v.currentTime >= s.t0 && v.currentTime <= s.t1);
    if (seg) { track = (seg.vision || {}).shuttle_track || []; sourceT = seg.sourceStart + (v.currentTime - seg.t0); }
  }
  if (!track || sourceT == null) return [];
  return track
    .filter(p => Number(p.t) <= sourceT + 1e-3 && Number(p.t) >= sourceT - windowSec && Number(p.confidence || 0) >= 0.3)
    .sort((a, b) => a.t - b.t)
    .map(p => videoFitPoint(Number(p.x), Number(p.y)));
}

function shuttleTrailSvg(sh) {
  const pts = recentShuttleScreenPoints();
  if (pts.length < 2) return "";
  const poly = pts.map(p => `${p.left.toFixed(2)},${p.top.toFixed(2)}`).join(" ");
  return `<svg class="shuttle-trail-svg" viewBox="0 0 100 100" preserveAspectRatio="none">` +
    `<polyline points="${poly}" fill="none" stroke="var(--lime)" stroke-width="2.4" ` +
    `stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" ` +
    `style="opacity:${0.55 * sh.opacity}"/></svg>`;
}

function updateOverlayPreview() {
  const wrap = $("aiOverlays");
  const state = studio.editorState;
  if (!wrap || !state) return;
  applyFraming();
  const parts = [];
  // Shuttle: draw ONLY when the shuttle is actually tracked at the current time —
  // no fixed-default/last-position marker (that was the phantom "circle"). The trail
  // follows the shuttle's real recent path, not a fixed-offset bar.
  const sh = state.overlays.shuttle;
  const p = sh.enabled ? currentShuttlePoint() : null;
  if (p) {
    const pos = videoFitPoint(Number(p.x), Number(p.y));
    if (sh.trail) parts.push(shuttleTrailSvg(sh));
    parts.push(`<div class="shuttle-mark ${esc(sh.style)}" style="left:${pos.left}%;top:${pos.top}%;width:${sh.size}px;height:${sh.size}px;margin-left:${-sh.size / 2}px;margin-top:${-sh.size / 2}px;--overlay-opacity:${sh.opacity}"></div>`);
  }
  // Players & pose layer: draw the tracked player boxes at the current time (real
  // data from the YOLO worker), smoothed over time, hidden when none. Pose keypoints
  // (skeleton) render on top once exposed (currentPose() is null until then).
  const po = state.overlays.pose;
  if (po.enabled) {
    const target = (state.camera && state.camera.targetPlayer != null) ? state.camera.targetPlayer : null;
    for (const b of smoothedPlayerBoxes()) {
      parts.push(renderPlayerBox(b, po, b.id === target));
    }
    const pose = currentPose();
    if (pose) parts.push(renderPoseOverlay(pose, po));
  }
  wrap.innerHTML = parts.join("");
}

// A tracked player's bounding box, framing-aware. Map both corners through
// videoFitPoint so crop/zoom/pan transforms apply correctly.
function renderPlayerBox(b, po, isTarget) {
  const tl = videoFitPoint(Number(b.x) - Number(b.w) / 2, Number(b.y) - Number(b.h) / 2);
  const br = videoFitPoint(Number(b.x) + Number(b.w) / 2, Number(b.y) + Number(b.h) / 2);
  const left = Math.min(tl.left, br.left), top = Math.min(tl.top, br.top);
  const w = Math.abs(br.left - tl.left), h = Math.abs(br.top - tl.top);
  return `<div class="player-box${isTarget ? " target" : ""}" data-pid="${b.id}" ` +
    `style="left:${left}%;top:${top}%;width:${w}%;height:${h}%;opacity:${po.opacity}">` +
    `<span class="player-tag">P${Number(b.id) + 1}</span></div>`;
}

// Real pose keypoints for the current time, or null. Maps reel time to source time
// the same way shuttle/player tracks do, then takes the nearest sampled pose frame.
function currentPose() {
  const v = $("stVideo");
  if (!studio.item || !v.duration) return null;
  const pick = (vision, t) => nearestTrackPoint((vision || {}).pose_track || [], t, 1.0);
  if (studio.mode === "source") {
    for (const seg of reelSegments()) {
      const fr = pick(seg.vision, v.currentTime);
      if (fr) return fr;
    }
    return null;
  }
  const seg = reelSegments().find(s => v.currentTime >= s.t0 && v.currentTime <= s.t1);
  if (!seg) return null;
  return pick(seg.vision, seg.sourceStart + (v.currentTime - seg.t0));
}

const POSE_LIMBS = [
  [5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
];

function renderPoseOverlay(pose, po) {
  const people = (pose.people || []).filter(p => Array.isArray(p.keypoints));
  if (!people.length) return "";
  const parts = [];
  for (const person of people) {
    const pts = person.keypoints.map(k => {
      if (Number(k.confidence || 0) < 0.12) return null;
      return videoFitPoint(Number(k.x), Number(k.y));
    });
    for (const [a, b] of POSE_LIMBS) {
      if (!pts[a] || !pts[b]) continue;
      parts.push(`<line class="pose-limb p${Number(person.id || 0) % 4}" x1="${pts[a].left.toFixed(2)}" y1="${pts[a].top.toFixed(2)}" x2="${pts[b].left.toFixed(2)}" y2="${pts[b].top.toFixed(2)}"></line>`);
    }
    pts.forEach((p, i) => {
      if (!p) return;
      parts.push(`<circle class="pose-joint p${Number(person.id || 0) % 4}" data-kp="${i}" cx="${p.left.toFixed(2)}" cy="${p.top.toFixed(2)}" r="2.8"></circle>`);
    });
  }
  if (!parts.length) return "";
  return `<svg class="pose-figure ${esc(po.style)}" viewBox="0 0 100 100" preserveAspectRatio="none" style="opacity:${po.opacity};--pose-width:${po.lineWidth}px">${parts.join("")}</svg>`;
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
  const cam = studio.editorState.camera;
  const camera = (cam && cam.enabled && (cam.keyframes || []).length) ? cam : null;
  studio.editorState.remix = { order, mirror };
  saveEditorState();
  $("rebuildBtn").disabled = true;
  $("editMsg").textContent = camera ? "baking your camera into the reel..."
    : mirror ? "rendering mirrored reel..." : "rendering reel...";
  try {
    await jfetch(`/api/jobs/${studio.item.id}/remix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rallies: order, mirror, camera }),
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
  $("editMsg").textContent = studio.editorState.remix.mirror ? "mirror preview enabled" : "";
  stateChanged();
};

// Drag the preview to pan the manual crop (active when the Framing layer is selected).
(function initFramingDrag() {
  const stage = $("stageFrame");
  if (!stage) return;
  let dragging = false, lx = 0, ly = 0;
  stage.addEventListener("pointerdown", (e) => {
    if (studio.selectedLayer !== "framing") return;
    dragging = true; lx = e.clientX; ly = e.clientY;
    stage.style.cursor = "grabbing"; stage.setPointerCapture(e.pointerId); e.preventDefault();
  });
  stage.addEventListener("pointermove", (e) => {
    if (!dragging || !studio.editorState) return;
    const f = framingState(), r = stage.getBoundingClientRect();
    f.x = Math.max(-1, Math.min(1, (f.x || 0) + (e.clientX - lx) / (r.width / 2)));
    f.y = Math.max(-1, Math.min(1, (f.y || 0) + (e.clientY - ly) / (r.height / 2)));
    lx = e.clientX; ly = e.clientY;
    applyFraming(); updateOverlayPreview();
    const sx = $("framingX"), sy = $("framingY");
    if (sx) sx.value = Math.round(f.x * 100);
    if (sy) sy.value = Math.round(f.y * 100);
  });
  const end = () => { if (dragging) { dragging = false; stage.style.cursor = ""; renderLayerList(); saveEditorState(); } };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
})();
$("speedToggle").querySelectorAll("button").forEach(b => b.onclick = () => {
  $("speedToggle").querySelectorAll("button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $("stVideo").playbackRate = parseFloat(b.dataset.rate);
});
/* ---------- Figma-style movable canvas: pan (drag) + zoom (wheel) ---------- */
// The stage-frame is a single object on an infinite canvas. studio.canvas {x,y,scale}
// is applied as translate()+scale(); wheel zooms toward the cursor, drag pans. The
// AI overlays live inside the frame so they pan/zoom with it for free.
function applyCanvas() {
  const c = studio.canvas;
  const tf = `translate(${c.x}px, ${c.y}px) scale(${c.scale})`;
  $("stageFrame").style.transform = tf;
  $("canvasNodes").style.transform = tf;   // clip nodes share the canvas transform
  $("zoomLabel").textContent = Math.abs(c.scale - 1) < 0.005 && !c.x && !c.y ? "Fit" : `${Math.round(c.scale * 100)}%`;
}
function resetCanvas() { studio.canvas = { x: 0, y: 0, scale: 1 }; applyCanvas(); }
function canvasZoomAt(clientX, clientY, factor) {
  const stage = $("studioStage"), rect = stage.getBoundingClientRect();
  const dx = clientX - (rect.left + rect.width / 2), dy = clientY - (rect.top + rect.height / 2);
  const c = studio.canvas;
  const newScale = Math.max(0.25, Math.min(6, c.scale * factor));
  // keep the world point under the cursor fixed while scaling
  c.x = dx - (dx - c.x) * (newScale / c.scale);
  c.y = dy - (dy - c.y) * (newScale / c.scale);
  c.scale = newScale;
  applyCanvas();
}
(function initCanvasControls() {
  const stage = $("studioStage");
  $("zoomOut").onclick = () => { const r = stage.getBoundingClientRect(); canvasZoomAt(r.left + r.width / 2, r.top + r.height / 2, 1 / 1.15); };
  $("zoomIn").onclick = () => { const r = stage.getBoundingClientRect(); canvasZoomAt(r.left + r.width / 2, r.top + r.height / 2, 1.15); };
  $("zoomLabel").onclick = resetCanvas;
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    canvasZoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.1 : 1 / 1.1);
  }, { passive: false });
  // Pan by dragging the canvas background, middle-mouse anywhere, or while the
  // Framing/Camera layer isn't grabbing the frame for crop repositioning.
  let panning = false, start = null;
  stage.addEventListener("pointerdown", (e) => {
    const onFrameCrop = e.target.closest("#stageFrame") && studio.selectedLayer === "framing";
    if (e.button === 1 || (!onFrameCrop && (e.button === 0))) {
      panning = true; start = { x: e.clientX, y: e.clientY, ox: studio.canvas.x, oy: studio.canvas.y };
      stage.setPointerCapture(e.pointerId); stage.classList.add("panning"); e.preventDefault();
    }
  });
  stage.addEventListener("pointermove", (e) => {
    if (!panning) return;
    studio.canvas.x = start.ox + (e.clientX - start.x);
    studio.canvas.y = start.oy + (e.clientY - start.y);
    applyCanvas();
  });
  const endPan = (e) => { if (panning) { panning = false; stage.classList.remove("panning"); try { stage.releasePointerCapture(e.pointerId); } catch { /* ignore */ } } };
  stage.addEventListener("pointerup", endPan);
  stage.addEventListener("pointercancel", endPan);
})();

// Preview aspect: Portrait (9:16 reel output) vs Landscape (the source video's
// native aspect — see the full uploaded landscape footage to reframe it).
function setPreviewAspect(aspect) {
  studio.previewAspect = aspect;
  const frame = $("stageFrame"), v = $("stVideo");
  const landscape = aspect === "landscape";
  // Landscape = the ORIGINAL footage. The reel (item.video) is a 9:16 portrait crop, so
  // showing IT in a landscape frame just pillarboxes it. The proxy is the un-cropped
  // source, so Landscape always plays the proxy; Portrait restores the current mode's
  // video. Swap the source if needed, preserving playback position.
  const wantSrc = landscape ? studio.item.proxy
    : (studio.mode === "reel" ? studio.item.video : studio.item.proxy);
  const fileOf = (u) => (u || "").split("?")[0].split("/").pop();
  const applyAR = () => {
    const realAR = (v.videoWidth && v.videoHeight) ? `${v.videoWidth}/${v.videoHeight}` : (landscape ? "16/9" : "9/16");
    frame.style.setProperty("--stage-ar", landscape ? realAR : "9/16");
    updateOverlayPreview();
  };
  if (wantSrc && fileOf(v.currentSrc) !== fileOf(wantSrc)) {
    const t = v.currentTime, playing = !v.paused;
    v.src = wantSrc;
    v.addEventListener("loadedmetadata", () => {
      try { v.currentTime = Math.min(t, (v.duration || t) - 0.01); } catch { /* ignore */ }
      if (playing) v.play().catch(() => {});
      applyAR();
    }, { once: true });
  } else {
    applyAR();
  }
  frame.classList.toggle("landscape", landscape);
  $("aspectToggle").querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.aspect === aspect));
  $("tpHint").textContent = landscape ? "landscape · original frame" : "";
  updateOverlayPreview();
}
$("aspectToggle").querySelectorAll("button").forEach(b => {
  b.onclick = () => setPreviewAspect(b.dataset.aspect);
});

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
$("modeCompose").onclick = () => setStudioMode("compose");
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
$("modalStudio").onclick = () => { const it = modalItem; closeModal(); if (it) openStudioById(it.id); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeModal(); closeStudio(); }
});

initWorkerOptions();
loadQueue();
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
