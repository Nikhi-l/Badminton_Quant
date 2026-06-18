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
    const mark = st === "done" ? "✓" : icon;
    return `<li class="${st}"><span class="dot">${mark}</span>${label}</li>`;
  }).join("");
}

function poll(id) {
  clearInterval(pollTimer);
  const tick = async () => {
    let job;
    try { job = await (await fetch(`/api/jobs/${id}`)).json(); } catch { return; }
    renderStages(job.stages || []);
    $("jobMsg").textContent = job.message || "";
    if (job.status === "done") {
      clearInterval(pollTimer);
      showResult(job);
    } else if (job.status === "error") {
      clearInterval(pollTimer);
      failJob(`Something broke: ${job.error}`);
    }
  };
  tick();
  pollTimer = setInterval(tick, 2500);
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

/* ---------- studio: editor-style rally timeline ---------- */
const studio = { item: null, mode: "reel", raf: 0 };
const fmtT = (s) => { s = Math.max(0, s || 0); return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`; };

function openStudio(item) {
  studio.item = item;
  $("studio").hidden = false;
  $("studioFile").textContent = [item.filename, item.sport].filter(Boolean).join(" · ");
  $("studioDownload").href = item.video;
  document.body.style.overflow = "hidden";
  initEdit();
  renderCoachbar(item);
  $("editbar").hidden = true;
  $("editToggle").classList.remove("on");
  setStudioMode("reel");
  cancelAnimationFrame(studio.raf);
  studioTick();
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
    ? "click a block to jump to that rally"
    : hasAll
      ? "every rally the AI found in your video — dashed blocks didn't make the reel"
      : "showing reel rallies only (older job)";
}

function buildTimeline() {
  const item = studio.item;
  const lane = $("tlLane"), ruler = $("tlRuler");
  lane.innerHTML = ""; ruler.innerHTML = "";
  let dur, segs;
  if (studio.mode === "reel") {
    dur = item.duration || 1;
    let acc = 0;
    segs = (item.rallies || []).map((r, i) => {
      const signal = rallyVisionText(r.vision);
      const seg = { t0: acc, t1: acc + (r.clip_dur || r.dur || 0),
        label: `RALLY ${i + 1}`,
        sub: `${Math.round(r.dur || r.clip_dur || 0)}s${r.note ? " · " + r.note : ""}${r.trimmed ? " · trimmed" : ""}${signal ? " · " + signal : ""}`,
        skip: false,
        vision: r.vision };
      acc = seg.t1;
      return seg;
    });
  } else {
    dur = item.source_duration || 1;
    const list = (item.all_rallies && item.all_rallies.length)
      ? item.all_rallies
      : (item.rallies || []).map(r => ({ ...r, used: true }));
    segs = list.map((r, i) => ({ t0: r.start || 0, t1: r.end || (r.start || 0) + (r.dur || 0),
      label: `R${i + 1} · ${Math.round(r.dur || 0)}s`, sub: r.note || "", skip: !r.used }));
  }
  studio.dur = dur;
  const step = dur > 200 ? 30 : dur > 90 ? 15 : dur > 40 ? 10 : 5;
  for (let t = 0; t <= dur; t += step) {
    const el = document.createElement("div");
    el.className = "tick";
    el.style.left = `${t / dur * 100}%`;
    el.textContent = fmtT(t);
    ruler.appendChild(el);
  }
  segs.forEach(s => {
    const el = document.createElement("div");
    el.className = "seg" + (s.skip ? " skip" : "") +
      (s.vision && s.vision.status === "ok" ? " vision-ok" : "") +
      (s.vision && s.vision.mask_enabled ? " mask-on" : "");
    el.style.left = `${s.t0 / dur * 100}%`;
    el.style.width = `${Math.max((s.t1 - s.t0) / dur * 100, 1.4)}%`;
    el.innerHTML = `<b>${esc(s.label)}</b><span>${esc(s.sub)}</span>`;
    if (s.vision) el.title = rallyVisionTitle(s.vision);
    el.onclick = (e) => {
      e.stopPropagation();
      const v = $("stVideo");
      v.currentTime = s.t0 + 0.05;
      v.play().catch(() => {});
    };
    lane.appendChild(el);
  });
}

function studioTick() {
  if ($("studio").hidden) return;
  const v = $("stVideo");
  const dur = v.duration || studio.dur || 1;
  $("tlHead").style.left = `${Math.min(v.currentTime / dur, 1) * 100}%`;
  $("tpTime").textContent = `${fmtT(v.currentTime)} / ${fmtT(dur)}`;
  $("tpPlay").textContent = v.paused ? "▶" : "⏸";
  studio.raf = requestAnimationFrame(studioTick);
}

/* ---------- studio edit mode: pick / reorder / mirror / rebuild ---------- */
function initEdit() {
  // Edit against the full pool of rendered rallies; mark which are currently in.
  const pool = studio.item.rally_pool || studio.item.rallies || [];
  const current = new Set((studio.item.remix && studio.item.remix.order) || pool.map((_, i) => i + 1));
  const inOrder = (studio.item.remix && studio.item.remix.order) || [];
  const seq = [...inOrder, ...pool.map((_, i) => i + 1).filter(i => !current.has(i) || !inOrder.includes(i))]
    .filter((v, i, a) => a.indexOf(v) === i);
  studio.edit = seq.map(idx => ({ idx, on: current.has(idx), r: pool[idx - 1] })).filter(e => e.r);
  $("mirrorChk").checked = !!(studio.item.remix && studio.item.remix.mirror);
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
    chip.querySelector("b").onclick = () => { e.on = !e.on; renderEditChips(); };
    chip.querySelectorAll(".mv").forEach(mv => mv.onclick = (ev) => {
      ev.stopPropagation();
      const to = pos + parseInt(mv.dataset.mv, 10);
      if (to < 0 || to >= studio.edit.length) return;
      [studio.edit[pos], studio.edit[to]] = [studio.edit[to], studio.edit[pos]];
      renderEditChips();
    });
    wrap.appendChild(chip);
  });
}

async function rebuildReel() {
  const order = studio.edit.filter(e => e.on).map(e => e.idx);
  if (!order.length) { $("editMsg").textContent = "keep at least one rally"; return; }
  const mirror = $("mirrorChk").checked;
  $("rebuildBtn").disabled = true;
  $("editMsg").textContent = mirror ? "re-rendering mirrored clips…" : "re-stitching…";
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
          ? "rebuilt ✓ (overlays re-rendered)"
          : "rebuilt ✓ — fast rebuilds keep original badge numbers; mirror rebuild renumbers";
        $("stVideo").classList.remove("stVideo-mirror");
        initEdit();
        renderCoachbar(studio.item);
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

$("editToggle").onclick = () => {
  const bar = $("editbar");
  bar.hidden = !bar.hidden;
  $("editToggle").classList.toggle("on", !bar.hidden);
};
$("rebuildBtn").onclick = rebuildReel;
$("mirrorChk").onchange = () => {
  $("stVideo").classList.toggle("stVideo-mirror", $("mirrorChk").checked);
  $("editMsg").textContent = $("mirrorChk").checked
    ? "mirror preview on — rebuild to bake it in (overlays re-rendered)" : "";
};
$("speedToggle").querySelectorAll("button").forEach(b => b.onclick = () => {
  $("speedToggle").querySelectorAll("button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $("stVideo").playbackRate = parseFloat(b.dataset.rate);
});
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
