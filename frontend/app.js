const stateLabel = document.getElementById("stateLabel");
const hintEl = document.getElementById("hint");
const logEl = document.getElementById("log");
const composer = document.getElementById("composer");
const inputEl = document.getElementById("input");
const startBtn = document.getElementById("startBtn");
const muteBtn = document.getElementById("muteBtn");
const quitBtn = document.getElementById("quitBtn");

// The packaged desktop app opens a transparent, frameless, always-on-top
// window (see launcher/jarvis_launcher.py) so the orb floats directly over
// the desktop instead of sitting in an opaque app window — a plain browser
// tab has neither the transparency nor a window to quit, so all of this
// only activates once pywebview's own bridge object actually shows up.
// `pywebviewready` covers the normal case; the immediate check covers the
// (backend-dependent) case where the bridge is already there by the time
// this script runs.
function enableWidgetMode() {
  document.documentElement.classList.add("widget-mode");
  quitBtn.hidden = false;
}
if (window.pywebview) enableWidgetMode();
else window.addEventListener("pywebviewready", enableWidgetMode);

quitBtn.addEventListener("click", () => {
  if (window.pywebview) window.pywebview.api.quit();
});

// The old debug/chat sidebar (and its toggle button) is gone — a window
// sized for just the floating orb has no room for one, and the turn-by-turn
// record it showed now goes to backend/transcript.log instead. #log and
// #input still exist in the DOM (see index.html) and this code still
// writes to them below, but nothing ever reveals that container on screen.

let history = [];

// Once the rolling history window fills up, the oldest chunk used to just
// be dropped outright — mid-conversation amnesia with no trace left. Now
// it's folded into a short summary via the backend instead, so at least
// the gist of it (and any open task) survives past the cutoff.
const HISTORY_CAP = 20; // entries (10 turns) kept verbatim
const SUMMARIZE_CHUNK = 10; // oldest entries condensed into one summary line once the cap is hit

async function trimHistory() {
  if (history.length <= HISTORY_CAP) return;
  const stale = history.slice(0, history.length - HISTORY_CAP + SUMMARIZE_CHUNK);
  const rest = history.slice(stale.length);
  let summary = "";
  try {
    const r = await fetch("/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history: stale }),
    });
    if (r.ok) summary = ((await r.json()).summary || "").trim();
  } catch (_) {}
  history = summary
    ? [{ role: "system", content: `Zusammenfassung des bisherigen Gesprächs: ${summary}` }, ...rest]
    : rest; // summarizing failed — losing the old turns beats blocking the conversation on it
}
let micReady = false;
let micStream = null;
let muted = false;
// True while a request is in flight or Jarvis is speaking. Recording is
// off during this window (it would capture Jarvis's own voice); the
// echo-cancelled VAD below is what listens for barge-in instead.
let busy = false;
let fillerUrls = [];

let activeTurn = null;
let turnCounter = 0;

// Filler ("Warte mal...") only fires if nothing has come back by now. With
// sentence streaming that's rare — mostly during a tool round, where no
// text streams until the tool resolves.
const FILLER_DELAY_MS = 2200;

fetch("/fillers")
  .then((r) => r.json())
  .then((d) => { fillerUrls = d.fillers || []; })
  .catch(() => {});

/* ---------- state ---------- */

const HINTS = {
  idle: "Mikrofon freigeben, dann hört Jarvis dauerhaft zu.",
  listening: "Hört zu — sprich einfach, oder tippe.",
  thinking: "Arbeitet.",
  speaking: "Sprich dazwischen, um zu unterbrechen.",
  off: "Mikro ist aus. Tippen geht weiter.",
};

const LABELS = {
  idle: "bereit",
  listening: "hört zu",
  thinking: "denkt nach",
  speaking: "spricht",
  off: "mikro aus",
};

function setState(state) {
  document.body.dataset.state = state;
  stateLabel.textContent = LABELS[state] || state;
  hintEl.textContent = HINTS[state] || "";
}

function restingState() {
  if (!micReady) return "idle";
  return muted ? "off" : "listening";
}

function settle() {
  if (!busy) setState(restingState());
}

/* ---------- the orb: a voice-reactive 3D wireframe mesh ---------- */
//
// A UV-sphere wireframe, hand-rotated and perspective-projected on a plain
// 2D canvas — no WebGL/Three.js, so it stays dependency-free and works
// fully offline like the rest of Jarvis. At rest it's a calm, slowly
// turning sphere; audio level (voice in, Jarvis's own speech out) both
// speeds the spin and ripples each vertex outward, so it visibly "listens"
// and "speaks" instead of just pulsing a flat circle.

const orbCanvas = document.getElementById("orb");
const orbCtx = orbCanvas.getContext("2d");

// A rotating 3D wireframe orb — an icosphere (subdivided icosahedron), so
// every face is a genuine triangle that varies in size/orientation, unlike
// a lat/long grid where each cell is really a quad with a diagonal drawn
// in. Rendered at native (devicePixelRatio-aware) resolution — a flat,
// pixel-textured "cloud" version was tried and just looked blurry.
//
// One blue for every active state — a green/amber/red code barely showed
// up floating over an arbitrary desktop background, and needing to
// recognize a *hue* at a glance to know what's happening was the wrong
// idea for a widget you mostly see out of the corner of your eye anyway.
// States are told apart by motion instead: listening blinks (see
// LISTEN_PULSE below), thinking sweeps top-to-bottom, speaking ripples
// with the actual audio level. Grey is the one deliberate exception.
const ORB_COLORS = {
  idle: "#4a9eff",
  listening: "#4a9eff",
  thinking: "#4a9eff",
  speaking: "#4a9eff",
  off: "#9a9aa2",
};

const ORB_SWEEP_PERIOD = 1.6; // seconds per top-to-bottom pass while thinking
const ORB_SUBDIVISIONS = 3; // denser point cloud now that there's no wireframe to keep legible

function normalize3([x, y, z]) {
  const len = Math.hypot(x, y, z) || 1;
  return [x / len, y / len, z / len];
}

function buildIcosphere(subdivisions) {
  const PHI = (1 + Math.sqrt(5)) / 2;
  let verts = [
    [-1, PHI, 0], [1, PHI, 0], [-1, -PHI, 0], [1, -PHI, 0],
    [0, -1, PHI], [0, 1, PHI], [0, -1, -PHI], [0, 1, -PHI],
    [PHI, 0, -1], [PHI, 0, 1], [-PHI, 0, -1], [-PHI, 0, 1],
  ].map(normalize3);

  let faces = [
    [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
    [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
    [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
  ];

  for (let s = 0; s < subdivisions; s++) {
    const midCache = new Map();
    const midpoint = (a, b) => {
      const key = a < b ? `${a}_${b}` : `${b}_${a}`;
      if (midCache.has(key)) return midCache.get(key);
      const va = verts[a], vb = verts[b];
      const m = normalize3([(va[0] + vb[0]) / 2, (va[1] + vb[1]) / 2, (va[2] + vb[2]) / 2]);
      const idx = verts.length;
      verts.push(m);
      midCache.set(key, idx);
      return idx;
    };
    const nextFaces = [];
    for (const [a, b, c] of faces) {
      const ab = midpoint(a, b), bc = midpoint(b, c), ca = midpoint(c, a);
      nextFaces.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
    }
    faces = nextFaces;
  }

  return verts;
}

const orbVerts = buildIcosphere(ORB_SUBDIVISIONS).map(([x, y, z]) => ({ x, y, z }));

// Muted state: a smooth noise field of grey shades flows across the sphere
// instead of one flat color — evaluated in object-space (x,y,z before
// rotation) so it turns with the sphere.
function mutedNoiseShade(x, y, z, t) {
  const raw =
    Math.sin(x * 3.0 + t * 0.31) * 0.4 +
    Math.sin(y * 2.7 - t * 0.24) * 0.4 +
    Math.sin(z * 3.3 + t * 0.27) * 0.3 +
    Math.sin((x + y) * 1.9 - t * 0.19) * 0.3;
  const n = (raw / 1.4 + 1) / 2; // ~0..1
  const light = 40 + n * 28;
  return `hsl(230, 4%, ${light}%)`;
}

function resizeOrbCanvas() {
  const rect = orbCanvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  orbCanvas.width = Math.max(1, rect.width * dpr);
  orbCanvas.height = Math.max(1, rect.height * dpr);
  orbCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resizeOrbCanvas);
resizeOrbCanvas();
// The packaged desktop app's embedded webview (pywebview) doesn't always
// report a correct viewport size on the very first layout pass — the orb
// measured 0×0 and stayed blank until *something* fired a real resize
// event. A real browser tab never needed this, but re-measuring a couple
// of times shortly after load is a harmless no-op there and fixes it here.
window.addEventListener("load", resizeOrbCanvas);
setTimeout(resizeOrbCanvas, 300);

let orbSpin = 0;

function renderOrb(level, stateName) {
  const rect = orbCanvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  if (!w || !h) return;
  orbCtx.clearRect(0, 0, w, h);

  const cx = w / 2, cy = h / 2;
  const baseR = Math.min(w, h) * 0.4;
  const color = ORB_COLORS[stateName] || ORB_COLORS.idle;
  const t = Date.now() / 1000;
  const muted = stateName === "off";
  const thinking = stateName === "thinking";
  const listening = stateName === "listening";
  // Listening has no distinct colour anymore, so it needs its own motion to
  // still read as "actively listening" rather than idle — a slow breathing
  // blink, brightest right as it dips into shadow and back.
  const listenPulse = listening ? 0.55 + 0.45 * Math.sin(t * 2.4) : 1;

  // Keeps spinning at rest even while muted — muting only stops audio from
  // being recorded, it doesn't pause Jarvis (a reply already in flight
  // keeps going, typed messages still work), so freezing the orb here
  // used to visually claim otherwise. The grey colour below is still the
  // signal that the mic itself is off.
  orbSpin += 0.0032 + level * 0.014;
  const tilt = 0.32 + Math.sin(t / 4) * 0.06;
  const cosY = Math.cos(orbSpin), sinY = Math.sin(orbSpin);
  const cosX = Math.cos(tilt), sinX = Math.sin(tilt);

  let sweepT = -1;
  if (thinking) {
    // Triangle wave: top→bottom→top continuously, no jump back to start.
    const phase = (t % (ORB_SWEEP_PERIOD * 2)) / (ORB_SWEEP_PERIOD * 2);
    sweepT = phase < 0.5 ? phase * 2 : 2 - phase * 2;
  }

  const projected = orbVerts.map((v) => {
    const ripple = Math.sin(v.x * 4 + t * 1.6) * Math.cos(v.y * 4 - t * 1.1);
    let sweep = 0;
    if (thinking) {
      const rowT = (1 - v.y) / 2;
      sweep = Math.exp(-((Math.abs(rowT - sweepT) * 6) ** 2));
    }
    const r = 1 + level * 0.2 * ripple + sweep * 0.12;

    const x = v.x * r, y = v.y * r, z = v.z * r;
    const x1 = x * cosY + z * sinY;
    const z1 = -x * sinY + z * cosY;
    const y1 = y * cosX - z1 * sinX;
    const z2 = y * sinX + z1 * cosX;

    const perspective = 3.1 / (3.1 + z2);
    return {
      sx: cx + x1 * baseR * perspective, sy: cy + y1 * baseR * perspective,
      depth: z2, sweep, x: v.x, y: v.y, z: v.z,
    };
  });

  const dotR = Math.max(1, baseR * 0.018);
  for (const p of projected) {
    const depth = p.depth; // ~-1 front .. ~1 back
    orbCtx.globalAlpha =
      Math.min(1, 0.25 + Math.max(0, (1 - (depth + 1) / 2)) * 0.65 + p.sweep * 0.6) * listenPulse;
    orbCtx.fillStyle = muted ? mutedNoiseShade(p.x, p.y, p.z, t) : color;
    // Points closer to the viewer read as slightly bigger — a cheap depth cue.
    const size = dotR * (0.7 + Math.max(0, (1 - (depth + 1) / 2)) * 0.6);
    orbCtx.beginPath();
    orbCtx.arc(p.sx, p.sy, size, 0, Math.PI * 2);
    orbCtx.fill();
  }

  const glow = orbCtx.createRadialGradient(cx, cy, 0, cx, cy, baseR * 1.1);
  glow.addColorStop(0, `${color}33`);
  glow.addColorStop(1, `${color}00`);
  orbCtx.globalAlpha = (0.3 + level * 0.35) * listenPulse;
  orbCtx.fillStyle = glow;
  orbCtx.beginPath();
  orbCtx.arc(cx, cy, baseR * 1.1, 0, Math.PI * 2);
  orbCtx.fill();
  orbCtx.globalAlpha = 1;
}

/* ---------- sub-orb: shows a background job (e.g. build_project) is running ---------- */
//
// build_project answers immediately and keeps working on its own thread —
// without this, that work is invisible until it announces itself minutes
// later. Every such job is tracked here by id (from the "task" panel
// event) and rendered as a small second orb next to the main one for as
// long as at least one is active.

const backgroundTasks = new Map(); // id -> label
const subOrbCanvas = document.getElementById("subOrb");
const subOrbCtx = subOrbCanvas.getContext("2d");
const subOrbVerts = buildIcosphere(1).map(([x, y, z]) => ({ x, y, z }));

function resizeSubOrbCanvas() {
  const rect = subOrbCanvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  subOrbCanvas.width = Math.max(1, rect.width * dpr);
  subOrbCanvas.height = Math.max(1, rect.height * dpr);
  subOrbCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resizeSubOrbCanvas);

let subOrbSpin = 0;

function renderSubOrb() {
  const rect = subOrbCanvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  if (!w || !h) return;
  subOrbCtx.clearRect(0, 0, w, h);

  const cx = w / 2, cy = h / 2;
  const baseR = Math.min(w, h) * 0.42;
  const t = Date.now() / 1000;
  const color = ORB_COLORS.thinking;

  subOrbSpin += 0.045;
  const cosY = Math.cos(subOrbSpin), sinY = Math.sin(subOrbSpin);
  const cosX = Math.cos(0.5), sinX = Math.sin(0.5);
  const pulse = 0.85 + Math.sin(t * 3) * 0.15;

  const dotR = Math.max(1, baseR * 0.05);
  for (const v of subOrbVerts) {
    const x1 = v.x * cosY + v.z * sinY;
    const z1 = -v.x * sinY + v.z * cosY;
    const y1 = v.y * cosX - z1 * sinX;
    const z2 = v.y * sinX + z1 * cosX;
    const perspective = 3 / (3 + z2);
    const sx = cx + x1 * baseR * perspective;
    const sy = cy + y1 * baseR * perspective;
    subOrbCtx.globalAlpha = Math.min(1, 0.35 + Math.max(0, (1 - (z2 + 1) / 2)) * 0.65);
    subOrbCtx.fillStyle = color;
    subOrbCtx.beginPath();
    subOrbCtx.arc(sx, sy, dotR * pulse, 0, Math.PI * 2);
    subOrbCtx.fill();
  }

  const glow = subOrbCtx.createRadialGradient(cx, cy, 0, cx, cy, baseR * 1.2);
  glow.addColorStop(0, `${color}55`);
  glow.addColorStop(1, `${color}00`);
  subOrbCtx.globalAlpha = 0.5;
  subOrbCtx.fillStyle = glow;
  subOrbCtx.beginPath();
  subOrbCtx.arc(cx, cy, baseR * 1.2, 0, Math.PI * 2);
  subOrbCtx.fill();
  subOrbCtx.globalAlpha = 1;
}

function updateSubOrbVisibility() {
  const active = backgroundTasks.size > 0;
  subOrbCanvas.hidden = !active;
  subOrbCanvas.title = [...backgroundTasks.values()].join(", ");
  if (active) resizeSubOrbCanvas();
}

function taskStarted(id, label) {
  backgroundTasks.set(id, label || "Arbeitet im Hintergrund");
  updateSubOrbVisibility();
}

function taskEnded(id) {
  backgroundTasks.delete(id);
  updateSubOrbVisibility();
}

let outputAnalyser = null; // set while Jarvis speaks
let smoothed = 0;

function rmsFrom(analyser, buf) {
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

let outBuf = null;

function meterLoop() {
  let level = 0;

  if (outputAnalyser) {
    if (!outBuf || outBuf.length !== outputAnalyser.fftSize) {
      outBuf = new Uint8Array(outputAnalyser.fftSize);
    }
    level = Math.min(rmsFrom(outputAnalyser, outBuf) * 4.5, 1);
  } else if (vadAnalyser && !muted && !busy) {
    level = Math.min(Math.max(rmsFrom(vadAnalyser, vadData) - 0.006, 0) * 11, 1);
  }

  smoothed += (level - smoothed) * (level > smoothed ? 0.5 : 0.12);
  renderOrb(smoothed, document.body.dataset.state);
  if (backgroundTasks.size) renderSubOrb();

  requestAnimationFrame(meterLoop);
}
requestAnimationFrame(meterLoop);

/* ---------- conversation log ---------- */

function addTurn(who, text) {
  const el = document.createElement("div");
  el.className = `turn ${who}`;
  const label = document.createElement("div");
  label.className = "who";
  label.textContent = who === "you" ? "du" : "jarvis";
  const said = document.createElement("div");
  said.className = "said";
  said.textContent = text;
  el.append(label, said);
  logEl.appendChild(el);
  logEl.scrollTop = logEl.scrollHeight;
  return said;
}

/* ---------- inline tool output (Claude Code-style verbose log) ---------- */

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Deliberately tiny: panel text is model output, so it is escaped first and
// only a fixed set of inline shapes is re-enabled afterwards.
function miniMarkdown(src) {
  const lines = escapeHtml(src).split("\n");
  let html = "";
  let inList = false;

  const inline = (s) =>
    s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  for (const line of lines) {
    const t = line.trim();
    const bullet = t.match(/^[-*]\s+(.*)$/);
    const heading = t.match(/^(#{1,3})\s+(.*)$/);

    if (bullet) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(bullet[1])}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }

    if (heading) html += `<h3>${inline(heading[2])}</h3>`;
    else if (t) html += `<p>${inline(t)}</p>`;
  }
  if (inList) html += "</ul>";
  return html;
}

function addBlock(title, bodyNode) {
  const block = document.createElement("div");
  block.className = "block";
  if (title) {
    const h = document.createElement("div");
    h.className = "block-title";
    h.textContent = title;
    block.appendChild(h);
  }
  block.appendChild(bodyNode);
  logEl.appendChild(block);
  logEl.scrollTop = logEl.scrollHeight;
}

// Every "action" event for the same tool call shares item.id (first "läuft",
// then "erfolgreich"/"fehlgeschlagen") — tracked here so the second event
// updates the existing line instead of appending a duplicate.
const toolLines = new Map();

function toolArgSummary(target) {
  if (!target || typeof target !== "object") return "";
  const value = Object.values(target).find((v) => typeof v === "string" && v);
  if (!value) return "";
  return value.length > 60 ? value.slice(0, 57) + "…" : value;
}

function renderAction(item) {
  let line = toolLines.get(item.id);
  if (!line) {
    line = document.createElement("div");
    line.className = "tool";
    line.innerHTML = `<div class="call"><span class="bullet">●</span><span class="name"></span></div><div class="result" hidden></div>`;
    logEl.appendChild(line);
    toolLines.set(item.id, line);
  }

  const status = item.status || "läuft";
  line.className = `tool ${status === "erfolgreich" ? "ok" : status === "fehlgeschlagen" ? "fail" : "running"}`;
  const arg = toolArgSummary(item.target);
  line.querySelector(".name").textContent = arg ? `${item.action}(${arg})` : item.action || "Aktion";

  const resultEl = line.querySelector(".result");
  if (item.detail) {
    resultEl.textContent = item.detail.length > 500 ? item.detail.slice(0, 500) + "…" : item.detail;
    resultEl.hidden = false;
  }
  logEl.scrollTop = logEl.scrollHeight;
}

function renderPanelItem(item) {
  if (item.kind === "action") {
    renderAction(item);
    return;
  }

  if (item.kind === "task") {
    if (item.status === "started") taskStarted(item.id, item.label);
    else taskEnded(item.id);
    return;
  }

  if (item.kind === "notify") {
    speakNotification(item.text);
    addTurn("jarvis", item.text);
    return;
  }

  if (item.kind === "image") {
    const img = document.createElement("img");
    img.src = item.data_url;
    img.alt = item.title || "Screenshot";
    addBlock(item.title || "Bild", img);
    return;
  }

  if (item.kind === "code") {
    const pre = document.createElement("pre");
    pre.textContent = item.text;
    addBlock(item.title || "Code", pre);
    return;
  }

  if (item.kind === "markdown") {
    const div = document.createElement("div");
    div.className = "prose";
    div.innerHTML = miniMarkdown(item.text || "");
    addBlock(item.title || "", div);
    return;
  }

  if (item.kind === "files") {
    const wrap = document.createElement("div");
    const ul = document.createElement("ul");
    ul.className = "filelist";
    (item.files || []).forEach((f) => {
      const li = document.createElement("li");
      li.textContent = f;
      ul.appendChild(li);
    });
    const p = document.createElement("div");
    p.className = "path";
    p.textContent = item.path || "";
    wrap.append(ul, p);
    addBlock(item.title || "Dateien", wrap);
    return;
  }

  if (item.kind === "link") {
    const a = document.createElement("a");
    a.href = item.url;
    a.textContent = item.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    addBlock(item.title || "Link", a);
  }
}

/* ---------- audio ---------- */

let audioCtx = null;

function ensureCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function base64ToBlob(base64, mime) {
  const bytes = atob(base64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

function playFiller(turn) {
  if (!fillerUrls.length || turn.aborted) return;
  const audio = new Audio(fillerUrls[Math.floor(Math.random() * fillerUrls.length)]);
  turn.fillerAudio = audio;
  audio.play().catch(() => {});
}

function stopFiller(turn) {
  if (turn.fillerAudio) { turn.fillerAudio.pause(); turn.fillerAudio = null; }
  clearTimeout(turn.fillerTimer);
}

function playClip(blob, turn) {
  const audio = new Audio(URL.createObjectURL(blob));
  if (turn) turn.audio = audio;

  const ctx = ensureCtx();
  const src = ctx.createMediaElementSource(audio);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser);
  analyser.connect(ctx.destination);
  outputAnalyser = analyser;

  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      if (outputAnalyser === analyser) outputAnalyser = null;
      resolve();
    };
    audio.onended = finish;
    audio.onpause = finish;   // also fires when a barge-in pauses it
    audio.play().catch(finish);
  });
}

// Background jobs (a finished build) announce themselves out of band.
async function speakNotification(text) {
  try {
    const r = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reply: text }),
    });
    if (!r.ok) return;
    const wasBusy = busy;
    if (!wasBusy) setState("speaking");
    await playClip(await r.blob(), null);
    if (!wasBusy) settle();
  } catch (_) {}
}

/* ---------- turns ---------- */

function interruptActiveTurn() {
  if (!activeTurn) return;
  const turn = activeTurn;
  turn.aborted = true;
  stopFiller(turn);
  if (turn.audio) turn.audio.pause();
  outputAnalyser = null;
  activeTurn = null;
  busy = false;
  settle();
}

async function handleUserMessage(text) {
  if (!text) return;

  if (activeTurn) interruptActiveTurn();
  cancelRecording();

  addTurn("you", text);

  const turn = { id: ++turnCounter, aborted: false, audio: null, fillerAudio: null, fillerTimer: null };
  activeTurn = turn;
  busy = true;
  setState("thinking");

  turn.fillerTimer = setTimeout(() => playFiller(turn), FILLER_DELAY_MS);

  const said = addTurn("jarvis", "");
  said.parentElement.classList.add("pending");
  const parts = [];
  let fullText = "";

  try {
    const resp = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history }),
    });
    if (turn.aborted) return;
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(`Server antwortete mit ${resp.status}${detail ? `: ${detail.slice(0, 200)}` : ""}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { value, done } = await reader.read();
      if (turn.aborted) { reader.cancel(); return; }
      if (done) break;

      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        const evt = JSON.parse(line);

        if (evt.type === "sentence") {
          stopFiller(turn);
          setState("speaking");
          parts.push(evt.text);
          said.textContent = parts.join(" ");
          logEl.scrollTop = logEl.scrollHeight;
          if (turn.aborted) return;
          if (evt.audio) await playClip(base64ToBlob(evt.audio, evt.mime || "audio/mpeg"), turn);
        } else if (evt.type === "done") {
          fullText = evt.full_text;
        }
      }
    }

    if (!turn.aborted) {
      // A stream that ends without ever sending a sentence event is a
      // backend bug, not silence — surface it instead of leaving the turn
      // looking like Jarvis never heard the question at all.
      if (!parts.length) said.textContent = "Keine Antwort erhalten. Bitte nochmal versuchen.";
      history.push({ role: "user", content: text });
      history.push({ role: "assistant", content: fullText || parts.join(" ") });
      await trimHistory();
    }
  } catch (err) {
    if (!turn.aborted) {
      console.error(err);
      said.textContent = "Verbindung zum Server unterbrochen.";
    }
  } finally {
    said.parentElement.classList.remove("pending");
    if (!said.textContent) said.parentElement.remove();
    stopFiller(turn);
    if (activeTurn === turn) {
      activeTurn = null;
      busy = false;
      settle();
    }
  }
}

/* ---------- text input ---------- */

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  handleUserMessage(text);
});

/* ---------- local speech-to-text (record on VAD, transcribe via Whisper) ---------- */
//
// Chrome's Web Speech API was the previous mechanism here, but its German
// recognition was unreliable enough to be a running complaint. This
// records raw audio locally and posts it to the backend's /stt endpoint (a
// local Whisper model — see backend/stt.py) once the same echo-cancelled
// VAD used for barge-in below decides the person has stopped talking.
// Nothing about voice input leaves the machine.
//
// Raw PCM via a ScriptProcessor, not MediaRecorder — a WebM/Opus stream
// only carries its container header in the very first chunk it ever emits.
// A continuously-running MediaRecorder feeding a rolling pre-roll buffer
// (the previous approach here) eventually rotates that header chunk out,
// leaving every later utterance a headerless, undecodable fragment — that
// silently broke every single transcription. Building our own WAV file
// from raw samples sidesteps the problem: every utterance is a complete,
// self-contained file, pre-roll included.

let pcmNode = null;
let pcmSampleRate = 48000;
let pcmRing = []; // rolling pre-roll buffer, Float32Array chunks
let utterancePCM = null; // non-null while actively capturing an utterance
let utteranceStartedAt = 0;
let silenceStreak = 0;

const PCM_BUFFER_SIZE = 4096;
// Generous on purpose: onset-cutting persisted at 700ms because actual
// detection latency (noise floor still adapting, a soft-spoken first
// syllable, echo-cancellation's own ramp-in) can exceed a small window —
// this is cheap (a couple seconds of Float32 samples) insurance against
// that, not a precisely-tuned value.
const PREROLL_MS = 1500;
// ~960ms used to end the utterance, which cut people off mid-sentence during
// completely normal speech (a thinking pause, searching for a word, a breath
// before the next clause) — raised to ~2.2s of real silence.
const RECORD_SILENCE_SUSTAIN = 28; // ~28 * VAD_CHECK_MS ≈ 2240ms of silence ends the utterance
const RECORD_MIN_MS = 300; // ignore accidental blips shorter than this

function startContinuousRecording() {
  if (pcmNode || !micStream) return;
  const ctx = ensureCtx();
  pcmSampleRate = ctx.sampleRate;
  const source = ctx.createMediaStreamSource(micStream);
  pcmNode = ctx.createScriptProcessor(PCM_BUFFER_SIZE, 1, 1);
  const preRollChunks = Math.ceil((PREROLL_MS / 1000) * pcmSampleRate / PCM_BUFFER_SIZE);

  pcmNode.onaudioprocess = (e) => {
    const data = new Float32Array(e.inputBuffer.getChannelData(0));
    if (utterancePCM) {
      utterancePCM.push(data);
    } else {
      pcmRing.push(data);
      if (pcmRing.length > preRollChunks) pcmRing.shift();
    }
  };
  // ScriptProcessor only fires once connected through to a destination —
  // route through a silent gain so nothing is actually audible.
  const silentGain = ctx.createGain();
  silentGain.gain.value = 0;
  source.connect(pcmNode);
  pcmNode.connect(silentGain);
  silentGain.connect(ctx.destination);
}

// Marks the start of an utterance, seeded with whatever's already in the
// rolling pre-roll buffer so the trigger delay never costs real audio.
function beginUtterance() {
  if (utterancePCM) return;
  utterancePCM = pcmRing.slice();
  utteranceStartedAt = Date.now();
}

// Ends the utterance and sends it for transcription.
function stopRecording() {
  if (!utterancePCM) return;
  const chunks = utterancePCM;
  const startedAt = utteranceStartedAt;
  utterancePCM = null;
  pcmRing = [];
  sendUtterance(chunks, startedAt);
}

// Ends the utterance and discards it — used when something else (typed
// text, a barge-in) supersedes whatever was being captured.
function cancelRecording() {
  if (!utterancePCM) return;
  utterancePCM = null;
  pcmRing = [];
}

const isRecording = () => utterancePCM !== null;

function concatFloat32(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) { out.set(c, offset); offset += c.length; }
  return out;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return new Blob([view], { type: "audio/wav" });
}

async function sendUtterance(chunks, startedAt) {
  if (!chunks.length || Date.now() - startedAt < RECORD_MIN_MS) return;
  const samples = concatFloat32(chunks);
  if (samples.length < pcmSampleRate * 0.2) return; // shorter than ~200ms
  const blob = encodeWav(samples, pcmSampleRate);

  try {
    const form = new FormData();
    form.append("audio", blob, "speech.wav");
    const resp = await fetch("/stt", { method: "POST", body: form });
    if (!resp.ok) return;
    const data = await resp.json();
    const text = (data.text || "").trim();
    if (text) handleUserMessage(text);
  } catch (err) {
    console.error(err);
  }
}

/* ---------- VAD: drives recording; voice barge-in is off ---------- */
//
// This used to double as barge-in detection too, relying on the mic
// stream's own echoCancellation to subtract Jarvis's speaker output back
// out of the signal — so a level spike while Jarvis was talking reliably
// meant a real person interrupting, not feedback. echoCancellation is off
// now (see startBtn's handler — macOS's echo-cancelled "voice processing"
// audio path was locking the mic exclusively for every other app on the
// machine the whole time Jarvis was running), so that assumption no longer
// holds: without it, Jarvis's own voice bleeding into a built-in mic reads
// as a sustained level spike too, and would trigger this on every single
// reply instead of on real interruptions. Voice barge-in is only ever
// checked during "listening" below now; interrupting a reply in progress
// still works, just via the hotkey (Cmd/Ctrl+Shift+J) instead of talking
// over it.

let vadAnalyser = null;
let vadData = null;
let vadNoiseFloor = 0.01;
let vadAbove = 0;

const VAD_CHECK_MS = 80;
const VAD_MULTIPLIER = 2.4;
const VAD_MIN_ABS = 0.025;
const VAD_SUSTAIN = 2; // ~160ms — kept short since the pre-roll buffer, not this, is what protects the onset

function vadTick() {
  if (!vadAnalyser || muted) return;
  const rms = rmsFrom(vadAnalyser, vadData);
  const state = document.body.dataset.state;

  // No voice-triggered barge-in while Jarvis is talking or thinking
  // anymore — without echoCancellation, Jarvis's own voice bleeding into
  // the mic would read as a level spike on every reply (see the comment
  // above). Use the hotkey to interrupt instead.
  if (state === "speaking") return;

  if (state !== "listening") {
    vadNoiseFloor = vadNoiseFloor * 0.98 + rms * 0.02;
    vadAbove = 0;
    if (isRecording()) cancelRecording();
    return;
  }

  // Idle listening: use the same threshold logic to detect speech start,
  // then track sustained silence to know when the utterance is over. The
  // VAD_SUSTAIN wait here is just a false-positive guard, not an audio-loss
  // window — beginUtterance() below seeds itself from the pre-roll buffer,
  // so whatever was said during this confirmation delay is not lost.
  const threshold = Math.max(vadNoiseFloor * VAD_MULTIPLIER, VAD_MIN_ABS);
  if (!isRecording()) {
    if (rms > threshold) {
      vadAbove++;
      if (vadAbove >= VAD_SUSTAIN) {
        vadAbove = 0;
        beginUtterance();
      }
    } else {
      vadAbove = 0;
      vadNoiseFloor = vadNoiseFloor * 0.98 + rms * 0.02;
    }
  } else if (rms > threshold) {
    silenceStreak = 0;
  } else {
    silenceStreak++;
    if (silenceStreak >= RECORD_SILENCE_SUSTAIN) stopRecording();
  }
}

function setupVad(stream) {
  const ctx = ensureCtx();
  const source = ctx.createMediaStreamSource(stream);
  vadAnalyser = ctx.createAnalyser();
  vadAnalyser.fftSize = 512;
  source.connect(vadAnalyser);
  vadData = new Uint8Array(vadAnalyser.fftSize);
  setInterval(vadTick, VAD_CHECK_MS);
}

/* ---------- controls ---------- */

function setMuted(next) {
  muted = next;
  muteBtn.title = muted ? "Mikro aktivieren" : "Mikro stummschalten";
  muteBtn.classList.toggle("off", muted);
  if (muted) cancelRecording();
  settle();
}

startBtn.addEventListener("click", async () => {
  if (micReady) return;
  try {
    // echoCancellation off on purpose (see the VAD comment below) — with
    // built-in speakers + mic, macOS engages a "voice processing" audio
    // path for echo-cancelled input that claims the mic exclusively, so no
    // other app can use it at all while Jarvis is running. Trading away
    // voice barge-in for that was a deliberate call, not an oversight.
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true },
    });
    micReady = true;
    micStream = stream;
    startBtn.hidden = true;
    muteBtn.hidden = false;
    setupVad(stream);
    startContinuousRecording();
    settle();
  } catch (_) {
    hintEl.textContent = "Mikrofon abgelehnt. Tippen funktioniert trotzdem.";
  }
});

muteBtn.addEventListener("click", () => setMuted(!muted));

// Cmd+Shift+J on macOS, Ctrl+Shift+J on Windows — matching
// launcher/hotkey_listener.py's own platform check for the equivalent
// global hotkey. e.metaKey is the Windows key on Windows, essentially
// never pressed together with Shift+J, so without this branch the
// in-page shortcut simply never fired there at all.
const IS_MAC = /Mac|iPod|iPhone|iPad/.test(navigator.platform);

document.addEventListener("keydown", (e) => {
  const modifierPressed = IS_MAC ? e.metaKey : e.ctrlKey;
  if (modifierPressed && e.shiftKey && e.key.toLowerCase() === "j") {
    e.preventDefault();
    if (muted) setMuted(false);
    else if (busy) interruptActiveTurn();
  }
});

/* ---------- server channel ---------- */

function connectWs() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws`);

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch (_) { return; }

    if (msg.type === "panel") {
      renderPanelItem(msg.item);
    } else if (msg.type === "wake") {
      if (!micReady) return;
      if (muted) setMuted(false);
      else if (busy) interruptActiveTurn();
    }
  };

  ws.onclose = () => setTimeout(connectWs, 2000);
}

connectWs();
setState("idle");
