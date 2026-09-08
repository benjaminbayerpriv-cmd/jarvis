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
    audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/></svg>',
    paperclip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="18" height="18" x="3" y="3" rx="4" fill="currentColor"/></svg>',
    volume: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/></svg>',
    muted: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4.702a.7.7 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.7.7 0 0 0 11 19.298z"/><path d="m16.5 14.5 5-5"/><path d="m16.5 9.5 5 5"/></svg>',
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
    // Bewusst OHNE WebAudio-Routing (createMediaElementSource): das würde das
    // TTS durch den (ggf. gesperrten) AudioContext der Mikrofon-Einrichtung
    // leiten. Ist der Context im Sprachmodus "suspended", ist der gesamte
    // Output stumm — genau der "Supertonic geht im Sprachmodus nicht"-Fehler.
    // Direktes audio.play() hängt nur vom Autoplay-Gestenstatus ab und spielt
    // in jedem Modus gleich zuverlässig.
    const audio = new Audio(URL.createObjectURL(blob));
    return new Promise((resolve) => {
      let done = false;
      const finish = () => { if (done) return; done = true; clearTimeout(timer); resolve(); };
      const timer = setTimeout(finish, 4000);
      audio.onended = finish;
      audio.onerror = finish;
      audio.play().then(() => {}).catch(finish);
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
  let composerTray = null, composerInput = null, sendBtn = null, speechBtn = null, noteBtn = null;
  let uploadBtn = null, settingsBtn = null, modelEl = null, modelMenuEl = null, fileInput = null;
  let speechBarEl = null, spMuteBtn = null, spStopBtn = null, spSendBtn = null, spChatBtn = null;
  let settingsSheetEl = null, settingsModelsEl = null;

  // Sprachmodus + VAD + Diktat
  let speechMode = false, dictating = false, micReady = false, micStream = null, muted = false;
  let pcmNode = null, pcmSampleRate = 0, pcmRing = [], utterancePCM = null, utteranceStartedAt = 0;
  let silenceStreak = 0, vadAnalyser = null, vadData = null;
  let vadNoiseFloor = 0.01;

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
            <button class="js-pill" data-mode="code" title="Coming soon" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 10px;border-radius:8px;border:none;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,color .15s;">${ICONS.code}<span>Code</span></button>
          </div>
          <button class="js-new" style="display:flex;align-items:center;gap:8px;padding:9px 12px;background:${C.bgHover};border:1px solid ${C.border};border-radius:11px;color:${C.text};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s;">${ICONS.plus}<span>New conversation</span></button>
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
      </div>
      <div class="js-composer" style="position:absolute;left:308px;right:0;bottom:0;padding:0 24px 22px;background:linear-gradient(transparent,${C.bg} 55%);">
        <div style="max-width:760px;margin:0 auto;">
          <div style="background:${C.bgSoft};border:1px solid ${C.border};border-radius:18px;box-shadow:0 10px 34px rgba(0,0,0,.38);">
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
          <div class="js-modelmenu" style="display:none;margin-top:8px;background:${C.bgSoft};border:1px solid ${C.border};border-radius:12px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,.4);"></div>
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
        <button class="js-sp-mute" title="Mute" style="width:40px;height:40px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.volume}</button>
        <button class="js-sp-stop" title="Stop" style="width:40px;height:40px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.stop}</button>
        <button class="js-sp-send" title="Send" style="width:52px;height:52px;border-radius:50%;background:${C.accent};border:none;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.send}</button>
        <button class="js-sp-chat" title="Chat mode" style="width:40px;height:40px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.chat}</button>
      </div>
    `;
    document.body.appendChild(speechBarEl);

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
        <div style="padding:12px 16px 16px;border-top:1px solid ${C.border};font-size:12px;color:${C.textDim};">More settings coming soon.</div>
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
    settingsBtn = $('.js-settings', uiEl);
    modelEl = $('.js-model-label', uiEl);
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
      body.js-app-active > :not(#jsApp):not(#jarvisOrb):not(#jsSpeechbar):not(#jsSettingsSheet):not(script):not(style) { display:none !important; }
      body.js-app-active { overflow:hidden; }
      .js-sidebar button:focus-visible, .js-main button:focus-visible { outline:2px solid ${C.accent}; outline-offset:2px; }
      .js-editor:empty::before, .js-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-editor:focus::before { opacity:.7; }
      .js-side-toggle svg, .js-new svg, .js-upload svg, .js-note svg, .js-speech svg, .js-settings svg { width:16px; height:16px; display:block; }
      .js-upload svg, .js-note svg, .js-settings svg { width:18px; height:18px; }
      .js-speech svg, .js-send svg { width:18px; height:18px; display:block; }
      .js-sp-mute svg, .js-sp-stop svg, .js-sp-chat svg, .js-sp-send svg { width:20px; height:20px; display:block; }
      .js-pill svg { width:16px; height:16px; display:block; }
      .js-side-toggle:hover, .js-new:hover, .js-upload:hover, .js-note:hover, .js-model:hover, .js-settings:hover, .js-sp-mute:hover, .js-sp-stop:hover, .js-sp-chat:hover { background:${C.bgHover}; color:${C.text}; }
      .js-pill.active { background:${C.accent} !important; color:#fff !important; }
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
    `;
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------- wire UI
  function setMode(mode) {
    if (mode !== 'chat' && mode !== 'code') return;
    if (currentConversationId) localStorage.setItem(modeKey(activeMode), currentConversationId);
    activeMode = mode;
    const pills = uiEl ? uiEl.querySelectorAll('.js-pill') : [];
    pills.forEach((p) => p.classList.toggle('active', p.dataset.mode === mode));
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
        if (sendBtn) sendBtn.disabled = composerInput.innerText.trim().length === 0;
      });
    }
    if (speechBtn) speechBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); speechMode ? exitSpeech() : enterSpeech(); });
    if (noteBtn) noteBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); setDictating(!dictating); });
    if (uploadBtn) uploadBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); if (fileInput) fileInput.click(); });
    if (settingsBtn) settingsBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); openSettings(); });
    const closeSettingsBtn = $('.js-settings-close', settingsSheetEl);
    if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', closeSettings);
    if (settingsSheetEl) settingsSheetEl.addEventListener('click', (e) => { if (e.target === settingsSheetEl) closeSettings(); });

    if (modelEl) modelEl.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleModelMenu(); });
    window.addEventListener('click', () => { if (modelMenuEl) modelMenuEl.style.display = 'none'; });

    // Sprachmodus-Bottom-Leiste
    if (spMuteBtn) spMuteBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); muted = !muted; updateMuteIcon(); });
    if (spStopBtn) spStopBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); cancelRecording(); silenceStreak = 0; });
    if (spSendBtn) spSendBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); stopRecording(); });
    if (spChatBtn) spChatBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); exitSpeech(); });

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
    progressHostEl = null; // neue Runde eigener Fortschrittsblöcke
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
            if (evt.audio) await playClip(base64ToBlob(evt.audio, evt.mime || 'audio/mpeg'));
          } else if (evt.type === 'done') {
            fullText = evt.full_text || '';
          }
        }
      }
    } catch (err) {
      const fb = "I can't reach my language model right now. Is LM Studio running with Gemma loaded?";
      if (!fullText) { fullText = fb; said.classList.remove('thinking'); said.textContent = fb; }
    }
    if (fullText) {
      history.push({ role: 'user', content: text });
      history.push({ role: 'assistant', content: fullText });
      if (history.length > 40) history = history.slice(-40);
    }
    setBusy(false);
    loadConversationList();
    setTimeout(loadConversationList, 2500);
  }

  function sendFromComposer() {
    const text = composerInput ? composerInput.innerText.trim() : '';
    if (text) sendMessage(text);
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
      d.textContent = 'No models — LM Studio running?';
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

  // ---------------------------------------------------------------- settings
  /* Echte Einstellungen statt Fake-Profil: ein Sheet mit der Modell-Auswahl. */
  async function openSettings() {
    if (!settingsSheetEl) return;
    settingsSheetEl.style.display = 'flex';
    if (settingsModelsEl) {
      settingsModelsEl.innerHTML = '';
      const load = async () => {
        let models = [];
        try {
          const r = await fetch('/models');
          const j = await r.json();
          models = j.models || [];
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
      else { silenceStreak++; if (silenceStreak >= 14) { silenceStreak = 0; stopRecording(); } }
    }
  }

  function updateMuteIcon() {
    if (!spMuteBtn) return;
    spMuteBtn.innerHTML = muted ? ICONS.muted : ICONS.volume;
    spMuteBtn.title = muted ? 'Unmute' : 'Mute';
  }

  function enterSpeech() {
    ensureMic().then(() => {
      speechMode = true;
      showOrb();
      if (composerTray) composerTray.style.display = 'none';
      if (chatRootEl) chatRootEl.classList.add('js-speech-active');
      if (speechBarEl) speechBarEl.style.display = 'flex';
      if (speechBtn) speechBtn.classList.add('on');
    }).catch(() => {
      if (speechBtn) speechBtn.title = 'Microphone denied — typing still works';
    });
  }
  function exitSpeech() {
    speechMode = false;
    hideOrb();
    cancelRecording();
    if (composerTray) composerTray.style.display = '';
    if (chatRootEl) chatRootEl.classList.remove('js-speech-active');
    if (speechBarEl) speechBarEl.style.display = 'none';
    if (speechBtn) speechBtn.classList.remove('on');
  }

  // Diktat-Modus: transkribiert ins Eingabefeld.
  function setDictating(should) {
    if (should && !micReady) {
      ensureMic().then(() => {
        dictating = true;
        if (noteBtn) noteBtn.classList.add('on');
        if (noteBtn) noteBtn.title = 'Dictation off';
      }).catch(() => {
        if (noteBtn) noteBtn.title = 'Microphone denied';
        dictating = false;
      });
      return;
    }
    dictating = should;
    if (noteBtn) noteBtn.classList.toggle('on', should);
    if (noteBtn) noteBtn.title = should ? 'Dictation off' : 'Dictate';
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
  let orbPoints = makeSpherePoints(420);
  let orbRotY = 0, orbRotX = -0.38;

  function drawOrb(now) {
    const cw = orbCanvas.clientWidth, ch = orbCanvas.clientHeight;
    if (cw < 4 || ch < 4) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (orbCanvas.width !== cw * dpr || orbCanvas.height !== ch * dpr) { orbCanvas.width = cw * dpr; orbCanvas.height = ch * dpr; }
    orbCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    orbCtx.clearRect(0, 0, cw, ch);
    // Zentrum über dem Chat-Bereich (rechts der Sidebar), nicht der Mitte
    // des Vollbildes — ein <canvas> ist ein replaced element, seine Box ist
    // also das, was width/height/clientWidth melden; die Position des
    // Sprechbereichs holen wir daher über den echten Layout-Container.
    const rect = chatRootEl ? chatRootEl.getBoundingClientRect() : { left: 0, top: 0, width: cw, height: ch };
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const R = Math.min(rect.width, rect.height) * 0.32;
    const lvl = orbLevel || 0;
    // langsame Rotation, beim Sprechen beschleunigt
    orbRotY += 0.0042 + lvl * 0.012;
    const cosY = Math.cos(orbRotY), sinY = Math.sin(orbRotY);
    const cosX = Math.cos(orbRotX), sinX = Math.sin(orbRotX);
    orbCtx.fillStyle = DOT_COLOR;
    for (let i = 0; i < orbPoints.length; i++) {
      const p = orbPoints[i];
      // Rotation um Y
      const x = p.x * cosY + p.z * sinY;
      const z = -p.x * sinY + p.z * cosY;
      // Rotation um X (dauerhafter Kippwinkel)
      const y = p.y * cosX - z * sinX;
      const zT = p.y * sinX + z * cosX;
      // perspektivische Projektion — näher = größer
      const persp = 3.4;
      const scale = persp / (persp - zT);
      const sx = cx + x * R * scale;
      const sy = cy + y * R * scale;
      const depth = (zT + 1) / 2;                 // 0 fern … 1 nah
      const pulse = lvl * (0.4 + 0.6 * depth);
      const size = 1.2 + depth * 2.0 + pulse * 2.6;
      const alpha = Math.min(1, 0.12 + depth * 0.5 + pulse * 0.35);
      orbCtx.globalAlpha = alpha;
      orbCtx.beginPath();
      orbCtx.arc(sx, sy, size, 0, Math.PI * 2);
      orbCtx.fill();
    }
    orbCtx.globalAlpha = 1;
  }

  function orbLoop(now) {
    if (!orbVisible) return;
    orbLevel = Math.max(0, orbLevel * 0.9 + getMicLevel() * 0.1);
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

  // ---------------------------------------------------------------- boot
  function boot() {
    buildUi();
    setMode(activeMode); // Sidebar befüllen + aktive Konversation des Modus laden
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
    });
    fetch('/models').then((r) => r.json()).then((j) => { if (j.current) setModelLabel(j.current); }).catch(() => {});
    openPanelSocket();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
