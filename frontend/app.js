const consoleEl = document.getElementById("console");
const stateLabel = document.getElementById("stateLabel");
const hintEl = document.getElementById("hint");
const logEl = document.getElementById("log");
const coreEl = document.getElementById("core");
const ticksEl = document.getElementById("ticks");
const composer = document.getElementById("composer");
const inputEl = document.getElementById("input");
const startBtn = document.getElementById("startBtn");
const muteBtn = document.getElementById("muteBtn");
const benchBody = document.getElementById("benchBody");
const clearBench = document.getElementById("clearBench");

let history = [];
let recognition = null;
let micReady = false;
let muted = false;
// True while a request is in flight or Jarvis is speaking. Web Speech
// recognition is off during this window (it would transcribe Jarvis's own
// voice); the echo-cancelled VAD below is what listens for barge-in.
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

/* ---------- the meter ---------- */

const TICK_COUNT = 56;

(function buildTicks() {
  const ns = "http://www.w3.org/2000/svg";
  for (let i = 0; i < TICK_COUNT; i++) {
    const angle = (i / TICK_COUNT) * Math.PI * 2 - Math.PI / 2;
    const r1 = 72, r2 = 88;
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("class", "tick");
    rect.setAttribute("x", "98.8"); // half the 2.4 width, so ticks sit centred
    rect.setAttribute("y", String(100 - r2));
    rect.setAttribute("width", "2.4");
    rect.setAttribute("height", String(r2 - r1));
    rect.setAttribute("rx", "1.2");
    rect.setAttribute(
      "transform",
      `rotate(${(i / TICK_COUNT) * 360} 100 100)`
    );
    ticksEl.appendChild(rect);
    void angle;
  }
})();

const tickNodes = () => ticksEl.children;

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

  const lit = Math.round(smoothed * TICK_COUNT);
  const nodes = tickNodes();
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].classList.toggle("lit", i < lit);
  }
  coreEl.style.transform = `scale(${(1 + smoothed * 0.16).toFixed(3)})`;

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

/* ---------- bench (rich content) ---------- */

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

function showBench() {
  consoleEl.classList.add("has-bench");
}

function addCard(title, bodyNode) {
  const card = document.createElement("div");
  card.className = "card";
  if (title) {
    const h = document.createElement("h3");
    h.textContent = title;
    card.appendChild(h);
  }
  card.appendChild(bodyNode);
  benchBody.appendChild(card);
  showBench();
  benchBody.scrollTop = benchBody.scrollHeight;
}

function renderPanelItem(item) {
  if (item.kind === "action") {
    const div = document.createElement("div");
    div.className = `action action-${item.status || "läuft"}`;
    const label = document.createElement("strong");
    label.textContent = `${item.status || "läuft"}: ${item.action || "Aktion"}`;
    const detail = document.createElement("span");
    detail.textContent = item.detail || "";
    div.append(label, detail);
    addCard("Aktionsprotokoll", div);
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
    addCard(item.title || "Bild", img);
    return;
  }

  if (item.kind === "code") {
    const pre = document.createElement("pre");
    pre.textContent = item.text;
    addCard(item.title || "Code", pre);
    return;
  }

  if (item.kind === "markdown") {
    const div = document.createElement("div");
    div.className = "prose";
    div.innerHTML = miniMarkdown(item.text || "");
    addCard(item.title || "", div);
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
    addCard(item.title || "Dateien", wrap);
    return;
  }

  if (item.kind === "link") {
    const a = document.createElement("a");
    a.href = item.url;
    a.textContent = item.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    addCard(item.title || "Link", a);
  }
}

clearBench.addEventListener("click", () => {
  benchBody.innerHTML = "";
  consoleEl.classList.remove("has-bench");
});

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
  if (recognition) recognition.stop();

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
      history.push({ role: "user", content: text });
      history.push({ role: "assistant", content: fullText || parts.join(" ") });
      if (history.length > 20) history = history.slice(-20);
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
      startListening();
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

/* ---------- speech recognition ---------- */

const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;

function initRecognition() {
  if (!SpeechRecognitionImpl) {
    hintEl.textContent = "Spracherkennung braucht Chrome. Tippen geht überall.";
    return null;
  }
  const rec = new SpeechRecognitionImpl();
  rec.lang = "de-DE";
  rec.continuous = true;
  rec.interimResults = true;

  rec.onstart = () => { if (!busy) setState(restingState()); };

  rec.onresult = (event) => {
    let text = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      text += event.results[i][0].transcript;
    }
    text = text.trim();
    if (event.results[event.results.length - 1].isFinal && text) {
      handleUserMessage(text);
    }
  };

  rec.onerror = (event) => {
    if (event.error === "no-speech" || event.error === "aborted") return;
    if (event.error === "not-allowed") {
      micReady = false;
      settle();
      hintEl.textContent = "Mikrofon ist blockiert. In den Browser-Einstellungen freigeben.";
    }
  };

  // Chrome stops recognition on its own after silence, even with
  // continuous=true — restart it unless muted or mid-turn.
  rec.onend = () => {
    if (!muted && !busy && micReady) setTimeout(startListening, 250);
  };

  return rec;
}

function startListening() {
  if (!recognition || muted || busy || !micReady) return;
  try { recognition.start(); } catch (_) {}
}

/* ---------- barge-in (echo-cancelled VAD) ---------- */
//
// Web Speech ignores getUserMedia's echoCancellation constraint, so leaving
// it running while Jarvis speaks means it transcribes Jarvis and interrupts
// him in a loop. Instead we watch a separate, explicitly echo-cancelled
// stream: the OS subtracts Jarvis's own output from it, so a sustained
// level spike there means a real person is talking.

let vadAnalyser = null;
let vadData = null;
let vadNoiseFloor = 0.01;
let vadAbove = 0;

const VAD_CHECK_MS = 80;
const VAD_MULTIPLIER = 2.4;
const VAD_MIN_ABS = 0.025;
const VAD_SUSTAIN = 3; // ~240ms

function vadTick() {
  if (!vadAnalyser || muted) return;
  const rms = rmsFrom(vadAnalyser, vadData);

  if (!busy) {
    vadNoiseFloor = vadNoiseFloor * 0.98 + rms * 0.02;
    vadAbove = 0;
    return;
  }

  const threshold = Math.max(vadNoiseFloor * VAD_MULTIPLIER, VAD_MIN_ABS);
  vadAbove = rms > threshold ? vadAbove + 1 : 0;

  if (vadAbove >= VAD_SUSTAIN) {
    vadAbove = 0;
    interruptActiveTurn();
    startListening();
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
  muteBtn.textContent = muted ? "Mikro an" : "Mikro aus";
  muteBtn.classList.toggle("off", muted);
  if (muted) {
    if (recognition) recognition.stop();
  } else {
    startListening();
  }
  settle();
}

startBtn.addEventListener("click", async () => {
  if (micReady) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    micReady = true;
    startBtn.hidden = true;
    muteBtn.hidden = false;
    setupVad(stream);
    settle();
    startListening();
  } catch (_) {
    hintEl.textContent = "Mikrofon abgelehnt. Tippen funktioniert trotzdem.";
  }
});

muteBtn.addEventListener("click", () => setMuted(!muted));

document.addEventListener("keydown", (e) => {
  if (e.metaKey && e.shiftKey && e.key.toLowerCase() === "j") {
    e.preventDefault();
    if (muted) setMuted(false);
    else if (busy) { interruptActiveTurn(); startListening(); }
    else inputEl.focus();
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
      else if (busy) { interruptActiveTurn(); startListening(); }
    }
  };

  ws.onclose = () => setTimeout(connectWs, 2000);
}

recognition = initRecognition();
connectWs();
setState("idle");
