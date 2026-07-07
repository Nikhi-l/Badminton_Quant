/* Baddy frontend: upload, job progress, gallery. Vanilla JS, no build step. */
const $ = (id) => document.getElementById(id);

/* ---------- per-job vision worker selection ---------- */
function currentOptions() {
  const opts = {
    shuttle: $("optShuttle").checked ? "tracknetv3" : "off",
    pose: $("optPose").checked ? "yolo11" : "off",
    coach: $("optCoach").checked,
  };
  if (courtPick.corners.length === 4) opts.court_corners = courtPick.corners;
  return opts;
}

/* ---------- TASK-027: mark the court before processing ----------
A frame is grabbed CLIENT-SIDE from the selected file (no round trip); the user
clicks the four outer corners in the guided order the backend expects. Corners
ride along in options at upload-finish; drawing can continue while chunks
upload — anything short of 4 corners is simply dropped by validation, and the
Studio's "Draw court" covers jobs submitted without them. */
const courtPick = {
  corners: [],           // [[x, y] * 4] normalized to the source frame
  video: { x: 0, y: 0, w: 1, h: 1 },   // drawn video box within the canvas
  ready: false,
};
const COURT_PICK_ORDER = ["FAR-LEFT", "FAR-RIGHT", "NEAR-RIGHT", "NEAR-LEFT"];

async function courtPickLoad(file) {
  const wrap = $("voptCourt");
  if (!wrap) return;
  courtPick.corners = [];
  courtPick.ready = false;
  wrap.hidden = false;
  courtPickHint();
  const url = URL.createObjectURL(file);
  const v = document.createElement("video");
  v.muted = true;
  v.playsInline = true;
  v.preload = "auto";
  v.src = url;
  try {
    await new Promise((res, rej) => { v.onloadedmetadata = res; v.onerror = rej; setTimeout(rej, 8000); });
    await new Promise((res) => {
      v.onseeked = res;
      v.currentTime = Math.min((v.duration || 4) * 0.25, (v.duration || 4) - 0.1);
      setTimeout(res, 3000);
    });
    const canvas = $("courtPickCanvas");
    const g = canvas.getContext("2d");
    const vw = v.videoWidth || 16, vh = v.videoHeight || 9;
    const scale = Math.min(canvas.width / vw, canvas.height / vh);
    const w = vw * scale, h = vh * scale;
    const x = (canvas.width - w) / 2, y = (canvas.height - h) / 2;
    g.fillStyle = "#0b0d12";
    g.fillRect(0, 0, canvas.width, canvas.height);
    g.drawImage(v, x, y, w, h);
    courtPick.video = { x, y, w, h };
    courtPick.frame = g.getImageData(0, 0, canvas.width, canvas.height);
    courtPick.ready = true;
  } catch {
    wrap.hidden = true;   // unreadable codec etc. — picker is optional
  } finally {
    URL.revokeObjectURL(url);
  }
}

function courtPickHint() {
  const hint = $("courtPickHint"), status = $("courtPickStatus");
  if (!hint) return;
  const n = courtPick.corners.length;
  hint.textContent = n < 4
    ? `Click the ${COURT_PICK_ORDER[n]} corner (${n + 1}/4) — far = the baseline away from the camera`
    : "Court marked ✓ — it will be used for heatmaps & 3D replay";
  hint.classList.toggle("done", n === 4);
  if (status) status.textContent = n === 4 ? "included with this upload" : n ? `${n}/4 corners` : "";
}

function courtPickRedraw() {
  const canvas = $("courtPickCanvas");
  if (!canvas || !courtPick.frame) return;
  const g = canvas.getContext("2d");
  g.putImageData(courtPick.frame, 0, 0);
  const vb = courtPick.video;
  const px = (c) => [vb.x + c[0] * vb.w, vb.y + c[1] * vb.h];
  if (courtPick.corners.length > 1) {
    g.strokeStyle = "rgba(183,245,66,.9)";
    g.lineWidth = 2;
    g.beginPath();
    courtPick.corners.forEach((c, i) => {
      const [x, y] = px(c);
      if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
    });
    if (courtPick.corners.length === 4) g.closePath();
    g.stroke();
    if (courtPick.corners.length === 4) {
      g.fillStyle = "rgba(183,245,66,.08)";
      g.fill();
    }
  }
  courtPick.corners.forEach((c, i) => {
    const [x, y] = px(c);
    g.fillStyle = "#b7f542";
    g.strokeStyle = "#0a0c08";
    g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.fill(); g.stroke();
    g.fillStyle = "#0a0c08";
    g.font = "700 8px Inter";
    g.fillText(String(i + 1), x - 2.5, y + 3);
  });
}

(function initCourtPick() {
  const canvas = $("courtPickCanvas");
  if (!canvas) return;
  canvas.addEventListener("click", (e) => {
    if (!courtPick.ready || courtPick.corners.length >= 4) return;
    const r = canvas.getBoundingClientRect();
    const cx = (e.clientX - r.left) * (canvas.width / r.width);
    const cy = (e.clientY - r.top) * (canvas.height / r.height);
    const vb = courtPick.video;
    const nx = (cx - vb.x) / vb.w, ny = (cy - vb.y) / vb.h;
    if (nx < -0.02 || nx > 1.02 || ny < -0.02 || ny > 1.02) return;   // letterbox click
    courtPick.corners.push([Math.min(1, Math.max(0, +nx.toFixed(4))),
                            Math.min(1, Math.max(0, +ny.toFixed(4)))]);
    courtPickRedraw();
    courtPickHint();
  });
  const reset = $("courtPickReset");
  if (reset) reset.onclick = () => { courtPick.corners = []; courtPickRedraw(); courtPickHint(); };
})();

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
fileInput.onchange = () => {
  pickerBusy = false;
  if (fileInput.files.length) {
    courtPickLoad(fileInput.files[0]);   // draw corners while the upload runs
    startUpload([...fileInput.files]);
  }
};
["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => {
  const fs = [...e.dataTransfer.files];
  if (fs.length) {
    courtPickLoad(fs[0]);
    startUpload(fs);
  }
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
      ${st === "failed" ? `<button class="btn btn-small btn-ghost q-retry" data-rid="${esc(j.id)}">↻ Retry</button>` : ""}
    </div>`;
  }).join("");
  list.querySelectorAll(".q-open").forEach(b => b.onclick = () => openStudioById(b.dataset.qid));
  list.querySelectorAll(".q-retry").forEach(b => b.onclick = async () => {
    b.disabled = true;
    b.textContent = "retrying…";
    try {
      await jfetch(`/api/jobs/${b.dataset.rid}/retry`, { method: "POST" });
      myJobs.add(b.dataset.rid);
      localStorage.setItem("baddy_jobs", JSON.stringify([...myJobs]));
      loadQueue();
    } catch (e) {
      b.disabled = false;
      b.textContent = `retry failed`;
    }
  });
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
      court: { enabled: !!courtOf(item), opacity: 0.8, showNet: true },
      replay3d: { enabled: false },   // TASK-025: low-fps 3D replay, off by default
    },
    audio: { bed: "current-stitch", editable: false },
  };
}

// Detected court geometry (TASK-022), or null when detection didn't run/succeed.
function courtOf(item = studio.item) {
  const c = item && item.court;
  return (c && c.status === "ok" && Array.isArray(c.corners) && c.corners.length === 4) ? c : null;
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
      court: { ...base.overlays.court, ...((saved.overlays || {}).court || {}) },
      replay3d: { ...base.overlays.replay3d, ...((saved.overlays || {}).replay3d || {}) },
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
  const src = desiredVideoSrc();
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
  $("tpHint").textContent = effectiveMode() === "reel"
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
  list.querySelectorAll("[data-lib]").forEach(b => initLibraryDrag(b, clips[Number(b.dataset.lib)]));
}

let _nodeSeq = 0;
function addClipNode(clip, at = null) {
  const comp = compositionState();
  const n = comp.nodes.length;
  comp.nodes.push({
    id: `n${_nodeSeq++}_${comp.nodes.length}`,
    kind: clip.kind, refId: clip.refId, src: clip.src, label: clip.label, thumb: clip.thumb,
    t0: clip.t0, t1: clip.t1,
    x: at ? at.x : 40 + (n % 4) * 34,   // drop position, or staggered default
    y: at ? at.y : 40 + (n % 4) * 28,
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

// Convert a client (screen) point into canvas-node world coordinates, inverting
// the canvas translate+scale (transform-origin is the stage centre).
function clientToWorld(clientX, clientY) {
  const stage = $("studioStage"), rect = stage.getBoundingClientRect();
  const c = studio.canvas, s = c.scale || 1;
  const cx = rect.width / 2, cy = rect.height / 2;
  return {
    x: (clientX - rect.left - cx - c.x) / s + cx,
    y: (clientY - rect.top - cy - c.y) / s + cy,
  };
}

// Drag a clip node in canvas space. Listeners go on WINDOW: element-bound
// pointermove stops firing the instant a fast drag outruns the node (the "drag
// doesn't work properly" bug) — window-level tracking never loses the pointer.
function initNodeDrag(el) {
  const id = el.dataset.node;
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".clip-node-x")) return;
    e.stopPropagation();   // don't pan the canvas while dragging a node
    e.preventDefault();
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
    const up = () => {
      el.classList.remove("dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      saveEditorState();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  });
}

// Drag a clip from the library onto the canvas: a ghost follows the pointer and
// the node lands where you drop it (in world coordinates). A plain click (no
// movement) still adds the clip at the staggered default spot.
function initLibraryDrag(btn, clip) {
  btn.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const startX = e.clientX, startY = e.clientY;
    let ghost = null;
    const move = (ev) => {
      if (!ghost && Math.hypot(ev.clientX - startX, ev.clientY - startY) > 6) {
        ghost = document.createElement("div");
        ghost.className = "lib-ghost";
        ghost.textContent = clip.label;
        document.body.appendChild(ghost);
      }
      if (ghost) { ghost.style.left = `${ev.clientX + 10}px`; ghost.style.top = `${ev.clientY + 8}px`; }
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      if (!ghost) { addClipNode(clip); return; }          // plain click
      ghost.remove();
      const stage = $("studioStage"), r = stage.getBoundingClientRect();
      const inStage = ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
      if (!inStage) return;                                // dropped outside — cancel
      const w = clientToWorld(ev.clientX, ev.clientY);
      addClipNode(clip, { x: w.x - 86, y: w.y - 48 });     // centre the card on the drop
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  });
}

// Rally clips as reel-time segments. Two subtleties the overlays depend on:
// (1) the stitch crossfades consecutive clips, so clip k starts k·xfade EARLIER
//     than the plain running sum — without this, overlay timing drifts by
//     0.45s per rally boundary;
// (2) each clip is rendered from start−PAD_BEFORE, so mapping reel time to
//     source time uses the exported render_window (fallback: the 1.0s pad).
const PAD_BEFORE_FALLBACK = 1.0;   // config.PAD_BEFORE for results without render_window
function reelSegments() {
  const xfade = Number((studio.item.stitch || {}).xfade || 0);
  let acc = 0;
  return (studio.item.rallies || []).map((r, i) => {
    const dur = r.clip_dur || r.dur || 0;
    const t0 = Math.max(0, acc - i * xfade);
    const rw = Array.isArray(r.render_window) ? r.render_window : null;
    const seg = {
      t0,
      t1: t0 + dur,
      label: `R${i + 1}`,
      sub: `${Math.round(r.dur || dur)}s${r.note ? " · " + r.note : ""}`,
      layer: "reel",
      r,
      idx: i + 1,
      sourceStart: rw ? Number(rw[0])
        : (r.trimmed ? Number(r.start ?? 0)
                     : Math.max(0, Number(r.start ?? r.src_start ?? 0) - PAD_BEFORE_FALLBACK)),
      camPath: Array.isArray(r.camera_path) && r.camera_path.length ? r.camera_path : null,
      vision: r.vision,
    };
    acc += dur;
    return seg;
  });
}

// What the <video> element is showing right now. Landscape always plays the
// uncropped proxy (source frames, source time); Portrait plays the rendered
// 9:16 reel in Reel mode and the proxy in Source mode.
function displayedKind() {
  if (studio.previewAspect === "landscape") return "source";
  return studio.mode === "reel" ? "reel" : "source";
}

// The timeline/overlay mode the stage should reflect: Landscape forces the
// source-rally view (the reel timeline makes no sense against proxy playback).
function effectiveMode() {
  if (studio.mode === "compose") return "compose";
  return studio.previewAspect === "landscape" ? "source" : studio.mode;
}

function desiredVideoSrc() {
  if (studio.previewAspect === "landscape") return studio.item.proxy;
  return studio.mode === "reel" ? studio.item.video : studio.item.proxy;
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
  if (effectiveMode() === "reel") {
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
    if (track.id === "shuttle" && effectiveMode() === "source") {
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
    if (track.id === "pose" && effectiveMode() === "source" && studio.editorState.overlays.pose.enabled) {
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
    if (track.id === "camera" && effectiveMode() === "reel" && (studio.editorState.camera || {}).enabled) {
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

// TASK-025: 3D replay panel visibility + render. Called from the rAF tick via
// updateOverlayPreview so explicit repaints (seeks, occluded windows) stay in
// sync; render() itself is gated to the low-fps sim clock (repaints only when
// the sim bucket / camera / size changes).
function syncReplay3d(ctx) {
  const r3o = studio.editorState && studio.editorState.overlays.replay3d;
  const show = !!(r3o && r3o.enabled && studio.mode !== "compose"
                  && typeof replay3D !== "undefined" && replay3D.anyRally3d());
  const panel = $("replay3d");
  if (panel && panel.hidden !== !show) panel.hidden = !show;
  if (show) replay3D.render(ctx || trackContext());
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
    { id: "court", ico: "▦", title: "Court", sub: courtOf() ? `detected · ${fmtPct(courtOf().confidence)}` : "not detected", state: courtOf() ? (state.overlays.court.enabled ? "on" : "off") : "n/a" },
    { id: "replay3d", ico: "▲", title: "3D replay", sub: (typeof replay3D !== "undefined" && replay3D.anyRally3d()) ? `reconstructed · sim ${(reelSegments().find(x => x.r && x.r.rally_3d) || { r: { rally_3d: { fps: 12 } } }).r.rally_3d.fps}fps` : "no reconstruction", state: (typeof replay3D !== "undefined" && replay3D.anyRally3d()) ? (state.overlays.replay3d.enabled ? "on" : "off") : "n/a" },
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
        <button class="btn btn-small" id="camAddKf" ${effectiveMode() !== "reel" ? "disabled" : ""}>+ Keyframe at playhead</button>
        ${effectiveMode() !== "reel" ? `<div class="control-hint muted">Keyframes are authored in reel time — switch to Portrait · Reel to add or preview them.</div>` : ""}
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
      <div class="control-group">
        <div class="control-title"><span>Movement heatmap</span><span>post-game</span></div>
        <div class="heatmap-grid" id="heatmapGrid"></div>
        <div class="control-hint muted">${courtOf() ? "Court-plane positions via the detected court homography." : "No court detected — positions shown in camera space."}</div>
      </div>
      ${qualityMetrics()}`;
    $("poseEnabled").onchange = (e) => { po.enabled = e.target.checked; stateChanged(); };
    $("poseWidth").oninput = (e) => { po.lineWidth = Number(e.target.value); stateChanged(false); };
    $("poseOpacity").oninput = (e) => { po.opacity = Number(e.target.value) / 100; stateChanged(false); };
    panel.querySelectorAll("[data-pose-style]").forEach(btn => btn.onclick = () => {
      po.style = btn.dataset.poseStyle;
      stateChanged();
    });
    renderHeatmaps($("heatmapGrid"));
  } else if (studio.selectedLayer === "court") {
    const co = state.overlays.court;
    const c = courtOf();
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>Court lines</span><label><input type="checkbox" id="courtEnabled" ${co.enabled && c ? "checked" : ""} ${c ? "" : "disabled"}> Visible</label></div>
        ${c ? `
        <div class="control-row"><label>Opacity</label><input type="range" id="courtOpacity" min="25" max="100" value="${Math.round(co.opacity * 100)}"></div>
        <div class="control-row"><label>Net line</label><input type="checkbox" id="courtNet" ${co.showNet ? "checked" : ""}></div>
        <div class="metric-list">
          <div class="metric"><b>${fmtPct(c.confidence)}</b><span>confidence</span></div>
          <div class="metric"><b>${c.frames_used || 1}</b><span>frames agreed</span></div>
        </div>
        <div class="control-hint muted">Boundary + corners ${c.source === "manual" ? "drawn by you" : "detected on the source frame"}; the homography maps play onto a ${(c.court_size_m || [6.1, 13.4])[0]}×${(c.court_size_m || [6.1, 13.4])[1]}m court plane for heatmaps and the 3D view.</div>`
        : `<div class="control-hint muted">No court boundary detected in this video (POV or occluded footage skips it). Draw it yourself below — heatmaps and 3D replay recompute instantly.</div>`}
      <button class="btn btn-small" id="courtDrawBtn">${courtDraw.active ? "Cancel drawing" : (c ? "Redraw court corners" : "✏️ Draw court corners")}</button>
      ${courtDraw.active ? `<div class="control-hint muted">Click the four OUTER corners on the video in order: far-left, far-right, near-right, near-left.</div>` : ""}
      </div>`;
    if (c) {
      $("courtEnabled").onchange = (e) => { co.enabled = e.target.checked; stateChanged(); };
      $("courtOpacity").oninput = (e) => { co.opacity = Number(e.target.value) / 100; stateChanged(false); };
      $("courtNet").onchange = (e) => { co.showNet = e.target.checked; stateChanged(false); };
    }
    $("courtDrawBtn").onclick = () => (courtDraw.active ? endCourtDraw(true) : startCourtDraw());
  } else if (studio.selectedLayer === "replay3d") {
    const r3o = state.overlays.replay3d;
    const has = typeof replay3D !== "undefined" && replay3D.anyRally3d();
    const seg = reelSegments().find(x => x.r && x.r.rally_3d && x.r.rally_3d.status === "ok");
    const r3 = seg && seg.r.rally_3d;
    panel.innerHTML = `
      <div class="control-group">
        <div class="control-title"><span>3D replay</span><label><input type="checkbox" id="r3dEnabled" ${r3o.enabled && has ? "checked" : ""} ${has ? "" : "disabled"}> Show</label></div>
        ${has ? `
        <div class="control-hint muted">Monocular reconstruction: camera pose from the detected court, shuttle 3D from a drag-ballistic fit over the TrackNet rays. Simulation runs at ${r3 ? r3.fps : 12}fps (view interpolates); drag the panel to orbit, wheel to zoom.</div>
        <div class="metric-list">
          <div class="metric"><b>${reelSegments().filter(x => x.r && x.r.rally_3d && x.r.rally_3d.status === "ok").length}</b><span>rallies reconstructed</span></div>
          <div class="metric"><b>${r3 ? r3.shots.length : 0}</b><span>shots (first rally)</span></div>
        </div>
        ${r3 ? `<div class="kf-list">${r3.shots.slice(0, 8).map(sh => `<div class="kf-item"><span class="kf-t">${fmtT(sh.t0)}</span><span class="kf-tgt">${sh.speed_kmh} km/h · peak ${sh.peak_z}m · ±${sh.residual_px}px</span></div>`).join("")}</div>` : ""}`
        : `<div class="control-hint muted">No 3D reconstruction on this reel — it needs a detected court and a TrackNet shuttle track, and is computed for new jobs at render time.</div>`}
      </div>`;
    if (has) $("r3dEnabled").onchange = (e) => { r3o.enabled = e.target.checked; if (typeof replay3D !== "undefined") replay3D.invalidate(); stateChanged(); };
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
  // Keyframes are authored in reel time; in Landscape the video runs on source
  // time, so the camera preview would track the wrong moments — skip it there.
  if (effectiveMode() !== "reel") return null;
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

/* ---------- track interpolation (TASK-022) ----------
The public tracks are sampled at ≤10Hz; snapping to the nearest sample made
markers hop up to ±50ms of real motion. These lerp between the bracketing
samples when the gap is small (a continuous trajectory), and fall back to the
nearest sample inside `window` across real gaps (detector dropouts). */

function _bracket(track, t) {
  let lo = 0, hi = track.length - 1;
  if (t <= Number(track[0].t)) return [0, 0];
  if (t >= Number(track[hi].t)) return [hi, hi];
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (Number(track[m].t) <= t) lo = m; else hi = m;
  }
  return [lo, hi];
}

function interpTrackPoint(track, t, window = 0.55, maxGap = 0.6) {
  if (!track || !track.length) return null;
  const [i, j] = _bracket(track, t);
  const a = track[i], b = track[j];
  if (i !== j) {
    const gap = Number(b.t) - Number(a.t);
    if (gap > 0 && gap <= maxGap) {
      const k = (t - Number(a.t)) / gap;
      return {
        t,
        x: Number(a.x) + (Number(b.x) - Number(a.x)) * k,
        y: Number(a.y) + (Number(b.y) - Number(a.y)) * k,
        confidence: Math.min(Number(a.confidence || 0), Number(b.confidence || 0)),
      };
    }
  }
  const n = Math.abs(Number(a.t) - t) <= Math.abs(Number(b.t) - t) ? a : b;
  return Math.abs(Number(n.t) - t) <= window ? n : null;
}

// Per-id box interpolation between two sampled frames. An id present on only
// one side holds its position (better than blinking off for 100ms).
function interpPlayerBoxes(frames, t, window = 1.0, maxGap = 1.2) {
  if (!frames || !frames.length) return [];
  const [i, j] = _bracket(frames, t);
  const A = frames[i], B = frames[j];
  const nearest = () => {
    const n = Math.abs(Number(A.t) - t) <= Math.abs(Number(B.t) - t) ? A : B;
    return Math.abs(Number(n.t) - t) <= window ? (n.boxes || []) : [];
  };
  if (i === j || Number(B.t) - Number(A.t) > maxGap) return nearest();
  const k = (t - Number(A.t)) / (Number(B.t) - Number(A.t));
  const after = new Map((B.boxes || []).map(b => [b.id, b]));
  const out = [];
  for (const a of (A.boxes || [])) {
    const b = after.get(a.id);
    if (!b) { out.push(a); continue; }
    after.delete(a.id);
    out.push({
      id: a.id,
      confidence: Math.min(Number(a.confidence || 0), Number(b.confidence || 0)),
      x: Number(a.x) + (Number(b.x) - Number(a.x)) * k,
      y: Number(a.y) + (Number(b.y) - Number(a.y)) * k,
      w: Number(a.w) + (Number(b.w) - Number(a.w)) * k,
      h: Number(a.h) + (Number(b.h) - Number(a.h)) * k,
    });
  }
  after.forEach(b => out.push(b));
  return out;
}

// Pose interpolation: match people by id, lerp the 17 keypoints index-wise
// (and the bbox), so skeletons glide between sparse samples.
function interpPoseFrame(frames, t, window = 1.0, maxGap = 1.2) {
  if (!frames || !frames.length) return null;
  const [i, j] = _bracket(frames, t);
  const A = frames[i], B = frames[j];
  const nearest = () => {
    const n = Math.abs(Number(A.t) - t) <= Math.abs(Number(B.t) - t) ? A : B;
    return Math.abs(Number(n.t) - t) <= window ? n : null;
  };
  if (i === j || Number(B.t) - Number(A.t) > maxGap) return nearest();
  const k = (t - Number(A.t)) / (Number(B.t) - Number(A.t));
  const after = new Map((B.people || []).map(p => [p.id, p]));
  const people = [];
  const lerp = (a, b) => a + (b - a) * k;
  for (const pa of (A.people || [])) {
    const pb = after.get(pa.id);
    if (!pb || !Array.isArray(pa.keypoints) || !Array.isArray(pb.keypoints)) {
      people.push(pa);
      if (pb) after.delete(pa.id);
      continue;
    }
    after.delete(pa.id);
    const kp = pa.keypoints.map((ka, n) => {
      const kb = pb.keypoints[n];
      if (!kb) return ka;
      return {
        x: lerp(Number(ka.x), Number(kb.x)),
        y: lerp(Number(ka.y), Number(kb.y)),
        confidence: Math.min(Number(ka.confidence || 0), Number(kb.confidence || 0)),
      };
    });
    const person = { ...pa, keypoints: kp };
    if (pa.bbox && pb.bbox) {
      person.bbox = {
        x: lerp(Number(pa.bbox.x), Number(pb.bbox.x)),
        y: lerp(Number(pa.bbox.y), Number(pb.bbox.y)),
        w: lerp(Number(pa.bbox.w), Number(pb.bbox.w)),
        h: lerp(Number(pa.bbox.h), Number(pb.bbox.h)),
        confidence: Math.min(Number(pa.bbox.confidence || 0), Number(pb.bbox.confidence || 0)),
      };
    }
    people.push(person);
  }
  after.forEach(p => people.push(p));
  return { t, people };
}

/* ---------- TASK-021: displayed-video-aware track mapping ----------
All tracking coordinates (shuttle/players/pose) are normalized to the SOURCE
frame. What's on screen differs:
  · proxy (Landscape, or Source mode)  → source frames; currentTime IS source time.
  · rendered reel (Portrait + Reel)    → each frame is a moving virtual-camera
    CROP of the source. Overlays must (a) map reel time → source time through the
    rally's render_window and (b) project source coords through the exported
    camera_path crop rect. Without camera_path (legacy reels) the projection is
    impossible — overlays hide and a hint explains why. */

// The playhead's source time + the rally segment owning it, kind-aware.
function trackContext() {
  const v = $("stVideo");
  if (!studio.item || !v.duration || !studio.editorState) return null;
  const segs = reelSegments();
  if (displayedKind() === "source") {
    const t = v.currentTime;
    const seg = segs.find(s => t >= s.sourceStart - 0.3
                            && t <= s.sourceStart + (s.t1 - s.t0) + 0.3) || null;
    return { kind: "source", sourceT: t, seg, segs };
  }
  const seg = segs.find(s => v.currentTime >= s.t0 && v.currentTime <= s.t1);
  if (!seg) return null;
  return { kind: "reel", sourceT: seg.sourceStart + (v.currentTime - seg.t0), seg, segs };
}

// The render crop window (normalized source rect) at source time t, lerped
// between the exported camera_path samples. Null when the reel predates the
// camera_path export.
function cropRectAt(seg, t) {
  const path = seg && seg.camPath;
  if (!path || !path.length) return null;
  let a = path[0], b = path[path.length - 1];
  if (t <= a.t) b = a;
  else if (t >= b.t) a = b;
  else {
    for (let i = 0; i < path.length - 1; i++) {
      if (path[i + 1].t >= t) { a = path[i]; b = path[i + 1]; break; }
    }
  }
  const span = b.t - a.t;
  const k = span > 0 ? (t - a.t) / span : 0;
  const L = (p, q) => p + (q - p) * k;
  return { x: L(a.x, b.x), y: L(a.y, b.y), w: L(a.w, b.w), h: L(a.h, b.h) };
}

const bakedMirror = () => !!((studio.item && studio.item.remix) || {}).mirror;

// Source-normalized point → the DISPLAYED video's own normalized space.
// Identity on source video; inverts the baked virtual camera on the reel.
// `clamp` drops points outside the visible crop (markers); boxes pass false so a
// half-visible player still draws (the stage clips the rest).
function toDisplayNorm(x, y, ctx, clamp = true) {
  if (ctx.kind !== "reel") return { x, y };
  const rect = cropRectAt(ctx.seg, ctx.sourceT);
  if (!rect || rect.w <= 0 || rect.h <= 0) return null;
  let nx = (x - rect.x) / rect.w;
  const ny = (y - rect.y) / rect.h;
  if (bakedMirror()) nx = 1 - nx;   // reel content is baked mirrored; return FILE coords
  if (clamp && (nx < -0.12 || nx > 1.12 || ny < -0.12 || ny > 1.12)) return null;
  return { x: nx, y: ny };
}

// Track point → screen {left,top} percentages, or null when unmappable.
function trackPointToScreen(x, y, ctx, clamp = true) {
  const n = toDisplayNorm(Number(x), Number(y), ctx, clamp);
  return n ? videoFitPoint(n.x, n.y) : null;
}

// Player boxes ({id,x,y,w,h,confidence}) tracked at the playhead, or [].
function currentPlayers(ctx = trackContext()) {
  if (!ctx) return [];
  const pick = (vision, t) => interpPlayerBoxes((vision || {}).players_track || [], t);
  if (ctx.seg) return pick(ctx.seg.vision, ctx.sourceT);
  if (ctx.kind === "source") {
    for (const seg of ctx.segs) {
      const boxes = pick(seg.vision, ctx.sourceT);
      if (boxes.length) return boxes;
    }
  }
  return [];
}

function currentShuttlePoint(ctx = trackContext()) {
  if (!ctx) return null;
  if (ctx.seg) return interpTrackPoint(((ctx.seg.vision || {}).shuttle_track || []), ctx.sourceT);
  if (ctx.kind === "source") {
    for (const seg of ctx.segs) {
      const p = interpTrackPoint(((seg.vision || {}).shuttle_track || []), ctx.sourceT);
      if (p) return p;
    }
  }
  return null;
}

// Player boxes smoothed over time (per id) so the overlay glides instead of snapping
// between sparse samples. Snaps on a big jump (new detection / rally cut).
function smoothedPlayerBoxes(ctx = trackContext()) {
  const raw = currentPlayers(ctx);
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
// Past positions are projected through the CURRENT crop (they are places in space,
// not time) — points that have scrolled out of the crop just drop off the trail.
function recentShuttleScreenPoints(ctx, windowSec = 0.7) {
  if (!ctx) return [];
  let track = null;
  if (ctx.seg) track = (ctx.seg.vision || {}).shuttle_track || [];
  else if (ctx.kind === "source") {
    for (const seg of ctx.segs) {
      const t = (seg.vision || {}).shuttle_track || [];
      if (nearestTrackPoint(t, ctx.sourceT)) { track = t; break; }
    }
  }
  if (!track) return [];
  return track
    .filter(p => Number(p.t) <= ctx.sourceT + 1e-3 && Number(p.t) >= ctx.sourceT - windowSec && Number(p.confidence || 0) >= 0.3)
    .sort((a, b) => a.t - b.t)
    .map(p => trackPointToScreen(p.x, p.y, ctx))
    .filter(Boolean);
}

// Comet-style trail: per-segment opacity and width ramp from the oldest point to
// the newest, so the trail fades out behind the shuttle instead of reading as a
// flat line. A soft glow dot marks the freshest end.
function shuttleTrailSvg(sh, ctx) {
  const pts = recentShuttleScreenPoints(ctx);
  if (pts.length < 2) return "";
  const segs = [];
  const n = pts.length - 1;
  for (let i = 0; i < n; i++) {
    const k = (i + 1) / n;                       // 0 oldest → 1 newest
    const w = (0.8 + 2.6 * k).toFixed(2);
    const o = (sh.opacity * (0.08 + 0.62 * k)).toFixed(3);
    segs.push(`<line x1="${pts[i].left.toFixed(2)}" y1="${pts[i].top.toFixed(2)}" ` +
      `x2="${pts[i + 1].left.toFixed(2)}" y2="${pts[i + 1].top.toFixed(2)}" ` +
      `stroke="var(--lime)" stroke-width="${w}" stroke-linecap="round" ` +
      `vector-effect="non-scaling-stroke" opacity="${o}"></line>`);
  }
  const tip = pts[pts.length - 1];
  segs.push(`<circle cx="${tip.left.toFixed(2)}" cy="${tip.top.toFixed(2)}" r="1.6" ` +
    `fill="var(--lime)" opacity="${(sh.opacity * 0.5).toFixed(3)}" class="trail-tip"></circle>`);
  return `<svg class="shuttle-trail-svg" viewBox="0 0 100 100" preserveAspectRatio="none">${segs.join("")}</svg>`;
}

// One-time-per-state hint when overlays can't be aligned (legacy reel without
// an exported camera_path, viewed in Portrait+Reel).
function overlayAlignmentHint(ctx, anyOverlayOn) {
  const el = $("tpHint");
  const need = anyOverlayOn && ctx && ctx.kind === "reel" && ctx.seg && !ctx.seg.camPath;
  const msg = "overlays need a re-render to align on this reel — Rebuild cuts, or switch to Landscape";
  if (need && el.textContent !== msg) el.textContent = msg;
  else if (!need && el.textContent === msg) el.textContent = "";
}

function updateOverlayPreview() {
  const wrap = $("aiOverlays");
  const state = studio.editorState;
  if (!wrap || !state) return;
  applyFraming();
  const ctx = trackContext();
  const parts = [];
  // Court boundary first — it sits UNDER the action overlays.
  const courtSvg = renderCourtOverlay(ctx);
  if (courtSvg) parts.push(courtSvg);
  // Shuttle: draw ONLY when the shuttle is actually tracked at the current time —
  // no fixed-default/last-position marker (that was the phantom "circle"). The trail
  // follows the shuttle's real recent path, not a fixed-offset bar.
  const sh = state.overlays.shuttle;
  const p = (sh.enabled && ctx) ? currentShuttlePoint(ctx) : null;
  const pos = p ? trackPointToScreen(p.x, p.y, ctx) : null;
  if (pos) {
    if (sh.trail) parts.push(shuttleTrailSvg(sh, ctx));
    parts.push(`<div class="shuttle-mark ${esc(sh.style)}" style="left:${pos.left}%;top:${pos.top}%;width:${sh.size}px;height:${sh.size}px;margin-left:${-sh.size / 2}px;margin-top:${-sh.size / 2}px;--overlay-opacity:${sh.opacity}"></div>`);
  }
  // Players & pose layer: draw the tracked player boxes at the current time (real
  // data from the YOLO worker), smoothed over time, hidden when none, plus the
  // pose skeleton for every tracked person.
  const po = state.overlays.pose;
  if (po.enabled && ctx) {
    const target = (state.camera && state.camera.targetPlayer != null) ? state.camera.targetPlayer : null;
    for (const b of smoothedPlayerBoxes(ctx)) {
      const html = renderPlayerBox(b, po, b.id === target, ctx);
      if (html) parts.push(html);
    }
    const pose = currentPose(ctx);
    if (pose) parts.push(renderPoseOverlay(pose, po, ctx));
    for (const rb of currentRacquets(ctx)) {
      const tl = trackPointToScreen(Number(rb.x) - Number(rb.w) / 2, Number(rb.y) - Number(rb.h) / 2, ctx, false);
      const br = trackPointToScreen(Number(rb.x) + Number(rb.w) / 2, Number(rb.y) + Number(rb.h) / 2, ctx, false);
      if (!tl || !br) continue;
      const left = Math.min(tl.left, br.left), top = Math.min(tl.top, br.top);
      const w = Math.abs(br.left - tl.left), hh = Math.abs(br.top - tl.top);
      if (left > 104 || top > 104 || left + w < -4 || top + hh < -4) continue;
      parts.push(`<div class="racquet-box" style="left:${left}%;top:${top}%;width:${w}%;height:${hh}%;opacity:${po.opacity}"><span class="racquet-tag">racquet</span></div>`);
    }
  }
  overlayAlignmentHint(ctx, sh.enabled || po.enabled);
  wrap.innerHTML = parts.join("");
  syncReplay3d(ctx);
}

// A tracked player's bounding box, framing-aware. Map both corners through the
// crop projection + videoFitPoint so camera/zoom/pan transforms apply correctly.
function renderPlayerBox(b, po, isTarget, ctx) {
  const tl = trackPointToScreen(Number(b.x) - Number(b.w) / 2, Number(b.y) - Number(b.h) / 2, ctx, false);
  const br = trackPointToScreen(Number(b.x) + Number(b.w) / 2, Number(b.y) + Number(b.h) / 2, ctx, false);
  if (!tl || !br) return "";
  const left = Math.min(tl.left, br.left), top = Math.min(tl.top, br.top);
  const w = Math.abs(br.left - tl.left), h = Math.abs(br.top - tl.top);
  if (left > 104 || top > 104 || left + w < -4 || top + h < -4) return "";   // fully outside the crop
  return `<div class="player-box p${Number(b.id) % 4}${isTarget ? " target" : ""}" data-pid="${b.id}" ` +
    `style="left:${left}%;top:${top}%;width:${w}%;height:${h}%;opacity:${po.opacity}">` +
    `<span class="player-tag">P${Number(b.id) + 1}</span></div>`;
}

// Measured racquet boxes at the playhead (TASK-027), or [].
function currentRacquets(ctx = trackContext()) {
  if (!ctx) return [];
  const pick = (vision, t) => {
    const fr = nearestTrackPoint((vision || {}).racquet_track || [], t, 0.6);
    return fr ? (fr.boxes || []) : [];
  };
  if (ctx.seg) return pick(ctx.seg.vision, ctx.sourceT);
  if (ctx.kind === "source") {
    for (const seg of ctx.segs) {
      const boxes = pick(seg.vision, ctx.sourceT);
      if (boxes.length) return boxes;
    }
  }
  return [];
}

// Real pose keypoints for the current time, or null.
function currentPose(ctx = trackContext()) {
  if (!ctx) return null;
  const pick = (vision, t) => interpPoseFrame((vision || {}).pose_track || [], t);
  if (ctx.seg) return pick(ctx.seg.vision, ctx.sourceT);
  if (ctx.kind === "source") {
    for (const seg of ctx.segs) {
      const fr = pick(seg.vision, ctx.sourceT);
      if (fr) return fr;
    }
  }
  return null;
}

const POSE_LIMBS = [
  [5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
];

// Velocity style: per-person centroid speed (normalized units/s) → color ramp.
const _poseVel = {};   // person id -> {x, y, t, speed}
function _poseSpeed(person, keypoints) {
  const good = keypoints.filter(Boolean);
  if (!good.length) return 0;
  const cx = good.reduce((s, p) => s + p.nx, 0) / good.length;
  const cy = good.reduce((s, p) => s + p.ny, 0) / good.length;
  const now = performance.now();
  const prev = _poseVel[person.id];
  if (!prev) { _poseVel[person.id] = { x: cx, y: cy, t: now, speed: 0 }; return 0; }
  const dt = (now - prev.t) / 1000;
  if (dt < 0.04) return prev.speed;          // sub-frame call: keep the smoothed value
  const inst = Math.min(Math.hypot(cx - prev.x, cy - prev.y) / dt, 2.5);
  const speed = prev.speed * 0.7 + inst * 0.3;
  _poseVel[person.id] = { x: cx, y: cy, t: now, speed };
  return speed;
}
const _velColor = (s) => s < 0.12 ? "#7ee0a3" : s < 0.3 ? "#b7f542" : s < 0.6 ? "#ffd166" : "#ff4d6d";

// Skeleton overlay in PIXEL space. The old 0-100 viewBox with
// preserveAspectRatio="none" stretched joint circles into huge blobs on a wide
// stage (r=2.8 meant 2.8% OF FRAME WIDTH). Pixel coordinates keep joints round
// and line widths true at any aspect.
function renderPoseOverlay(pose, po, ctx) {
  const frame = $("stageFrame");
  const fw = frame.clientWidth || 1, fh = frame.clientHeight || 1;
  const people = (pose.people || []).filter(p => Array.isArray(p.keypoints));
  if (!people.length) return "";
  const lw = Number(po.lineWidth) || 3;
  const jr = Math.max(2.2, lw * 0.9 + 0.8);
  const parts = [];
  for (const person of people) {
    const pid = Number(person.id || 0) % 4;
    const pts = person.keypoints.map(k => {
      if (Number(k.confidence || 0) < 0.12) return null;
      const s = trackPointToScreen(k.x, k.y, ctx);
      return s ? { x: s.left / 100 * fw, y: s.top / 100 * fh, nx: Number(k.x), ny: Number(k.y) } : null;
    });
    const vel = po.style === "velocity" ? _poseSpeed(person, pts) : 0;
    const velStyle = po.style === "velocity" ? ` style="stroke:${_velColor(vel)}"` : "";
    const velFill = po.style === "velocity" ? ` style="fill:${_velColor(vel)}"` : "";
    for (const [a, b] of POSE_LIMBS) {
      if (!pts[a] || !pts[b]) continue;
      parts.push(`<line class="pose-limb p${pid}"${velStyle} x1="${pts[a].x.toFixed(1)}" y1="${pts[a].y.toFixed(1)}" x2="${pts[b].x.toFixed(1)}" y2="${pts[b].y.toFixed(1)}"></line>`);
    }
    pts.forEach((pt, i) => {
      if (!pt || i in { 1: 1, 2: 1, 3: 1, 4: 1 }) return;   // eyes/ears clutter at small scale
      parts.push(`<circle class="pose-joint p${pid}"${velFill} data-kp="${i}" cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="${(i === 0 ? jr * 1.7 : jr).toFixed(1)}"></circle>`);
    });
  }
  if (!parts.length) return "";
  return `<svg class="pose-figure ${esc(po.style)}" viewBox="0 0 ${fw} ${fh}" preserveAspectRatio="none" style="opacity:${po.opacity};--pose-width:${lw}px">${parts.join("")}</svg>`;
}

/* ---------- TASK-027: draw the court on an existing job ---------- */
// Landscape + reset framing makes the stage a pure contain-box of the SOURCE
// frame, so a click inverts to source-normalized coordinates with no crop math.
const courtDraw = { active: false, pts: [] };

function startCourtDraw() {
  courtDraw.active = true;
  courtDraw.pts = [];
  setPreviewAspect("landscape");
  studio.editorState.framing = { fit: "fit", zoom: 1, x: 0, y: 0 };
  applyFraming();
  const frame = $("stageFrame");
  frame.style.cursor = "crosshair";
  frame.addEventListener("pointerdown", courtDrawClick, true);
  courtDrawHint();
  renderInspector();
}

function endCourtDraw(cancelled = false) {
  courtDraw.active = false;
  const frame = $("stageFrame");
  frame.style.cursor = "";
  frame.removeEventListener("pointerdown", courtDrawClick, true);
  const layer = $("courtDrawLayer");
  if (layer) layer.remove();
  if (cancelled) $("tpHint").textContent = "";
  renderInspector();
}

function courtDrawHint() {
  const n = courtDraw.pts.length;
  $("tpHint").textContent = n < 4
    ? `court: click the ${COURT_PICK_ORDER[n]} corner (${n + 1}/4)`
    : "court: saving…";
}

function courtDrawClick(e) {
  if (!courtDraw.active) return;
  e.stopPropagation();
  e.preventDefault();
  const frame = $("stageFrame"), v = $("stVideo");
  const r = frame.getBoundingClientRect();
  const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
  // invert the contain box (fit, zoom 1, no pan — enforced by startCourtDraw)
  const fw = frame.clientWidth || 1, fh = frame.clientHeight || 1;
  const vw = v.videoWidth || 16, vh = v.videoHeight || 9;
  const frameAspect = fw / fh, videoAspect = vw / vh;
  let w = fw, h = fh, ox = 0, oy = 0;
  if (videoAspect > frameAspect) { h = fw / videoAspect; oy = (fh - h) / 2; }
  else { w = fh * videoAspect; ox = (fw - w) / 2; }
  const nx = (fx * fw - ox) / w, ny = (fy * fh - oy) / h;
  if (nx < -0.02 || nx > 1.02 || ny < -0.02 || ny > 1.02) return;
  courtDraw.pts.push([Math.min(1, Math.max(0, +nx.toFixed(4))),
                      Math.min(1, Math.max(0, +ny.toFixed(4)))]);
  courtDrawRender();
  courtDrawHint();
  if (courtDraw.pts.length === 4) submitCourtDraw();
}

function courtDrawRender() {
  let layer = $("courtDrawLayer");
  if (!layer) {
    layer = document.createElement("div");
    layer.id = "courtDrawLayer";
    layer.className = "court-draw-layer";
    $("stageFrame").appendChild(layer);
  }
  const ctx = trackContext() || { kind: "source", sourceT: 0, seg: null, segs: [] };
  layer.innerHTML = courtDraw.pts.map((p, i) => {
    const s = videoFitPoint(p[0], p[1]);
    return `<span class="court-draw-dot" style="left:${s.left}%;top:${s.top}%">${i + 1}</span>`;
  }).join("");
}

async function submitCourtDraw() {
  try {
    const resp = await jfetch(`/api/jobs/${studio.item.id}/court`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ corners: courtDraw.pts }),
    });
    // pull the recomputed rallies (court + rally_3d) without resetting the editor
    const job = await jfetch(`/api/jobs/${studio.item.id}`);
    if (job && job.result) {
      studio.item = { ...studio.item, court: job.result.court,
                      rallies: job.result.rallies, rally_pool: job.result.rally_pool };
    }
    studio.editorState.overlays.court.enabled = true;
    if (typeof replay3D !== "undefined") replay3D.invalidate();
    endCourtDraw();
    $("tpHint").textContent = `court saved — heatmaps updated · ${resp.rallies_3d} rall${resp.rallies_3d === 1 ? "y" : "ies"} reconstructed in 3D`;
    renderLayerList();
    renderInspector();
    updateOverlayPreview();
  } catch (e) {
    endCourtDraw(true);
    $("tpHint").textContent = `court not saved: ${e.message}`;
  }
}

/* ---------- TASK-022: court overlay + post-game movement heatmaps ---------- */
function courtProject(h, x, y) {
  const w = h[6] * x + h[7] * y + h[8];
  if (Math.abs(w) < 1e-9) return null;
  return { u: (h[0] * x + h[1] * y + h[2]) / w, v: (h[3] * x + h[4] * y + h[5]) / w };
}

// The detected court boundary drawn through the SAME projection as the tracks,
// so it stays glued to the floor in every view (landscape, portrait, reel crop).
function renderCourtOverlay(ctx) {
  const state = studio.editorState;
  const co = state.overlays.court;
  const c = courtOf();
  if (!co || !co.enabled || !c || !ctx) return "";
  const frame = $("stageFrame");
  const fw = frame.clientWidth || 1, fh = frame.clientHeight || 1;
  const px = (p) => {
    const s = trackPointToScreen(p[0], p[1], ctx, false);
    return s ? { x: s.left / 100 * fw, y: s.top / 100 * fh } : null;
  };
  const corners = c.corners.map(px);
  if (!corners.every(Boolean)) return "";
  const pts = corners.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const parts = [`<polygon class="court-edge" points="${pts}"></polygon>`];
  if (co.showNet && Array.isArray(c.net)) {
    const a = px([c.net[0], c.net[1]]), b = px([c.net[2], c.net[3]]);
    if (a && b) parts.push(`<line class="court-net" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}"></line>`);
  }
  corners.forEach(p => parts.push(`<circle class="court-corner" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4"></circle>`));
  return `<svg class="court-overlay" viewBox="0 0 ${fw} ${fh}" preserveAspectRatio="none" style="opacity:${co.opacity}">${parts.join("")}</svg>`;
}

// Foot positions (box bottom-center) for one player id across ALL rallies —
// the post-game aggregate the heatmaps ask for.
function playerFootPoints(pid) {
  const pts = [];
  for (const seg of reelSegments()) {
    for (const f of ((seg.vision || {}).players_track || [])) {
      for (const b of (f.boxes || [])) {
        if (Number(b.id) !== pid) continue;
        pts.push({ x: Number(b.x), y: Number(b.y) + Number(b.h) / 2 });
      }
    }
  }
  return pts;
}

function trackedPlayerIds() {
  const ids = new Set();
  for (const seg of reelSegments())
    for (const f of ((seg.vision || {}).players_track || []))
      for (const b of (f.boxes || [])) ids.add(Number(b.id));
  return [...ids].sort((a, b) => a - b).slice(0, 4);
}

function _heatColor(t) {
  return `hsla(${Math.round(100 - 85 * t)}, 92%, ${Math.round(46 + 12 * t)}%, ${(0.22 + 0.68 * t).toFixed(2)})`;
}

// Standard court markings on the schematic (meters): net, short service lines
// (1.98m off the net), doubles long service (0.76m off each baseline), center
// lines, singles side lines (0.46m in).
function _drawCourtSchematic(g, X, Y) {
  const Wm = 6.1, Lm = 13.4;
  g.strokeStyle = "rgba(255,255,255,.55)"; g.lineWidth = 1.2;
  g.strokeRect(X(0), Y(0), X(Wm) - X(0), Y(Lm) - Y(0));
  g.lineWidth = 0.8; g.strokeStyle = "rgba(255,255,255,.25)";
  const hline = (m) => { g.beginPath(); g.moveTo(X(0), Y(m)); g.lineTo(X(Wm), Y(m)); g.stroke(); };
  const vline = (m, m0, m1) => { g.beginPath(); g.moveTo(X(m), Y(m0)); g.lineTo(X(m), Y(m1)); g.stroke(); };
  hline(6.7 - 1.98); hline(6.7 + 1.98); hline(0.76); hline(Lm - 0.76);
  vline(0.46, 0, Lm); vline(Wm - 0.46, 0, Lm);
  vline(Wm / 2, 0, 6.7 - 1.98); vline(Wm / 2, 6.7 + 1.98, Lm);
  g.strokeStyle = "rgba(70,227,255,.75)"; g.lineWidth = 1.4;
  hline(6.7);
}

function drawPlayerHeatmap(canvas, pid) {
  const c = courtOf();
  const H = c && c.homography;
  const pts = playerFootPoints(pid);
  const gx = H ? 18 : 30, gy = H ? 38 : 17;
  const grid = new Float32Array(gx * gy);
  const splat = (u, v) => {   // 3x3 soft splat into grid coords
    const cx = u * (gx - 1), cy = v * (gy - 1);
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const ix = Math.round(cx) + dx, iy = Math.round(cy) + dy;
      if (ix < 0 || iy < 0 || ix >= gx || iy >= gy) continue;
      const d2 = (ix - cx) ** 2 + (iy - cy) ** 2;
      grid[iy * gx + ix] += Math.exp(-d2 / 1.2);
    }
  };
  let used = 0;
  for (const p of pts) {
    if (H) {
      const m = courtProject(H, p.x, p.y);
      if (!m || m.u < -1.2 || m.u > 7.3 || m.v < -1.5 || m.v > 14.9) continue;
      splat(Math.min(1, Math.max(0, m.u / 6.1)), Math.min(1, Math.max(0, m.v / 13.4)));
    } else {
      splat(Math.min(1, Math.max(0, p.x)), Math.min(1, Math.max(0, p.y)));
    }
    used++;
  }
  const pad = 8;
  canvas.width = H ? 120 : 200;
  canvas.height = H ? 236 : 120;
  const g = canvas.getContext("2d");
  g.fillStyle = "#0d1015";
  g.fillRect(0, 0, canvas.width, canvas.height);
  const X = (m) => pad + m / 6.1 * (canvas.width - 2 * pad);
  const Y = (m) => pad + m / 13.4 * (canvas.height - 2 * pad);
  const mx = Math.max(1e-6, Math.max(...grid));
  const cw = (canvas.width - 2 * pad) / gx, ch = (canvas.height - 2 * pad) / gy;
  for (let iy = 0; iy < gy; iy++) for (let ix = 0; ix < gx; ix++) {
    const t = grid[iy * gx + ix] / mx;
    if (t < 0.04) continue;
    g.fillStyle = _heatColor(Math.min(1, t));
    g.beginPath();
    g.arc(pad + (ix + 0.5) * cw, pad + (iy + 0.5) * ch, Math.max(cw, ch) * 0.85, 0, Math.PI * 2);
    g.fill();
  }
  if (H) _drawCourtSchematic(g, X, Y);
  else { g.strokeStyle = "rgba(255,255,255,.35)"; g.strokeRect(pad, pad, canvas.width - 2 * pad, canvas.height - 2 * pad); }
  return used;
}

function renderHeatmaps(container) {
  if (!container) return;
  const ids = trackedPlayerIds();
  if (!ids.length) {
    container.innerHTML = `<div class="muted" style="font-size:11px;grid-column:1/-1">No player tracks on this reel yet.</div>`;
    return;
  }
  container.innerHTML = "";
  for (const pid of ids) {
    const cell = document.createElement("div");
    cell.className = "heatmap-cell";
    const canvas = document.createElement("canvas");
    const n = drawPlayerHeatmap(canvas, pid);
    const label = document.createElement("span");
    label.className = `heatmap-label hp${pid % 4}`;
    label.textContent = `P${pid + 1} · ${n} pts`;
    cell.appendChild(canvas);
    cell.appendChild(label);
    container.appendChild(cell);
  }
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
  // source, so Landscape always plays the proxy (and the timeline/overlays switch to
  // SOURCE time — see effectiveMode). Swap the source if needed, keeping position.
  const wantSrc = desiredVideoSrc();
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
  $("tpHint").textContent = landscape ? "landscape · original frame · source time" : "";
  if (studio.mode !== "compose") buildTimeline();   // lanes follow the effective mode
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

// Timeline scrubbing (TASK-021). The old handler was a plain click on #tl that
// divided by the WHOLE timeline rect — the 154px label column skewed every seek
// right, and there was no drag at all (dragging fell through to whatever was
// under the pointer). This scrubs on press+drag against the LANE rect, which is
// zoom- and scroll-correct, and captures the pointer so a fast drag can't be
// stolen by the canvas.
(function initTimelineScrub() {
  const board = $("tlBoard"), lane = $("tlLane");
  let scrubbing = false, moved = false, startX = 0, suppressClick = false;
  const seekTo = (clientX) => {
    const r = lane.getBoundingClientRect();   // the (possibly zoomed+scrolled) lane
    const v = $("stVideo");
    const d = v.duration || studio.dur;
    if (!d || r.width <= 0) return;
    const frac = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    v.currentTime = frac * d;
    updateOverlayPreview();
  };
  board.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    scrubbing = true; moved = false; startX = e.clientX;
    // Pressing empty lane/ruler seeks immediately; pressing a segment stays a
    // click (jump to rally start) unless the pointer actually drags.
    if (!e.target.closest(".seg") && !e.target.closest(".kf-mark")) { seekTo(e.clientX); moved = true; }
    board.setPointerCapture(e.pointerId);
  });
  board.addEventListener("pointermove", (e) => {
    if (!scrubbing) return;
    if (!moved && Math.abs(e.clientX - startX) < 4) return;
    if (!moved) suppressClick = true;   // a drag that started on a segment
    moved = true;
    seekTo(e.clientX);
  });
  const end = (e) => {
    if (!scrubbing) return;
    scrubbing = false;
    try { board.releasePointerCapture(e.pointerId); } catch { /* ignore */ }
  };
  board.addEventListener("pointerup", end);
  board.addEventListener("pointercancel", end);
  // After a drag that began on a segment, swallow the segment's click-to-seek.
  board.addEventListener("click", (e) => {
    if (suppressClick) { suppressClick = false; e.stopPropagation(); e.preventDefault(); }
  }, true);
})();

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
