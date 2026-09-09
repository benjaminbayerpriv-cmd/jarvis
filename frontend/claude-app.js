// JARVIS — funktionale Schicht über dem eingefrorenen claude.ai-SSR-DOM.
// Der Snapshot (frontend/claude.html) ist inert: seine Anthropic-Skripte sind
// in serve_index() gestrippt, React läuft nie. Seine CSS-Tokens/Fonts
// (--font-anthropic-sans, --text-primary/…, Terracotta #d97757) behalten wir;
// das tote DOM verdecken wir mit einer EIGENEN, funktionalen UI-Schicht (#jsApp):
// Sidebar mit echten Chats + Einstellungen, Uhrzeit-Begrüßung, Chat/Code-Toggle,
// Composer -> /chat/stream (NDJSON + TTS), Modell-Auswahl, Datei-Upload,
// Diktat (Mikrofon) und Sprachmodus (mittiges graues Punktnetz, Canvas2D).
// Bewusst OHNE Logo/Wortbild; Oberfläche auf Englisch; Code-Modus als Stub.
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);

  // ------------------------------------------------ claude-design-tokens
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

  // ------------------------------------------------ lucide-icons (24x24 stroke)
  // Echte Lucide-Ikonen, 1:1 aus dem Internet (lucide-static), stroke=currentColor.
  const ICONS = {
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>',
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/></svg>',
    code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 16 4-4-4-4"/><path d="m6 8-4 4 4 4"/><path d="m14.5 4-5 16"/></svg>',
    mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>',
    micOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="2" x2="22" y1="2" y2="22"/><path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2"/><path d="M5 10v2a7 7 0 0 0 12 5"/><path d="M15 9.34V5a3 3 0 0 0-5.68-1.33"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12"/><line x1="12" x2="12" y1="19" y2="22"/></svg>',
    audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/></svg>',
    paperclip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="18" height="18" x="3" y="3" rx="4" fill="currentColor"/></svg>',
    restart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/><path d="M3 3v5h5"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
    volume: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/></svg>',
    muted: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4.702a.7.7 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.7.7 0 0 0 11 19.298z"/><path d="m16.5 14.5 5-5"/><path d="m16.5 9.5 5 5"/></svg>',
    folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>',
  };

  // ---------------------------------------------------------------- helfer
  // Datei-Anhang: liest den Inhalt der Datei clientseitig, statt nur
  // "📎 dateiname.txt" als reinen Text in den Composer zu schreiben und die
  // Datei selbst zu verwerfen (der alte Zustand — es gibt auch keinen
  // generischen Upload-Endpoint im Backend). Zwei Fälle:
  //  - Bilder gehen, wenn das AKTUELLE Modell laut LM Studio ein "vlm" ist
  //    (siehe llm_client.list_model_capabilities), als Data-URL direkt mit
  //    ins Chat-Request (images[], siehe sendMessage) — das Modell sieht
  //    das Bild wirklich, nicht nur einen Dateinamen.
  //  - Alles andere wird als Text gelesen und inline in die Nachricht
  //    eingefügt (PDFs/Audio landen ehrlich als "kann ich nicht lesen"
  //    statt stillschweigend Datenmüll in den Prompt zu kippen).
  const ATTACH_MAX_CHARS = 20000;
  let pendingImages = [];  // {name, image: Data-URL} der aktuell angehängten Bilder, siehe sendMessage
  function canSendNow() {
    const hasText = !!(composerInput && composerInput.innerText.trim());
    return hasText || pendingImages.length > 0;
  }
  function renderAttachPreviews() {
    if (sendBtn) sendBtn.disabled = !canSendNow();
    if (!attachPreviewEl) return;
    if (!pendingImages.length) { attachPreviewEl.style.display = 'none'; attachPreviewEl.innerHTML = ''; return; }
    attachPreviewEl.style.display = 'flex';
    attachPreviewEl.innerHTML = pendingImages.map((att, i) => `
      <div style="position:relative;width:56px;height:56px;flex:0 0 auto;">
        <img src="${att.image}" title="${att.name.replace(/"/g, '&quot;')}" style="width:100%;height:100%;object-fit:cover;border-radius:10px;border:1px solid ${C.border};" />
        <button class="js-attach-remove" data-idx="${i}" title="Entfernen" style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;border-radius:50%;background:${C.bgSoft};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;font-size:11px;line-height:1;display:flex;align-items:center;justify-content:center;padding:0;">×</button>
      </div>
    `).join('');
    attachPreviewEl.querySelectorAll('.js-attach-remove').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        pendingImages.splice(Number(btn.dataset.idx), 1);
        renderAttachPreviews();
      });
    });
  }
  function looksBinary(text) {
    // NUL-Bytes oder ein hoher Anteil des Unicode-Replacement-Zeichens
    // deuten auf eine Datei hin, die keine echte Textdatei ist (PDF,
    // Audio, …) — FileReader.readAsText() wirft dafür keinen Fehler,
    // sondern liefert einfach unlesbaren Müll zurück.
    if (text.indexOf('\x00') !== -1) return true;
    let bad = 0;
    for (let i = 0; i < text.length && i < 2000; i++) if (text[i] === '�') bad++;
    return bad > 20;
  }
  function readFileAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file);
    });
  }
  function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }
  const IMAGE_MAX_DIM = 1568;  // matches the encoder's own downscale point — no benefit past this
  // Real phone photos (progressive/CMYK JPEGs, odd chroma subsampling, EXIF
  // orientation) can silently fail to decode in LM Studio's image pipeline —
  // the model then answers as if no image was ever attached at all, with no
  // error anywhere. A synthetic canvas-drawn PNG never hit this because
  // toBlob() only ever emits a plain baseline image. Routing every real
  // photo through the same canvas re-encode (which also applies EXIF
  // rotation automatically via createImageBitmap) normalizes it the same
  // way and fixed real-world photos that were failing.
  async function normalizeImageFile(file) {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    let { width, height } = bitmap;
    if (width > IMAGE_MAX_DIM || height > IMAGE_MAX_DIM) {
      const scale = IMAGE_MAX_DIM / Math.max(width, height);
      width = Math.round(width * scale);
      height = Math.round(height * scale);
    }
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    return new Promise((resolve, reject) => {
      canvas.toBlob(blob => {
        if (!blob) { reject(new Error('toBlob failed')); return; }
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      }, 'image/jpeg', 0.9);
    });
  }
  async function readAttachedFile(file) {
    if (file.type && file.type.startsWith('image/')) {
      if (!currentModelSupportsVision) {
        return { text: `📎 ${file.name}: das aktuelle Modell kann keine Bilder lesen — wechsle oben im Modell-Menü zu einem vision-fähigen Modell (z. B. gemma-4-e4b, qwen3.5-9b/3.8-27b, devstral).`, image: null };
      }
      try {
        let image;
        try {
          image = await normalizeImageFile(file);
        } catch (e) {
          image = await readFileAsDataURL(file);
        }
        return { text: `📎 ${file.name} (Bild angehängt)`, image };
      } catch (e) {
        return { text: `📎 ${file.name}: konnte nicht gelesen werden.`, image: null };
      }
    }
    let text;
    try {
      text = await readFileAsText(file);
    } catch (e) {
      return { text: `📎 ${file.name}: konnte nicht gelesen werden.`, image: null };
    }
    if (looksBinary(text)) {
      return { text: `📎 ${file.name}: Inhalt kann nicht als Text gelesen werden (PDF/Binärdatei) — nur Text- und Bilddateien werden derzeit unterstützt.`, image: null };
    }
    let truncated = false;
    if (text.length > ATTACH_MAX_CHARS) { text = text.slice(0, ATTACH_MAX_CHARS); truncated = true; }
    const note = truncated ? ` (gekürzt auf ${ATTACH_MAX_CHARS} Zeichen)` : '';
    return { text: `📎 ${file.name}${note}:\n\`\`\`\n${text}\n\`\`\``, image: null };
  }

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

  // Sprachausgabe als sequenzielle Warteschlange: Der streamende Text landet
  // SOFORT im Thread, die vertonten Sätze folgen nacheinander, ohne sich zu
  // überlappen. Für die „sprechen"-Animation wird die TTS-Ausgabe über einen
  // EIGENEN AudioContext gemessen (getrennt vom Mikrofon-Context, damit das
  // Routing die Stimme nicht stummschaltet); der Pegel treibt den Orb.
  let speaking = false;
  let audioQueue = [];
  let audioDraining = false;
  // Ausgabe-Pegel-Messung (gesprochene Stimme) für die Orb-Animation
  let ttsAudioCtx = null, outputAnalyser = null, outBuf = null, speakingLevel = 0;
  let currentAudioEl = null, currentAudioSrc = null;
  // Abbruch-Zustand für eine laufende Antwort (Stop-Button)
  let turnAborted = false, activeReader = null, abortController = null, currentTurnId = null;
  // Live-Diktat: Basis-Text im Eingabefeld beim Start
  let dictBase = '';

  function rmsFrom(analyser, buf) {
    analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
    return Math.sqrt(sum / buf.length);
  }

  function playClip(blob) {
    const audio = new Audio(URL.createObjectURL(blob));
    return new Promise((resolve) => {
      let done = false;
      let src = null;
      const finish = () => { if (done) return; done = true; clearTimeout(timer); teardownMeter(audio, src); resolve(); };
      const timer = setTimeout(finish, 4000);
      // Ausgabe-Pegel nur im Sprachmodus messen (dort ist die Orb sichtbar).
      try {
        if (speechMode) {
          if (!ttsAudioCtx) ttsAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
          if (ttsAudioCtx.state === 'suspended') ttsAudioCtx.resume().catch(() => {});
          src = ttsAudioCtx.createMediaElementSource(audio);
          const analyser = ttsAudioCtx.createAnalyser();
          analyser.fftSize = 512;
          src.connect(analyser);
          analyser.connect(ttsAudioCtx.destination);   // Analyser speist UND lässt die Stimme hörbar
          outputAnalyser = analyser;
          if (!outBuf || outBuf.length !== analyser.fftSize) outBuf = new Uint8Array(analyser.fftSize);
          currentAudioSrc = src;
        }
      } catch (e) { src = null; outputAnalyser = null; }
      currentAudioEl = audio;
      audio.onplaying = () => { speaking = true; if (speechMode) setSpeechStatus('Antworte'); };
      audio.onended = () => { speaking = false; finish(); };
      audio.onerror = () => { speaking = false; finish(); };
      audio.play().then(() => {}).catch(() => { speaking = false; finish(); });
    });
  }

  function teardownMeter(el, src) {
    if (currentAudioSrc === src) currentAudioSrc = null;
    if (currentAudioEl === el) currentAudioEl = null;
    if (src) { try { src.disconnect(); } catch (e) {} }
    outputAnalyser = null;
    speakingLevel = 0;
  }

  function enqueueClip(blob) {
    audioQueue.push(blob);
    if (!audioDraining) drainAudioQueue();
  }
  async function drainAudioQueue() {
    audioDraining = true;
    speaking = false;
    while (audioQueue.length) {
      const blob = audioQueue.shift();
      try { await playClip(blob); } catch (e) { /* nie den Faden abreißen */ }
    }
    speaking = false;
    audioDraining = false;
    // nach der Ausgabe wieder in den Bereit-Zustand, wenn noch im Sprachmodus
    if (speechMode && !busy) setSpeechStatus('Bereit');
    // Erst jetzt ist die Antwort wirklich zu Ende — wieder hinhören, sonst
    // würde die Erkennung Jarvis' eigene Stimme aufgreifen (Echo).
    resumeListening();
  }

  // Stop-Button: unterbricht die laufende Antwort UND die Sprachausgabe.
  function stopSpeech() {
    turnAborted = true;
    try { if (abortController) abortController.abort(); } catch (e) {}
    try { if (activeReader) activeReader.cancel(); } catch (e) {}
    audioQueue.length = 0;
    audioDraining = false;
    if (currentAudioSrc) { try { currentAudioSrc.disconnect(); } catch (e) {} currentAudioSrc = null; }
    if (currentAudioEl) { try { currentAudioEl.pause(); } catch (e) {} currentAudioEl = null; }
    outputAnalyser = null;
    speaking = false;
    speakingLevel = 0;
    if (busy) setBusy(false);
    if (currentTurnId) { fetch('/chat/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ turn_id: currentTurnId }) }).catch(() => {}); }
    if (speechMode && !busy) setSpeechStatus('Bereit');
    resumeListening();
  }

  // ------------------------------------------------------------------ zustand
  let activeMode = 'chat';      // "chat" | "code"
  let history = [];             // OpenAI-Format [{role, content}]
  let turnCounter = 0;
  let busy = false;

  // UI-Anker (in buildUi() gesetzt)
  let uiEl = null, sidebarEl = null, chatListEl = null, chatRootEl = null, threadEl = null;
  let composerTray = null, composerInput = null, sendBtn = null, speechBtn = null, noteBtn = null;
  let uploadBtn = null, settingsBtn = null, modelEl = null, modelBtnEl = null, modelMenuEl = null, fileInput = null;
  let attachPreviewEl = null;
  let speechBarEl = null, spMuteBtn = null, spStopBtn = null, spSendBtn = null, spChatBtn = null;
  let speechCaptionEl = null, spcStatusEl = null, spcUserEl = null, spcReplyEl = null;
  let settingsSheetEl = null, settingsModelsEl = null;

  // Code-Tab (echte opencode-TUI in einem eingebetteten xterm.js-Terminal)
  let codeViewEl = null, codeTermEl = null, codeDirEl = null;
  let codeStatusLabelEl = null, codeDotEl = null, codeRestartBtn = null;
  let codeTerm = null, codeFit = null;
  let codeWs = null, codeWsOpen = false, codeReconnectTimer = null, codeExited = false;

  // Sprachmodus + VAD + Diktat + Web-Speech-Erkennung
  let speechMode = false, dictating = false, micReady = false, micStream = null, muted = false;
  let vadAnalyser = null, vadData = null, vadNoiseFloor = 0.01, vadAbove = 0;
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;

  // Graues Punktnetz (Sprachmodus)
  let orbCtx = null, orbCanvas = null, orbLevel = 0, orbRaf = 0, orbVisible = false;
  const DOT_COLOR = '#8b8b8f';

  // Persisted conversation id; ?conv=<id>-Deep-Link priorisiert (siehe unten).
  const params = new URLSearchParams(location.search);
  const deepConv = params.get('conv');
  // Pro Modus getrennte Konversationen: Chat und Code bekommen je einen
  // eigenen Speicher. IDs sind mit dem Modus geprefixt ("code-…"), damit das
  // Backend sie in eigene Dateien legt und die Sidebar nur die Konversationen
  // des aktiven Modus zeigt. Alte (ungepräfixte) IDs zählen als Chat, damit
  // nichts verloren geht.
  function modeKey(mode) { return 'jarvis_conv_' + mode; }
  function isModeConv(mode, id) {
    return mode === 'code' ? String(id).startsWith('code-') : !String(id).startsWith('code-');
  }
  if (deepConv) {
    activeMode = String(deepConv).startsWith('code-') ? 'code' : 'chat';
    localStorage.setItem(modeKey(activeMode), deepConv);
  }
  let currentConversationId =
    (deepConv && isModeConv(activeMode, deepConv)) ? deepConv
    : localStorage.getItem(modeKey(activeMode))
    || (activeMode === 'chat' ? localStorage.getItem('jarvis_conversation_id') : null)
    || null;
  function ensureConversationId() {
    if (!currentConversationId || !isModeConv(activeMode, currentConversationId)) {
      currentConversationId = activeMode + '-' + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
    }
    localStorage.setItem(modeKey(activeMode), currentConversationId);
    return currentConversationId;
  }

  // Uhrzeit-Begrüßung (bewusst deutsch, vom Nutzer so gewünscht).
  function timeGreeting() {
    const h = new Date().getHours();
    if (h >= 5 && h < 11) return 'Morgen, Chef';
    if (h >= 11 && h < 15) return 'Mittag, Chef';
    if (h >= 15 && h < 22) return 'Abend, Chef';
    return 'Mondscheingespräch';
  }

  // --------------------------------------------------------- UI: buildUi()
  function buildUi() {
    uiEl = document.createElement('div');
    uiEl.id = 'jsApp';
    uiEl.style.cssText = `position:fixed;inset:0;z-index:30;display:flex;background:${C.bg};color:${C.text};font-family:${C.font};`;
    uiEl.innerHTML = `
      <button class="js-side-toggle" title="Toggle sidebar" style="position:absolute;top:18px;left:16px;z-index:31;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;">${ICONS.menu}</button>
      <aside class="js-sidebar" style="width:308px;flex:0 0 308px;height:100%;display:flex;flex-direction:column;background:${C.bgSoft};border-right:1px solid ${C.border};">
        <div class="js-sidebar-top" style="padding:16px 12px 6px;display:flex;flex-direction:column;gap:12px;">
          <div class="js-mode" style="display:flex;padding:3px;gap:3px;background:${C.bgHover};border:1px solid ${C.border};border-radius:11px;margin-left:44px;">
            <button class="js-pill active" data-mode="chat" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 10px;border-radius:8px;border:none;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,color .15s;">${ICONS.chat}<span>Chat</span></button>
            <button class="js-pill" data-mode="code" title="Code with opencode" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 10px;border-radius:8px;border:none;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,color .15s;">${ICONS.code}<span>Code</span></button>
          </div>
          <button class="js-new" style="display:flex;align-items:center;gap:8px;padding:9px 12px;background:${C.bgHover};border:1px solid ${C.border};border-radius:11px;color:${C.text};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s;">${ICONS.plus}<span>New conversation</span></button>
          <button class="js-projects" style="display:flex;align-items:center;gap:8px;padding:9px 12px;background:${C.bgHover};border:1px solid ${C.border};border-radius:11px;color:${C.text};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s;">${ICONS.folder}<span>Projekte</span></button>
          <div style="padding:2px 8px 4px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Conversations</div>
        </div>
        <div class="js-chats" style="flex:1 1 auto;overflow-y:auto;padding:2px 8px 10px;"></div>
        <div class="js-settings-row" style="padding:10px 12px;border-top:1px solid ${C.border};display:flex;align-items:center;gap:8px;">
          <button class="js-settings" title="Settings" style="width:32px;height:32px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.settings}</button>
          <span class="js-settings-label" style="font-size:13px;color:${C.textSoft};">Settings</span>
        </div>
      </aside>
      <div class="js-main" style="flex:1;height:100%;display:flex;flex-direction:column;min-width:0;position:relative;">
        <div class="js-welcome" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 32px;gap:14px;">
          <h1 class="js-welcome-title" style="font-family:${C.serif};font-size:30px;font-weight:600;letter-spacing:-.01em;color:${C.text};margin:0 0 4px;">${timeGreeting()}</h1>
          <p class="js-welcome-sub" style="font-size:14px;color:${C.textSoft};margin:0;max-width:440px;line-height:1.55;">How can I help you today? Speak, dictate, or just type.</p>
        </div>
        <div class="js-thread" style="flex:1;overflow-y:auto;scrollbar-width:thin;position:relative;"></div>
        <div class="js-codeview" style="position:absolute;inset:0;display:none;flex-direction:column;min-width:0;min-height:0;">
          <div class="js-code-header" style="display:flex;align-items:center;gap:10px;padding:12px 18px;border-bottom:1px solid ${C.border};flex:0 0 auto;">
            <span class="js-code-title" style="font-size:14px;font-weight:600;color:${C.text};">Code</span>
            <span class="js-code-dir" style="flex:1;font-size:12px;color:${C.textDim};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:left;cursor:pointer;" title="Arbeitsverzeichnis — klicken zum Ändern"></span>
            <span class="js-code-status" style="display:inline-flex;align-items:center;gap:6px;font-size:11px;color:${C.textDim};">
              <span class="js-code-dot" style="width:8px;height:8px;border-radius:50%;background:#e5a50a;display:inline-block;"></span>
              <span class="js-code-status-label">verbinde…</span>
            </span>
            <button class="js-code-restart" title="Terminal neu starten" style="display:none;align-items:center;gap:6px;padding:5px 10px;background:none;border:1px solid ${C.border};border-radius:9px;color:${C.textSoft};font-size:12px;cursor:pointer;font-family:${C.font};">${ICONS.restart}</button>
          </div>
          <div class="js-code-terminal" style="flex:1 1 auto;min-width:0;min-height:0;overflow:hidden;background:#12121c;padding:4px 2px 6px;"></div>
        </div>
      </div>
      <div class="js-composer" style="position:absolute;left:308px;right:0;bottom:0;padding:0 24px 22px;background:linear-gradient(transparent,${C.bg} 55%);">
        <div style="max-width:760px;margin:0 auto;position:relative;">
          <div style="background:${C.bgSoft};border:1px solid ${C.border};border-radius:18px;box-shadow:0 10px 34px rgba(0,0,0,.38);">
            <div class="js-attach-preview" style="display:none;gap:8px;padding:12px 16px 0;flex-wrap:wrap;"></div>
            <div class="js-editor" contenteditable="true" data-placeholder="Describe a task or ask a question" style="min-height:60px;max-height:200px;overflow-y:auto;padding:16px;color:${C.text};font-size:15px;line-height:1.5;outline:none;white-space:pre-wrap;word-break:break-word;"></div>
            <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 10px;">
              <button class="js-upload" title="Attach files" style="width:34px;height:34px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.paperclip}</button>
              <div style="flex:1;"></div>
              <button class="js-model" title="Change model" style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;transition:background .15s;">
                <span class="js-model-label">Model…</span>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
              </button>
              <button class="js-note" title="Dictate" style="width:34px;height:34px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.mic}</button>
              <button class="js-speech" title="Voice mode" style="width:38px;height:38px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;">${ICONS.audio}</button>
              <button class="js-send" title="Send" style="width:38px;height:38px;border-radius:50%;background:${C.accent};border:none;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.send}</button>
            </div>
          </div>
          <div class="js-modelmenu" style="display:none;position:absolute;width:220px;bottom:calc(100% + 8px);max-height:280px;overflow-y:auto;background:${C.bgSoft};border:1px solid ${C.border};border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.4);"></div>
        </div>
      </div>
    `;
    document.body.appendChild(uiEl);
    document.body.classList.add('js-app-active');

    // Sprachmodus-Bottom-Leiste (mute / stop / send / chat) — body-Kind, z-index 50.
    speechBarEl = document.createElement('div');
    speechBarEl.id = 'jsSpeechbar';
    speechBarEl.style.cssText = 'position:fixed;left:0;right:0;bottom:24px;z-index:50;display:none;justify-content:center;pointer-events:none;';
    speechBarEl.innerHTML = `
      <div style="pointer-events:auto;display:flex;align-items:center;gap:10px;padding:8px 12px;background:${C.bgSoft};border:1px solid ${C.border};border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.5);">
        <button class="js-sp-mute" title="Mikrofon aus" style="width:44px;height:44px;border-radius:14px;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.mic}</button>
        <button class="js-sp-stop" title="Stopp" style="width:44px;height:44px;border-radius:14px;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.stop}</button>
        <button class="js-sp-send" title="Senden" style="width:44px;height:44px;border-radius:14px;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.send}</button>
        <button class="js-sp-chat" title="Chat-Modus" style="width:44px;height:44px;border-radius:14px;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.close}</button>
      </div>
    `;
    document.body.appendChild(speechBarEl);

    // Sprachmodus-Beschriftung (live erkannte Wörter + Jarvis-Antwort). In
    // Speech-Mode ist der Chatverlauf versteckt, also bleibt hier eine
    // lesbare Zeile darüber, was gerade passiert.
    speechCaptionEl = document.createElement('div');
    speechCaptionEl.id = 'jsSpeechCaption';
    speechCaptionEl.style.cssText = `position:fixed;left:0;right:0;bottom:92px;z-index:50;display:none;justify-content:center;pointer-events:none;`;
    speechCaptionEl.innerHTML = `
      <div style="pointer-events:auto;max-width:720px;width:calc(100% - 64px);padding:10px 16px;background:${C.bgSoft};border:1px solid ${C.border};border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.5);display:flex;flex-direction:column;gap:4px;">
        <div class="js-spc-status" style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Listen</div>
        <div class="js-spc-user" style="font-size:15px;color:${C.text};min-height:20px;white-space:pre-wrap;word-break:break-word;">…</div>
        <div class="js-spc-reply" style="font-size:14px;color:${C.textSoft};min-height:0;white-space:pre-wrap;word-break:break-word;"></div>
      </div>
    `;
    spcStatusEl = $('.js-spc-status', speechCaptionEl);
    spcUserEl = $('.js-spc-user', speechCaptionEl);
    spcReplyEl = $('.js-spc-reply', speechCaptionEl);
    document.body.appendChild(speechCaptionEl);

    // Settings-Sheet (kein Fake-Profil — echte Einstellungen hier).
    settingsSheetEl = document.createElement('div');
    settingsSheetEl.id = 'jsSettingsSheet';
    settingsSheetEl.style.cssText = `position:fixed;inset:0;z-index:60;display:none;align-items:flex-start;justify-content:flex-start;padding:64px 0 24px 320px;background:rgba(0,0,0,.35);`;
    settingsSheetEl.innerHTML = `
      <div style="width:340px;max-width:90vw;background:${C.bgSoft};border:1px solid ${C.border};border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.5);overflow:hidden;">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid ${C.border};">
          <span style="font-size:15px;font-weight:600;color:${C.text};">Settings</span>
          <button class="js-settings-close" title="Close" style="width:28px;height:28px;border-radius:8px;background:none;border:none;color:${C.textSoft};cursor:pointer;font-size:16px;line-height:1;">×</button>
        </div>
        <div style="padding:12px 6px;">
          <div style="padding:6px 10px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Model</div>
          <div class="js-settings-models"></div>
        </div>
        <div style="padding:12px 6px 16px;border-top:1px solid ${C.border};">
          <div style="padding:6px 10px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Code</div>
          <div style="padding:4px 10px;display:flex;flex-direction:column;gap:8px;">
            <span style="font-size:12px;color:${C.textSoft};">Working directory for opencode</span>
            <input class="js-code-dir-input" type="text" placeholder="~/Developer" spellcheck="false" style="width:100%;box-sizing:border-box;padding:9px 10px;background:${C.bg};border:1px solid ${C.border};border-radius:8px;color:${C.text};font-size:13px;outline:none;font-family:${C.font};" />
            <button class="js-code-dir-save" style="align-self:flex-start;padding:7px 12px;border:none;border-radius:8px;background:${C.accent};color:#fff;font-size:12px;cursor:pointer;font-family:${C.font};">Save</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(settingsSheetEl);

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
    attachPreviewEl = $('.js-attach-preview', uiEl);
    settingsBtn = $('.js-settings', uiEl);
    modelEl = $('.js-model-label', uiEl);
    modelBtnEl = $('.js-model', uiEl);
    modelMenuEl = $('.js-modelmenu', uiEl);
    spMuteBtn = $('.js-sp-mute', speechBarEl);
    spStopBtn = $('.js-sp-stop', speechBarEl);
    spSendBtn = $('.js-sp-send', speechBarEl);
    spChatBtn = $('.js-sp-chat', speechBarEl);
    settingsModelsEl = $('.js-settings-models', settingsSheetEl);

    injectSkinCss();
    wireUi();
    setMode('chat');
  }

  function injectSkinCss() {
    if (document.getElementById('jsAppCss')) return;
    const s = document.createElement('style');
    s.id = 'jsAppCss';
    s.textContent = `
      body.js-app-active > :not(#jsApp):not(#jarvisOrb):not(#jsSpeechbar):not(#jsSpeechCaption):not(#jsSettingsSheet):not(script):not(style) { display:none !important; }
      body.js-app-active { overflow:hidden; }
      .js-sidebar button:focus-visible, .js-main button:focus-visible { outline:2px solid ${C.accent}; outline-offset:2px; }
      .js-editor:empty::before, .js-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-editor:focus::before { opacity:.7; }
      .js-side-toggle svg, .js-new svg, .js-projects svg, .js-upload svg, .js-note svg, .js-speech svg, .js-settings svg { width:16px; height:16px; display:block; }
      .js-upload svg, .js-note svg, .js-settings svg { width:18px; height:18px; }
      .js-speech svg, .js-send svg { width:18px; height:18px; display:block; }
      .js-sp-mute svg, .js-sp-stop svg, .js-sp-chat svg, .js-sp-send svg { width:20px; height:20px; display:block; }
      .js-pill svg { width:16px; height:16px; display:block; }
      .js-side-toggle:hover, .js-new:hover, .js-projects:hover, .js-upload:hover, .js-note:hover, .js-model:hover, .js-settings:hover, .js-sp-mute:hover, .js-sp-stop:hover, .js-sp-chat:hover { background:${C.bgHover}; color:${C.text}; }
      .js-pill.active { background:${C.accent} !important; color:#fff !important; }
      .js-code-active .js-projects, .js-code-active .js-projects-note { display:none !important; }
      .js-pill:not(.active):hover { background:${C.bgHover}; color:${C.text}; }
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
      .js-turn { max-width:760px; margin:0 auto 26px; font-family:${C.font}; line-height:1.6; display:flex; }
      .js-you { justify-content:flex-end; }
      .js-jarvis { justify-content:flex-start; text-align:left; }
      .js-you .js-text { background:${C.accent}; color:#fff; border-radius:20px; padding:10px 16px; max-width:72%; white-space:pre-wrap; word-break:break-word; }
      .js-jarvis .js-text { color:${C.text}; white-space:pre-wrap; word-break:break-word; max-width:100%; }
      .js-jarvis .js-text.thinking { color:${C.textDim}; font-style:italic; }
      .js-thread { padding:64px 24px 180px; }
      .js-main .js-welcome { opacity:1; transition:opacity .25s ease; }
      .js-main.has-content .js-welcome { opacity:0; pointer-events:none; }
      .js-main.js-speech-active .js-thread, .js-main.js-speech-active .js-welcome { display:none !important; }
      .js-code-editor:empty::before, .js-code-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-code-editor:focus::before { opacity:.7; }
      #jsApp.js-code-active .js-thread, #jsApp.js-code-active .js-welcome, #jsApp.js-code-active .js-composer { display:none !important; }
      #jsApp.js-code-active .js-codeview { display:flex !important; }
    `;
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------- wire UI
  function setMode(mode) {
    if (mode !== 'chat' && mode !== 'code') return;
    const isCode = mode === 'code';
    const pills = uiEl ? uiEl.querySelectorAll('.js-pill') : [];
    pills.forEach((p) => p.classList.toggle('active', p.dataset.mode === mode));
    if (uiEl) uiEl.classList.toggle('js-code-active', isCode);
    if (isCode) {
      // Code-Tab führt keine Chat-Konversationen; eigener Zustand + Socket.
      buildCodeView();
      loadCodeStatus();
      ensureCodeSocket();
      return;
    }
    // Code-Tab verlassen: den Terminal-Socket schließen (der Server beendet die
    // opencode-TUI). Kein Auto-Reconnect — beim nächsten Betreten wird neu
    // verbunden und ein frischer opencode-Prozess gestartet.
    if (codeWs) {
      const w = codeWs;
      codeWs = null; codeWsOpen = false;
      w.onclose = null; w.onerror = null; w.onmessage = null;
      try { w.close(); } catch (e) {}
    }
    if (codeReconnectTimer) { clearTimeout(codeReconnectTimer); codeReconnectTimer = null; }
    if (currentConversationId) localStorage.setItem(modeKey(activeMode), currentConversationId);
    activeMode = mode;
    const saved = localStorage.getItem(modeKey(mode));
    const nextId = saved && isModeConv(mode, saved) ? saved : null;
    if (nextId === currentConversationId) { loadConversationList(); return; }
    currentConversationId = nextId;
    renderConversation(nextId);
    loadConversationList();
  }

  // Lädt die Turns einer Konversation in den Thread (oder leert ihn, wenn
  // id=null). Wird von setMode und openConversation gemeinsam genutzt.
  async function renderConversation(id) {
    const el = ensureThread();
    if (!el) return;
    el.innerHTML = '';
    history = [];
    let turns = [];
    if (id) {
      try {
        const r = await fetch(`/conversations/${encodeURIComponent(id)}`);
        const j = await r.json();
        turns = j.turns || [];
      } catch (e) { turns = []; }
    }
    for (const t of turns) {
      addThreadTurn(t.role === 'you' ? 'you' : 'jarvis', t.text);
      history.push({ role: t.role === 'you' ? 'user' : 'assistant', content: t.text });
    }
    if (history.length > 40) history = history.slice(-40);
    if (el.children.length) el.scrollTop = el.scrollHeight;
    syncWelcome();
  }

  function syncWelcome() {
    if (!threadEl) return;
    chatRootEl.classList.toggle('has-content', threadEl.children.length > 0);
  }

  // Sidebar list — backed by the real per-conversation store.
  async function loadConversationList() {
    if (!chatListEl) return;
    let list = [];
    try {
      const r = await fetch('/conversations');
      const j = await r.json();
      list = (j.conversations || []).filter((c) => isModeConv(activeMode, c.id));
    } catch (e) { list = []; }
    chatListEl.innerHTML = '';
    if (!list.length) {
      const d = document.createElement('div');
      d.className = 'js-chat-item';
      d.style.color = C.textDim;
      d.style.cursor = 'default';
      d.textContent = 'No conversations yet';
      chatListEl.appendChild(d);
      return;
    }
    for (const conv of list) {
      const el = document.createElement('div');
      el.className = 'js-chat-item';
      if (conv.id === currentConversationId) el.classList.add('selected');
      const ico = document.createElement('span');
      ico.className = 'js-ico';
      ico.innerHTML = ICONS.chat;
      const txt = document.createElement('span');
      txt.className = 'js-txt';
      txt.textContent = conv.title || 'New chat';
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
    localStorage.setItem(modeKey(activeMode), id);
    await renderConversation(id);
    loadConversationList();
  }

  function startNewConversation() {
    currentConversationId = activeMode + '-' + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
    localStorage.setItem(modeKey(activeMode), currentConversationId);
    history = [];
    clearThreadUI();
    loadConversationList();
  }

  function wireUi() {
    $('.js-new', uiEl).addEventListener('click', startNewConversation);
    // Projects gibt es (noch) nicht als echtes Feature — nur der Button, wie
    // angefragt. Ein Klick zeigt das ehrlich statt so zu tun, als würde
    // etwas passieren.
    $('.js-projects', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      const btn = e.currentTarget;
      const existing = btn.nextElementSibling && btn.nextElementSibling.classList.contains('js-projects-note') ? btn.nextElementSibling : null;
      if (existing) { existing.remove(); return; }
      const note = document.createElement('div');
      note.className = 'js-projects-note';
      note.textContent = 'Projekte gibt es noch nicht — kommt später.';
      note.style.cssText = `padding:6px 12px 2px;font-size:12px;color:${C.textDim};`;
      btn.insertAdjacentElement('afterend', note);
    });

    // Chat/Code-Toggle
    uiEl.querySelectorAll('.js-pill').forEach((p) => {
      p.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        setMode(p.dataset.mode);
      });
    });

    if (sendBtn) sendBtn.addEventListener('click', (e) => { e.preventDefault(); sendFromComposer(); });
    if (composerInput) {
      composerInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendFromComposer(); }
      });
      composerInput.addEventListener('input', () => {
        composerInput.classList.toggle('is-empty', composerInput.innerText.trim().length === 0);
        if (sendBtn) sendBtn.disabled = !canSendNow();
      });
    }
    if (speechBtn) speechBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); speechMode ? exitSpeech() : enterSpeech(); });
    if (noteBtn) noteBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); setDictating(!dictating); });
    if (uploadBtn) uploadBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); if (fileInput) fileInput.click(); });
    if (settingsBtn) settingsBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); openSettings(); });
    const closeSettingsBtn = $('.js-settings-close', settingsSheetEl);
    if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', closeSettings);
    if (settingsSheetEl) settingsSheetEl.addEventListener('click', (e) => { if (e.target === settingsSheetEl) closeSettings(); });

    // Code-Verzeichnis speichern
    const codeDirInput = $('.js-code-dir-input', settingsSheetEl);
    const codeDirSave = $('.js-code-dir-save', settingsSheetEl);
    if (codeDirSave && codeDirInput) {
      codeDirSave.addEventListener('click', async () => {
        const v = codeDirInput.value.trim();
        if (!v) return;
        try {
          await fetch('/code/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: v }) });
          if (codeDirEl) { codeDirEl.textContent = v; codeDirEl.title = v; }
        } catch (e) {}
      });
    }

    if (modelBtnEl) modelBtnEl.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleModelMenu(); });
    window.addEventListener('click', () => { if (modelMenuEl) modelMenuEl.style.display = 'none'; });

    // Sprachmodus-Bottom-Leiste
    if (spMuteBtn) spMuteBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); muted = !muted; updateMuteIcon(); if (muted) stopListening(); else startListening(); });
    if (spStopBtn) spStopBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); stopSpeech(); });
    if (spSendBtn) spSendBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); const t = composerInput ? composerInput.innerText.trim() : ''; if (t) sendMessage(t); });
    if (spChatBtn) spChatBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); exitSpeech(); });

    fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.style.display = 'none';
    fileInput.addEventListener('change', async () => {
      const files = fileInput.files ? [...fileInput.files] : [];
      fileInput.value = '';
      if (!files.length) return;
      const results = await Promise.all(files.map(readAttachedFile));
      results.forEach((r, i) => { if (r.image) pendingImages.push({ name: files[i].name, image: r.image }); });
      // Bilder bekommen nur die Vorschau-Kachel, keinen Text ins Eingabefeld
      // — die Kachel zeigt ja schon, was angehängt ist. Nur Text-/andere
      // Dateien (kein `.image`) landen weiterhin als Text im Eingabefeld,
      // weil die gar keine visuelle Vorschau haben.
      const textResults = results.filter((r) => !r.image);
      if (textResults.length && composerInput) {
        const base = composerInput.innerText.trim();
        const attach = textResults.map((r) => r.text).join('\n\n');
        composerInput.innerText = base ? base + '\n\n' + attach : attach;
        composerInput.classList.remove('is-empty');
      }
      renderAttachPreviews();
    });
    document.body.appendChild(fileInput);

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
    if (!threadEl) { const m = $('.js-thread', uiEl); if (m) threadEl = m; }
    return threadEl;
  }
  function showThread() {}

  function addThreadTurn(role, text, images) {
    const el = ensureThread();
    if (!el) return { classList: { add(){}, remove(){}, toggle(){} }, textContent: '' };
    const row = document.createElement('div');
    row.className = 'js-turn ' + (role === 'you' ? 'js-you' : 'js-jarvis');
    if (images && images.length) {
      const imgRow = document.createElement('div');
      imgRow.style.cssText = `display:flex;gap:6px;flex-wrap:wrap;${text ? 'margin-bottom:8px;' : ''}`;
      imgRow.innerHTML = images.map((src) => `<img src="${src}" style="width:64px;height:64px;object-fit:cover;border-radius:8px;" />`).join('');
      row.appendChild(imgRow);
    }
    const inner = document.createElement('div');
    inner.className = 'js-text';
    inner.textContent = text;
    row.appendChild(inner);
    el.appendChild(row);
    el.scrollTop = el.scrollHeight;
    syncWelcome();
    return inner;
  }

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
    if ((!text && !pendingImages.length) || busy) return;
    // Sofort abgreifen und leeren: ein Bild, das während dieses laufenden
    // Requests noch angehängt wird, gehört zum NÄCHSTEN Turn, nicht zu
    // diesem hier.
    const imagesForThisTurn = pendingImages.map((att) => att.image);
    pendingImages = [];
    renderAttachPreviews();
    if (composerInput) { composerInput.innerText = ''; composerInput.classList.remove('is-empty'); }
    showThread();
    progressHostEl = null; // neue Runde eigener Fortschrittsblöcke
    addThreadTurn('you', text, imagesForThisTurn);
    const said = addThreadTurn('jarvis', '');
    said.classList.add('thinking');
    said.textContent = '';
    setBusy(true);
    stopListening();   // während Jarvis antwortet nicht mithören (Echo-Schutz)
    noteSpeechReply('');
    setSpeechStatus('Denke');

    const parts = [];
    let fullText = '';
    turnAborted = false;
    abortController = new AbortController();
    activeReader = null;
    currentTurnId = String(++turnCounter);
    try {
      const resp = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortController.signal,
        body: JSON.stringify({ message: text, history, turn_id: currentTurnId, mode: activeMode, conversation_id: ensureConversationId(), images: imagesForThisTurn }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const reader = resp.body.getReader();
      activeReader = reader;
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
            noteSpeechReply(parts.join(' '));
          } else if (evt.type === 'audio') {
            // Sprache NUR im Sprachmodus abspielen; in allen anderen Modi
            // (Text-/Diktat) wird vertonter Text verworfen — Jarvis spricht
            // ausschließlich, wenn der Sprachmodus aktiv ist.
            if (speechMode) enqueueClip(base64ToBlob(evt.audio, evt.mime || 'audio/mpeg'));
          } else if (evt.type === 'done') {
            fullText = evt.full_text || '';
          }
        }
      }
    } catch (err) {
      // Abbruch durch den Stop-Button ist KEIN Fehler — keine Meldung anzeigen.
      if (turnAborted) { fullText = fullText || ''; }
      else if (!fullText) { const fb = "I can't reach my language model right now. Is LM Studio running with Gemma loaded?"; fullText = fb; said.classList.remove('thinking'); said.textContent = fb; }
    }
    activeReader = null;
    abortController = null;
    if (turnAborted) {
      // abgebrochen: keine Historie, Status zurück in den Bereit-Zustand
      turnAborted = false;
      setBusy(false);
      resumeListening();
      if (speechMode) setSpeechStatus('Bereit');
      return;
    }
    if (fullText) {
      history.push({ role: 'user', content: text });
      history.push({ role: 'assistant', content: fullText });
      if (history.length > 40) history = history.slice(-40);
    }
    setBusy(false);
    // Ohne Sprachausgabe (Text-/Diktatmodus) sofort wieder zuhören; im
    // Sprachmodus übernimmt drainAudioQueue das nach dem letzten Clip.
    if (!audioDraining && !audioQueue.length) resumeListening();
    loadConversationList();
    setTimeout(loadConversationList, 2500);
  }

  function sendFromComposer() {
    const text = composerInput ? composerInput.innerText.trim() : '';
    if (text || pendingImages.length) sendMessage(text);
  }

  // ------------------------------------------------------ panel / Fortschritt
  /* Builds und andere Tool-Aktionen laufen im Hintergrund (async) und pinken
     ihre Fortschritte über den /ws-Kanal: "task" (Status-Lebenszyklus),
     "files", "code", "notify", "markdown", "link", "action". Ohne diesen
     Handler bliebe davon nichts im Interface sichtbar — genau das war
     "verbose fehlt". Die Task-Status werden je id aktualisiert (started ->
     done/failed), damit sie sich nicht stapeln. */
  let progressHostEl = null;
  let panelSock = null;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function openPanelSocket() {
    if (panelSock) return;
    try {
      panelSock = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    } catch (e) { return; }
    panelSock.onmessage = (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg && msg.type === 'panel' && msg.item) renderPanelItem(msg.item);
    };
    panelSock.onclose = () => { panelSock = null; };
    panelSock.onerror = () => { try { panelSock.close(); } catch (e) {} };
  }

  function progressHost() {
    const el = ensureThread();
    if (!el) return null;
    if (!progressHostEl || !progressHostEl.isConnected) {
      progressHostEl = document.createElement('div');
      progressHostEl.className = 'js-progress';
      progressHostEl.style.cssText = `max-width:760px;margin:0 auto 26px;display:flex;flex-direction:column;gap:10px;font-family:${C.font};`;
      el.appendChild(progressHostEl);
      el.scrollTop = el.scrollHeight;
    }
    return progressHostEl;
  }

  function scrollThread() {
    const el = ensureThread();
    if (el) el.scrollTop = el.scrollHeight;
  }

  function renderPanelItem(item) {
    const host = progressHost();
    if (!host) return;
    const kind = item.kind;

    if (kind === 'task' || kind === 'action') {
      // Ein Lebenszyklus (started -> done/failed) lebt in EINEM Block, keyed by id.
      const key = item.id || (item.action ? item.action : 't');
      let block = host.querySelector(`[data-progresstask="${key}"]`);
      if (!block) {
        block = document.createElement('div');
        block.setAttribute('data-progresstask', String(key));
        block.style.cssText = `display:flex;align-items:center;gap:9px;padding:10px 12px;border:1px solid ${C.border};border-radius:12px;background:${C.bgSoft};font-size:13px;`;
        host.appendChild(block);
      }
      const status = item.status || 'läuft';
      let col = C.accent, txt = item.label || (item.action ? item.action : 'Build'), tail = status;
      if (status === 'done') { col = '#3dbd7d'; txt = item.action ? (item.action + ' fertig') : 'fertig'; tail = ''; }
      else if (status === 'failed' || status === 'fehlgeschlagen') { col = '#e5534b'; txt = item.action ? (item.action + ' fehlgeschlagen') : 'fehlgeschlagen'; tail = ''; }
      else if (status === 'started') { txt = item.label || (item.action ? item.action : 'build'); tail = 'läuft'; }
      const detail = item.detail || '';
      block.innerHTML = `<span style="width:9px;height:9px;border-radius:50%;background:${col};flex:0 0 auto;"></span><span style="flex:1 1 auto;color:${C.text};">${escapeHtml(txt)}${detail ? ' <span style="color:' + C.textDim + ';">' + escapeHtml(detail) + '</span>' : ''}</span><span style="color:${col};font-size:12px;flex:0 0 auto;">${escapeHtml(tail)}</span>`;
      scrollThread();
      return;
    }

    if (kind === 'notify') {
      const b = document.createElement('div');
      b.style.cssText = `padding:10px 12px;border:1px solid ${C.border};border-left:3px solid ${C.accent};border-radius:10px;background:${C.bgSoft};font-size:13px;color:${C.text};`;
      b.textContent = item.text || '';
      host.appendChild(b);
      scrollThread();
      return;
    }

    if (kind === 'markdown') {
      const b = document.createElement('div');
      b.style.cssText = `padding:10px 12px;border:1px solid ${C.border};border-radius:10px;background:${C.bgSoft};font-size:13px;color:${C.textSoft};`;
      b.textContent = (item.title ? item.title + ' — ' : '') + (item.text || '');
      host.appendChild(b);
      scrollThread();
      return;
    }

    if (kind === 'link') {
      const b = document.createElement('button');
      b.textContent = item.title || 'Öffnen';
      b.style.cssText = `align-self:flex-start;padding:8px 14px;border:none;border-radius:10px;background:${C.accent};color:#fff;font-size:13px;cursor:pointer;font-family:${C.font};`;
      b.addEventListener('click', () => { try { window.open(item.url, '_blank'); } catch (e) {} });
      host.appendChild(b);
      scrollThread();
      return;
    }

    if (kind === 'code') {
      const wrap = document.createElement('details');
      wrap.className = 'js-code';
      wrap.style.cssText = `border:1px solid ${C.border};border-radius:10px;overflow:hidden;background:#0e1220;`;
      const sum = document.createElement('summary');
      sum.textContent = (item.title || 'Code') + (item.language ? ' · ' + item.language : '');
      sum.style.cssText = `padding:8px 12px;font-size:12px;color:${C.textDim};cursor:pointer;background:${C.bgSoft};`;
      const pre = document.createElement('pre');
      pre.style.cssText = `margin:0;padding:12px;overflow:auto;font-size:12px;line-height:1.5;`;
      const code = document.createElement('code');
      code.textContent = item.text || '';
      code.style.cssText = `font-family:${C.font + ',monospace'};color:#d8dee9;white-space:pre-wrap;word-break:break-word;`;
      pre.appendChild(code); wrap.appendChild(sum); wrap.appendChild(pre);
      wrap.open = true;
      host.appendChild(wrap);
      scrollThread();
      return;
    }

    if (kind === 'files') {
      const files = Array.isArray(item.files) ? item.files : [];
      const wrap = document.createElement('details');
      wrap.className = 'js-files';
      wrap.style.cssText = `border:1px solid ${C.border};border-radius:10px;overflow:hidden;background:${C.bgSoft};`;
      const sum = document.createElement('summary');
      sum.textContent = item.title || (files.length + ' Datei(en)');
      sum.style.cssText = `padding:8px 12px;font-size:12px;color:${C.textDim};cursor:pointer;`;
      const list = document.createElement('div');
      list.style.cssText = `padding:0 12px 12px;font-size:12px;color:${C.textSoft};white-space:pre-wrap;word-break:break-word;`;
      list.textContent = files.length ? files.slice(0, 40).join('\n') + (files.length > 40 ? '\n…' : '') : (item.path || '');
      wrap.appendChild(sum); wrap.appendChild(list);
      wrap.open = true;
      host.appendChild(wrap);
      scrollThread();
      return;
    }

    // Unbekannte kind (z.B. image) — kleine Zeile, damit nichts verschluckt wird.
    const b = document.createElement('div');
    b.style.cssText = `padding:10px 12px;border:1px dashed ${C.border};border-radius:10px;font-size:12px;color:${C.textDim};`;
    b.textContent = item.title || String(kind);
    host.appendChild(b);
    scrollThread();
  }

  // ---------------------------------------------------------------- modelle
  // Bild-Anhänge (siehe readAttachedFile) brauchen ein vision-fähiges Modell
  // ("vlm" laut LM Studios eigener Klassifikation, siehe
  // llm_client.list_model_capabilities) — modelCapsMap merkt sich das pro
  // Modell-Id, currentModelSupportsVision spiegelt das gerade aktive.
  let modelCapsMap = {};
  let currentModelSupportsVision = false;
  function applyModelCaps(j) {
    modelCapsMap = j.model_caps || {};
    currentModelSupportsVision = (j.current_caps || []).includes('vision');
  }
  function selectModelCaps(id) {
    currentModelSupportsVision = (modelCapsMap[id] || []).includes('vision');
  }

  let lastModelsList = null;  // Cache: sofort anzeigen statt bei jedem Klick auf den Netzwerk-Roundtrip zu warten
  function positionModelMenu() {
    if (!modelMenuEl || !modelBtnEl) return;
    const wrap = modelMenuEl.parentElement;
    if (!wrap) return;
    const wrapRect = wrap.getBoundingClientRect();
    const btnRect = modelBtnEl.getBoundingClientRect();
    const menuWidth = 220;
    // Am linken Rand des Buttons ausgerichtet (nicht am rechten) — sitzt
    // dadurch direkt über dem ausgewählten Modellnamen statt weiter links.
    let left = btnRect.left - wrapRect.left;
    left = Math.max(0, Math.min(left, wrapRect.width - menuWidth));
    modelMenuEl.style.left = left + 'px';
  }
  function renderModelMenu(models) {
    modelMenuEl.innerHTML = '';
    if (!models.length) {
      const d = document.createElement('div');
      d.textContent = 'No models — LM Studio running?';
      d.style.cssText = `padding:10px 14px;font-size:13px;color:${C.textDim};`;
      modelMenuEl.appendChild(d);
      return;
    }
    for (const m of models) {
      const b = document.createElement('button');
      b.textContent = m.id;
      b.style.cssText = `display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`;
      b.onmouseenter = () => { b.style.background = C.bgHover; };
      b.onmouseleave = () => { b.style.background = 'none'; };
      b.addEventListener('click', async (e) => {
        e.stopPropagation();
        modelMenuEl.style.display = 'none';
        setModelLabel(m.id);
        selectModelCaps(m.id);
        try { await fetch('/models/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: m.id }) }); } catch (e2) {}
      });
      modelMenuEl.appendChild(b);
    }
  }
  async function toggleModelMenu() {
    if (!modelMenuEl) return;
    const open = modelMenuEl.style.display !== 'none';
    if (open) { modelMenuEl.style.display = 'none'; return; }
    // Sofort öffnen — mit dem letzten bekannten Stand, falls vorhanden —
    // statt erst auf den fetch zu warten. Vorher fühlte sich ein Klick
    // wirkungslos an, solange /models noch unterwegs war, und ein zweiter
    // Klick währenddessen stieß einen weiteren parallelen fetch an.
    if (lastModelsList) renderModelMenu(lastModelsList);
    else { modelMenuEl.innerHTML = `<div style="padding:10px 14px;font-size:13px;color:${C.textDim};">Lädt…</div>`; }
    positionModelMenu();
    modelMenuEl.style.display = 'block';
    try {
      const r = await fetch('/models');
      const j = await r.json();
      const models = (j.models || []).map((m) => ({ id: m }));
      applyModelCaps(j);
      if (j.current) setModelLabel(j.current);
      lastModelsList = models;
      if (modelMenuEl.style.display !== 'none') { renderModelMenu(models); positionModelMenu(); }
    } catch (e) {
      if (!lastModelsList) renderModelMenu([]);
    }
  }

  function setModelLabel(id) {
    const short = String(id).split('/').pop();
    if (modelEl) modelEl.textContent = short;
  }

  // ------------------------------------------------------------- code-tab
  /* Der Code-Tab treibt headless OpenCode (opencode run --format json) über
     einen WebSocket; die Events werden als eigene Chat-Antwort gerendert —
     kein Terminal, keine Raw-TUI. opencode braucht ~20k Context-Token, daher
     zeigt das Modell-Dropdown die geladene Context-Größe und warnt zu kleine
     Modelle (Exceed-context-Fehler würde LM Studio sonst still schlucken). */

  // ------------------------------------------------------------- code (terminal)
  /* Der Code-Tab rendert die echte opencode-TUI in einem eingebetteten
     xterm.js-Terminal. Der Server spawnt `opencode <dir>` auf einem PTY und
     streamt die rohen Bytes über /code/tty/ws (Binär-Frames). Tastendrücke
     gehen als Binär-Frames zurück, Resize als {"type":"resize"}. opencode
     wählt sein Modell selbst über die TUI — es gibt kein JARVIS-Modell-Dropdown
     mehr, nur das Arbeitsverzeichnis (klickbar → Einstellungen) und einen
     Neustart-Button. */
  function buildCodeView() {
    if (codeViewEl) return;
    if (!uiEl) return;
    codeViewEl = $('.js-codeview', uiEl);
    codeTermEl = $('.js-code-terminal', uiEl);
    codeDirEl = $('.js-code-dir', uiEl);
    codeStatusLabelEl = $('.js-code-status-label', uiEl);
    codeDotEl = $('.js-code-dot', uiEl);
    codeRestartBtn = $('.js-code-restart', uiEl);

    if (typeof Terminal === 'undefined' || !codeTermEl) {
      if (codeTermEl) {
        codeTermEl.innerHTML = '<div style="padding:24px;color:#5c6370;font-size:13px;">xterm.js nicht geladen.</div>';
      }
      return;
    }

    codeTerm = new Terminal({
      cursorBlink: true,
      fontFamily: '"Menlo","Monaco","DejaVu Sans Mono","Courier New",monospace',
      fontSize: 13,
      lineHeight: 1.3,
      scrollback: 5000,
      theme: {
        background: '#12121c', foreground: '#d8dee9', cursor: '#6aa6ff',
        cursorAccent: '#12121c', selectionBackground: '#3b4261',
        black: '#1b1b27', red: '#e5534b', green: '#3dbd7d', yellow: '#e5a50a',
        blue: '#6aa6ff', magenta: '#c586c0', cyan: '#56b6c2', white: '#d8dee9',
        brightBlack: '#5c6370', brightRed: '#ff6b6b', brightGreen: '#4ce0a2',
        brightYellow: '#ffc857', brightBlue: '#9dbaff', brightMagenta: '#e79ce0',
        brightCyan: '#6fe0e6', brightWhite: '#ffffff',
      },
    });
    codeFit = new window.FitAddon.FitAddon();
    codeTerm.loadAddon(codeFit);
    codeTerm.open(codeTermEl);
    codeTerm.onData((data) => sendCodeInput(data));
    if (codeRestartBtn) codeRestartBtn.addEventListener('click', (e) => { e.preventDefault(); restartCodeTerminal(); });
    if (codeDirEl) codeDirEl.addEventListener('click', (e) => { e.preventDefault(); openSettings(); });
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => fitCodeTerminal());
      ro.observe(codeTermEl);
    }
    fitCodeTerminal();
    updateCodeStatus('verbinde…', '#e5a50a');
  }

  function sendCodeInput(data) {
    if (!codeWs || !codeWsOpen) return;
    try { codeWs.send(new TextEncoder().encode(data)); } catch (e) {}
  }

  function fitCodeTerminal() {
    if (!codeFit || !codeTerm) return;
    try { codeFit.fit(); } catch (e) {}
    if (codeWs && codeWsOpen && codeTerm) {
      try { codeWs.send(JSON.stringify({ type: 'resize', cols: codeTerm.cols, rows: codeTerm.rows })); } catch (e) {}
    }
  }

  function updateCodeStatus(label, color) {
    if (codeStatusLabelEl) codeStatusLabelEl.textContent = label;
    if (codeDotEl) codeDotEl.style.background = color || '#e5a50a';
  }
  function setCodeRestartBtn(show) {
    if (codeRestartBtn) codeRestartBtn.style.display = show ? 'inline-flex' : 'none';
  }

  async function loadCodeStatus() {
    try {
      const r = await fetch('/code/status');
      const j = await r.json();
      if (j.dir && codeDirEl) { codeDirEl.textContent = j.dir; codeDirEl.title = j.dir; }
    } catch (e) {}
  }

  function ensureCodeSocket() {
    if (codeWsOpen || codeWs) return;
    if (codeReconnectTimer) { clearTimeout(codeReconnectTimer); codeReconnectTimer = null; }
    openCodeSocket();
  }

  function openCodeSocket() {
    if (codeWsOpen || codeWs) return;
    try {
      codeWs = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/code/tty/ws');
    } catch (e) { codeWs = null; scheduleCodeReconnect(); return; }
    codeWs.binaryType = 'arraybuffer';
    codeWs.onopen = () => {
      codeWsOpen = true; codeExited = false;
      updateCodeStatus('verbunden', '#3dbd7d');
      setCodeRestartBtn(false);
      // Frischer opencode-Prozess: Terminal zurücksetzen und Steuergröße senden.
      if (codeTerm) codeTerm.reset();
      fitCodeTerminal();
    };
    codeWs.onmessage = (ev) => {
      if (typeof ev.data === 'string') { handleCodeControl(ev.data); return; }
      if (ev.data instanceof ArrayBuffer && codeTerm) codeTerm.write(new Uint8Array(ev.data));
    };
    codeWs.onclose = () => {
      codeWsOpen = false; codeWs = null;
      if (codeExited) {
        updateCodeStatus('beendet', '#e5534b');
        setCodeRestartBtn(true);
      } else {
        updateCodeStatus('verbindung verloren', '#e5a50a');
        setCodeRestartBtn(true);
        scheduleCodeReconnect();
      }
    };
    codeWs.onerror = () => { try { codeWs.close(); } catch (e) {} };
  }

  function handleCodeControl(text) {
    let msg; try { msg = JSON.parse(text); } catch (e) { return; }
    if (msg.type === 'exit') {
      codeExited = true;
      updateCodeStatus('beendet (Code ' + String(msg.code == null ? '?' : msg.code) + ')', '#e5534b');
      setCodeRestartBtn(true);
    }
  }

  function scheduleCodeReconnect() {
    if (codeReconnectTimer || activeMode !== 'code') return;
    updateCodeStatus('verbinde…', '#e5a50a');
    codeReconnectTimer = setTimeout(() => { codeReconnectTimer = null; openCodeSocket(); }, 2000);
  }

  function restartCodeTerminal() {
    codeExited = false;
    // Alte Verbindung (falls noch offen) ablösen, ohne dass onclose neu verbindet.
    const old = codeWs;
    codeWs = null; codeWsOpen = false;
    if (old) { old.onclose = null; old.onerror = null; old.onmessage = null; try { old.close(); } catch (e) {} }
    if (codeReconnectTimer) { clearTimeout(codeReconnectTimer); codeReconnectTimer = null; }
    if (codeTerm) codeTerm.reset();
    updateCodeStatus('verbinde…', '#e5a50a');
    openCodeSocket();
  }

  // ---------------------------------------------------------------- settings
  /* Echte Einstellungen statt Fake-Profil: ein Sheet mit der Modell-Auswahl. */
  async function openSettings() {
    if (!settingsSheetEl) return;
    settingsSheetEl.style.display = 'flex';
    // Code-Verzeichnis aus /code/status vorbelegen.
    try {
      const r = await fetch('/code/status');
      const j = await r.json();
      const din = $('.js-code-dir-input', settingsSheetEl);
      if (din && j.dir) din.value = j.dir;
    } catch (e) {}
    if (settingsModelsEl) {
      settingsModelsEl.innerHTML = '';
      const load = async () => {
        let models = [];
        try {
          const r = await fetch('/models');
          const j = await r.json();
          models = j.models || [];
          applyModelCaps(j);
          if (j.current) setModelLabel(j.current);
        } catch (e) { models = []; }
        if (!models.length) {
          const d = document.createElement('div');
          d.textContent = 'No models — LM Studio running?';
          d.style.cssText = `padding:10px 14px;font-size:13px;color:${C.textDim};`;
          settingsModelsEl.appendChild(d);
          return;
        }
        for (const m of models) {
          const b = document.createElement('button');
          b.textContent = m;
          b.style.cssText = `display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;`;
          b.onmouseenter = () => { b.style.background = C.bgHover; };
          b.onmouseleave = () => { b.style.background = 'none'; };
          b.addEventListener('click', () => {
            setModelLabel(m);
            selectModelCaps(m);
            try { fetch('/models/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: m }) }); } catch (e2) {}
          });
          settingsModelsEl.appendChild(b);
        }
      };
      load();
    }
  }
  function closeSettings() {
    if (settingsSheetEl) settingsSheetEl.style.display = 'none';
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

  // Der Mikrofon-Stream versorgt nur noch den VAD (Orb-Pulsation + Barge-in).
  // Echo-Unterdrückung ist hier Pflicht: Die Web-Speech-Erkennung läuft im
  // Sprachmodus kontinuierlich und würde Jarvis' eigene Antwort mitschreiben,
  // wenn der Stream nicht gegengekoppelt wäre.
  async function ensureMic() {
    if (micReady) return micStream;
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    micReady = true;
    setupVad(micStream);
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
  // ------------------------------------------- Sprachmodus-Beschriftung
  function showSpeechCaption() {
    if (speechCaptionEl) speechCaptionEl.style.display = 'flex';
  }
  function hideSpeechCaption() {
    if (speechCaptionEl) speechCaptionEl.style.display = 'none';
  }
  function setSpeechStatus(s) {
    if (spcStatusEl) spcStatusEl.textContent = s;
  }
  function noteSpeechWords(t) {
    if (spcUserEl) spcUserEl.textContent = t || '…';
  }
  function noteSpeechReply(t) {
    if (spcReplyEl) { spcReplyEl.textContent = t || ''; spcReplyEl.style.minHeight = t ? '' : '0'; }
  }

  // ------------------------------------------- Web-Speech-Erkennung
  // Zurück zur alten, eingebauten Browser-Erkennung statt lokalem Whisper:
  // Chrome transkribiert selbst (de-DE, kontinuierlich, Zwischenergebnisse),
  // das Backend /stt wird nicht mehr angerufen. Chrome stoppt die Erkennung
  // nach Stille von selbst — onend startet sie neu, solange wir noch zuhören
  // sollen (Sprachmodus/Diktat aktiv, nicht stumm, nicht mitten in einer
  // Antwort).
  function initRecognition() {
    if (!SpeechRecognitionImpl) {
      if (speechBtn) speechBtn.title = 'Spracherkennung braucht Chrome';
      return null;
    }
    const rec = new SpeechRecognitionImpl();
    rec.lang = 'de-DE';
    rec.continuous = true;
    rec.interimResults = true;

    rec.onstart = () => { if (speechMode && !busy) setSpeechStatus('Hören'); };

    rec.onresult = (event) => {
      let text = '';
      for (let i = event.resultIndex; i < event.results.length; i++) text += event.results[i][0].transcript;
      text = text.trim();
      if (!text) return;
      const final = event.results[event.results.length - 1].isFinal;

      if (speechMode) {
        noteSpeechWords(text);
        if (final) { setSpeechStatus('Denke'); sendMessage(text); }
      } else if (dictating && composerInput) {
        // Diktat: Zwischenergebnisse live ins Eingabefeld, aufbauend auf dem
        // gesicherten Stand (dictBase); abgeschlossene Segmente rücken auf.
        if (dictBase === null) dictBase = composerInput ? composerInput.innerText.trim() : '';
        const composed = dictBase ? dictBase + ' ' + text : text;
        composerInput.innerText = composed;
        composerInput.classList.remove('is-empty');
        if (sendBtn) sendBtn.disabled = false;
        if (final) dictBase = composed;
      }
    };

    rec.onerror = (event) => {
      if (event.error === 'no-speech' || event.error === 'aborted') return;
      if (event.error === 'not-allowed') micReady = false;
    };

    // Chrome beendet die Erkennung nach Stille auch bei continuous=true —
    // wiederholen, außer es ist gerade nicht gewünscht.
    rec.onend = () => {
      if (!muted && !busy && (speechMode || dictating) && micReady) setTimeout(startListening, 250);
    };

    return rec;
  }

  function startListening() {
    if (!recognition || muted || busy || !(speechMode || dictating)) return;
    try { recognition.start(); } catch (_) {}
  }
  function stopListening() {
    if (recognition) { try { recognition.stop(); } catch (_) {} }
  }
  function resumeListening() {
    if (!muted && micReady && (speechMode || dictating)) startListening();
  }

  function vadTick() {
    if (!vadAnalyser || !vadData || muted) return;
    const rms = rmsFrom(vadAnalyser, vadData);

    if (!busy) {
      vadNoiseFloor = vadNoiseFloor * 0.98 + rms * 0.02;
      vadAbove = 0;
      return;
    }

    // Barge-in: solange Jarvis antwortet, unterbricht eine anhaltende Stimme
    // den Turn. Der Stream ist echo-kompensiert, also ist ein Pegel dort echte
    // Person — Jarvis' eigene Ausgabe ist bereits abgezogen.
    const threshold = Math.max(vadNoiseFloor * 2.4, 0.025);
    vadAbove = rms > threshold ? vadAbove + 1 : 0;

    if (vadAbove >= 3) {   // ~240 ms anhaltend
      vadAbove = 0;
      stopSpeech();
      resumeListening();
    }
  }

  function updateMuteIcon() {
    if (!spMuteBtn) return;
    spMuteBtn.innerHTML = muted ? ICONS.micOff : ICONS.mic;
    spMuteBtn.title = muted ? 'Mikrofon an' : 'Mikrofon aus';
  }

  // Speech-Bar über dem Chat-Bereich zentrieren (gleicher Mittelpunkt wie der
  // Orb), nicht über dem Vollbild — die Sidebar verschiebt den Chat-Bereich.
  function layoutSpeechBar() {
    if (!speechBarEl || !chatRootEl) return;
    const rect = chatRootEl.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const delta = cx - window.innerWidth / 2;
    const inner = speechBarEl.firstElementChild;
    if (inner) inner.style.transform = 'translateX(' + delta + 'px)';
  }

  function enterSpeech() {
    ensureMic().then(() => {
      speechMode = true;
      showOrb();
      showSpeechCaption();
      setSpeechStatus('Bereit');
      startListening();
      if (composerTray) composerTray.style.display = 'none';
      if (chatRootEl) chatRootEl.classList.add('js-speech-active');
      if (speechBarEl) speechBarEl.style.display = 'flex';
      layoutSpeechBar();
      if (speechBtn) speechBtn.classList.add('on');
    }).catch(() => {
      if (speechBtn) speechBtn.title = 'Microphone denied — typing still works';
    });
  }
  function exitSpeech() {
    speechMode = false;
    stopListening();
    hideOrb();
    hideSpeechCaption();
    noteSpeechWords('…');
    if (composerTray) composerTray.style.display = '';
    if (chatRootEl) chatRootEl.classList.remove('js-speech-active');
    if (speechBarEl) speechBarEl.style.display = 'none';
    if (speechBtn) speechBtn.classList.remove('on');
  }

  // Diktat-Modus: transkribiert ins Eingabefeld. Die Zwischenergebnisse der
  // Web-Speech-Erkennung erscheinen live; fertige Segmente werden zur Basis
  // für das nächste (dictBase).
  function setDictating(should) {
    dictating = should;
    if (should && !micReady) {
      ensureMic().then(() => {
        if (!dictating) return;
        if (noteBtn) noteBtn.classList.add('on');
        if (noteBtn) noteBtn.title = 'Dictation off';
        dictBase = null;
        startListening();
      }).catch(() => {
        if (noteBtn) noteBtn.title = 'Microphone denied';
        dictating = false;
      });
      return;
    }
    dictating = should;
    if (noteBtn) noteBtn.classList.toggle('on', should);
    if (noteBtn) noteBtn.title = should ? 'Dictation off' : 'Dictate';
    if (should) { dictBase = null; startListening(); } else stopListening();
  }

    // ------------------------------------------- 3D-Punktkugel (Sprachmodus)
  function makeSpherePoints(n) {
    // Fibonacci-Kugel: gleichmäßige Verteilung, ohne Pole zu klumpen.
    const pts = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const t = i / n;
      const y = 1 - t * 2;                        // +1 … -1
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = golden * i;
      pts.push({ x: Math.cos(th) * r, y, z: Math.sin(th) * r });
    }
    return pts;
  }
  let orbPoints = makeSpherePoints(300);   // weniger Punkte → klare, ruhige Kugel
  let orbRotY = 0, orbRotX = -0.38;

  // Eine konstante Farbe für alle Zustände — die Status werden nur über die
  // BEWEGUNG erzählt (wie in der alten JARVIS-Kugel), nicht über Farbwechsel.
  // Ausnahme: stummgeschaltet wird ausdrücklich grau eingefärbt, als klares
  // visuelles Signal, dass das Mikrofon gerade nichts aufnimmt.
  const ORB_COLOR = C.accent;
  const ORB_MUTED_COLOR = '#8c877c';
  function currentOrbColor() { return muted ? ORB_MUTED_COLOR : ORB_COLOR; }

  // aktueller Orb-Zustand: jeder bekommt eine eigene Animation
  function orbStatus() {
    if (speaking) return 'speaking';
    if (busy) return 'thinking';
    if (speechMode && !muted) return 'listening';
    return 'idle';
  }

  function drawOrb(now) {
    const cw = orbCanvas.clientWidth, ch = orbCanvas.clientHeight;
    if (cw < 4 || ch < 4) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (orbCanvas.width !== cw * dpr || orbCanvas.height !== ch * dpr) { orbCanvas.width = cw * dpr; orbCanvas.height = ch * dpr; }
    orbCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    orbCtx.clearRect(0, 0, cw, ch);
    // Zentrum über dem Chat-Bereich (rechts der Sidebar)
    const rect = chatRootEl ? chatRootEl.getBoundingClientRect() : { left: 0, top: 0, width: cw, height: ch };
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const R = Math.min(rect.width, rect.height) * 0.10;   // viel kleinere Kugel
    const lvl = orbLevel || 0;
    const status = orbStatus();
    const t = now / 1000;

    // Rotationsgeschwindigkeit je Zustand — spürbar schneller als zuvor
    let rotSpeed = 0.005;
    if (status === 'listening') rotSpeed = 0.006 + lvl * 0.03;
    else if (status === 'thinking') rotSpeed = 0.011;
    else if (status === 'speaking') rotSpeed = 0.013;
    orbRotY += rotSpeed;
    orbRotX = -0.38 + Math.sin(t * 1.5) * 0.05;   // zügigeres Wanken

    // Denk-Sweep: ein Band wandert von oben nach unten (0 = oben … 1 = unten).
    // Dreieck-Welle, damit es ohne Sprung durchläuft — wie in der alten Kugel.
    let sweepT = -1;
    if (status === 'thinking') {
      const period = 0.9;
      const phase = (t % (period * 2)) / (period * 2);
      sweepT = phase < 0.5 ? phase * 2 : 2 - phase * 2;
    }

    const cosY = Math.cos(orbRotY), sinY = Math.sin(orbRotY);
    const cosX = Math.cos(orbRotX), sinX = Math.sin(orbRotX);

    // weicher Glow hinter der Kugel (eine Farbe, keine Status-Änderung —
    // außer stummgeschaltet, siehe currentOrbColor())
    const orbColor = currentOrbColor();
    const glow = orbCtx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.5);
    glow.addColorStop(0, orbColor + '22');
    glow.addColorStop(1, orbColor + '00');
    orbCtx.globalAlpha = 0.5;
    orbCtx.fillStyle = glow;
    orbCtx.beginPath();
    orbCtx.arc(cx, cy, R * 1.5, 0, Math.PI * 2);
    orbCtx.fill();

    orbCtx.fillStyle = orbColor;
    for (let i = 0; i < orbPoints.length; i++) {
      const p = orbPoints[i];
      const bx = p.x, by = p.y, bz = p.z;

      // POSITIONS-Dynamik: radialer Versatz je Punkt — die Punkte bewegen sich,
      // die Farbe bleibt gleich. Alle Wellen basieren auf der POSITION (nicht
      // auf Zufall), damit Nachbarpunkte kohärent zusammenlaufen statt
      // chaotisch zu zucken — wie in der alten Kugel.
      let dr = 0;
      if (status === 'idle') {
        // ruhiges Atmen + langsame kohärente Welle (ohne Zufall)
        const breathe = Math.sin(t * 1.4);
        const wave = Math.sin(bx * 2.1 + by * 1.8 + t * 1.1);
        dr = breathe * 0.03 + wave * 0.05;
      } else if (status === 'listening') {
        // Rippel: kohärente Welle über die Position, von der Lautstärke gesteuert
        const ripple = Math.sin(bx * 4 + t * 5.0) * Math.cos(by * 4 - t * 3.6);
        dr = lvl * 0.5 * ripple;
      } else if (status === 'thinking') {
        // Sweep-Band wandert von oben nach unten (Dreieck-Welle) und drückt
        // die Punkte darin nach außen; leichte kohärente Welle dazu
        const rowT = (1 - by) / 2;
        const sweep = sweepT >= 0 ? Math.exp(-Math.pow((rowT - sweepT) * 6, 2)) : 0;
        dr = 0.3 * sweep + 0.06 * Math.sin(bx * 2 + bz * 2 + t * 2.6);
      } else { // speaking — mehrere kohärente Wellen; jeder Punkt hat seinen
               // eigenen Wert, aber Bewegungen laufen als Wellen über die Fläche
        const rippleA = Math.sin(bx * 3.5 + t * 6.5) * Math.cos(by * 3.3 - t * 5.2);
        const rippleB = Math.sin(bz * 4.2 - t * 6.0);
        const rippleC = Math.sin((bx + bz) * 2.6 + t * 7.5);
        dr = 0.20 * rippleA + 0.15 * rippleB + 0.13 * rippleC;
      }
      const r = 1 + dr;
      const x = bx * r, y = by * r, z = bz * r;
      // Rotation um Y
      const x1 = x * cosY + z * sinY;
      const z1 = -x * sinY + z * cosY;
      // Rotation um X (Kippwinkel)
      const y1 = y * cosX - z1 * sinX;
      const z2 = y * sinX + z1 * cosX;
      const persp = 3.4;
      const scale = persp / (persp - z2);
      const sx = cx + x1 * R * scale;
      const sy = cy + y1 * R * scale;
      const depth = (z2 + 1) / 2;                 // 0 fern … 1 nah
      // fettere Punkte, dicht beieinander; Alpha nur = Tiefenausblendung
      const size = 1.4 + depth * 1.9;
      const alpha = 0.16 + depth * 0.55;
      orbCtx.globalAlpha = Math.min(1, Math.max(0, alpha));
      orbCtx.beginPath();
      orbCtx.arc(sx, sy, size, 0, Math.PI * 2);
      orbCtx.fill();
    }
    orbCtx.globalAlpha = 1;
  }

  // Pegel der gesprochenen Stimme aus dem TTS-Ausgangsanalysator — die Orb
  // pulsiert mit dem, was wirklich aus dem Lautsprecher kommt (nicht mit einem
  // erfundenen Wert). Leichte Verstärkung, damit die Rippel sichtbar werden.
  function speechLevel() {
    if (outputAnalyser && outBuf) {
      const r = rmsFrom(outputAnalyser, outBuf);
      return Math.min(1, r * 1.8);
    }
    return 0;
  }

  function orbLoop(now) {
    if (!orbVisible) return;
    // Zuletzt gesprochen wird beim „Hören" das Mikrofon gemessen, beim
    // „Sprechen" die eigene TTS-Ausgabe — alles dynamisch am echten Audio.
    const listening = speechMode && !muted && !busy && !speaking;
    const source = speaking ? speechLevel() : (listening ? getMicLevel() : 0);
    orbLevel = Math.max(0, orbLevel * 0.78 + source * 0.22);
    drawOrb(now);
    orbRaf = requestAnimationFrame(orbLoop);
  }

  function showOrb() {
    orbVisible = true;
    if (orbCanvas) orbCanvas.style.display = 'block';
    if (!orbRaf) orbRaf = requestAnimationFrame(orbLoop);
  }
  function hideOrb() {
    orbVisible = false;
    // orbRaf zurücksetzen, nicht nur orbVisible: orbLoop() bricht bei
    // orbVisible=false einfach mit `return` ab, OHNE einen neuen Frame
    // anzufordern — orbRaf behält dabei die alte (jetzt tote) Frame-ID.
    // Ohne den Reset hier sieht showOrb()'s `if (!orbRaf)`-Check die ID
    // fälschlich als "läuft noch" an und startet nie wieder einen neuen
    // requestAnimationFrame-Loop — die Kugel bleibt dann beim nächsten
    // Öffnen des Sprachmodus als eingefrorenes Standbild stehen (genau der
    // gemeldete "Animation hängt sich beim Unterbrechen auf"-Fall).
    if (orbRaf) { cancelAnimationFrame(orbRaf); orbRaf = 0; }
    // nicht nur die Animationsschleife stoppen, sondern den Canvas wirklich
    // ausblenden — sonst bleibt der letzte Frame als "Geister-Kugel" stehen.
    if (orbCanvas) { orbCanvas.style.display = 'none'; }
    if (orbCtx && orbCanvas) { const w = orbCanvas.clientWidth, h = orbCanvas.clientHeight; if (w && h) { orbCtx.setTransform(1,0,0,1,0,0); orbCtx.clearRect(0,0,w,h); } }
  }

  // ---------------------------------------------------------------- boot
  function boot() {
    buildUi();
    setMode(activeMode); // Sidebar befüllen + aktive Konversation des Modus laden
    recognition = initRecognition();
    document.title = 'Jarvis';
    orbCanvas = document.createElement('canvas');
    orbCanvas.id = 'jarvisOrb';
    orbCanvas.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;z-index:40;pointer-events:none;background:transparent;';
    document.body.appendChild(orbCanvas);
    orbCtx = orbCanvas.getContext('2d');
    const t = $('.js-side-toggle', uiEl);
    if (t) t.addEventListener('click', () => {
      const aside = $('.js-sidebar', uiEl);
      const open = aside.style.display !== 'none';
      aside.style.display = open ? 'none' : 'flex';
      const comp = $('.js-composer', uiEl);
      if (comp) comp.style.left = open ? '0' : '308px';
      if (orbCanvas) orbCanvas.style.left = open ? '0' : '308px';
      layoutSpeechBar();
    });
    window.addEventListener('resize', layoutSpeechBar);
    fetch('/models').then((r) => r.json()).then((j) => { applyModelCaps(j); if (j.current) setModelLabel(j.current); }).catch(() => {});
    openPanelSocket();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
