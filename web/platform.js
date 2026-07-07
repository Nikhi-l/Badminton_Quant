/* Baddy Schools app shell (TASK-026 P0): role-routed panels, vanilla JS. */
const $ = (id) => document.getElementById(id);
const esc = (s = "") => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (ts) => ts ? new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—";
const fmtPct = (v) => v == null ? "—" : `${Math.round(Number(v) * 100)}%`;

let ME = null;
let route = { view: null, arg: null };

async function jfetch(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch { /* keep status */ }
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

async function boot() {
  try {
    ME = await jfetch("/api/auth/me");
  } catch {
    location.href = "/login.html";
    return;
  }
  $("topSchool").textContent = ME.school_name || "";
  $("userChip").innerHTML = `${esc(ME.name)}<span class="role">${esc(ME.role || "")}</span>`;
  $("logoutBtn").onclick = async () => { await fetch("/api/auth/logout", { method: "POST" }); location.href = "/login.html"; };
  buildNav();
  go(ME.role === "student" ? "profile" : "overview", ME.role === "student" ? ME.id : null);
}

const NAVS = {
  admin:   [["overview", "▦ Overview"], ["sessions", "🎞 Sessions"], ["students", "🧑‍🎓 Students"]],
  coach:   [["overview", "▦ Overview"], ["sessions", "🎞 Sessions"], ["students", "🧑‍🎓 Students"]],
  student: [["profile", "🧑‍🎓 My progress"]],
};

function buildNav() {
  const items = NAVS[ME.role] || NAVS.student;
  $("appNav").innerHTML = items.map(([v, label]) =>
    `<button data-nav="${v}">${label}</button>`).join("");
  $("appNav").querySelectorAll("[data-nav]").forEach(b =>
    b.onclick = () => go(b.dataset.nav, b.dataset.nav === "profile" ? ME.id : null));
}

function go(view, arg = null) {
  route = { view, arg };
  $("appNav").querySelectorAll("[data-nav]").forEach(b =>
    b.classList.toggle("active", b.dataset.nav === view));
  $("appMain").innerHTML = `<div class="app-loading">Loading…</div>`;
  ({ overview: renderOverview, sessions: renderSessions, students: renderStudents,
     profile: renderProfile }[view] || renderOverview)(arg).catch(err => {
    $("appMain").innerHTML = `<div class="empty-note">⚠ ${esc(err.message)}</div>`;
  });
}

/* ---------- coach/admin: overview ---------- */
async function renderOverview() {
  const o = await jfetch("/api/school/overview");
  const codes = [];
  if (o.join_codes.student) codes.push(["Student join code", o.join_codes.student, "share with players"]);
  if (o.join_codes.coach) codes.push(["Coach join code", o.join_codes.coach, "admins only — share with staff"]);
  $("appMain").innerHTML = `
    <div class="pg-title">${esc(o.school.name)}</div>
    <div class="pg-sub">${o.students.length} students · ${o.coaches.length} coaching staff · ${o.jobs.length} sessions</div>
    <div class="pcard">
      <h3>Join codes <span class="muted">new members sign up at /login.html → “Join with code”</span></h3>
      <div class="code-row">${codes.map(([label, code, hint]) => `
        <div class="code-pill"><div><b>${esc(code)}</b><br><span>${esc(label)} · ${esc(hint)}</span></div>
        <button class="code-copy" data-copy="${esc(code)}">copy</button></div>`).join("")}
      </div>
    </div>
    <div class="pcard">
      <h3>Recent sessions <span class="muted">upload from the <a href="/" style="color:var(--cyan)">reel generator</a> while signed in — they land here</span></h3>
      ${sessionsTable(o, 6)}
    </div>
    <div class="pcard">
      <h3>Students</h3>
      ${studentsTable(o.students)}
    </div>`;
  bindOverview(o);
}

function studentsTable(students) {
  if (!students.length) return `<div class="empty-note">No students yet — share the student join code.</div>`;
  return `<table class="ptable"><tr><th>Name</th><th>Username</th><th>Joined</th><th></th></tr>
    ${students.map(s => `<tr class="rowlink" data-student="${esc(s.id)}">
      <td>${esc(s.name)}</td><td class="muted">@${esc(s.username)}</td>
      <td class="muted">${fmtDate(s.created_at)}</td><td style="text-align:right;color:var(--cyan)">profile →</td></tr>`).join("")}
  </table>`;
}

function sessionsTable(o, limit = 100) {
  const jobs = o.jobs.slice(0, limit);
  if (!jobs.length) return `<div class="empty-note">No sessions yet.</div>`;
  const studentOpts = o.students.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
  return `<table class="ptable"><tr><th></th><th>Session</th><th>Status</th><th>Assigned</th><th>Assign</th></tr>
    ${jobs.map(j => `<tr>
      <td>${j.thumb ? `<img class="sess-thumb" src="${esc(j.thumb)}" alt="">` : ""}</td>
      <td><b>${esc(j.filename || j.id)}</b><br><span class="muted" style="font-size:11px">${fmtDate(j.created_at)}${j.duration ? ` · ${Math.round(j.duration)}s reel` : ""}${j.n_rallies_used ? ` · ${j.n_rallies_used} rallies` : ""}</span></td>
      <td><span class="badge ${esc(j.status)}">${esc(j.status)}</span></td>
      <td>${(j.assignees || []).map(a => `<span class="assignee-chip">${esc(a.name)}${a.player_id != null ? ` · P${a.player_id + 1}` : ""}<button title="unassign" data-unassign="${esc(j.id)}|${esc(a.id)}">✕</button></span>`).join("") || `<span class="muted">—</span>`}</td>
      <td>${j.status === "done" && o.students.length ? `
        <div class="assign-row">
          <select data-as-student="${esc(j.id)}">${studentOpts}</select>
          <select data-as-player="${esc(j.id)}"><option value="">whole video</option><option value="0">P1 (near)</option><option value="1">P2 (far)</option></select>
          <button class="btn btn-small" data-assign="${esc(j.id)}">Assign</button>
        </div>` : ""}</td>
    </tr>`).join("")}
  </table>`;
}

function bindOverview(o) {
  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => {
    await navigator.clipboard.writeText(b.dataset.copy);
    b.textContent = "✓ copied";
    setTimeout(() => { b.textContent = "copy"; }, 1400);
  });
  document.querySelectorAll("[data-student]").forEach(r => r.onclick = () => go("profile", r.dataset.student));
  document.querySelectorAll("[data-assign]").forEach(b => b.onclick = async () => {
    const jobId = b.dataset.assign;
    const student = document.querySelector(`[data-as-student="${jobId}"]`).value;
    const player = document.querySelector(`[data-as-player="${jobId}"]`).value;
    b.disabled = true;
    try {
      await jfetch(`/api/jobs/${jobId}/assign`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: student, player_id: player === "" ? null : Number(player) }),
      });
      go(route.view, route.arg);
    } catch (e) { alert(e.message); b.disabled = false; }
  });
  document.querySelectorAll("[data-unassign]").forEach(b => b.onclick = async () => {
    const [jobId, sid] = b.dataset.unassign.split("|");
    await jfetch(`/api/jobs/${jobId}/assign/${sid}`, { method: "DELETE" });
    go(route.view, route.arg);
  });
}

async function renderSessions() {
  const o = await jfetch("/api/school/overview");
  $("appMain").innerHTML = `
    <div class="pg-title">Sessions</div>
    <div class="pg-sub">Every video uploaded by your school, newest first. Assign a session to a student (pin P1/P2 for per-player metrics).</div>
    <div class="pcard">${sessionsTable(o)}</div>`;
  bindOverview(o);
}

async function renderStudents() {
  const o = await jfetch("/api/school/overview");
  $("appMain").innerHTML = `
    <div class="pg-title">Students</div>
    <div class="pg-sub">Click a student for their full progress panel.</div>
    <div class="pcard">${studentsTable(o.students)}</div>`;
  bindOverview(o);
}

/* ---------- student profile ---------- */
function spark(values, w = 120, h = 30) {
  const vals = values.filter(v => v != null);
  if (vals.length < 2) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const span = (mx - mn) || 1;
  const pts = values.map((v, i) => v == null ? null :
    `${(i / (values.length - 1) * (w - 4) + 2).toFixed(1)},${(h - 3 - (v - mn) / span * (h - 8)).toFixed(1)}`)
    .filter(Boolean);
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <polyline points="${pts.join(" ")}" fill="none" stroke="var(--lime)" stroke-width="1.6" stroke-linejoin="round"/>
    <circle cx="${pts[pts.length - 1].split(",")[0]}" cy="${pts[pts.length - 1].split(",")[1]}" r="2.4" fill="var(--cyan)"/>
  </svg>`;
}

async function renderProfile(studentId) {
  const p = await jfetch(`/api/students/${studentId || ME.id}/profile`);
  const S = p.sessions;
  const totalRallies = S.reduce((s, x) => s + (x.n_rallies || 0), 0);
  const longest = Math.max(0, ...S.map(x => x.longest_rally || 0));
  const distance = S.reduce((s, x) => s + ((x.movement || {}).distance_m || 0), 0);
  const initials = p.student.name.split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
  $("appMain").innerHTML = `
    <div class="profile-head">
      <div class="avatar">${esc(initials)}</div>
      <div>
        <div class="pg-title">${esc(p.student.name)}</div>
        <div class="pg-sub" style="margin:0">@${esc(p.student.username)} · ${esc(p.school.name)}</div>
      </div>
    </div>
    <div class="stat-grid">
      <div class="stat"><b>${S.length}</b><span>sessions</span>${spark(S.map(x => x.n_rallies))}</div>
      <div class="stat"><b>${totalRallies}</b><span>rallies played</span>${spark(S.map(x => x.longest_rally))}</div>
      <div class="stat"><b>${longest ? longest + "s" : "—"}</b><span>longest rally</span></div>
      <div class="stat"><b>${distance ? Math.round(distance) + "m" : "—"}</b><span>court distance covered</span>${spark(S.map(x => (x.movement || {}).distance_m))}</div>
      <div class="stat"><b>${S.length ? fmtPct(S[S.length - 1].quality.pose) : "—"}</b><span>latest pose signal</span>${spark(S.map(x => x.quality.pose))}</div>
    </div>
    ${S.length ? S.slice().reverse().map(sessCard).join("")
      : `<div class="pcard"><div class="empty-note">No sessions assigned yet${ME.role === "student" ? " — your coach will assign your match videos here." : " — assign one from Sessions."}</div></div>`}`;
}

function sessCard(s) {
  return `<div class="sess-card">
    <div class="sess-media">
      <video src="${esc(s.video)}" poster="${esc(s.thumb)}" controls playsinline preload="none"></video>
    </div>
    <div class="sess-body">
      <h4>${esc(s.filename || s.job_id)}</h4>
      <div class="sess-date">${fmtDate(s.date)}${s.player_id != null ? ` · tracked as P${s.player_id + 1}` : ""}</div>
      <div class="sess-metrics">
        <span><b>${s.n_rallies}</b> rallies</span>
        <span>longest <b>${s.longest_rally}s</b></span>
        ${(s.movement || {}).distance_m != null ? `<span>moved <b>${s.movement.distance_m}m</b></span>` : ""}
        ${(s.movement || {}).coverage_pct ? `<span>court coverage <b>${s.movement.coverage_pct}%</b></span>` : ""}
        <span>shuttle signal <b>${fmtPct((s.quality || {}).shuttle)}</b></span>
      </div>
      <div class="rally-chips">
        ${(s.rallies || []).slice(0, 8).map(r => `<span class="rally-chip">R${r.i} · ${Math.round(r.dur || 0)}s${r.note ? " · " + esc(String(r.note).slice(0, 34)) : ""}</span>`).join("")}
      </div>
      ${s.coach ? `<div class="coach-box">
        <b>AI coach:</b> ${esc(s.coach.headline || "")}
        ${(s.coach.strengths || []).length ? `<div class="cb-row"><span>Good:</span> ${s.coach.strengths.map(esc).join(" · ")}</div>` : ""}
        ${(s.coach.work_on || []).length ? `<div class="cb-row"><span>Work on:</span> ${s.coach.work_on.map(esc).join(" · ")}</div>` : ""}
      </div>` : ""}
    </div>
  </div>`;
}

boot();
