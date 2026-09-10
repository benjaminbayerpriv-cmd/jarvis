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
  // Echte claude.ai-Dark-Palette (aus dem live-DOM extrahiert: --cds-surface-1
  // #151515 für Seite/Sidebar, --cds-surface-3 #1f1f1e fürs Composer-Karten,
  // --cds-gray-200/-350 für Sekundär-/Tertiärtext, ein HELLER Haarlinien-Rand
  // bei ~10% Deckkraft statt eines dunklen Randtons — auf dunklem Grund liegt
  // dort ein dezenter LICHTER Ring, kein brauner Schatten).
  const C = {
    bg: '#151515',
    bgSoft: '#151515',
    bgSurface3: '#1f1f1e',
    bgHover: 'rgba(255,255,255,.11)',
    text: '#f0efe8',
    textSoft: '#c3c0b4',
    textDim: '#8a8680',
    border: 'rgba(240,236,225,.14)',
    borderStrong: 'rgba(240,236,225,.24)',
    accent: '#d97757',                 // Claude-Terracotta
    font: 'var(--font-anthropic-sans, system-ui, sans-serif)',
    serif: 'var(--font-anthropic-serif, Georgia, serif)',
  };

  // ------------------------------------------------ lucide-icons (24x24 stroke)
  // Echte Lucide-Ikonen, 1:1 aus dem Internet (lucide-static), stroke=currentColor.
  const ICONS = {
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><line x1="12" x2="12" y1="5" y2="19"/><line x1="5" x2="19" y1="12" y2="12"/></svg>',
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
    folder: '<svg viewBox="131 97 738 806" fill="currentColor" fill-rule="evenodd" aria-hidden="true"><path d="M225 303Q213 303 205.0 295.0Q197 287 197 275Q197 263 205.0 255.0Q213 247 225 247H775Q787 247 795.0 255.0Q803 263 803 275Q803 287 795.0 295.0Q787 303 775 303ZM300 153Q288 153 280.0 145.0Q272 137 272 125Q272 113 280.0 105.0Q288 97 300 97H700Q712 97 720.0 105.0Q728 113 728 125Q728 137 720.0 145.0Q712 153 700 153ZM209 397H791Q815 397 834.0 410.0Q853 423 862.5 443.5Q872 464 868 488L810 838Q805 866 783.0 884.5Q761 903 733 903H267Q239 903 217.0 884.5Q195 866 190 838L132 488Q128 464 137.5 443.5Q147 423 166.0 410.0Q185 397 209 397ZM209 453Q199 453 192.5 461.0Q186 469 187 479L246 829Q247 837 253.0 842.0Q259 847 267 847H733Q741 847 747.0 842.0Q753 837 754 829L813 479Q814 469 807.5 461.0Q801 453 791 453Z"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
    sort: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 16 4 4 4-4"/><path d="M7 20V4"/><path d="m21 8-4-4-4 4"/><path d="M17 4v16"/></svg>',
    dots: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>',
    chevronDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    bullet: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/></svg>',
    layers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    sliders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/></svg>',
    palette: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22a1 1 0 0 1 0-20 10 9 0 0 1 10 9 5 5 0 0 1-5 5h-2.25a1.75 1.75 0 0 0-1.4 2.8l.3.4a1.75 1.75 0 0 1-1.4 2.8z"/><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1z"/></svg>',
    pinFilled: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><path d="M12 17v5h-1v-5z"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1z"/></svg>',
    spark: '<svg viewBox="0 0 100 100" fill="currentColor" aria-hidden="true"><path d="m19.6 66.5 19.7-11 .3-1-.3-.5h-1l-3.3-.2-11.2-.3L14 53l-9.5-.5-2.4-.5L0 49l.2-1.5 2-1.3 2.9.2 6.3.5 9.5.6 6.9.4L38 49.1h1.6l.2-.7-.5-.4-.4-.4L29 41l-10.6-7-5.6-4.1-3-2-1.5-2-.6-4.2 2.7-3 3.7.3.9.2 3.7 2.9 8 6.1L37 36l1.5 1.2.6-.4.1-.3-.7-1.1L33 25l-6-10.4-2.7-4.3-.7-2.6c-.3-1-.4-2-.4-3l3-4.2L28 0l4.2.6L33.8 2l2.6 6 4.1 9.3L47 29.9l2 3.8 1 3.4.3 1h.7v-.5l.5-7.2 1-8.7 1-11.2.3-3.2 1.6-3.8 3-2L61 2.6l2 2.9-.3 1.8-1.1 7.7L59 27.1l-1.5 8.2h.9l1-1.1 4.1-5.4 6.9-8.6 3-3.5L77 13l2.3-1.8h4.3l3.1 4.7-1.4 4.9-4.4 5.6-3.7 4.7-5.3 7.1-3.2 5.7.3.4h.7l12-2.6 6.4-1.1 7.6-1.3 3.5 1.6.4 1.6-1.4 3.4-8.2 2-9.6 2-14.3 3.3-.2.1.2.3 6.4.6 2.8.2h6.8l12.6 1 3.3 2 1.9 2.7-.3 2-5.1 2.6-6.8-1.6-16-3.8-5.4-1.3h-.8v.4l4.6 4.5 8.3 7.5L89 80.1l.5 2.4-1.3 2-1.4-.2-9.2-7-3.6-3-8-6.8h-.5v.7l1.8 2.7 9.8 14.7.5 4.5-.7 1.4-2.6 1-2.7-.6-5.8-8-6-9-4.7-8.2-.5.4-2.9 30.2-1.3 1.5-3 1.2-2.5-2-1.4-3 1.4-6.2 1.6-8 1.3-6.4 1.2-7.9.7-2.6v-.2H49L43 72l-9 12.3-7.2 7.6-1.7.7-3-1.5.3-2.8L24 86l10-12.8 6-7.9 4-4.6-.1-.5h-.3L17.2 77.4l-4.7.6-2-2 .2-3 1-1 8-5.5Z"/></svg>',
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
  // Composer-Sende-Slot: im Leerlauf steht dort das Sprachmodus-Icon (Equalizer-
  // Balken), sobald Text/Anhang vorhanden ist, springt an dieser Stelle der
  // Senden-Button ein — beide teilen sich den gleichen Platz statt nebeneinander
  // zu stehen (spiegelt claude.ai's Composer-Verhalten).
  function updateSendSlot() {
    const canSend = canSendNow();
    if (speechBtn) speechBtn.style.display = canSend ? 'none' : 'inline-flex';
    if (sendBtn) sendBtn.style.display = canSend ? 'inline-flex' : 'none';
  }
  function renderAttachPreviews() {
    updateSendSlot();
    if (!attachPreviewEl) return;
    if (!pendingImages.length) { attachPreviewEl.style.display = 'none'; attachPreviewEl.innerHTML = ''; return; }
    attachPreviewEl.style.display = 'flex';
    attachPreviewEl.innerHTML = pendingImages.map((att, i) => {
      const title = (att.note ? `${att.name} — ${att.note}` : att.name).replace(/"/g, '&quot;');
      return `
      <div style="position:relative;width:56px;height:56px;flex:0 0 auto;">
        ${att.image
          ? `<img src="${att.image}" title="${title}" style="width:100%;height:100%;object-fit:cover;border-radius:10px;border:1px solid ${C.border};" />`
          : `<div title="${title}" style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border-radius:10px;border:1px solid ${att.note ? C.accent : C.border};background:${C.bgHover};color:${C.textSoft};padding:2px;">
               <span style="display:inline-flex;">${ICONS.copy}</span>
               <span style="font-size:9px;line-height:1.1;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${att.name.replace(/"/g, '&quot;')}</span>
             </div>`}
        <button class="js-attach-remove" data-idx="${i}" title="Entfernen" style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;border-radius:50%;background:${C.bgSurface3};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;font-size:11px;line-height:1;display:flex;align-items:center;justify-content:center;padding:0;">×</button>
      </div>
    `;
    }).join('');
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
  // Jede Datei wird angehängt (Chip außerhalb der Nachricht, wie bei anderen
  // KI-Chats) — nur WAS an den Text angehängt wird, wenn tatsächlich gesendet
  // wird, unterscheidet sich: Bilder gehen als echtes Bild mit, lesbarer Text
  // wird beim Senden unsichtbar an die Nachricht angehängt, unlesbare
  // Binärdateien (Fonts, PDFs, …) bekommen nur ihren Dateinamen mit — ihr
  // Inhalt lässt sich ohne OCR/Parser ohnehin nicht sinnvoll verwenden.
  async function readAttachedFile(file) {
    if (file.type && file.type.startsWith('image/')) {
      if (!currentModelSupportsVision) {
        return { name: file.name, image: null, sendText: null, note: 'aktuelles Modell kann keine Bilder lesen' };
      }
      try {
        let image;
        try {
          image = await normalizeImageFile(file);
        } catch (e) {
          image = await readFileAsDataURL(file);
        }
        return { name: file.name, image, sendText: null, note: null };
      } catch (e) {
        return { name: file.name, image: null, sendText: null, note: 'konnte nicht gelesen werden' };
      }
    }
    let text;
    try {
      text = await readFileAsText(file);
    } catch (e) {
      return { name: file.name, image: null, sendText: null, note: 'konnte nicht gelesen werden' };
    }
    if (looksBinary(text)) {
      return { name: file.name, image: null, sendText: null, note: 'Inhalt ist eine Binärdatei — Name wird mitgesendet, Inhalt nicht' };
    }
    let truncated = false;
    if (text.length > ATTACH_MAX_CHARS) { text = text.slice(0, ATTACH_MAX_CHARS); truncated = true; }
    const note = truncated ? `gekürzt auf ${ATTACH_MAX_CHARS} Zeichen` : null;
    return { name: file.name, image: null, sendText: `📎 ${file.name}:\n\`\`\`\n${text}\n\`\`\``, note };
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
  let settingsSheetEl = null, settingsModelsEl = null, newProjectSheetEl = null;

  // Code-Tab (echte opencode-TUI in einem eingebetteten xterm.js-Terminal)
  let codeViewEl = null, codeTermEl = null, codeDirEl = null;
  let codeStatusLabelEl = null, codeDotEl = null, codeRestartBtn = null;
  let codeTerm = null, codeFit = null;
  let codeWs = null, codeWsOpen = false, codeReconnectTimer = null, codeExited = false;

  // Projects-Ansicht Anker
  let projectsViewEl = null, projectsGridEl = null, projectsSearchRowEl = null, projectsSearchInputEl = null;
  let projectsList = [], projectsSortMode = 'newest', projectsSearchOpen = false;
  let projectCardMenuTargetId = null, editingProjectId = null;
  let currentProjectId = null;  // getaggt an die NÄCHSTE neu angelegte Konversation, siehe sendMessage
  // Projekt-Detailseite Anker
  let projectDetailViewEl = null, pdBackEl = null, pdNameEl = null, pdTitleEl = null;
  let pdEditorEl = null, pdUploadBtn = null, pdModelBtn = null, pdModelLabelEl = null;
  let pdNoteBtn = null, pdSpeechBtn = null, pdSendBtn = null, pdRecentEl = null;
  let viewingProjectId = null;

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
    if (h >= 5 && h < 11) return 'Guten Morgen, Chef';
    if (h >= 11 && h < 15) return 'Guten Tag, Chef';
    if (h >= 15 && h < 22) return 'Guten Abend, Chef';
    return 'Mondscheingespräch';
  }

  // --------------------------------------------------------- UI: buildUi()
  function buildUi() {
    uiEl = document.createElement('div');
    uiEl.id = 'jsApp';
    uiEl.style.cssText = `position:fixed;inset:0;z-index:30;display:flex;background:${C.bg};color:${C.text};font-family:${C.font};`;
    uiEl.innerHTML = `
      <button class="js-side-toggle-float" title="Sidebar einblenden" style="display:none;position:absolute;top:15px;left:12px;z-index:31;background:none;border:none;color:${C.textSoft};cursor:pointer;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;">${ICONS.menu}</button>
      <aside class="js-sidebar" style="width:308px;flex:0 0 308px;height:100%;display:flex;flex-direction:column;background:${C.bgSoft};border-right:1px solid ${C.border};">
        <div class="js-sidebar-top" style="padding:16px 12px 6px;display:flex;flex-direction:column;gap:12px;">
          <div class="js-sidebar-header" style="display:flex;align-items:center;justify-content:space-between;">
            <span style="font-family:${C.serif};font-size:15px;font-weight:500;color:${C.text};">Jarvis</span>
            <div style="display:flex;align-items:center;gap:2px;">
              <button class="js-side-toggle" title="Sidebar ausblenden" style="background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;">${ICONS.menu}</button>
              <button class="js-search-toggle" title="Bald verfügbar" disabled style="background:none;border:none;color:${C.textDim};cursor:default;display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;opacity:.5;">${ICONS.search}</button>
            </div>
          </div>
          <div class="js-search-row" style="display:none;">
            <input class="js-search-input" type="text" placeholder="Chats durchsuchen…" style="width:100%;padding:7px 10px;background:${C.bgHover};border:1px solid ${C.border};border-radius:9px;color:${C.text};font-size:13px;font-family:${C.font};outline:none;" />
          </div>
          <div class="js-mode" style="display:flex;padding:3px;gap:3px;background:${C.bgHover};border-radius:11px;">
            <button class="js-pill active" data-mode="chat" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 10px;border-radius:8px;border:none;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,color .15s;">${ICONS.chat}<span>Startseite</span></button>
            <button class="js-pill" data-mode="code" title="Code mit JARVIS Code" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 10px;border-radius:8px;border:none;background:transparent;color:${C.textSoft};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s,color .15s;">${ICONS.code}<span>Code</span></button>
          </div>
          <button class="js-new" style="display:flex;align-items:center;gap:8px;padding:9px 12px;background:${C.bgHover};border:none;border-radius:11px;color:${C.text};font-size:13px;font-weight:500;cursor:pointer;transition:background .15s;">${ICONS.plus}<span>Neu</span></button>
          <div class="js-nav-list" style="display:flex;flex-direction:column;gap:1px;">
            <button class="js-projects js-navrow" style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:none;border:none;border-radius:9px;color:${C.textSoft};font-size:13px;cursor:pointer;transition:background .15s,color .15s;text-align:left;">${ICONS.folder}<span>Projekte</span></button>
            <button class="js-artifacts js-navrow" title="Bald verfügbar" style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:none;border:none;border-radius:9px;color:${C.textDim};font-size:13px;cursor:default;text-align:left;opacity:.55;">${ICONS.layers}<span>Artefakte</span></button>
            <button class="js-customize js-navrow" style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:none;border:none;border-radius:9px;color:${C.textSoft};font-size:13px;cursor:pointer;transition:background .15s,color .15s;text-align:left;">${ICONS.sliders}<span>Anpassen</span></button>
          </div>
          <div class="js-projects-pin-section">
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 8px 4px;">
              <span style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:${C.textDim};">Projekte</span>
              <button class="js-projects-pin-add" title="Projekt erstellen" style="background:none;border:none;color:${C.textDim};cursor:pointer;display:inline-flex;padding:3px;">${ICONS.plus}</button>
            </div>
            <div class="js-projects-pin-hint" style="display:flex;align-items:center;gap:10px;padding:7px 10px;color:${C.textDim};font-size:12.5px;line-height:1.3;">${ICONS.folder}<span>Projekte anheften, um sie hier zu behalten</span></div>
          </div>
          <div class="js-chats-toggle-row" style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;">
            <button class="js-chats-toggle" style="display:flex;align-items:center;gap:4px;padding:8px 8px 4px;background:none;border:none;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};cursor:pointer;font-family:${C.font};">
              <span class="js-chats-chevron" style="display:inline-flex;transition:transform .15s;">${ICONS.chevronDown}</span>
              <span>Chats und Aufgaben</span>
            </button>
            <button class="js-chats-sort" title="Filtern und gruppieren" style="background:none;border:none;color:${C.textDim};cursor:pointer;display:inline-flex;padding:5px;">${ICONS.sort}</button>
          </div>
        </div>
        <div class="js-chats" style="flex:1 1 auto;overflow-y:auto;padding:2px 8px 10px;"></div>
        <button class="js-settings-row" style="padding:10px 12px;border-top:1px solid ${C.border};border-radius:0;display:flex;align-items:center;gap:8px;background:none;border-left:none;border-right:none;border-bottom:none;width:100%;text-align:left;cursor:pointer;transition:background .15s;font-family:${C.font};">
          <span class="js-settings" style="width:32px;height:32px;border-radius:9px;color:${C.textSoft};display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;">${ICONS.settings}</span>
          <span class="js-settings-label" style="font-size:13px;color:${C.textSoft};flex:1;">Einstellungen</span>
        </button>
      </aside>
      <div class="js-main" style="flex:1;height:100%;display:flex;flex-direction:column;min-width:0;position:relative;">
        <div class="js-welcome" style="position:absolute;top:40%;left:0;right:0;transform:translateY(-100%);display:flex;flex-direction:column;align-items:center;text-align:center;padding:0 32px;gap:14px;">
          <h1 class="js-welcome-title" style="font-family:${C.serif};font-size:30px;font-weight:400;letter-spacing:-.01em;color:${C.text};margin:0;">
            <span>${timeGreeting()}</span>
          </h1>
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
        <div class="js-projects-view" style="position:absolute;inset:0;display:none;flex-direction:column;min-width:0;min-height:0;overflow-y:auto;padding:40px 48px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:28px;">
            <h1 style="font-family:${C.serif};font-size:28px;font-weight:600;color:${C.text};margin:0;">Projekte</h1>
            <div style="display:flex;align-items:center;gap:14px;">
              <button class="js-projects-search-btn" title="Suchen" style="background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;padding:6px;">${ICONS.search}</button>
              <button class="js-projects-sort-btn" title="Sortieren" style="background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;padding:6px;">${ICONS.sort}</button>
              <button class="js-projects-new" style="padding:9px 18px;background:${C.text};border:none;border-radius:20px;color:${C.bg};font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;">Neues Projekt</button>
            </div>
          </div>
          <div class="js-projects-search-row" style="display:none;margin-bottom:20px;">
            <input class="js-projects-search-input" type="text" placeholder="Projekte durchsuchen…" style="width:100%;max-width:360px;padding:9px 14px;background:${C.bgHover};border:1px solid ${C.border};border-radius:10px;color:${C.text};font-size:13px;font-family:${C.font};outline:none;" />
          </div>
          <div class="js-projects-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;"></div>
          <div class="js-project-card-menu" style="display:none;position:absolute;width:170px;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.4);overflow:hidden;z-index:5;">
            <button class="js-pcm-rename" style="display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.text};font-size:13px;cursor:pointer;font-family:${C.font};">Umbenennen</button>
            <button class="js-pcm-delete" style="display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:#e5735f;font-size:13px;cursor:pointer;font-family:${C.font};">Löschen</button>
          </div>
          <div class="js-projects-sort-menu" style="display:none;position:absolute;width:190px;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.4);overflow:hidden;z-index:5;">
            <button class="js-psm-opt" data-sort="newest" style="display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.text};font-size:13px;cursor:pointer;font-family:${C.font};">Neueste zuerst</button>
            <button class="js-psm-opt" data-sort="oldest" style="display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.text};font-size:13px;cursor:pointer;font-family:${C.font};">Älteste zuerst</button>
            <button class="js-psm-opt" data-sort="updated" style="display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.text};font-size:13px;cursor:pointer;font-family:${C.font};">Zuletzt bearbeitet</button>
            <button class="js-psm-opt" data-sort="alpha" style="display:block;width:100%;text-align:left;padding:9px 14px;background:none;border:none;color:${C.text};font-size:13px;cursor:pointer;font-family:${C.font};">Alphabetisch</button>
          </div>
        </div>
        <div class="js-project-detail-view" style="position:absolute;inset:0;display:none;flex-direction:column;min-width:0;min-height:0;overflow-y:auto;padding:40px 48px;">
          <div style="font-size:13px;color:${C.textSoft};margin-bottom:18px;">
            <span class="js-pd-back" style="cursor:pointer;">Projekte</span>
            <span style="margin:0 4px;">/</span>
            <span class="js-pd-name" style="color:${C.text};font-weight:600;"></span>
          </div>
          <h1 class="js-pd-title" style="font-family:${C.serif};font-size:30px;font-weight:600;color:${C.text};margin:0 0 24px;"></h1>
          <div style="max-width:640px;position:relative;">
            <div style="background:${C.bgSurface3};border:1px solid ${C.border};border-radius:18px;box-shadow:0 10px 34px rgba(0,0,0,.25);">
              <div class="js-pd-editor" contenteditable="true" data-placeholder="Wie kann ich dir heute helfen?" style="min-height:52px;max-height:160px;overflow-y:auto;padding:16px 16px 8px;color:${C.text};font-size:15px;line-height:1.5;outline:none;white-space:pre-wrap;word-break:break-word;"></div>
              <div style="display:flex;align-items:center;gap:8px;padding:6px 10px 10px;">
                <button class="js-pd-upload" title="Datei anhängen" style="width:34px;height:34px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.plus}</button>
                <div style="padding:5px 10px;background:${C.bgHover};border-radius:8px;font-size:12px;color:${C.text};font-weight:500;">Chat</div>
                <div style="flex:1;"></div>
                <button class="js-pd-model" title="Modell wechseln" style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;">
                  <span class="js-pd-model-label">Modell…</span>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
                </button>
                <button class="js-pd-note" title="Diktieren" style="width:34px;height:34px;border-radius:9px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.mic}</button>
                <button class="js-pd-speech" title="Sprachmodus" style="width:38px;height:38px;border-radius:50%;background:${C.bgHover};border:1px solid ${C.border};color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.audio}</button>
                <button class="js-pd-send" title="Senden" style="width:38px;height:38px;border-radius:50%;background:${C.accent};border:none;color:#fff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">${ICONS.send}</button>
              </div>
            </div>
          </div>
          <div class="js-pd-recent-label" style="font-size:12px;color:${C.textDim};margin:28px 0 4px;max-width:640px;">Zuletzt verwendet</div>
          <div class="js-pd-recent" style="display:flex;flex-direction:column;max-width:640px;"></div>
        </div>
      </div>
      <div class="js-composer" style="position:absolute;left:308px;right:0;bottom:0;padding:0 24px 22px;background:linear-gradient(transparent,${C.bg} 55%);">
        <div style="max-width:672px;margin:0 auto;position:relative;">
          <div style="background:${C.bgSurface3};border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,.18),0 0 0 1px ${C.borderStrong};">
            <div class="js-attach-preview" style="display:none;gap:8px;padding:14px 14px 0;flex-wrap:wrap;"></div>
            <div style="padding:14px;display:flex;flex-direction:column;gap:12px;">
              <div class="js-editor" contenteditable="true" data-placeholder="Wie kann ich dir heute helfen?" style="min-height:48px;max-height:200px;overflow-y:auto;padding:6px 6px 0;color:${C.text};font-size:15px;line-height:1.5;outline:none;white-space:pre-wrap;word-break:break-word;"></div>
              <div style="display:flex;align-items:center;gap:8px;">
                <button class="js-upload" title="Dateien anhängen" style="width:32px;height:32px;margin-left:2px;border-radius:8px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;flex:0 0 auto;">${ICONS.plus}</button>
                <div style="flex:1;"></div>
                <button class="js-model" title="Modell wechseln" style="display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:8px;background:none;border:none;color:${C.textSoft};font-size:13px;cursor:pointer;transition:background .15s;flex:0 0 auto;">
                  <span class="js-model-label">Modell…</span>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
                </button>
                <button class="js-note" title="Diktieren" style="width:32px;height:32px;border-radius:8px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;flex:0 0 auto;">${ICONS.mic}</button>
                <button class="js-speech" title="Sprachmodus" style="width:32px;height:32px;border-radius:8px;background:none;border:none;color:${C.textSoft};cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .15s;flex:0 0 auto;">${ICONS.audio}</button>
                <button class="js-send" title="Senden" style="width:32px;height:32px;border-radius:8px;background:${C.accent};border:none;color:#fff;cursor:pointer;display:none;align-items:center;justify-content:center;flex:0 0 auto;">${ICONS.send}</button>
              </div>
            </div>
          </div>
          <div class="js-modelmenu" style="display:none;position:absolute;width:220px;max-height:280px;overflow-y:auto;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.4);z-index:10;"></div>
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
      <div style="pointer-events:auto;display:flex;align-items:center;gap:10px;padding:8px 12px;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.5);">
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
      <div style="pointer-events:auto;max-width:720px;width:calc(100% - 64px);padding:10px 16px;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.5);display:flex;flex-direction:column;gap:4px;">
        <div class="js-spc-status" style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Zuhören</div>
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
      <div style="width:340px;max-width:90vw;max-height:calc(100vh - 96px);display:flex;flex-direction:column;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.5);overflow:hidden;">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid ${C.border};flex:0 0 auto;">
          <span style="font-size:15px;font-weight:600;color:${C.text};">Einstellungen</span>
          <button class="js-settings-close" title="Close" style="width:28px;height:28px;border-radius:8px;background:none;border:none;color:${C.textSoft};cursor:pointer;font-size:16px;line-height:1;">×</button>
        </div>
        <div style="flex:1 1 auto;overflow-y:auto;">
        <div style="padding:12px 6px;">
          <div style="padding:6px 10px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Modell</div>
          <div class="js-settings-models"></div>
        </div>
        <div style="padding:12px 6px;border-top:1px solid ${C.border};">
          <div style="padding:6px 10px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Verbindung</div>
          <div style="padding:4px 10px;display:flex;flex-direction:column;gap:8px;">
            <span style="font-size:12px;color:${C.textSoft};">LM Studio Endpoint</span>
            <input class="js-lmstudio-url-input" type="text" placeholder="http://127.0.0.1:1234/v1" spellcheck="false" style="width:100%;box-sizing:border-box;padding:9px 10px;background:${C.bg};border:1px solid ${C.border};border-radius:8px;color:${C.text};font-size:13px;outline:none;font-family:${C.font};" />
            <div style="display:flex;align-items:center;gap:10px;">
              <button class="js-lmstudio-url-save" style="align-self:flex-start;padding:7px 12px;border:none;border-radius:8px;background:${C.accent};color:#fff;font-size:12px;cursor:pointer;font-family:${C.font};">Speichern</button>
              <span class="js-lmstudio-url-status" style="font-size:11.5px;color:${C.textDim};"></span>
            </div>
          </div>
        </div>
        <div style="padding:12px 6px 16px;border-top:1px solid ${C.border};">
          <div style="padding:6px 10px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:${C.textDim};">Code</div>
          <div style="padding:4px 10px;display:flex;flex-direction:column;gap:8px;">
            <span style="font-size:12px;color:${C.textSoft};">Arbeitsverzeichnis für JARVIS Code</span>
            <input class="js-code-dir-input" type="text" placeholder="~/Developer" spellcheck="false" style="width:100%;box-sizing:border-box;padding:9px 10px;background:${C.bg};border:1px solid ${C.border};border-radius:8px;color:${C.text};font-size:13px;outline:none;font-family:${C.font};" />
            <button class="js-code-dir-save" style="align-self:flex-start;padding:7px 12px;border:none;border-radius:8px;background:${C.accent};color:#fff;font-size:12px;cursor:pointer;font-family:${C.font};">Speichern</button>
          </div>
        </div>
        </div>
      </div>
    `;
    document.body.appendChild(settingsSheetEl);

    // Neues-Projekt-Dialog (zentriert, wie ein einfacher Modal-Dialog).
    newProjectSheetEl = document.createElement('div');
    newProjectSheetEl.id = 'jsNewProjectSheet';
    newProjectSheetEl.style.cssText = `position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.5);`;
    newProjectSheetEl.innerHTML = `
      <div style="width:420px;max-width:90vw;background:${C.bgSurface3};border:1px solid ${C.border};border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.5);overflow:hidden;">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid ${C.border};">
          <span class="js-newproject-title" style="font-size:16px;font-weight:600;color:${C.text};">Neues Projekt</span>
          <button class="js-newproject-close" title="Schließen" style="width:28px;height:28px;border-radius:8px;background:none;border:none;color:${C.textSoft};cursor:pointer;font-size:16px;line-height:1;">×</button>
        </div>
        <div style="padding:18px;display:flex;flex-direction:column;gap:12px;">
          <div class="js-newproject-dir-row" style="display:flex;flex-direction:column;gap:6px;">
            <label style="font-size:12px;color:${C.textSoft};">Ordner</label>
            <input class="js-newproject-dir" type="text" placeholder="z. B. C:\Users\du\Documents\MeinProjekt" spellcheck="false" style="width:100%;box-sizing:border-box;padding:9px 10px;background:${C.bg};border:1px solid ${C.border};border-radius:8px;color:${C.text};font-size:13px;outline:none;font-family:${C.font};" />
            <span style="font-size:11px;color:${C.textDim};">Pfad eines bestehenden Ordners, oder ein neuer wird angelegt. Die Chats dieses Projekts landen dort drin.</span>
          </div>
          <div class="js-newproject-dir-display" style="display:none;font-size:12px;color:${C.textDim};font-family:monospace;word-break:break-all;"></div>
          <div class="js-newproject-error" style="font-size:12px;color:#e5735f;min-height:0;"></div>
          <div style="display:flex;flex-direction:column;gap:6px;">
            <label style="font-size:12px;color:${C.textSoft};">Name (optional, sonst der Ordnername)</label>
            <input class="js-newproject-name" type="text" placeholder="z. B. Lokale Coding KI" style="width:100%;box-sizing:border-box;padding:9px 10px;background:${C.bg};border:1px solid ${C.border};border-radius:8px;color:${C.text};font-size:13px;outline:none;font-family:${C.font};" />
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;">
            <label style="font-size:12px;color:${C.textSoft};">Beschreibung (optional)</label>
            <textarea class="js-newproject-desc" rows="3" placeholder="Worum geht's in diesem Projekt?" style="width:100%;box-sizing:border-box;padding:9px 10px;background:${C.bg};border:1px solid ${C.border};border-radius:8px;color:${C.text};font-size:13px;outline:none;font-family:${C.font};resize:vertical;"></textarea>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:4px;">
            <button class="js-newproject-cancel" style="padding:8px 14px;border:1px solid ${C.border};border-radius:8px;background:none;color:${C.textSoft};font-size:13px;cursor:pointer;font-family:${C.font};">Abbrechen</button>
            <button class="js-newproject-create" style="padding:8px 14px;border:none;border-radius:8px;background:${C.accent};color:#fff;font-size:13px;font-weight:600;cursor:pointer;font-family:${C.font};">Erstellen</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(newProjectSheetEl);

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
    projectsViewEl = $('.js-projects-view', uiEl);
    projectsGridEl = $('.js-projects-grid', uiEl);
    projectsSearchRowEl = $('.js-projects-search-row', uiEl);
    projectsSearchInputEl = $('.js-projects-search-input', uiEl);
    projectDetailViewEl = $('.js-project-detail-view', uiEl);
    pdBackEl = $('.js-pd-back', uiEl);
    pdNameEl = $('.js-pd-name', uiEl);
    pdTitleEl = $('.js-pd-title', uiEl);
    pdEditorEl = $('.js-pd-editor', uiEl);
    pdUploadBtn = $('.js-pd-upload', uiEl);
    pdModelBtn = $('.js-pd-model', uiEl);
    pdModelLabelEl = $('.js-pd-model-label', uiEl);
    pdNoteBtn = $('.js-pd-note', uiEl);
    pdSpeechBtn = $('.js-pd-speech', uiEl);
    pdSendBtn = $('.js-pd-send', uiEl);
    pdRecentEl = $('.js-pd-recent', uiEl);
    settingsBtn = $('.js-settings-row', uiEl);
    modelEl = $('.js-model-label', uiEl);
    modelBtnEl = $('.js-model', uiEl);
    modelMenuEl = $('.js-modelmenu', uiEl);
    // Aus dem Composer-Wrapper gelöst und direkt an #jsApp gehängt, damit es
    // sich relativ zu JEDEM Modell-Button im ganzen Interface positionieren
    // lässt (siehe positionModelMenu) — nicht nur dem im Haupt-Composer.
    uiEl.appendChild(modelMenuEl);
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
      body.js-app-active > :not(#jsApp):not(#jarvisOrb):not(#jsSpeechbar):not(#jsSpeechCaption):not(#jsSettingsSheet):not(#jsNewProjectSheet):not(script):not(style) { display:none !important; }
      body.js-app-active { overflow:hidden; }
      .js-sidebar button:focus-visible, .js-main button:focus-visible { outline:2px solid ${C.accent}; outline-offset:2px; }
      .js-editor:empty::before, .js-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-editor:focus::before { opacity:.7; }
      .js-side-toggle svg, .js-side-toggle-float svg, .js-new svg, .js-projects svg, .js-upload svg, .js-note svg, .js-speech svg, .js-settings svg, .js-navrow svg { width:16px; height:16px; display:block; flex:0 0 auto; }
      .js-side-toggle:hover, .js-side-toggle-float:hover { background:${C.bgHover}; color:${C.text}; }
      .js-search-toggle svg, .js-projects-pin-add svg, .js-chats-sort svg, .js-projects-pin-hint svg { width:15px; height:15px; display:block; flex:0 0 auto; }
      .js-search-toggle:hover, .js-projects-pin-add:hover, .js-chats-sort:hover { background:${C.bgHover}; color:${C.text}; border-radius:7px; }
      .js-projects-search-btn svg, .js-projects-sort-btn svg { width:18px; height:18px; display:block; }
      .js-project-menu-btn svg, .js-project-pin-btn svg { width:16px; height:16px; display:block; }
      .js-upload svg, .js-note svg, .js-settings svg { width:18px; height:18px; }
      .js-speech svg, .js-send svg { width:18px; height:18px; display:block; }
      .js-sp-mute svg, .js-sp-stop svg, .js-sp-chat svg, .js-sp-send svg { width:20px; height:20px; display:block; }
      .js-pill svg { width:16px; height:16px; display:block; }
      .js-side-toggle:hover, .js-new:hover, .js-projects:hover, .js-upload:hover, .js-note:hover, .js-speech:hover, .js-model:hover, .js-settings-row:hover, .js-sp-mute:hover, .js-sp-stop:hover, .js-sp-chat:hover { background:${C.bgHover}; color:${C.text}; }
      .js-navrow:not([disabled]):not(.js-artifacts):not(.js-scheduled):hover { background:${C.bgHover}; color:${C.text}; }
      .js-pill.active { background:${C.bgHover} !important; color:${C.text} !important; box-shadow:inset 0 0 0 1px ${C.border}; }
      .js-pill:not(.active):hover { background:${C.bgHover}; color:${C.text}; }
      .js-note.on { color:${C.accent} !important; background:rgba(217,119,87,.12) !important; }
      .js-note.on svg { animation:js-note-pulse 1.4s ease-in-out infinite; }
      @keyframes js-note-pulse { 0%,100% { opacity:1; } 50% { opacity:.45; } }
      .js-speech.on { background:${C.accent} !important; border-color:${C.accent} !important; color:#fff !important; }
      .js-speech.on svg { animation:js-speech-pulse 1.3s ease-in-out infinite; }
      @keyframes js-speech-pulse { 0%,100% { transform:scale(1); } 50% { transform:scale(1.14); } }
      .js-chat-item { position:relative; display:flex; align-items:center; gap:9px; padding:7px 32px 7px 10px; border-radius:10px; cursor:pointer; font-size:13px; color:${C.textSoft}; }
      .js-chat-item:hover { background:${C.bgHover}; color:${C.text}; }
      .js-chat-item.selected { background:${C.bgHover}; color:${C.text}; }
      .js-chat-item .js-ico { flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center; width:15px; height:15px; color:${C.textDim}; }
      .js-chat-item .js-ico svg { width:15px; height:15px; display:block; }
      .js-chat-delete { position:absolute; right:6px; top:50%; transform:translateY(-50%); width:22px; height:22px; border-radius:6px; background:none; border:none; color:${C.textDim}; cursor:pointer; display:none; align-items:center; justify-content:center; }
      .js-chat-item:hover .js-chat-delete { display:inline-flex; }
      .js-chat-delete:hover { background:${C.border}; color:#e5735f; }
      .js-chat-delete svg { width:13px; height:13px; display:block; }
      .js-chats-toggle .js-chats-chevron svg { width:13px; height:13px; display:block; }
      .js-chats-toggle.is-collapsed .js-chats-chevron { transform:rotate(-90deg); }
      .js-chats.is-collapsed { display:none !important; }
      .js-chat-item .js-txt { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .js-turn { max-width:768px; margin:0 auto 24px; font-family:${C.font}; line-height:1.6; display:flex; flex-direction:column; }
      .js-you { align-items:flex-end; }
      .js-jarvis { align-items:flex-start; text-align:left; }
      .js-you .js-text { background:${C.bgSurface3}; color:${C.text}; border-radius:18px; padding:12px 16px; max-width:85%; white-space:pre-wrap; word-break:break-word; font-size:15px; }
      .js-jarvis .js-text { color:${C.text}; white-space:pre-wrap; word-break:break-word; max-width:100%; font-family:${C.serif}; line-height:1.65; }
      .js-jarvis .js-text.thinking {
        font-style:italic; font-family:${C.font};
        background-image:linear-gradient(90deg, ${C.textDim} 0%, ${C.text} 50%, ${C.textDim} 100%);
        background-size:200% 100%; -webkit-background-clip:text; background-clip:text; color:transparent;
        animation:js-thinking-shimmer 1.6s linear infinite;
      }
      @keyframes js-thinking-shimmer { 0% { background-position:200% 0; } 100% { background-position:-200% 0; } }
      @media (prefers-reduced-motion:reduce) { .js-jarvis .js-text.thinking { animation:none; color:${C.textDim}; -webkit-background-clip:initial; background-clip:initial; background-image:none; } }
      .js-turn-actions { display:flex; align-items:center; gap:2px; margin-top:4px; opacity:0; transition:opacity .12s ease; }
      .js-turn:hover .js-turn-actions, .js-turn.js-actions-pinned .js-turn-actions { opacity:1; }
      .js-turn-copy { width:28px; height:28px; border-radius:7px; background:none; border:none; color:${C.textDim}; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; }
      .js-turn-copy:hover { background:${C.bgHover}; color:${C.text}; }
      .js-turn-copy svg { width:14px; height:14px; display:block; }
      .js-thread { padding:64px 24px 180px; }
      .js-main .js-welcome { opacity:1; transition:opacity .25s ease; }
      .js-main.has-content .js-welcome { opacity:0; pointer-events:none; }
      .js-composer { transition:top .25s ease, bottom .25s ease, transform .25s ease; }
      #jsApp:not(.js-has-content) .js-composer { top:40%; bottom:auto; transform:translateY(24px); background:none; padding:0 24px; }
      #jsApp.js-has-content .js-composer { top:auto; bottom:0; transform:none; }
      .js-main.js-speech-active .js-thread, .js-main.js-speech-active .js-welcome { display:none !important; }
      .js-code-editor:empty::before, .js-code-editor.is-empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-code-editor:focus::before { opacity:.7; }
      #jsApp.js-code-active .js-thread, #jsApp.js-code-active .js-welcome, #jsApp.js-code-active .js-composer { display:none !important; }
      #jsApp.js-code-active .js-codeview { display:flex !important; }
      #jsApp.js-projects-active .js-thread, #jsApp.js-projects-active .js-welcome, #jsApp.js-projects-active .js-composer { display:none !important; }
      #jsApp.js-projects-active .js-projects-view { display:flex !important; }
      #jsApp.js-project-detail-active .js-thread, #jsApp.js-project-detail-active .js-welcome, #jsApp.js-project-detail-active .js-composer { display:none !important; }
      #jsApp.js-project-detail-active .js-project-detail-view { display:flex !important; }
      /* Projekte ist über Chat UND Code hinweg erreichbar (Sidebar-Button
         bleibt in beiden Modi sichtbar) — diese beiden Regeln müssen NACH
         den .js-code-active-Regeln oben stehen, damit sie bei gleicher
         Spezifität + !important gewinnen, wenn jemand Projekte aus dem
         Code-Tab heraus öffnet (sonst läge das Terminal weiterhin sichtbar
         unter der Projekte-Ansicht). */
      #jsApp.js-projects-active .js-codeview, #jsApp.js-project-detail-active .js-codeview { display:none !important; }
      .js-project-card:hover { border-color:${C.textDim}; }
      .js-project-card { position:relative; cursor:pointer; }
      .js-project-menu-btn { opacity:0; transition:opacity .1s; }
      .js-project-card:hover .js-project-menu-btn, .js-project-menu-btn.is-open { opacity:1; }
      .js-pcm-rename:hover, .js-pcm-delete:hover, .js-psm-opt:hover { background:${C.bgHover}; }
      .js-psm-opt.active { color:${C.accent} !important; }
      .js-pd-back:hover { text-decoration:underline; }
      .js-pd-editor:empty::before { content:attr(data-placeholder); color:${C.textDim}; pointer-events:none; }
      .js-pd-upload:hover, .js-pd-model:hover, .js-pd-note:hover, .js-pd-speech:hover { background:${C.bgHover}; }
      .js-pd-upload svg, .js-pd-note svg { width:16px; height:16px; display:block; }
      .js-pd-speech svg, .js-pd-send svg { width:18px; height:18px; display:block; }
      .js-pd-recent-item:hover { background:${C.bgHover}; }
    `;
    document.head.appendChild(s);
  }

  // ------------------------------------------------------------- wire UI
  function setMode(mode) {
    if (mode !== 'chat' && mode !== 'code') return;
    closeProjectsView();
    closeProjectDetail();
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
  async function renderConversation(id, projectId) {
    const el = ensureThread();
    if (!el) return;
    el.innerHTML = '';
    history = [];
    let turns = [];
    if (id) {
      try {
        const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
        const r = await fetch(`/conversations/${encodeURIComponent(id)}${qs}`);
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
    const hasContent = threadEl.children.length > 0;
    chatRootEl.classList.toggle('has-content', hasContent);
    // Solange kein Gespräch läuft, sitzt der Composer direkt unter der
    // Begrüßung (mittig, wie auf claude.ais /new-Seite) statt permanent am
    // unteren Bildschirmrand — er wandert erst nach unten, sobald der erste
    // Turn im Thread steht.
    if (uiEl) uiEl.classList.toggle('js-has-content', hasContent);
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
    chatListEl.dataset.empty = list.length ? '' : '1';
    if (!list.length) {
      const d = document.createElement('div');
      d.className = 'js-chat-item';
      d.style.color = C.textDim;
      d.style.cursor = 'default';
      d.textContent = 'Noch keine Unterhaltungen';
      chatListEl.appendChild(d);
      return;
    }
    for (const conv of list) {
      const el = document.createElement('div');
      el.className = 'js-chat-item';
      el.dataset.title = (conv.title || 'Neu').toLowerCase();
      if (conv.id === currentConversationId) el.classList.add('selected');
      const ico = document.createElement('span');
      ico.className = 'js-ico';
      ico.innerHTML = '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;border:1px solid currentColor;opacity:.5;"></span>';
      const txt = document.createElement('span');
      txt.className = 'js-txt';
      txt.textContent = conv.title || 'Neu';
      txt.title = txt.textContent;
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'js-chat-delete';
      delBtn.title = 'Löschen';
      delBtn.innerHTML = ICONS.trash;
      delBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!confirm(`"${conv.title || 'Neu'}" löschen?`)) return;
        try {
          const qs = conv.project_id ? `?project_id=${encodeURIComponent(conv.project_id)}` : '';
          await fetch(`/conversations/${encodeURIComponent(conv.id)}${qs}`, { method: 'DELETE' });
        } catch (e2) {}
        if (conv.id === currentConversationId) startNewConversation();
        loadConversationList();
      });
      el.appendChild(ico);
      el.appendChild(txt);
      el.appendChild(delBtn);
      el.addEventListener('click', () => openConversation(conv.id));
      chatListEl.appendChild(el);
    }
  }

  function filterChatList(query) {
    if (!chatListEl) return;
    const q = query.trim().toLowerCase();
    chatListEl.querySelectorAll('.js-chat-item').forEach((el) => {
      if (!el.dataset.title) return;
      el.style.display = !q || el.dataset.title.includes(q) ? '' : 'none';
    });
  }

  async function openConversation(id, projectId) {
    closeProjectsView();
    currentProjectId = projectId || null;
    if (id === currentConversationId) return;
    currentConversationId = id;
    localStorage.setItem(modeKey(activeMode), id);
    await renderConversation(id, projectId);
    loadConversationList();
  }

  function startNewConversation() {
    currentProjectId = null;
    currentConversationId = activeMode + '-' + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
    localStorage.setItem(modeKey(activeMode), currentConversationId);
    history = [];
    clearThreadUI();
    loadConversationList();
  }

  // ------------------------------------------------------------ Projekte
  const _PROJECT_MONTHS = ['Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sep.', 'Okt.', 'Nov.', 'Dez.'];
  function formatProjectDate(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const now = new Date();
    const dayMs = 86400000;
    const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / dayMs);
    if (diffDays === 0) return 'heute';
    if (diffDays === 1) return 'gestern';
    if (diffDays === 2) return 'vorgestern';
    return `${d.getDate()}. ${_PROJECT_MONTHS[d.getMonth()]}`;
  }
  function openProjectsView() {
    closeProjectDetail();
    if (uiEl) uiEl.classList.add('js-projects-active');
    loadProjects();
  }
  function closeProjectsView() {
    if (uiEl) uiEl.classList.remove('js-projects-active');
  }
  function openProjectDetail(project) {
    closeProjectsView();
    viewingProjectId = project.id;
    if (uiEl) uiEl.classList.add('js-project-detail-active');
    if (pdNameEl) pdNameEl.textContent = project.name;
    if (pdTitleEl) pdTitleEl.textContent = project.name;
    if (pdEditorEl) { pdEditorEl.innerText = ''; }
    loadProjectRecent();
  }
  function closeProjectDetail() {
    if (uiEl) uiEl.classList.remove('js-project-detail-active');
    viewingProjectId = null;
  }
  async function loadProjectRecent() {
    if (!pdRecentEl || !viewingProjectId) return;
    pdRecentEl.innerHTML = `<div style="font-size:13px;color:${C.textDim};">Lädt…</div>`;
    try {
      const r = await fetch(`/conversations?project_id=${encodeURIComponent(viewingProjectId)}`);
      const j = await r.json();
      const list = j.conversations || [];
      if (!list.length) {
        pdRecentEl.innerHTML = `<div style="font-size:13px;color:${C.textDim};">Noch keine Unterhaltungen in diesem Projekt.</div>`;
        return;
      }
      pdRecentEl.innerHTML = list.map((c) => `
        <button class="js-pd-recent-item" data-id="${c.id}" style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 4px;background:none;border:none;border-bottom:1px solid ${C.border};color:${C.text};font-size:14px;cursor:pointer;text-align:left;font-family:${C.font};">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(c.title || 'Unbenannt')}</span>
          <span style="flex:0 0 auto;font-size:12px;color:${C.textDim};">${formatProjectDate(c.updated_at)}</span>
        </button>
      `).join('');
      pdRecentEl.querySelectorAll('.js-pd-recent-item').forEach((btn) => {
        btn.addEventListener('click', () => {
          const pid = viewingProjectId;
          closeProjectDetail();
          setMode('chat');
          openConversation(btn.dataset.id, pid);
        });
      });
    } catch (e) {
      pdRecentEl.innerHTML = '';
    }
  }
  // Übergibt vom Projekt-Composer in den echten Chat: neue Konversation
  // anlegen, mit diesem Projekt taggen, dann die eigentliche Aktion
  // (senden/anhängen/diktieren/Sprachmodus) auf dem echten Composer
  // auslösen — vermeidet eine zweite komplette Composer-Logik nur für
  // diese Seite.
  function pdEnterChat() {
    const pid = viewingProjectId;
    closeProjectDetail();
    startNewConversation();
    currentProjectId = pid;
  }
  async function loadProjects() {
    try {
      const r = await fetch('/projects');
      const j = await r.json();
      projectsList = j.projects || [];
    } catch (e) { projectsList = []; }
    renderProjectsGrid();
    renderPinnedProjects();
  }
  function sortedProjects(list) {
    list = list.slice();
    if (projectsSortMode === 'oldest') list.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    else if (projectsSortMode === 'updated') list.sort((a, b) => (b.updated_at || b.created_at || '').localeCompare(a.updated_at || a.created_at || ''));
    else if (projectsSortMode === 'alpha') list.sort((a, b) => a.name.localeCompare(b.name, 'de', { sensitivity: 'base' }));
    else list.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')); // 'newest' (Standard)
    return list;
  }
  function renderProjectsGrid() {
    if (!projectsGridEl) return;
    let list = projectsList.slice();
    const q = (projectsSearchInputEl ? projectsSearchInputEl.value : '').trim().toLowerCase();
    if (q) list = list.filter((p) => p.name.toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q));
    list = sortedProjects(list);
    if (!list.length) {
      projectsGridEl.innerHTML = `<div style="grid-column:1/-1;color:${C.textDim};font-size:13px;padding:8px 2px;">${q ? 'Keine Projekte gefunden.' : 'Noch keine Projekte — leg oben eins an.'}</div>`;
      return;
    }
    projectsGridEl.innerHTML = list.map((p) => `
      <div class="js-project-card" data-id="${p.id}" style="position:relative;border:1px solid ${C.border};border-radius:14px;padding:16px 18px;background:${C.bgSurface3};transition:border-color .15s;display:flex;flex-direction:column;min-height:110px;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;padding-right:44px;">
          <span style="font-size:14px;font-weight:600;color:${C.text};">${escapeHtml(p.name)}</span>
          ${p.tag ? `<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:${C.bgHover};color:${C.textSoft};">${escapeHtml(p.tag)}</span>` : ''}
        </div>
        <button class="js-project-pin-btn" data-id="${p.id}" title="${isProjectPinned(p.id) ? 'Lösen' : 'Anheften'}" style="position:absolute;top:12px;right:32px;background:none;border:none;color:${isProjectPinned(p.id) ? C.accent : C.textSoft};cursor:pointer;padding:4px;display:inline-flex;">${isProjectPinned(p.id) ? ICONS.pinFilled : ICONS.pin}</button>
        <button class="js-project-menu-btn" data-id="${p.id}" title="Optionen" style="position:absolute;top:12px;right:10px;background:none;border:none;color:${C.textSoft};cursor:pointer;padding:4px;display:inline-flex;">${ICONS.dots}</button>
        ${p.dir ? `<div style="font-size:11px;color:${C.textDim};font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:8px;" title="${escapeHtml(p.dir)}">${escapeHtml(p.dir)}</div>` : ''}
        ${p.description ? `<div style="font-size:13px;color:${C.textSoft};line-height:1.45;flex:1;">${escapeHtml(p.description)}</div>` : '<div style="flex:1;"></div>'}
        <div style="font-size:12px;color:${C.textDim};margin-top:10px;">${formatProjectDate(p.created_at)}</div>
      </div>
    `).join('');
    projectsGridEl.querySelectorAll('.js-project-pin-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        toggleProjectPin(btn.dataset.id);
        renderProjectsGrid();
        renderPinnedProjects();
      });
    });
  }

  // Angeheftete Projekte — rein clientseitig in localStorage, da es nur
  // steuert, was in DIESER Sidebar oben auftaucht (keine geteilte
  // Server-Ansicht, die synchron sein müsste).
  function getPinnedProjectIds() {
    try { return JSON.parse(localStorage.getItem('jarvis_pinned_projects') || '[]'); } catch (e) { return []; }
  }
  function isProjectPinned(id) { return getPinnedProjectIds().includes(id); }
  function toggleProjectPin(id) {
    const ids = getPinnedProjectIds();
    const i = ids.indexOf(id);
    if (i >= 0) ids.splice(i, 1); else ids.push(id);
    localStorage.setItem('jarvis_pinned_projects', JSON.stringify(ids));
  }
  function renderPinnedProjects() {
    const hintEl = $('.js-projects-pin-hint', uiEl);
    if (!hintEl) return;
    const ids = getPinnedProjectIds();
    const pinned = ids.map((id) => projectsList.find((p) => p.id === id)).filter(Boolean);
    if (!pinned.length) {
      hintEl.style.display = 'flex';
      hintEl.nextElementSibling && hintEl.nextElementSibling.remove();
      return;
    }
    hintEl.style.display = 'none';
    let list = hintEl.nextElementSibling;
    if (!list || !list.classList.contains('js-projects-pinned-list')) {
      list = document.createElement('div');
      list.className = 'js-projects-pinned-list';
      hintEl.after(list);
    }
    list.innerHTML = pinned.map((p) => `
      <button class="js-navrow js-pinned-project" data-id="${p.id}" style="display:flex;align-items:center;gap:10px;padding:8px 10px;background:none;border:none;border-radius:9px;color:${C.textSoft};font-size:13px;cursor:pointer;text-align:left;width:100%;">${ICONS.folder}<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(p.name)}</span></button>
    `).join('');
    list.querySelectorAll('.js-pinned-project').forEach((btn) => {
      btn.addEventListener('click', () => {
        const p = pinned.find((x) => x.id === btn.dataset.id);
        if (p) openProjectDetail(p);
      });
    });
  }
  function openNewProjectModal() {
    if (!newProjectSheetEl) return;
    editingProjectId = null;
    $('.js-newproject-title', newProjectSheetEl).textContent = 'Neues Projekt';
    $('.js-newproject-create', newProjectSheetEl).textContent = 'Erstellen';
    $('.js-newproject-dir-row', newProjectSheetEl).style.display = 'flex';
    $('.js-newproject-dir-display', newProjectSheetEl).style.display = 'none';
    $('.js-newproject-dir', newProjectSheetEl).value = '';
    $('.js-newproject-name', newProjectSheetEl).value = '';
    $('.js-newproject-desc', newProjectSheetEl).value = '';
    newProjectSheetEl.style.display = 'flex';
    $('.js-newproject-dir', newProjectSheetEl).focus();
  }
  function openEditProjectModal(project) {
    if (!newProjectSheetEl) return;
    editingProjectId = project.id;
    $('.js-newproject-title', newProjectSheetEl).textContent = 'Projekt umbenennen';
    $('.js-newproject-create', newProjectSheetEl).textContent = 'Speichern';
    // Der Ordner ist die eigentliche Identität des Projekts (dort liegen
    // seine Chats) — beim Umbenennen nur anzeigen, nicht änderbar, um nicht
    // aus Versehen den Bezug zu den schon gespeicherten Chats zu kappen.
    $('.js-newproject-dir-row', newProjectSheetEl).style.display = 'none';
    const dirDisplay = $('.js-newproject-dir-display', newProjectSheetEl);
    dirDisplay.style.display = 'block';
    dirDisplay.textContent = project.dir || '';
    $('.js-newproject-name', newProjectSheetEl).value = project.name || '';
    $('.js-newproject-desc', newProjectSheetEl).value = project.description || '';
    newProjectSheetEl.style.display = 'flex';
    $('.js-newproject-name', newProjectSheetEl).focus();
  }
  function closeNewProjectModal() {
    if (newProjectSheetEl) newProjectSheetEl.style.display = 'none';
    editingProjectId = null;
  }
  async function createProjectFromModal() {
    const name = $('.js-newproject-name', newProjectSheetEl).value.trim();
    const description = $('.js-newproject-desc', newProjectSheetEl).value.trim();
    const errEl = $('.js-newproject-error', newProjectSheetEl);
    if (errEl) errEl.textContent = '';
    try {
      if (editingProjectId) {
        await fetch(`/projects/${encodeURIComponent(editingProjectId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, description }),
        });
      } else {
        const dir = $('.js-newproject-dir', newProjectSheetEl).value.trim();
        if (!dir) return;
        const r = await fetch('/projects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dir, name, description }),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          if (errEl) errEl.textContent = j.detail || 'Ordner konnte nicht verwendet werden.';
          return;
        }
      }
    } catch (e) {
      if (errEl) errEl.textContent = 'Netzwerkfehler.';
      return;
    }
    closeNewProjectModal();
    loadProjects();
  }
  async function deleteProject(id) {
    try { await fetch(`/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch (e) {}
    loadProjects();
  }
  function positionFloatingMenu(anchorBtn, menuEl) {
    const container = menuEl.parentElement;
    const containerRect = container.getBoundingClientRect();
    const btnRect = anchorBtn.getBoundingClientRect();
    const menuWidth = menuEl.offsetWidth || 180;
    let left = btnRect.right - containerRect.left - menuWidth + container.scrollLeft;
    left = Math.max(0, left);
    let top = btnRect.bottom - containerRect.top + 6 + container.scrollTop;
    menuEl.style.left = left + 'px';
    menuEl.style.top = top + 'px';
  }
  function closeProjectCardMenu() {
    const menu = $('.js-project-card-menu', uiEl);
    if (menu) menu.style.display = 'none';
    uiEl.querySelectorAll('.js-project-menu-btn.is-open').forEach((b) => b.classList.remove('is-open'));
    projectCardMenuTargetId = null;
  }
  function closeProjectsSortMenu() {
    const menu = $('.js-projects-sort-menu', uiEl);
    if (menu) menu.style.display = 'none';
  }

  function wireUi() {
    $('.js-new', uiEl).addEventListener('click', () => { closeProjectsView(); closeProjectDetail(); startNewConversation(); });
    $('.js-chats-toggle', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      const collapsed = chatListEl.classList.toggle('is-collapsed');
      $('.js-chats-toggle', uiEl).classList.toggle('is-collapsed', collapsed);
      localStorage.setItem('jarvis_chats_collapsed', collapsed ? '1' : '0');
    });
    if (localStorage.getItem('jarvis_chats_collapsed') === '1') {
      chatListEl.classList.add('is-collapsed');
      $('.js-chats-toggle', uiEl).classList.add('is-collapsed');
    }
    $('.js-projects', uiEl).addEventListener('click', (e) => { e.preventDefault(); openProjectsView(); });
    $('.js-customize', uiEl).addEventListener('click', (e) => { e.preventDefault(); openSettings(); });
    $('.js-projects-pin-add', uiEl).addEventListener('click', (e) => { e.preventDefault(); openNewProjectModal(); });
    $('.js-search-toggle', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      const row = $('.js-search-row', uiEl);
      const input = $('.js-search-input', uiEl);
      const show = row.style.display === 'none';
      row.style.display = show ? 'block' : 'none';
      if (show) { input.value = ''; input.focus(); filterChatList(''); } else { filterChatList(''); }
    });
    $('.js-search-input', uiEl).addEventListener('input', (e) => filterChatList(e.target.value));
    $('.js-chats-sort', uiEl).addEventListener('click', (e) => { e.preventDefault(); loadConversationList(); });
    $('.js-projects-new', uiEl).addEventListener('click', (e) => { e.preventDefault(); openNewProjectModal(); });
    $('.js-projects-search-btn', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      projectsSearchOpen = !projectsSearchOpen;
      if (projectsSearchRowEl) projectsSearchRowEl.style.display = projectsSearchOpen ? 'block' : 'none';
      if (projectsSearchOpen && projectsSearchInputEl) projectsSearchInputEl.focus();
      else if (projectsSearchInputEl) { projectsSearchInputEl.value = ''; renderProjectsGrid(); }
    });
    if (projectsSearchInputEl) projectsSearchInputEl.addEventListener('input', renderProjectsGrid);
    $('.js-projects-sort-btn', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeProjectCardMenu();
      const menu = $('.js-projects-sort-menu', uiEl);
      const open = menu.style.display !== 'none';
      if (open) { closeProjectsSortMenu(); return; }
      menu.querySelectorAll('.js-psm-opt').forEach((b) => b.classList.toggle('active', b.dataset.sort === projectsSortMode));
      menu.style.display = 'block';
      positionFloatingMenu(e.currentTarget, menu);
    });
    $('.js-projects-sort-menu', uiEl).querySelectorAll('.js-psm-opt').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        projectsSortMode = btn.dataset.sort;
        renderProjectsGrid();
        closeProjectsSortMenu();
      });
    });
    // Drei-Punkte-Menü pro Karte — Delegation, weil renderProjectsGrid() das
    // Grid bei jedem Render komplett neu aufbaut (frische Buttons, keine
    // pro-Karte-Listener nötig).
    projectsGridEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.js-project-menu-btn');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      closeProjectsSortMenu();
      const menu = $('.js-project-card-menu', uiEl);
      const alreadyOpenForThis = projectCardMenuTargetId === btn.dataset.id && menu.style.display !== 'none';
      closeProjectCardMenu();
      if (alreadyOpenForThis) return;
      projectCardMenuTargetId = btn.dataset.id;
      btn.classList.add('is-open');
      menu.style.display = 'block';
      positionFloatingMenu(btn, menu);
    });
    projectsGridEl.addEventListener('click', (e) => {
      if (e.target.closest('.js-project-menu-btn')) return;
      const card = e.target.closest('.js-project-card');
      if (!card) return;
      const project = projectsList.find((p) => p.id === card.dataset.id);
      if (project) openProjectDetail(project);
    });
    $('.js-pcm-rename', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      const project = projectsList.find((p) => p.id === projectCardMenuTargetId);
      closeProjectCardMenu();
      if (project) openEditProjectModal(project);
    });
    $('.js-pcm-delete', uiEl).addEventListener('click', (e) => {
      e.preventDefault();
      const id = projectCardMenuTargetId;
      const project = projectsList.find((p) => p.id === id);
      closeProjectCardMenu();
      if (id && confirm(`"${project ? project.name : 'Dieses Projekt'}" wirklich löschen?`)) deleteProject(id);
    });
    window.addEventListener('click', () => { closeProjectCardMenu(); closeProjectsSortMenu(); });
    $('.js-newproject-close', newProjectSheetEl).addEventListener('click', (e) => { e.preventDefault(); closeNewProjectModal(); });
    $('.js-newproject-cancel', newProjectSheetEl).addEventListener('click', (e) => { e.preventDefault(); closeNewProjectModal(); });
    $('.js-newproject-create', newProjectSheetEl).addEventListener('click', (e) => { e.preventDefault(); createProjectFromModal(); });
    newProjectSheetEl.addEventListener('click', (e) => { if (e.target === newProjectSheetEl) closeNewProjectModal(); });

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
        updateSendSlot();
      });
    }
    updateSendSlot();
    if (speechBtn) speechBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); speechMode ? exitSpeech() : enterSpeech(); });
    if (noteBtn) noteBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); setDictating(!dictating); });
    if (uploadBtn) uploadBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); if (fileInput) fileInput.click(); });

    // Projekt-Detailseite: eigener kleiner Composer, der bei jeder echten
    // Interaktion (senden/anhängen/diktieren/Sprechen) in den normalen Chat
    // übergibt — siehe pdEnterChat(). Nur der Modell-Button bleibt hier
    // stehen (Modell wechseln muss die Seite nicht verlassen).
    if (pdBackEl) pdBackEl.addEventListener('click', () => openProjectsView());
    if (pdEditorEl) {
      pdEditorEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (pdSendBtn) pdSendBtn.click(); }
      });
    }
    if (pdSendBtn) pdSendBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const text = pdEditorEl ? pdEditorEl.innerText.trim() : '';
      if (!text) return;
      pdEnterChat();
      sendMessage(text);
    });
    if (pdUploadBtn) pdUploadBtn.addEventListener('click', (e) => {
      e.preventDefault();
      pdEnterChat();
      if (fileInput) fileInput.click();
    });
    if (pdNoteBtn) pdNoteBtn.addEventListener('click', (e) => {
      e.preventDefault();
      pdEnterChat();
      setDictating(true);
    });
    if (pdSpeechBtn) pdSpeechBtn.addEventListener('click', (e) => {
      e.preventDefault();
      pdEnterChat();
      enterSpeech();
    });
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

    // LM-Studio-Endpoint speichern
    const lmUrlInput = $('.js-lmstudio-url-input', settingsSheetEl);
    const lmUrlSave = $('.js-lmstudio-url-save', settingsSheetEl);
    const lmUrlStatus = $('.js-lmstudio-url-status', settingsSheetEl);
    if (lmUrlSave && lmUrlInput) {
      lmUrlSave.addEventListener('click', async () => {
        const v = lmUrlInput.value.trim();
        if (!v) return;
        if (lmUrlStatus) lmUrlStatus.textContent = 'Speichert…';
        try {
          await fetch('/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lm_studio_base_url: v }) });
          if (lmUrlStatus) lmUrlStatus.textContent = 'Gespeichert';
          lastModelsList = null;
          fetch('/models').then((r) => r.json()).then((j) => { applyModelCaps(j); if (j.current) setModelLabel(j.current); }).catch(() => {});
        } catch (e) { if (lmUrlStatus) lmUrlStatus.textContent = 'Fehlgeschlagen'; }
        setTimeout(() => { if (lmUrlStatus) lmUrlStatus.textContent = ''; }, 2500);
      });
    }

    if (modelBtnEl) modelBtnEl.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleModelMenu(modelBtnEl); });
    if (pdModelBtn) pdModelBtn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleModelMenu(pdModelBtn); });
    window.addEventListener('click', () => { if (modelMenuEl) modelMenuEl.style.display = 'none'; modelMenuAnchor = null; });

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
      // Jede Datei wird als Kachel angehängt — außerhalb des Eingabetextes,
      // wie bei anderen KI-Chats. Was davon beim Senden tatsächlich mitgeht
      // (Bild, gelesener Text, oder nur der Dateiname), regelt sendMessage.
      results.forEach((r) => pendingImages.push(r));
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

  function addThreadTurn(role, text, attachments) {
    const el = ensureThread();
    if (!el) return { classList: { add(){}, remove(){}, toggle(){} }, textContent: '' };
    // Letzter Turn markiert seine Aktionen dauerhaft sichtbar (nicht erst bei
    // Hover) — genau wie claude.ai es für die jeweils neueste Antwort tut.
    el.querySelectorAll('.js-turn.js-actions-pinned').forEach((t) => t.classList.remove('js-actions-pinned'));
    const row = document.createElement('div');
    row.className = 'js-turn js-actions-pinned ' + (role === 'you' ? 'js-you' : 'js-jarvis');
    if (attachments && attachments.length) {
      // Anhänge zeigen sich als Kacheln über der Nachricht — außerhalb des
      // eigentlichen Nachrichtentexts, wie bei anderen KI-Chats üblich.
      const attRow = document.createElement('div');
      attRow.style.cssText = `display:flex;gap:6px;flex-wrap:wrap;${text ? 'margin-bottom:8px;' : ''}`;
      attRow.innerHTML = attachments.map((a) => (a.image
        ? `<img src="${a.image}" title="${escapeHtml(a.name || '')}" style="width:64px;height:64px;object-fit:cover;border-radius:8px;" />`
        : `<div title="${escapeHtml(a.name || '')}" style="width:64px;height:64px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border-radius:8px;background:${C.bgHover};color:${C.textSoft};padding:2px;">${ICONS.copy}<span style="font-size:9px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(a.name || '')}</span></div>`
      )).join('');
      row.appendChild(attRow);
    }
    const inner = document.createElement('div');
    inner.className = 'js-text';
    if (role === 'you') {
      inner.textContent = text;
    } else {
      inner.dataset.raw = text;
      inner.innerHTML = renderMarkdown(text);
    }
    row.appendChild(inner);
    const actions = document.createElement('div');
    actions.className = 'js-turn-actions';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'js-turn-copy';
    copyBtn.title = 'Kopieren';
    copyBtn.innerHTML = ICONS.copy;
    copyBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      try { await navigator.clipboard.writeText(inner.dataset.raw !== undefined ? inner.dataset.raw : inner.textContent); } catch (e2) {}
    });
    actions.appendChild(copyBtn);
    row.appendChild(actions);
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
    const attachmentsForThisTurn = pendingImages.slice();
    const imagesForThisTurn = attachmentsForThisTurn.filter((a) => a.image).map((a) => a.image);
    // Lesbarer Text aus Text-Anhängen geht unsichtbar mit an das Modell —
    // sichtbar bleibt in der eigenen Nachricht nur, was der Nutzer selbst
    // getippt hat; der Anhang zeigt sich als Kachel, nicht als Textwand.
    const attachNote = attachmentsForThisTurn.filter((a) => a.sendText).map((a) => a.sendText).join('\n\n');
    const outgoingText = attachNote ? (text ? text + '\n\n' + attachNote : attachNote) : text;
    pendingImages = [];
    if (composerInput) { composerInput.innerText = ''; composerInput.classList.remove('is-empty'); }
    renderAttachPreviews();
    showThread();
    progressHostEl = null; // neue Runde eigener Fortschrittsblöcke
    addThreadTurn('you', text, attachmentsForThisTurn);
    const said = addThreadTurn('jarvis', '');
    said.classList.add('thinking');
    said.textContent = 'Denkt nach…';
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
        body: JSON.stringify({ message: outgoingText, history, turn_id: currentTurnId, mode: activeMode, conversation_id: ensureConversationId(), images: imagesForThisTurn, project_id: currentProjectId }),
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
            setAssistantText(said, parts.join(' ') + (evt.text || ''));
          } else if (evt.type === 'sentence') {
            said.classList.remove('thinking');
            if (evt.text) parts.push(evt.text);
            setAssistantText(said, parts.join(' '));
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
      else if (!fullText) { const fb = "I can't reach my language model right now. Is LM Studio running with Gemma loaded?"; fullText = fb; said.classList.remove('thinking'); setAssistantText(said, fb); }
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
    // Finaler Durchlauf mit dem autoritativen Volltext — die Live-Updates
    // während des Streamens können mitten in einem ```-Block gerendert
    // haben, bevor der schließende Zaun überhaupt eingetroffen ist.
    if (fullText) setAssistantText(said, fullText);
    if (fullText) {
      history.push({ role: 'user', content: outgoingText });
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

  // Kleiner, abhängigkeitsfreier Markdown-Renderer für Jarvis' Antworten —
  // deckt nur ab, was tatsächlich im Alltag vorkommt (Codeblöcke, Inline-Code,
  // fett/kursiv, Listen, Absätze). Kein voller CommonMark-Parser, aber genug,
  // damit ```-Blöcke nicht mehr als rohe Backticks im Fließtext auftauchen.
  function renderMarkdown(raw) {
    let text = String(raw);
    // Ein Modell (oder ein noch laufender Stream) lässt den schließenden Zaun
    // manchmal weg — ungerade Anzahl ``` heißt: der letzte Block ist offen,
    // also am Ende schließen, statt drei rohe Backticks im Fließtext zu zeigen.
    if (((text.match(/```/g) || []).length) % 2 === 1) text += '\n```';
    const blocks = [];
    // Codeblöcke zuerst herausziehen (Platzhalter einsetzen), damit ihr Inhalt
    // von den restlichen Regeln (fett/kursiv/Listen) nicht mehr angefasst wird.
    let withPlaceholders = text.replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, (m, lang, code) => {
      const idx = blocks.length;
      blocks.push(`<pre style="background:${C.bgHover};border:1px solid ${C.border};border-radius:10px;padding:12px 14px;overflow-x:auto;margin:8px 0;"><code style="font-family:Menlo,Monaco,'DejaVu Sans Mono',monospace;font-size:13px;line-height:1.5;white-space:pre;">${escapeHtml(code.replace(/\n$/, ''))}</code></pre>`);
      return ` ${idx} `;
    });
    let html = escapeHtml(withPlaceholders)
      .replace(/`([^`\n]+)`/g, (m, code) => `<code style="background:${C.bgHover};border-radius:4px;padding:1px 5px;font-family:Menlo,Monaco,'DejaVu Sans Mono',monospace;font-size:.9em;">${code}</code>`)
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
      .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul style="margin:6px 0;padding-left:22px;">${m}</ul>`)
      .split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
      .map((p) => (/^<(ul|pre)/.test(p) ? p : `<p style="margin:0 0 10px;">${p.replace(/\n/g, '<br>')}</p>`))
      .join('');
    return html.replace(/ (\d+) /g, (m, idx) => blocks[Number(idx)]);
  }

  function setAssistantText(el, text) {
    el.dataset.raw = text;
    el.innerHTML = renderMarkdown(text);
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
        block.style.cssText = `display:flex;align-items:center;gap:9px;padding:10px 12px;border:1px solid ${C.border};border-radius:12px;background:${C.bgSurface3};font-size:13px;`;
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
      b.style.cssText = `padding:10px 12px;border:1px solid ${C.border};border-left:3px solid ${C.accent};border-radius:10px;background:${C.bgSurface3};font-size:13px;color:${C.text};`;
      b.textContent = item.text || '';
      host.appendChild(b);
      scrollThread();
      return;
    }

    if (kind === 'markdown') {
      const b = document.createElement('div');
      b.style.cssText = `padding:10px 12px;border:1px solid ${C.border};border-radius:10px;background:${C.bgSurface3};font-size:13px;color:${C.textSoft};`;
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
      sum.style.cssText = `padding:8px 12px;font-size:12px;color:${C.textDim};cursor:pointer;background:${C.bgSurface3};`;
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
      wrap.style.cssText = `border:1px solid ${C.border};border-radius:10px;overflow:hidden;background:${C.bgSurface3};`;
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
  let modelMenuAnchor = null;  // welcher Button hat das Menü zuletzt geöffnet — für Repositionierung nach dem fetch
  function positionModelMenu(anchorBtn) {
    if (!modelMenuEl || !anchorBtn || !uiEl) return;
    const appRect = uiEl.getBoundingClientRect();
    const btnRect = anchorBtn.getBoundingClientRect();
    const menuWidth = 220;
    // Am linken Rand des Buttons ausgerichtet (nicht am rechten) — sitzt
    // dadurch direkt über/unter dem ausgewählten Modellnamen statt weiter links.
    let left = btnRect.left - appRect.left;
    left = Math.max(0, Math.min(left, appRect.width - menuWidth));
    modelMenuEl.style.left = left + 'px';
    const menuHeight = modelMenuEl.offsetHeight || 200;
    let top = btnRect.top - appRect.top - menuHeight - 8;
    if (top < 0) top = btnRect.bottom - appRect.top + 8;  // kein Platz oben -> unten öffnen
    modelMenuEl.style.top = top + 'px';
  }
  function renderModelMenu(models) {
    modelMenuEl.innerHTML = '';
    if (!models.length) {
      const d = document.createElement('div');
      d.textContent = 'Keine Modelle — läuft LM Studio?';
      d.style.cssText = `padding:14px;font-size:13px;color:${C.textDim};`;
      modelMenuEl.appendChild(d);
      return;
    }
    for (const m of models) {
      const publisher = String(m.id).includes('/') ? String(m.id).split('/')[0] : '';
      const b = document.createElement('button');
      b.style.cssText = `display:flex;flex-direction:column;gap:1px;width:100%;text-align:left;padding:8px 14px;background:none;border:none;color:${C.text};font-size:13.5px;font-weight:500;cursor:pointer;line-height:1.35;`;
      b.title = m.id;
      const nameEl = document.createElement('span');
      nameEl.textContent = prettyModelName(m.id);
      nameEl.style.cssText = `overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`;
      b.appendChild(nameEl);
      if (publisher) {
        const subEl = document.createElement('span');
        subEl.textContent = publisher;
        subEl.style.cssText = `font-size:11.5px;font-weight:400;color:${C.textDim};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`;
        b.appendChild(subEl);
      }
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
  async function toggleModelMenu(anchorBtn) {
    if (!modelMenuEl) return;
    anchorBtn = anchorBtn || modelBtnEl;
    const open = modelMenuEl.style.display !== 'none';
    if (open && modelMenuAnchor === anchorBtn) { modelMenuEl.style.display = 'none'; modelMenuAnchor = null; return; }
    modelMenuAnchor = anchorBtn;
    // Sofort öffnen — mit dem letzten bekannten Stand, falls vorhanden —
    // statt erst auf den fetch zu warten. Vorher fühlte sich ein Klick
    // wirkungslos an, solange /models noch unterwegs war, und ein zweiter
    // Klick währenddessen stieß einen weiteren parallelen fetch an.
    if (lastModelsList) renderModelMenu(lastModelsList);
    else { modelMenuEl.innerHTML = `<div style="padding:10px 14px;font-size:13px;color:${C.textDim};">Lädt…</div>`; }
    modelMenuEl.style.display = 'block';
    positionModelMenu(anchorBtn);
    try {
      const r = await fetch('/models');
      const j = await r.json();
      const models = (j.models || []).map((m) => ({ id: m }));
      applyModelCaps(j);
      if (j.current) setModelLabel(j.current);
      lastModelsList = models;
      if (modelMenuEl.style.display !== 'none') { renderModelMenu(models); positionModelMenu(modelMenuAnchor); }
    } catch (e) {
      if (!lastModelsList) renderModelMenu([]);
    }
  }

  // Rohe LM-Studio-IDs ("google/gemma-4-e4b", "qwen2.5-coder-32b-instruct")
  // sind technische Dateinamen, keine Anzeigenamen. Wir trennen an "-"/"_",
  // schreiben Wortsegmente groß und heben kurze Größen-/Versionscodes (4b,
  // e4b, 32b, 3.1 …) komplett in Großbuchstaben — ohne eine Lookup-Tabelle zu
  // pflegen, die bei jedem neuen Modell wieder veraltet wäre.
  function prettyModelName(id) {
    const short = String(id).split('/').pop();
    return short
      .split(/[-_]+/)
      .map((seg) => {
        if (!seg) return seg;
        if (seg.length <= 4 && /\d/.test(seg)) return seg.toUpperCase();
        return seg.charAt(0).toUpperCase() + seg.slice(1);
      })
      .join(' ');
  }

  function setModelLabel(id) {
    const pretty = prettyModelName(id);
    if (modelEl) { modelEl.textContent = pretty; modelEl.title = id; }
    if (pdModelLabelEl) { pdModelLabelEl.textContent = pretty; pdModelLabelEl.title = id; }
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
      lineHeight: 1.0,
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
    // LM-Studio-Endpoint aus /settings vorbelegen.
    try {
      const r = await fetch('/settings');
      const j = await r.json();
      const uin = $('.js-lmstudio-url-input', settingsSheetEl);
      if (uin && j.lm_studio_base_url) uin.value = j.lm_studio_base_url;
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
          d.textContent = 'Keine Modelle — läuft LM Studio?';
          d.style.cssText = `padding:10px 14px;font-size:13px;color:${C.textDim};`;
          settingsModelsEl.appendChild(d);
          return;
        }
        for (const m of models) {
          const publisher = String(m).includes('/') ? String(m).split('/')[0] : '';
          const b = document.createElement('button');
          b.title = m;
          b.style.cssText = `display:flex;flex-direction:column;gap:1px;width:100%;text-align:left;padding:8px 14px;background:none;border:none;color:${C.text};font-size:13.5px;font-weight:500;cursor:pointer;line-height:1.35;border-radius:8px;`;
          const nameEl = document.createElement('span');
          nameEl.textContent = prettyModelName(m);
          nameEl.style.cssText = `overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`;
          b.appendChild(nameEl);
          if (publisher) {
            const subEl = document.createElement('span');
            subEl.textContent = publisher;
            subEl.style.cssText = `font-size:11.5px;font-weight:400;color:${C.textDim};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`;
            b.appendChild(subEl);
          }
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
        updateSendSlot();
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
    if (noteBtn) noteBtn.title = should ? 'Diktat aus' : 'Diktieren';
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
    const toggleSidebar = () => {
      const aside = $('.js-sidebar', uiEl);
      const floatBtn = $('.js-side-toggle-float', uiEl);
      const open = aside.style.display !== 'none';
      aside.style.display = open ? 'none' : 'flex';
      if (floatBtn) floatBtn.style.display = open ? 'inline-flex' : 'none';
      const comp = $('.js-composer', uiEl);
      if (comp) comp.style.left = open ? '0' : '308px';
      if (orbCanvas) orbCanvas.style.left = open ? '0' : '308px';
      layoutSpeechBar();
    };
    const t = $('.js-side-toggle', uiEl);
    if (t) t.addEventListener('click', toggleSidebar);
    const tf = $('.js-side-toggle-float', uiEl);
    if (tf) tf.addEventListener('click', toggleSidebar);
    window.addEventListener('resize', layoutSpeechBar);
    fetch('/models').then((r) => r.json()).then((j) => { applyModelCaps(j); if (j.current) setModelLabel(j.current); }).catch(() => {});
    openPanelSocket();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
