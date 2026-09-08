// JARVIS — funktionale Schicht in Claude-Optik, die über dem eingefrorenen
// claude.ai-SSR-DOM liegt. Der Snapshot (frontend/claude.html) ist inert: seine
// Anthropic-Skripte sind in serve_index() gestrippt, React läuft nie. Seine CSS-
// Tokens/Fonts (--font-anthropic-sans, --text-primary/…, Terracotta #d97757)
// behalten wir; das tote, kollabierte DOM (Chef-Hero, 62 tote Buttons, Chat-
// Zeilen mit height:0, weil React die Höhen setzt) verdecken wir mit einer
// EIGENEN, funktionalen UI-Schicht (#jsApp): Sidebar mit echten Chats, Composer
// -> /chat/stream (NDJSON + TTS), Chat|Code-Umschalter, Modell-Auswahl und ein
// Sprachmodus mit 3D-Punktnetz-Kugel (Canvas2D, kein three.js).
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

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
  const ICONS = {
    logo: '<svg data-cds="ClaudeLogo" xmlns="http://www.w3.org/2000/svg" viewBox="30 0 82 24" height="20" fill="currentColor" role="img" aria-label="Claude" shape-rendering="geometricPrecision"><path d="M39.504 21.2643C37.688 21.2643 36.06 20.9003 34.62 20.1723C33.18 19.4443 32.048 18.4163 31.224 17.0883C30.408 15.7603 30 14.2243 30 12.4803C30 10.6563 30.412 9.03233 31.236 7.60833C32.06 6.17633 33.196 5.06833 34.644 4.28433C36.1 3.49233 37.74 3.09633 39.564 3.09633C40.692 3.09633 41.82 3.22033 42.948 3.46833C44.084 3.71633 45.072 4.09633 45.912 4.60833V8.56833H44.832C44.536 7.16833 43.96 6.12433 43.104 5.43633C42.256 4.74833 41.076 4.40433 39.564 4.40433C38.164 4.40433 36.996 4.73233 36.06 5.38833C35.132 6.03633 34.444 6.93633 33.996 8.08833C33.548 9.24033 33.324 10.5643 33.324 12.0603C33.324 13.5483 33.576 14.8883 34.08 16.0803C34.584 17.2723 35.328 18.2163 36.312 18.9123C37.296 19.6003 38.476 19.9443 39.852 19.9443C40.796 19.9443 41.608 19.7483 42.288 19.3563C42.968 18.9643 43.54 18.4363 44.004 17.7723C44.468 17.1003 44.908 16.2803 45.324 15.3123H46.464L45.684 19.6803C44.892 20.2003 43.936 20.5963 42.816 20.8683C41.704 21.1323 40.6 21.2643 39.504 21.2643ZM47.964 21.0003V19.9563C48.356 19.9003 48.668 19.8403 48.9 19.7763C49.14 19.7043 49.332 19.5883 49.476 19.4283C49.628 19.2683 49.704 19.0443 49.704 18.7563V5.83233L47.964 5.08833V4.28433L51.612 2.73633H52.56V18.7563C52.56 19.0523 52.632 19.2803 52.776 19.4403C52.928 19.6003 53.12 19.7123 53.352 19.7763C53.592 19.8403 53.912 19.9003 54.312 19.9563V21.0003H47.964ZM59.028 21.2643C58.38 21.2643 57.792 21.1363 57.264 20.8803C56.736 20.6243 56.32 20.2563 56.016 19.7763C55.712 19.2963 55.56 18.7363 55.56 18.0963C55.56 17.1203 55.86 16.3443 56.46 15.7683C57.068 15.1843 57.916 14.7403 59.004 14.4363L63.24 13.2363V11.7123C63.24 10.8883 63.048 10.2523 62.664 9.80433C62.288 9.34833 61.708 9.12033 60.924 9.12033C60.228 9.12033 59.704 9.33233 59.352 9.75633C59.008 10.1723 58.836 10.7483 58.836 11.4843V12.6123H56.988C56.764 12.4683 56.588 12.2763 56.46 12.0363C56.34 11.7883 56.28 11.5163 56.28 11.2203C56.28 10.5563 56.516 9.98833 56.988 9.51633C57.46 9.03633 58.06 8.67633 58.788 8.43633C59.516 8.19633 60.256 8.07633 61.008 8.07633C62.592 8.07633 63.836 8.44033 64.74 9.16833C65.644 9.89633 66.096 11.0003 66.096 12.4803V18.5403C66.096 18.8603 66.168 19.1043 66.312 19.2723C66.456 19.4403 66.644 19.5603 66.876 19.6323C67.116 19.6963 67.44 19.7563 67.848 19.8123V20.8563C67.536 20.9683 67.208 21.0563 66.864 21.1203C66.528 21.1843 66.204 21.2163 65.892 21.2163C65.148 21.2163 64.548 21.0483 64.092 20.7123C63.644 20.3683 63.372 19.8643 63.276 19.2003C62.716 19.8643 62.08 20.3763 61.368 20.7363C60.664 21.0883 59.884 21.2643 59.028 21.2643ZM60.444 19.3443C60.948 19.3443 61.44 19.2283 61.92 18.9963C62.408 18.7563 62.848 18.4403 63.24 18.0483V14.3403L60.168 15.2523C59.592 15.4283 59.152 15.7003 58.848 16.0683C58.544 16.4363 58.392 16.9003 58.392 17.4603C58.392 17.8203 58.48 18.1443 58.656 18.4323C58.832 18.7203 59.076 18.9443 59.388 19.1043C59.7 19.2643 60.052 19.3443 60.444 19.3443ZM73.608 21.2643C72.32 21.2643 71.356 20.9283 70.716 20.2563C70.084 19.5843 69.768 18.6363 69.768 17.4123V10.9083L68.016 10.2603L68.112 9.45633L71.664 8.07633H72.624V16.9323C72.624 17.6923 72.812 18.2563 73.188 18.6243C73.564 18.9923 74.14 19.1763 74.916 19.1763C75.428 19.1763 75.964 19.0603 76.524 18.8283C77.084 18.5883 77.6 18.2803 78.072 17.9043V10.9083L76.32 10.2603V9.45633L79.98 8.07633H80.928V17.8323C80.928 18.1523 81 18.4003 81.144 18.5763C81.288 18.7443 81.476 18.8643 81.708 18.9363C81.948 19.0083 82.272 19.0723 82.68 19.1283V20.1603L79.02 21.1803H78.072V19.0803C77.44 19.7363 76.728 20.2643 75.936 20.6643C75.144 21.0643 74.368 21.2643 73.608 21.2643ZM89.328 21.2643C88.264 21.2643 87.312 21.0083 86.472 20.4963C85.632 19.9763 84.976 19.2683 84.504 18.3723C84.032 17.4763 83.796 16.4843 83.796 15.3963C83.796 13.9643 84.08 12.6963 84.648 11.5923C85.224 10.4883 86.032 9.62833 87.072 9.01233C88.112 8.38833 89.32 8.07633 90.696 8.07633C91.12 8.07633 91.556 8.12433 92.004 8.22033C92.46 8.30833 92.896 8.43633 93.312 8.60433V5.82033L91.56 5.08833V4.28433L95.22 2.73633H96.168V17.8323C96.168 18.1523 96.24 18.4003 96.384 18.5763C96.536 18.7443 96.728 18.8643 96.96 18.9363C97.2 19.0083 97.52 19.0723 97.92 19.1283V20.1603L94.26 21.1803H93.312V19.5843C92.752 20.1123 92.132 20.5243 91.452 20.8203C90.78 21.1163 90.072 21.2643 89.328 21.2643ZM90.504 19.3323C90.976 19.3323 91.456 19.2363 91.944 19.0443C92.432 18.8523 92.888 18.5883 93.312 18.2523V10.3563C92.584 9.76433 91.776 9.46833 90.888 9.46833C89.992 9.46833 89.236 9.69633 88.62 10.1523C88.004 10.6083 87.54 11.2283 87.228 12.0123C86.924 12.7883 86.772 13.6563 86.772 14.6163C86.772 15.5283 86.908 16.3403 87.18 17.0523C87.452 17.7563 87.868 18.3123 88.428 18.7203C88.988 19.1283 89.68 19.3323 90.504 19.3323ZM105.252 21.2643C104.068 21.2643 103.004 20.9883 102.06 20.4363C101.116 19.8843 100.376 19.1163 99.84 18.1323C99.304 17.1483 99.036 16.0443 99.036 14.8203C99.036 13.5563 99.308 12.4123 99.852 11.3883C100.404 10.3563 101.156 9.54833 102.108 8.96433C103.068 8.37233 104.136 8.07633 105.312 8.07633C106.216 8.07633 107.048 8.26433 107.808 8.64033C108.568 9.01633 109.2 9.54433 109.704 10.2243C110.216 10.9043 110.552 11.6883 110.712 12.5763L101.928 15.2883C102.168 16.4003 102.644 17.2763 103.356 17.9163C104.076 18.5563 104.968 18.8763 106.032 18.8763C106.92 18.8763 107.716 18.6523 108.42 18.2043C109.124 17.7483 109.748 17.0603 110.292 16.1403L111.228 16.4403C111.012 17.4003 110.62 18.2443 110.052 18.9723C109.484 19.7003 108.784 20.2643 107.952 20.6643C107.128 21.0643 106.228 21.2643 105.252 21.2643ZM107.628 12.2043C107.516 11.6523 107.324 11.1683 107.052 10.7523C106.788 10.3283 106.46 10.0003 106.068 9.76833C105.676 9.53633 105.244 9.42033 104.772 9.42033C104.18 9.42033 103.656 9.60033 103.2 9.96033C102.752 10.3123 102.4 10.8163 102.144 11.4723C101.896 12.1203 101.772 12.8723 101.772 13.7283C101.772 13.8803 101.776 13.9963 101.784 14.0763L107.628 12.2043Z"></path></svg>',
    spark: '<svg data-cds="Spark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="currentColor" aria-hidden="true"><path d="m19.6 66.5 19.7-11 .3-1-.3-.5h-1l-3.3-.2-11.2-.3L14 53l-9.5-.5-2.4-.5L0 49l.2-1.5 2-1.3 2.9.2 6.3.5 9.5.6 6.9.4L38 49.1h1.6l.2-.7-.5-.4-.4-.4L29 41l-10.6-7-5.6-4.1-3-2-1.5-2-.6-4.2 2.7-3 3.7.3.9.2 3.7 2.9 8 6.1L37 36l1.5 1.2.6-.4.1-.3-.7-1.1L33 25l-6-10.4-2.7-4.3-.7-2.6c-.3-1-.4-2-.4-3l3-4.2L28 0l4.2.6L33.8 2l2.6 6 4.1 9.3L47 29.9l2 3.8 1 3.4.3 1h.7v-.5l.5-7.2 1-8.7 1-11.2.3-3.2 1.6-3.8 3-2L61 2.6l2 2.9-.3 1.8-1.1 7.7L59 27.1l-1.5 8.2h.9l1-1.1 4.1-5.4 6.9-8.6 3-3.5L77 13l2.3-1.8h4.3l3.1 4.7-1.4 4.9-4.4 5.6-3.7 4.7-5.3 7.1-3.2 5.7.3.4h.7l12-2.6 6.4-1.1 7.6-1.3 3.5 1.6.4 1.6-1.4 3.4-8.2 2-9.6 2-14.3 3.3-.2.1.2.3 6.4.6 2.8.2h6.8l12.6 1 3.3 2 1.9 2.7-.3 2-5.1 2.6-6.8-1.6-16-3.8-5.4-1.3h-.8v.4l4.6 4.5 8.3 7.5L89 80.1l.5 2.4-1.3 2-1.4-.2-9.2-7-3.6-3-8-6.8h-.5v.7l1.8 2.7 9.8 14.7.5 4.5-.7 1.4-2.6 1-2.7-.6-5.8-8-6-9-4.7-8.2-.5.4-2.9 30.2-1.3 1.5-3 1.2-2.5-2-1.4-3 1.4-6.2 1.6-8 1.3-6.4 1.2-7.9.7-2.6v-.2H49L43 72l-9 12.3-7.2 7.6-1.7.7-3-1.5.3-2.8L24 86l10-12.8 6-7.9 4-4.6-.1-.5h-.3L17.2 77.4l-4.7.6-2-2 .2-3 1-1 8-5.5Z"></path></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    sidebar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><line x1="9.5" y1="4" x2="9.5" y2="20"/><line x1="13.5" y1="8" x2="17.5" y2="8"/><line x1="13.5" y1="12" x2="17.5" y2="12"/><line x1="13.5" y1="16" x2="16.5" y2="16"/></svg>',
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
  let composerInput = null, sendBtn = null, micBtn = null, composerTray = null, modelEl = null, modelMenuEl = null;

  // Sprachmodus + VAD
  let speechMode = false, micReady = false, micStream = null, muted = false;
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
      <button class="js-side-toggle" title="Sidebar ein/aus" style="position:absolute;top:20px;left:16px;z-index:31;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:8px;">${ICONS.sidebar}</button>
      <aside class="js-sidebar" style="width:308px;flex:0 0 308px;height:100%;display:flex;flex-direction:column;background:${C.bgSoft};border-right:1px solid ${C.border};">
        <div class="js-sidebar-top" style="padding:20px 12px 8px;display:flex;flex-direction:column;gap:12px;">
          <div style="display:flex;align-items:center;gap:8px;padding:0 6px 0 44px;">
            <span class="js-brand" style="display:inline-flex;align-items:center;color:${C.text};">${ICONS.logo}</span>
          </div>
          <div class="js-mode" style="display:flex;gap:6px;background:${C.bgHover};border:1px solid ${C.border};border-radius:12px;padding:4px;">
            <button class="js-pill" data-mode="chat" style="flex:1;padding:8px 10px;border:none;border-radius:9px;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;">Chat</button>
            <button class="js-pill" data-mode="code" style="flex:1;padding:8px 10px;border:none;border-radius:9px;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;">Code</button>
          </div>
          <div style="display:flex;gap:8px;">
            <button class="js-new" style="flex:1;display:flex;align-items:center;gap:7px;padding:8px 12px;background:${C.bgHover};border:1px solid ${C.border};border-radius:10px;color:${C.text};font-size:13px;font-weight:500;cursor:pointer;">${ICONS.plus}<span>Neu</span></button>
          </div>
        </div>
        <div class="js-chats" style="flex:0 0 33%;overflow-y:auto;padding:4px 8px 12px;margin-top:auto;"></div>
        <div style="padding:10px 12px;border-top:1px solid ${C.border};display:flex;align-items:center;gap:8px;">
          <span style="width:18px;height:18px;border-radius:50%;background:${C.accent};display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;">M</span>
          <span style="font-size:13px;color:${C.text};">Chef · Pro</span>
        </div>
      </aside>
      <div class="js-main" style="flex:1;height:100%;display:flex;flex-direction:column;min-width:0;position:relative;">
        <div class="js-thread" style="flex:1;overflow-y:auto;scrollbar-width:thin;position:relative;"></div>
      </div>
      <div class="js-composer" style="position:absolute;left:308px;right:0;bottom:0;padding:0 24px 20px;background:linear-gradient(transparent,${C.bg} 55%);">
        <div style="max-width:760px;margin:0 auto;">
          <div class="js-inputbox" style="background:${C.bgSoft};border:1px solid ${C.border};border-radius:16px;box-shadow:0 6px 24px rgba(0,0,0,.35);">
            <div class="js-editor" contenteditable="true" data-placeholder="Beschreibe eine Aufgabe oder stelle eine Frage" style="min-height:64px;max-height:200px;overflow-y:auto;padding:16px;color:${C.text};font-size:15px;line-height:1.5;outline:none;white-space:pre-wrap;word-break:break-word;"></div>
            <div style="display:flex;align-items:center;gap:10px;padding:6px 10px 10px;">
              <button class="js-model" title="Modell wechseln" style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;">
                <span class="js-model-label">Modell…</span> ▾
              </button>
              <div style="flex:1;"></div>
              <button class="js-mic" title="Sprachmodus" style="width:36px;height:36px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.mic}</button>
              <button class="js-send" title="Senden" style="width:36px;height:36px;border-radius:50%;background:${C.accent};border:none;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.spark}</button>
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
    micBtn = $('.js-mic', uiEl);
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
      .js-pill.active { background:${C.bg} !important; color:${C.text} !important; box-shadow:inset 0 0 0 1px ${C.border}; }
      .js-editor:empty::before, .js-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-editor:focus::before { opacity:.7; }
      .js-brand svg { height:20px; width:auto; display:block; }
      .js-side-toggle:hover { background:${C.bgHover}; }
      .js-side-toggle svg, .js-new svg { width:16px; height:16px; display:block; }
      .js-mic svg, .js-send svg { width:19px; height:19px; display:block; }
      .js-mic:hover { background:${C.bgHover}; color:${C.text}; }
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
    `;
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------- wire UI
  function setMode(mode) {
    activeMode = mode;
    for (const p of $$('.js-pill', uiEl)) {
      const is = (p.getAttribute('data-mode') === mode);
      p.classList.toggle('active', is);
    }
    if (modelEl) modelEl.textContent = mode === 'code' ? 'Code' : 'Claude';
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
    // Chat|Code
    for (const p of $$('.js-pill', uiEl)) p.addEventListener('click', () => setMode(p.getAttribute('data-mode')));
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
    // Mikro (Sprachmodus)
    if (micBtn) micBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); speechMode ? exitSpeech() : enterSpeech(); });
    // Modell-Auswahl
    if (modelEl) modelEl.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleModelMenu(); });
    window.addEventListener('click', () => { if (modelMenuEl) modelMenuEl.style.display = 'none'; });

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
    return inner;
  }

  function showThread() {}
  function clearThreadUI() {
    if (threadEl) threadEl.innerHTML = '';
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
    if (text) { if (speechMode) sendMessage(text); else if (composerInput) { composerInput.innerText = text; composerInput.classList.remove('is-empty'); } }
  }
  function vadTick() {
    if (!vadAnalyser || !vadData) return;
    vadAnalyser.getByteTimeDomainData(vadData);
    let sum = 0;
    for (let i = 0; i < vadData.length; i++) { const v = (vadData[i] - 128) / 128; sum += v * v; }
    const rms = Math.sqrt(sum / vadData.length);
    const listening = speechMode && !muted && !busy;
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
      if (micBtn) micBtn.style.background = C.accent;
      if (micBtn) micBtn.style.color = '#fff';
    }).catch(() => {
      if (micBtn) micBtn.title = 'Mikrofon abgelehnt — Tippen funktioniert';
    });
  }
  function exitSpeech() {
    speechMode = false;
    hideOrb();
    cancelRecording();
    if (composerTray) composerTray.style.opacity = '';
    if (micBtn) micBtn.style.background = '';
    if (micBtn) micBtn.style.color = '';
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
