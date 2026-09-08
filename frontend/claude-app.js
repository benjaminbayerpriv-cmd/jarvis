// JARVIS — funktionale Schicht, die über dem eingefrorenen claude.ai-SSR-DOM
// liegt. Der Snapshot (frontend/claude.html) ist inert: seine Anthropic-Skripte
// sind in serve_index() gestrippt, React läuft nie. Seine CSS-Tokens/Fonts
// (--font-anthropic-sans, --text-primary/…, Terracotta #d97757) behalten wir;
// das tote, kollabierte DOM verdecken wir mit einer EIGENEN, funktionalen
// UI-Schicht (#jsApp): Sidebar mit echten Chats + Einstellungen, Willkommens-
// Hero, Composer -> /chat/stream (NDJSON + TTS), Modell-Auswahl, Datei-Upload,
// Diktat- und Sprachmodus (3D-Punktnetz-Kugel, Canvas2D, kein three.js).
// Bewusst OHNE Claude-Logo und ohne Chat/Code-Umschalter.
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);

  // ------------------------------------------------ claude-design-tokens
  // Um die "Cloud-Optik" 1:1 zu treffen, greife ich auf die Claude-Tokens des
  // Snapshots zurück; fallen sie aus, stehen hier die bekannten Werte.
  const C = {
    bg: 'var(--ground, #141311)',
    bgSoft: 'var(--bg-soft, #1b1a17)',
    bgHover: 'var(--df-hover, #26241f)',
    text: 'var(--text-primary, #efede8)',
    textSoft: 'var(--text-secondary, #b0aba0)',
    textDim: 'var(--text-tertiary, #6b665b)',
    border: 'var(--border-strong, #34312b)',
    accent: '#d97757',                 // Claude-Terracotta
    font: 'var(--font-anthropic-sans, system-ui, sans-serif)',
    serif: 'var(--font-anthropic-serif, Georgia, serif)',
  };

  // ------------------------------------------------ claude-icons (offline)
  // Die echte Claude-Ikonografie aus dem eingefrorenen Snapshot: das Wortbild
  // ("Claude") und der terracotta-farbene Spark-Generator. Beide sind inline
  // SVG und damit voll offline. Die Rund-Badge-SVGs unter vendor/ap/ sind nur
  // dekorative Deckblätter; die Werkzeug-Glyphen (Mic/Pfeil/Plus/Toggle) zeichne
  // ich im Claude-Linienstil (stroke=currentColor, runde Kappen, 24-er Box).
  // Eigene Ikonografie im flachen Linienstil (stroke=currentColor, runde Kappen,
  // 24er-Box) — bewusst KEIN Claude-Wortbild. Die Marke ist der kleine Terracotta-
  // Orb (Arc-Reactor) mit umlaufendem Ring; er passt zum 3D-Sprachmodus-Orb.
  const ICONS = {
    logo: '<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="5.4" fill="currentColor"/><circle cx="16" cy="16" r="10.6" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".45" stroke-dasharray="3.4 3.2"/><circle cx="25.4" cy="11.4" r="1.4" fill="currentColor" opacity=".8"/></svg>',
    spark: '<svg viewBox="0 0 100 100" fill="currentColor" aria-hidden="true"><path d="m19.6 66.5 19.7-11 .3-1-.3-.5h-1l-3.3-.2-11.2-.3L14 53l-9.5-.5-2.4-.5L0 49l.2-1.5 2-1.3 2.9.2 6.3.5 9.5.6 6.9.4L38 49.1h1.6l.2-.7-.5-.4-.4-.4L29 41l-10.6-7-5.6-4.1-3-2-1.5-2-.6-4.2 2.7-3 3.7.3.9.2 3.7 2.9 8 6.1L37 36l1.5 1.2.6-.4.1-.3-.7-1.1L33 25l-6-10.4-2.7-4.3-.7-2.6c-.3-1-.4-2-.4-3l3-4.2L28 0l4.2.6L33.8 2l2.6 6 4.1 9.3L47 29.9l2 3.8 1 3.4.3 1h.7v-.5l.5-7.2 1-8.7 1-11.2.3-3.2 1.6-3.8 3-2L61 2.6l2 2.9-.3 1.8-1.1 7.7L59 27.1l-1.5 8.2h.9l1-1.1 4.1-5.4 6.9-8.6 3-3.5L77 13l2.3-1.8h4.3l3.1 4.7-1.4 4.9-4.4 5.6-3.7 4.7-5.3 7.1-3.2 5.7.3.4h.7l12-2.6 6.4-1.1 7.6-1.3 3.5 1.6.4 1.6-1.4 3.4-8.2 2-9.6 2-14.3 3.3-.2.1.2.3 6.4.6 2.8.2h6.8l12.6 1 3.3 2 1.9 2.7-.3 2-5.1 2.6-6.8-1.6-16-3.8-5.4-1.3h-.8v.4l4.6 4.5 8.3 7.5L89 80.1l.5 2.4-1.3 2-1.4-.2-9.2-7-3.6-3-8-6.8h-.5v.7l1.8 2.7 9.8 14.7.5 4.5-.7 1.4-2.6 1-2.7-.6-5.8-8-6-9-4.7-8.2-.5.4-2.9 30.2-1.3 1.5-3 1.2-2.5-2-1.4-3 1.4-6.2 1.6-8 1.3-6.4 1.2-7.9.7-2.6v-.2H49L43 72l-9 12.3-7.2 7.6-1.7.7-3-1.5.3-2.8L24 86l10-12.8 6-7.9 4-4.6-.1-.5h-.3L17.2 77.4l-4.7.6-2-2 .2-3 1-1 8-5.5Z"></path></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    sidebar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><line x1="9.5" y1="4" x2="9.5" y2="20"/><line x1="13.5" y1="8" x2="17.5" y2="8"/><line x1="13.5" y1="12" x2="17.5" y2="12"/><line x1="13.5" y1="16" x2="16.5" y2="16"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V6"/><path d="M5.5 12.5 12 6l6.5 6.5"/></svg>',
    upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.4 12.6A9 9 0 1 1 11.4 3"/><path d="M12 3v9"/><path d="m8 6 4-3 4 3"/></svg>',
    dictation: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M12 2v12"/><path d="M9 10.5c0-.8.6-1.3 1.3-1.4l1.7-.1 1.7.1c.7.1 1.3.6 1.3 1.4"/><path d="M7 15.6l5-2.6 5 2.6"/><path d="M12 14v6"/><path d="M9 20h6"/></svg>',
    speech: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 9v6"/><path d="M8 6v12"/><path d="M12 3v18"/><path d="M16 6v12"/><path d="M20 9v6"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v2.2M12 19.8V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.2M19.8 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6"/></svg>',
  };

  // ---------------------------------------------------------------- helfer
  function base64ToBlob(base64, mime) {
    const bytes = atob(base64);
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  let audioCtx = null;
  function ensureCtx() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
    return audioCtx;
  }

  function playClip(blob) {
    const audio = new Audio(URL.createObjectURL(blob));
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
        clearTimeout(timer);
        if (outputAnalyser === analyser) outputAnalyser = null;
        resolve();
      };
      const timer = setTimeout(finish, 4000);
      audio.onended = finish;
      audio.onerror = finish;
      audio.play().then(() => {
        if (!audio.ended) { /* läuft */ }
      }).catch(finish);
    });
  }

  function encodeWav(samples, sampleRate) {
    sampleRate = sampleRate || 16000;
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const ws = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
    ws(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); ws(8, 'WAVE'); ws(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); ws(36, 'data');
    view.setUint32(40, samples.length * 2, true);
    let off = 44;
    for (let i = 0; i < samples.length; i++, off += 2) view.setInt16(off, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
    return new Blob([buffer], { type: 'audio/wav' });
  }

  // ------------------------------------------------------------------ zustand
  let activeMode = 'chat';      // "chat" | "code"
  let history = [];             // OpenAI-Format [{role, content}]
  let turnCounter = 0;
  let busy = false;

  // UI-Anker (in buildUi() gesetzt)
  let uiEl = null, sidebarEl = null, chatListEl = null, chatRootEl = null, threadEl = null;
  let composerInput = null, sendBtn = null, speechBtn = null, noteBtn = null, uploadBtn = null, settingsBtn = null;
  let composerTray = null, modelEl = null, modelMenuEl = null, fileInput = null;

  // Sprachmodus + VAD + Diktat
  let speechMode = false, dictating = false, micReady = false, micStream = null, muted = false;
  let pcmNode = null, pcmSampleRate = 0, pcmRing = [], utterancePCM = null, utteranceStartedAt = 0;
  let silenceStreak = 0, vadAnalyser = null, vadData = null;
  let vadNoiseFloor = 0.01;
  let outputAnalyser = null;

  // 3D-Punktnetz-Kugel
  let orbCtx = null, orbCanvas = null, orbSpin = 0, orbLevel = 0, orbRaf = 0, orbVisible = false;
  let orbPoints = [];
  const ORB_COLOR = C.accent;
  const ORB_LAT = 26, ORB_LON = 40;

  // Persisted so reloading the page continues the same conversation
  // instead of silently starting a new, empty one every time.
  let currentConversationId = localStorage.getItem('jarvis_conversation_id') || null;
  function ensureConversationId() {
    if (!currentConversationId) {
      currentConversationId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
      localStorage.setItem('jarvis_conversation_id', currentConversationId);
    }
    return currentConversationId;
  }

  function buildSpherePoints() {
    const pts = [];
    for (let la = 0; la <= ORB_LAT; la++) {
      const theta = (la / ORB_LAT) * Math.PI;
      const y = Math.cos(theta);
      const r = Math.sin(theta);
      for (let lo = 0; lo < ORB_LON; lo++) {
        const phi = (lo / ORB_LON) * Math.PI * 2;
        pts.push({ x: r * Math.cos(phi), y, z: r * Math.sin(phi) });
      }
    }
    return pts;
  }

  function drawOrb(now) {
    const cw = orbCanvas.clientWidth, ch = orbCanvas.clientHeight;
    if (cw < 4 || ch < 4) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (orbCanvas.width !== cw * dpr || orbCanvas.height !== ch * dpr) { orbCanvas.width = cw * dpr; orbCanvas.height = ch * dpr; }
    orbCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    orbCtx.clearRect(0, 0, cw, ch);
    const cx = cw / 2, cy = ch / 2;
    const base = Math.min(cw, ch) * 0.34 * (1 + orbLevel * 0.32);
    const yaw = orbSpin, pitch = -0.34 + Math.sin(now * 0.0005) * 0.04;
    const cosY = Math.cos(yaw), sinY = Math.sin(yaw);
    const cosP = Math.cos(pitch), sinP = Math.sin(pitch);
    const f = 3.2;
    const thickness = cw * 0.05;
    const proj = [];
    for (let i = 0; i < orbPoints.length; i++) {
      const p = orbPoints[i];
      const x1 = p.x * cosY - p.z * sinY;
      const z1 = p.x * sinY + p.z * cosY;
      const y2 = p.y * cosP - z1 * sinP;
      const z2 = p.y * sinP + z1 * cosP;
      const wob = 1 + Math.sin((p.x + p.y) * 5 + now * 0.0018) * 0.03 * (0.4 + orbLevel);
      proj.push({ x: cx + x1 * base * wob, y: cy + y2 * base * wob, z: z2, persp: f / (f + z2) });
    }
    proj.sort((a, b) => a.z - b.z);
    for (const pt of proj) {
      const size = Math.max(0.6, thickness * pt.persp * 0.5);
      const a = Math.max(0.12, Math.min(1, 0.28 + (1 - pt.persp) * 0.9));
      orbCtx.fillStyle = ORB_COLOR;
      orbCtx.globalAlpha = a;
      orbCtx.beginPath();
      orbCtx.arc(pt.x, pt.y, size, 0, Math.PI * 2);
      orbCtx.fill();
    }
    orbCtx.globalAlpha = 1;
  }

  function orbLoop(now) {
    if (!orbVisible) return;
    orbSpin = orbSpin * 0.9 + (now * 0.0002) * 0.1;
    if (outputAnalyser && vadData) {
      // Pegel aus dem Ausgangs-Analyser (Wiedergabe) switscht zum Input, falls still
      let sum = 0;
      outputAnalyser.getByteTimeDomainData(vadData);
      for (let i = 0; i < vadData.length; i++) { const v = (vadData[i] - 128) / 128; sum += v * v; }
      orbLevel = Math.min(1, Math.sqrt(sum / vadData.length) * 4);
    } else {
      orbLevel = Math.max(0, orbLevel * 0.95 - 0.005);
    }
    drawOrb(now);
    orbRaf = requestAnimationFrame(orbLoop);
  }

  function showOrb() {
    orbVisible = true;
    if (!orbRaf) orbRaf = requestAnimationFrame(orbLoop);
  }
  function hideOrb() {
    orbVisible = false;
  }

  // --------------------------------------------------------- UI: buildUi()
  // Ersetzt das kollabierte/leere Snapshot-DOM durch eine schlanke, funktionale
  // Claude-UI. Bewusst KEIN Klonen von Snapshot-Elementen — deren React-Maße
  // kollabieren zu height:0.
  function buildUi() {
    uiEl = document.createElement('div');
    uiEl.id = 'jsApp';
    uiEl.style.cssText = `position:fixed;inset:0;z-index:30;display:flex;background:${C.bg};color:${C.text};font-family:${C.font};`;
    uiEl.innerHTML = `
      <button class="js-side-toggle" title="Sidebar ein/aus" style="position:absolute;top:18px;left:16px;z-index:31;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;">${ICONS.sidebar}</button>
      <aside class="js-sidebar" style="width:308px;flex:0 0 308px;height:100%;display:flex;flex-direction:column;background:${C.bgSoft};border-right:1px solid ${C.border};">
        <div class="js-sidebar-top" style="padding:20px 12px 6px;display:flex;flex-direction:column;gap:14px;">
          <div class="js-brand" style="display:flex;align-items:center;gap:9px;padding:0 6px 0 44px;">
            <span style="width:26px;height:26px;border-radius:50%;background:${C.accent};color:#fff;display:inline-flex;align-items:center;justify-content:center;box-shadow:0 0 0 4px rgba(217,119,87,.15);">${ICONS.logo}</span>
            <span style="font-size:15px;font-weight:600;letter-spacing:.04em;color:${C.text};">JARVIS</span>
          </div>
          <button class="js-new" style="display:flex;align-items:center;gap:8px;padding:9px 12px;background:${C.bgHover};border:1px solid ${C.border};border-radius:11px;color:${C.text};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s;">${ICONS.plus}<span>Neue Unterhaltung</span></button>
          <div class="js-chats-label" style="padding:2px 8px 4px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Unterhaltungen</div>
        </div>
        <div class="js-chats" style="flex:0 0 1px;flex:1 1 auto;overflow-y:auto;padding:2px 8px 10px;"></div>
        <div class="js-settings-row" style="padding:10px 12px;border-top:1px solid ${C.border};display:flex;align-items:center;gap:8px;">
          <button class="js-settings" title="Einstellungen" style="width:32px;height:32px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.gear}</button>
          <span class="js-account" style="width:22px;height:22px;border-radius:50%;background:linear-gradient(135deg,${C.accent},#b45a3c);display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;">C</span>
          <div style="flex:1;min-width:0;display:flex;flex-direction:column;">
            <span style="font-size:13px;color:${C.text};line-height:1.2;">Chef · Pro</span>
            <span class="js-status" style="font-size:11px;color:${C.textDim};line-height:1.3;">Online</span>
          </div>
        </div>
      </aside>
      <div class="js-main" style="flex:1;height:100%;display:flex;flex-direction:column;min-width:0;position:relative;">
        <div class="js-welcome" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 32px;gap:18px;">
          <div class="js-welcome-mark" style="width:52px;height:52px;border-radius:50%;background:${C.accent};color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 0 0 8px rgba(217,119,87,.12), 0 12px 40px rgba(217,119,87,.25);">${ICONS.logo}</div>
          <div>
            <h1 class="js-welcome-title" style="font-size:30px;font-weight:600;letter-spacing:-.01em;color:${C.text};margin:0 0 8px;">Willkommen zurück.</h1>
            <p class="js-welcome-sub" style="font-size:14px;color:${C.textSoft};margin:0;max-width:440px;line-height:1.55;">Wie kann ich dir heute helfen? Sprich, diktiere oder schreib einfach los.</p>
          </div>
        </div>
        <div class="js-thread" style="flex:1;overflow-y:auto;scrollbar-width:thin;position:relative;"></div>
      </div>
      <div class="js-composer" style="position:absolute;left:308px;right:0;bottom:0;padding:0 24px 22px;background:linear-gradient(transparent,${C.bg} 55%);">
        <div style="max-width:760px;margin:0 auto;">
          <div class="js-inputbox" style="background:${C.bgSoft};border:1px solid ${C.border};border-radius:18px;box-shadow:0 10px 34px rgba(0,0,0,.38);">
            <div class="js-editor" contenteditable="true" data-placeholder="Beschreibe eine Aufgabe oder stelle eine Frage" style="min-height:60px;max-height:200px;overflow-y:auto;padding:16px;color:${C.text};font-size:15px;line-height:1.5;outline:none;white-space:pre-wrap;word-break:break-word;"></div>
            <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 10px;">
              <button class="js-upload" title="Dateien hochladen" style="width:34px;height:34px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.upload}</button>
              <button class="js-note" title="Diktieren" style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:9px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;transition:background .15s;">${ICONS.dictation}<span>Diktieren</span></button>
              <div style="flex:1;"></div>
              <button class="js-model" title="Modell wechseln" style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;transition:background .15s;">
                <span class="js-model-label">Modell…</span>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
              </button>
              <button class="js-speech" title="Sprachmodus" style="width:34px;height:34px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.speech}</button>
              <button class="js-send" title="Senden" style="width:34px;height:34px;border-radius:50%;background:${C.accent};border:none;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.send}</button>
            </div>
          </div>
          <div class="js-modelmenu" style="display:none;margin-top:8px;background:${C.bgSoft};border:1px solid ${C.border};border-radius:12px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,.4);"></div>
        </div>
      </div>
    `;
    document.body.appendChild(uiEl);
    // Die tote Snapshot-DOM verstecken, aber die CSS-Tokens auf :root behalten.
    document.body.classList.add('js-app-active');

    sidebarEl = $('.js-sidebar', uiEl);
    chatListEl = $('.js-chats', uiEl);
    chatRootEl = $('.js-main', uiEl);
    threadEl = $('.js-thread', uiEl);
    composerTray = $('.js-composer', uiEl);
    composerInput = $('.js-editor', uiEl);
    sendBtn = $('.js-send', uiEl);
    speechBtn = $('.js-speech', uiEl);
    noteBtn = $('.js-note', uiEl);
    uploadBtn = $('.js-upload', uiEl);
    settingsBtn = $('.js-settings', uiEl);
    modelEl = $('.js-model-label', uiEl);
    modelMenuEl = $('.js-modelmenu', uiEl);

    injectSkinCss();
    wireUi();
  }

  function injectSkinCss() {
    if (document.getElementById('jsAppCss')) return;
    const s = document.createElement('style');
    s.id = 'jsAppCss';
    s.textContent = `
      body.js-app-active > :not(#jsApp):not(#jarvisOrb):not(script):not(style) { display:none !important; }
      body.js-app-active { overflow:hidden; }
      .js-sidebar button:focus-visible, .js-main button:focus-visible { outline:2px solid ${C.accent}; outline-offset:2px; }
      .js-editor:empty::before, .js-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-editor:focus::before { opacity:.7; }
      .js-brand svg, .js-side-toggle svg, .js-new svg, .js-upload svg, .js-note svg, .js-speech svg, .js-settings svg { width:16px; height:16px; display:block; }
      .js-upload svg, .js-note svg, .js-speech svg, .js-settings svg { width:18px; height:18px; }
      .js-send svg { width:18px; height:18px; display:block; }
      .js-welcome-mark svg { width:26px; height:26px; display:block; }
      .js-side-toggle:hover, .js-new:hover, .js-upload:hover, .js-note:hover, .js-model:hover, .js-settings:hover { background:${C.bgHover}; color:${C.text}; }
      .js-note.on { color:${C.accent} !important; background:rgba(217,119,87,.12) !important; }
      .js-note.on svg { animation:js-note-pulse 1.4s ease-in-out infinite; }
      @keyframes js-note-pulse { 0%,100% { opacity:1; } 50% { opacity:.45; } }
      .js-speech.on { background:${C.accent} !important; border-color:${C.accent} !important; color:#fff !important; }
      .js-speech.on svg { animation:js-speech-pulse 1.3s ease-in-out infinite; }
      @keyframes js-speech-pulse { 0%,100% { transform:scale(1); } 50% { transform:scale(1.14); } }
      .js-chat-item { display:flex; align-items:center; gap:9px; padding:7px 10px; border-radius:10px; cursor:pointer; font-size:13px; color:${C.textSoft}; }
      .js-chat-item:hover { background:${C.bgHover}; color:${C.text}; }
      .js-chat-item.selected { background:${C.bgHover}; color:${C.text}; }
      .js-chat-item .js-ico { flex:0 0 auto; display:inline-flex; width:15px; height:15px; color:${C.accent}; }
      .js-chat-item .js-ico svg { width:15px; height:15px; display:block; }
      .js-chat-item .js-txt { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .js-turn { max-width:760px; margin:0 auto 26px; font-family:${C.font}; line-height:1.6; }
      .js-you .js-text { color:${C.textSoft}; }
      .js-jarvis .js-text { color:${C.text}; white-space:pre-wrap; word-break:break-word; }
      .js-you::before { content:"Du"; display:block; font-size:11px; letter-spacing:.2em; text-transform:uppercase; color:${C.accent}; margin-bottom:4px; }
      .js-jarvis::before { content:"Jarvis"; display:block; font-size:11px; letter-spacing:.2em; text-transform:uppercase; color:${C.textDim}; margin-bottom:4px; }
      .js-jarvis .js-text.thinking { color:${C.textDim}; font-style:italic; }
      .js-thread { padding:64px 24px 180px; }
      .js-main .js-welcome { opacity:1; transition:opacity .25s ease; }
      .js-main.has-content .js-welcome { opacity:0; pointer-events:none; }
    `;
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------- wire UI
  function setMode(mode) {
    activeMode = mode;
    if (modelEl) modelEl.textContent = 'Modell…';
  }

  // Der Willkommens-Hero rutscht weg, sobald die Unterhaltung Inhalt hat.
  function syncWelcome() {
    if (!threadEl) return;
    chatRootEl.classList.toggle('has-content', threadEl.children.length > 0);
  }

  // Sidebar list — backed by the real per-conversation store (backend/
  // conversations.py), not the flat /transcript debug log: each entry is
  // one actual conversation with a short, model-generated title (see
  // llm_client.generate_title), not a raw truncated first message.
  async function loadConversationList() {
    if (!chatListEl) return;
    let list = [];
    try {
      const r = await fetch('/conversations');
      const j = await r.json();
      list = j.conversations || [];
    } catch (e) { list = []; }
    chatListEl.innerHTML = '';
    if (!list.length) {
      const d = document.createElement('div');
      d.className = 'js-chat-item';
      d.style.color = C.textDim;
      d.style.cursor = 'default';
      d.textContent = 'Noch keine Gespräche';
      chatListEl.appendChild(d);
      return;
    }
    for (const conv of list) {
      const el = document.createElement('div');
      el.className = 'js-chat-item';
      if (conv.id === currentConversationId) el.classList.add('selected');
      const ico = document.createElement('span');
      ico.className = 'js-ico';
      ico.innerHTML = ICONS.spark;
      const txt = document.createElement('span');
      txt.className = 'js-txt';
      txt.textContent = conv.title || 'Neuer Chat';
      txt.title = txt.textContent;
      el.appendChild(ico);
      el.appendChild(txt);
      el.addEventListener('click', () => openConversation(conv.id));
      chatListEl.appendChild(el);
    }
  }

  async function openConversation(id) {
    if (id === currentConversationId) return;
    currentConversationId = id;
    localStorage.setItem('jarvis_conversation_id', id);
    let turns = [];
    try {
      const r = await fetch(`/conversations/${encodeURIComponent(id)}`);
      const j = await r.json();
      turns = j.turns || [];
    } catch (e) { turns = []; }
    showThread();
    const el = ensureThread();
    el.innerHTML = '';
    history = [];
    for (const t of turns) {
      addThreadTurn(t.role === 'you' ? 'you' : 'jarvis', t.text);
      history.push({ role: t.role === 'you' ? 'user' : 'assistant', content: t.text });
    }
    if (history.length > 40) history = history.slice(-40);
    if (el.children.length) el.scrollTop = el.scrollHeight;
    loadConversationList();
  }

  function startNewConversation() {
    currentConversationId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
    localStorage.setItem('jarvis_conversation_id', currentConversationId);
    history = [];
    clearThreadUI();
    loadConversationList();
  }

  function wireUi() {
    // Neu
    $('.js-new', uiEl).addEventListener('click', startNewConversation);
    // Senden
    if (sendBtn) sendBtn.addEventListener('click', (e) => { e.preventDefault(); sendFromComposer(); });
    // Composer: Enter sendet; Placeholder-Klasse beim Tippen entfernen.
    if (composerInput) {
      composerInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendFromComposer(); }
      });
      composerInput.addEventListener('input', () => {
        composerInput.classList.toggle('is-empty', composerInput.innerText.trim().length === 0);
        if (sendBtn) sendBtn.disabled = composerInput.innerText.trim().length === 0;
      });
    }
    // Sprachmodus (Vollbild-Orb, spricht Antworten)
    if (speechBtn) speechBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); speechMode ? exitSpeech() : enterSpeech(); });
    // Diktat (schreibt ins Eingabefeld)
    if (noteBtn) noteBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); setDictating(!dictating); });
    // Dateien hochladen
    if (uploadBtn) uploadBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); if (fileInput) fileInput.click(); });
    if (settingsBtn) settingsBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); window.alert('Einstellungen folgen in Kürze.'); });
    // Modell-Auswahl
    if (modelEl) modelEl.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleModelMenu(); });
    window.addEventListener('click', () => { if (modelMenuEl) modelMenuEl.style.display = 'none'; });

    // Verstecktes Datei-Eingabefeld; Inhalt wird dem Thread als Anhang gemeldet.
    fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.style.display = 'none';
    fileInput.addEventListener('change', () => {
      const names = fileInput.files ? [...fileInput.files].map((f) => f.name) : [];
      fileInput.value = '';
      if (!names.length) return;
      const base = (composerInput ? composerInput.innerText : '').trim();
      const attach = '📎 ' + names.join(', ');
      if (composerInput) { composerInput.innerText = base ? base + '\n' + attach : attach; composerInput.classList.remove('is-empty'); if (sendBtn) sendBtn.disabled = false; }
    });
    document.body.appendChild(fileInput);

    // Restore the last-open conversation's turns on load, then the sidebar
    // list — opening the app should reveal a chat that's already there,
    // not an empty thread until something is clicked.
    (async () => {
      if (currentConversationId) {
        try {
          const r = await fetch(`/conversations/${encodeURIComponent(currentConversationId)}`);
          const j = await r.json();
          const turns = j.turns || [];
          const el = ensureThread();
          for (const t of turns) {
            addThreadTurn(t.role === 'you' ? 'you' : 'jarvis', t.text);
            history.push({ role: t.role === 'you' ? 'user' : 'assistant', content: t.text });
          }
          if (el.children.length) el.scrollTop = el.scrollHeight;
        } catch (e) { /* fine — starts with an empty thread */ }
      }
      syncWelcome();
      loadConversationList();
    })();
  }

  // ---------------------------------------------------------------- thread
  function ensureThread() {
    if (!threadEl) return createThread();
    return threadEl;
  }
  function createThread() {
    // threadEl wird von buildUi() angelegt; hier nur zurückgeben falls fehlend.
    if (!threadEl) { const m = $('.js-thread', uiEl); if (m) threadEl = m; }
    return threadEl;
  }

  function addThreadTurn(role, text) {
    const el = ensureThread();
    if (!el) return { classList: { add(){}, remove(){}, toggle(){} }, textContent: '' };
    const row = document.createElement('div');
    row.className = 'js-turn ' + (role === 'you' ? 'js-you' : 'js-jarvis');
    const inner = document.createElement('div');
    inner.className = 'js-text';
    inner.textContent = text;
    row.appendChild(inner);
    el.appendChild(row);
    el.scrollTop = el.scrollHeight;
    syncWelcome();
    return inner;
  }

  function showThread() {}
  function clearThreadUI() {
    if (threadEl) threadEl.innerHTML = '';
    syncWelcome();
  }

  // ---------------------------------------------------------------- chat
  function setBusy(v) {
    busy = v;
    if (sendBtn) { sendBtn.disabled = v; sendBtn.style.opacity = v ? '0.5' : '1'; }
  }

  async function sendMessage(text) {
    text = (text || '').trim();
    if (!text || busy) return;
    if (composerInput) { composerInput.innerText = ''; composerInput.classList.remove('is-empty'); }
    showThread();
    addThreadTurn('you', text);
    const said = addThreadTurn('jarvis', '');
    said.classList.add('thinking');
    said.textContent = '';
    setBusy(true);

    const parts = [];
    let fullText = '';
    try {
      const resp = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history, turn_id: String(++turnCounter), mode: activeMode, conversation_id: ensureConversationId() }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          let evt;
          try { evt = JSON.parse(line); } catch (e) { continue; }
          if (evt.type === 'partial') {
            said.classList.remove('thinking');
            said.textContent = parts.join(' ') + (evt.text || '');
          } else if (evt.type === 'sentence') {
            said.classList.remove('thinking');
            if (evt.text) parts.push(evt.text);
            said.textContent = parts.join(' ');
            // The backend embeds each sentence's audio in this same event
            // (see backend/main.py's /chat/stream) rather than sending a
            // separate "audio"-typed event — that type never actually
            // arrives, so playback silently never fired without this.
            if (evt.audio) await playClip(base64ToBlob(evt.audio, evt.mime || 'audio/mpeg'));
          } else if (evt.type === 'done') {
            fullText = evt.full_text || '';
          }
        }
      }
    } catch (err) {
      const fb = "Ich komme gerade nicht an mein Sprachmodell ran. Läuft LM Studio und ist Gemma dort geladen?";
      if (!fullText) { fullText = fb; said.classList.remove('thinking'); said.textContent = fb; }
    }
    if (fullText) {
      history.push({ role: 'user', content: text });
      history.push({ role: 'assistant', content: fullText });
      if (history.length > 40) history = history.slice(-40);
    }
    setBusy(false);
    // Picks up the freshly generated title once it's ready — generation
    // runs in the background on the server, a beat behind the reply
    // itself, so a second refresh shortly after catches it for a brand
    // new conversation's first turn.
    loadConversationList();
    setTimeout(loadConversationList, 2500);
  }

  function sendFromComposer() {
    const text = composerInput ? composerInput.innerText.trim() : '';
    if (text) sendMessage(text);
  }

  // ---------------------------------------------------------------- modelle
  async function toggleModelMenu() {
    if (!modelMenuEl) return;
    const open = modelMenuEl.style.display !== 'none';
    if (open) { modelMenuEl.style.display = 'none'; return; }
    let models = [];
    try {
      const r = await fetch('/models');
      const j = await r.json();
      models = (j.models || []).map((m) => ({ id: m }));
      if (j.current) setModelLabel(j.current);
    } catch (e) { models = []; }
    modelMenuEl.innerHTML = '';
    if (!models.length) {
      const d = document.createElement('div');
      d.textContent = 'Keine Modelle — LM Studio gestartet?';
      d.style.cssText = `padding:10px 14px;font-size:13px;color:${C.textDim};`;
      modelMenuEl.appendChild(d);
    } else {
      for (const m of models) {
        const b = document.createElement('button');
        b.textContent = m.id;
        b.style.cssText = `display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;`;
        b.onmouseenter = () => { b.style.background = C.bgHover; };
        b.onmouseleave = () => { b.style.background = 'none'; };
        b.addEventListener('click', async (e) => {
          e.stopPropagation();
          modelMenuEl.style.display = 'none';
          setModelLabel(m.id);
          try { await fetch('/models/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: m.id }) }); } catch (e2) {}
        });
        modelMenuEl.appendChild(b);
      }
    }
    modelMenuEl.style.display = 'block';
  }
  function setModelLabel(id) {
    const short = String(id).split('/').pop();
    if (modelEl) modelEl.textContent = short;
  }

  // ---------------------------------------------------------------- sprache
  function getMicLevel() {
    if (vadAnalyser && vadData) {
      vadAnalyser.getByteFrequencyData(vadData);
      let sum = 0;
      for (let i = 0; i < vadData.length; i++) sum += vadData[i];
      return sum / vadData.length / 255;
    }
    return 0;
  }

  async function ensureMic() {
    if (micReady) return micStream;
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: !/Mac/i.test(navigator.platform), noiseSuppression: true, autoGainControl: true } });
    micReady = true;
    setupVad(micStream);
    startContinuousRecording();
    return micStream;
  }
  function setupVad(stream) {
    const ctx = ensureCtx();
    const src = ctx.createMediaStreamSource(stream);
    vadAnalyser = ctx.createAnalyser();
    vadAnalyser.fftSize = 512;
    src.connect(vadAnalyser);
    vadData = new Uint8Array(vadAnalyser.frequencyBinCount);
    setInterval(vadTick, 80);
  }
  function startContinuousRecording() {
    if (pcmNode || !micStream) return;
    const ctx = ensureCtx();
    pcmNode = ctx.createScriptProcessor(4096, 1, 1);
    pcmSampleRate = ctx.sampleRate;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    pcmNode.connect(gain);
    gain.connect(ctx.destination);
    const src = ctx.createMediaStreamSource(micStream);
    src.connect(pcmNode);
    pcmNode.onaudioprocess = (e) => {
      const data = new Float32Array(e.inputBuffer.getChannelData(0));
      if (utterancePCM) utterancePCM.push(data);
      else { pcmRing.push(data); if (pcmRing.length > 9) pcmRing.shift(); }
    };
  }
  function beginUtterance() { utterancePCM = pcmRing.slice(); utteranceStartedAt = Date.now(); }
  function stopRecording() {
    const chunks = utterancePCM || [];
    utterancePCM = null;
    if (chunks.length) sendUtterance(concatFloat32(chunks), utteranceStartedAt);
  }
  function cancelRecording() { utterancePCM = null; pcmRing.length = 0; }
  function concatFloat32(arrs) {
    let len = 0; for (const a of arrs) len += a.length;
    const out = new Float32Array(len); let o = 0;
    for (const a of arrs) { out.set(a, o); o += a.length; }
    return out;
  }
  async function sendUtterance(samples, startedAt) {
    const blob = encodeWav(samples, pcmSampleRate);
    const fd = new FormData(); fd.append('audio', blob, 'speech.wav');
    let text = '';
    try { const r = await fetch('/stt', { method: 'POST', body: fd }); const j = await r.json(); text = j.text || ''; }
    catch (e) { text = ''; }
    text = text.trim();
    if (!text) return;
    if (speechMode) { sendMessage(text); return; }
    // Diktat-Modus: transkribierten Text ans Eingabefeld anhängen, nicht senden.
    if (dictating && composerInput) {
      const cur = composerInput.innerText.trim();
      composerInput.innerText = cur ? cur + ' ' + text : text;
      composerInput.classList.remove('is-empty');
      if (sendBtn) sendBtn.disabled = false;
    }
  }
  function vadTick() {
    if (!vadAnalyser || !vadData) return;
    vadAnalyser.getByteTimeDomainData(vadData);
    let sum = 0;
    for (let i = 0; i < vadData.length; i++) { const v = (vadData[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / vadData.length);
    const listening = (speechMode || dictating) && !muted && !busy;
    vadNoiseFloor = vadNoiseFloor * 0.98 + rms * 0.02;
    const thresh = Math.max(vadNoiseFloor * 2.4, 0.025);
    const above = rms > thresh;
    if (above && !utterancePCM) { if (listening) beginUtterance(); }
    if (utterancePCM) {
      if (above) { silenceStreak = 0; }
      else { silenceStreak++; if (silenceStreak >= 28) { silenceStreak = 0; stopRecording(); } }
    }
  }

  function enterSpeech() {
    ensureMic().then(() => {
      speechMode = true;
      showOrb();
      if (composerTray) composerTray.style.opacity = '0.25';
      if (speechBtn) speechBtn.classList.add('on');
    }).catch(() => {
      if (speechBtn) speechBtn.title = 'Mikrofon abgelehnt — Tippen funktioniert';
    });
  }
  function exitSpeech() {
    speechMode = false;
    hideOrb();
    cancelRecording();
    if (composerTray) composerTray.style.opacity = '';
    if (speechBtn) speechBtn.classList.remove('on');
  }

  // Diktat-Modus: Hört zu und schreibt Transkripte ins Eingabefeld.
  function setDictating(should) {
    if (should && !micReady) {
      ensureMic().then(() => {
        dictating = true;
        if (noteBtn) noteBtn.classList.add('on');
        if (noteBtn) noteBtn.title = 'Diktat aus';
      }).catch(() => {
        if (noteBtn) noteBtn.title = 'Mikrofon abgelehnt';
        dictating = false;
      });
      return;
    }
    dictating = should;
    if (noteBtn) noteBtn.classList.toggle('on', should);
    if (noteBtn) noteBtn.title = should ? 'Diktat aus' : 'Diktieren';
  }

  // ---------------------------------------------------------------- boot
  function boot() {
    buildUi();
    // 3D-Orb-Canvas (Hintergrund, nur im Sprachmodus sichtbar)
    orbCanvas = document.createElement('canvas');
    orbCanvas.id = 'jarvisOrb';
    // z-index 40: die Vollbild-Kugel muss VOR der UI (z-index:30) liegen, sonst
    // verschwindet sie hinter dem opaken #jsApp-Hintergrund und der Sprachmodus
    // wirkt, als sei er verschwunden. pointer-events:none lässt Klicks zur UI durch.
    orbCanvas.style.cssText = 'position:fixed;inset:0;z-index:40;pointer-events:none;background:transparent;';
    document.body.appendChild(orbCanvas);
    orbCtx = orbCanvas.getContext('2d');
    orbPoints = buildSpherePoints();
    // Sidebar-Toggle
    const t = $('.js-side-toggle', uiEl);
    if (t) t.addEventListener('click', () => {
      const aside = $('.js-sidebar', uiEl);
      const open = aside.style.display !== 'none';
      aside.style.display = open ? 'none' : 'flex';
      const comp = $('.js-composer', uiEl);
      if (comp) comp.style.left = open ? '0' : '308px';
    });
    setMode('chat');
    // Initial Modell-Label setzen
    fetch('/models').then((r) => r.json()).then((j) => { if (j.current) setModelLabel(j.current); }).catch(() => {});
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
