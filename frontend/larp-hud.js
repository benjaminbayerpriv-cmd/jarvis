// JARVIS — "/larp"-Modus: ein Vollbild-Command-Center im Iron-Man-HUD-Stil,
// das sich über die normale Oberfläche legt. Eigenständiges Modul ohne
// Abhängigkeit von claude-app.js: es bringt sein eigenes CSS (inkl. lokal
// abgelegter Orbitron-/Rajdhani-Schriften, siehe assets/fonts/larp/) mit und
// wird über window.JarvisLarp.open(hooks) / .close() gesteuert. hooks kommen
// aus claude-app.js (Slash-Befehl /larp) und verbinden ein paar Knöpfe mit
// echten Aktionen (neuer Chat, Sprachmodus) — alles andere ist Kulisse.
// Geschlossen wird über das Kreuz oben rechts oder Escape.
(() => {
  'use strict';

  // Basis-URL der statischen Dateien aus der eigenen Skript-URL ableiten —
  // so zeigen die Schriftpfade sowohl unter /static als auch unter einem
  // anderen Präfix auf den richtigen Ordner.
  const SCRIPT_SRC = (document.currentScript && document.currentScript.src) || '/static/larp-hud.js';
  const STATIC_BASE = SCRIPT_SRC.replace(/\/[^/]*$/, '');
  const FONT_BASE = STATIC_BASE + '/assets/fonts/larp';

  // ---------------------------------------------------------------- Icons
  const P = {
    dashboard: '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/>',
    tasks: '<path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    calendar: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    book: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    workflow: '<rect width="8" height="8" x="3" y="3" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect width="8" height="8" x="13" y="13" rx="2"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    listchecks: '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8M13 12h8M13 18h8"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
    pr: '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7M6 9v12"/>',
    target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    alertc: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    gear: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    apps: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    user: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    chevr: '<path d="m9 18 6-6-6-6"/>',
    chevd: '<path d="m6 9 6 6 6-6"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h.79a4.5 4.5 0 1 1 0 9Z"/>',
    wifi: '<path d="M12 20h.01M2 8.82a15 15 0 0 1 20 0M5 12.86a10 10 0 0 1 14 0M8.5 16.43a5 5 0 0 1 7 0"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    command: '<path d="M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    aperture: '<circle cx="12" cy="12" r="10"/><path d="m14.31 8 5.74 9.94M9.69 8h11.48M7.38 12l5.74-9.94M9.69 16 3.95 6.06M14.31 16H2.83m13.79-4-5.74 9.94"/>',
    sparkle: '<path d="M12 3c.5 4.5 4.5 8.5 9 9-4.5.5-8.5 4.5-9 9-.5-4.5-4.5-8.5-9-9 4.5-.5 8.5-4.5 9-9z"/>',
    zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
    box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>',
    terminal: '<path d="m4 17 6-6-6-6M12 19h8"/>',
    pointer: '<path d="M4.04 4.95a.5.5 0 0 1 .65-.65l15.7 6.27a.5.5 0 0 1-.06.95l-6.02 1.54a2 2 0 0 0-1.44 1.44l-1.54 6.02a.5.5 0 0 1-.95.06z"/>',
  };
  const ic = (name, extra = '') => `<svg class="lh-ic ${extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;

  // Reaktor-Logo der Seitenleiste (konzentrische Ringe wie im Vorbild).
  const LOGO = `<svg class="lh-logo-svg" viewBox="0 0 48 48" aria-hidden="true">
    <circle cx="24" cy="24" r="22" fill="none" stroke="#22d3ff" stroke-opacity=".35" stroke-width="1"/>
    <circle cx="24" cy="24" r="18" fill="none" stroke="#22d3ff" stroke-width="2" stroke-dasharray="6 3"/>
    <circle cx="24" cy="24" r="12" fill="rgba(34,211,255,.12)" stroke="#7fe9ff" stroke-width="1.5"/>
    <circle cx="24" cy="24" r="5" fill="#bff6ff"/>
    <path d="M24 6v6M24 36v6M6 24h6M36 24h6" stroke="#22d3ff" stroke-width="1.5"/>
  </svg>`;

  // ---------------------------------------------------------------- Daten
  const NAV = [
    { id: 'command', label: 'Command Center', icon: 'dashboard', active: true },
    { id: 'core', label: 'AI Core', icon: 'cpu' },
    { id: 'agents', label: 'Agents', icon: 'bot' },
    { id: 'tasks', label: 'Tasks', icon: 'tasks', badge: '7' },
    { id: 'calendar', label: 'Calendar', icon: 'calendar' },
    { id: 'memory', label: 'Memory', icon: 'database' },
    { id: 'conversations', label: 'Conversations', icon: 'message', badge: '12' },
    { id: 'knowledge', label: 'Knowledge Base', icon: 'book' },
    { id: 'tools', label: 'Tools & Skills', icon: 'wrench', badge: '18' },
    { id: 'workflows', label: 'Workflows', icon: 'workflow' },
  ];
  const OVERVIEW = [
    { label: 'AI Core', status: 'Active', icon: 'cpu', tone: 'green' },
    { label: 'Memory', status: '3,380 Stored', icon: 'database', tone: 'dim', key: 'memory' },
    { label: 'Voice', status: 'Online', icon: 'mic', tone: 'green' },
    { label: 'Agents', status: '2 Running', icon: 'users', tone: 'orange' },
    { label: 'LLMs', status: '4 Connected', icon: 'layers', tone: 'green' },
    { label: 'System', status: 'Optimal', icon: 'shield', tone: 'green' },
  ];
  const FEED = [
    { title: 'Design review with the product team in 15 min', sub: 'Meeting', icon: 'calendar', tone: 'cyan', tag: 'INFO' },
    { title: '3 tasks are overdue — “Polish voice pipeline” and 2 more', sub: 'Overdue', icon: 'alert', tone: 'orange', tag: 'WARN' },
    { title: '3 pull requests are awaiting your review', sub: 'GitHub', icon: 'pr', tone: 'green', tag: 'TIP' },
    { title: 'Your deep-work block is 2–4 PM. Notifications muted.', sub: 'Focus', icon: 'target', tone: 'cyan', tag: 'TIP' },
    { title: 'CPU usage at 15%', sub: 'System load nominal', icon: 'activity', tone: 'green', tag: 'LIVE', key: 'cpu' },
    { title: '2 tasks overdue', sub: 'Review the board and reschedule', icon: 'alertc', tone: 'red', action: 'View Tasks' },
  ];
  const AGENTS = [
    { name: 'Coding Agent', icon: 'code', tone: 'cyan', active: true },
    { name: 'Research Agent', icon: 'search', tone: 'cyan', active: true },
    { name: 'Memory Agent', icon: 'database', tone: 'purple' },
    { name: 'Browser Agent', icon: 'globe', tone: 'orange' },
    { name: 'Task Agent', icon: 'listchecks', tone: 'cyan' },
    { name: 'System Agent', icon: 'shield', tone: 'green', check: true },
  ];
  // Termine relativ zu "jetzt" verankert, damit die Zeitleiste immer genau
  // so aussieht wie im Vorbild (ein erledigter Termin, dann "in 42m",
  // "in 1h 42m", "in 3h 42m") — egal, wann der Modus geöffnet wird.
  const TIMELINE = [
    { title: 'Daily Standup', offset: -138, done: true },
    { title: 'Finalize HUD panel spacing', offset: 42, progress: true },
    { title: 'Deep-work block: Voice pipeline', offset: 102, warn: true },
    { title: 'Design Review — Command Center V1', offset: 222 },
  ];
  const QUICK = [
    { label: 'Start New Task', icon: 'plus', action: 'newChat' },
    { label: 'Open Calendar', icon: 'calendar' },
    { label: 'Start Voice Chat', icon: 'mic', action: 'voice' },
    { label: 'Run Workflow', icon: 'play' },
  ];
  const LLMS = [
    { name: 'Claude', icon: 'sun', on: false },
    { name: 'OpenAI', icon: 'aperture', on: false },
    { name: 'Gemini', icon: 'sparkle', on: false },
    { name: 'Groq', icon: 'zap', on: true },
    { name: 'OpenRouter', icon: 'route', on: false },
    { name: 'Ollama', icon: 'box', on: false },
    { name: 'Claude Code', icon: 'terminal', on: true },
    { name: 'Cursor', icon: 'pointer', on: true },
    { name: 'Copilot', icon: 'bot', on: true },
  ];

  // ------------------------------------------------------------------ CSS
  const CSS = `
@font-face{font-family:'LH Orbitron';src:url('${FONT_BASE}/orbitron-latin-wght-normal.woff2') format('woff2');font-weight:400 900;font-display:swap}
@font-face{font-family:'LH Rajdhani';src:url('${FONT_BASE}/rajdhani-latin-500-normal.woff2') format('woff2');font-weight:500;font-display:swap}
@font-face{font-family:'LH Rajdhani';src:url('${FONT_BASE}/rajdhani-latin-600-normal.woff2') format('woff2');font-weight:600;font-display:swap}
@font-face{font-family:'LH Rajdhani';src:url('${FONT_BASE}/rajdhani-latin-700-normal.woff2') format('woff2');font-weight:700;font-display:swap}
.lh-root{
  --c:#22d3ff;--c2:#0ea5e9;--cg:rgba(34,211,255,.55);--t:#dff4ff;--ts:#9cc3da;--td:#5f86a3;
  --g:#3be8a0;--o:#ffab3d;--r:#ff4d61;--p:#a98bff;
  --pb:rgba(6,22,42,.74);--bd:rgba(56,189,248,.26);--bd2:rgba(56,189,248,.5);
  --fh:'LH Orbitron','Orbitron','Eurostile','Segoe UI',system-ui,sans-serif;
  --fb:'LH Rajdhani','Rajdhani','Segoe UI',system-ui,sans-serif;
  position:fixed;inset:0;z-index:2147483000;overflow:hidden;
  font-family:var(--fb);font-weight:600;color:var(--t);font-size:13px;line-height:1.25;
  background:
    radial-gradient(ellipse at 55% 32%,rgba(14,90,150,.38),transparent 55%),
    radial-gradient(ellipse at 50% 120%,rgba(10,70,120,.35),transparent 60%),
    linear-gradient(180deg,#041222 0%,#020a16 55%,#020812 100%);
  opacity:0;transition:opacity .35s ease;
  -webkit-font-smoothing:antialiased;user-select:none;
}
.lh-root.lh-in{opacity:1}
.lh-stage{position:absolute;inset:0;z-index:1;display:grid;grid-template-columns:clamp(176px,13.2vw,250px) 1fr;grid-template-rows:56px 1fr 58px;
  grid-template-areas:"side top" "side main" "bot bot";gap:10px;padding:10px 12px;transform-origin:0 0}
.lh-stage.lh-scaled{inset:auto;left:0;top:0;grid-template-columns:200px 1fr}
.lh-root *,.lh-root *::before,.lh-root *::after{box-sizing:border-box}
.lh-root::before{content:"";position:absolute;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(56,189,248,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,.05) 1px,transparent 1px);
  background-size:44px 44px;mask-image:radial-gradient(ellipse at center,#000 30%,transparent 85%);-webkit-mask-image:radial-gradient(ellipse at center,#000 30%,transparent 85%)}
.lh-root::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:0;
  background:repeating-linear-gradient(180deg,rgba(255,255,255,.012) 0 1px,transparent 1px 3px)}
.lh-ic{width:16px;height:16px;flex:none;display:block}
:where(.lh-root) button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
.lh-panel{background:var(--pb);border:1px solid var(--bd);border-radius:7px;position:relative;min-width:0;min-height:0;
  box-shadow:inset 0 0 22px rgba(14,165,233,.07),0 0 0 1px rgba(0,0,0,.25),0 8px 30px rgba(0,0,0,.35);
  padding:10px 12px;display:flex;flex-direction:column}
.lh-panel::before,.lh-panel::after{content:"";position:absolute;width:12px;height:12px;pointer-events:none;border-color:var(--c);border-style:solid;opacity:.85}
.lh-panel::before{top:-1px;left:-1px;border-width:1.5px 0 0 1.5px;border-top-left-radius:7px}
.lh-panel::after{bottom:-1px;right:-1px;border-width:0 1.5px 1.5px 0;border-bottom-right-radius:7px}
.lh-ph{display:flex;align-items:center;gap:8px;margin-bottom:8px;min-height:16px}
.lh-pt{font-family:var(--fb);font-weight:700;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#cfefff;white-space:nowrap}
.lh-ph .lh-sp{flex:1}
.lh-link{color:var(--c);font-size:12px;font-weight:600;display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.lh-link .lh-ic{width:12px;height:12px}
.lh-link:hover{color:#8ff0ff;text-shadow:0 0 8px var(--cg)}
.lh-ibox{width:28px;height:28px;border-radius:6px;display:grid;place-items:center;flex:none;border:1px solid rgba(56,189,248,.35);background:rgba(14,116,178,.16);color:var(--c);box-shadow:inset 0 0 10px rgba(34,211,255,.12)}
.lh-ibox .lh-ic{width:15px;height:15px}
.lh-t-cyan{color:var(--c)} .lh-t-green{color:var(--g)} .lh-t-orange{color:var(--o)} .lh-t-red{color:var(--r)} .lh-t-purple{color:var(--p)} .lh-t-dim{color:var(--ts)}
.lh-ibox.lh-t-green{border-color:rgba(59,232,160,.4);background:rgba(59,232,160,.1)}
.lh-ibox.lh-t-orange{border-color:rgba(255,171,61,.45);background:rgba(255,171,61,.1)}
.lh-ibox.lh-t-red{border-color:rgba(255,77,97,.5);background:rgba(255,77,97,.12)}
.lh-ibox.lh-t-purple{border-color:rgba(169,139,255,.45);background:rgba(169,139,255,.12)}
.lh-dot{width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 6px currentColor;display:inline-block;flex:none}

/* ---- Seitenleiste ---- */
.lh-side{grid-area:side;display:flex;flex-direction:column;gap:10px;min-height:0}
.lh-brand{display:flex;align-items:center;gap:10px;padding:4px 6px 6px;flex:none}
.lh-logo-svg{width:40px;height:40px;filter:drop-shadow(0 0 8px rgba(34,211,255,.6));animation:lh-spin 18s linear infinite}
.lh-brand-name{font-family:var(--fh);font-weight:800;font-size:21px;letter-spacing:.2em;color:#e8fbff;text-shadow:0 0 12px rgba(34,211,255,.55)}
.lh-brand-sub{font-size:10px;letter-spacing:.26em;color:var(--ts);margin-top:2px;white-space:nowrap}
.lh-nav{display:flex;flex-direction:column;gap:3px;flex:1;min-height:0;overflow:hidden;padding:2px}
.lh-nav-item{display:flex;align-items:center;gap:11px;padding:0 10px;flex:1 1 0;min-height:22px;max-height:38px;border-radius:6px;color:#b6d6ea;font-size:14px;font-weight:600;border:1px solid transparent;text-align:left;transition:background .15s,border-color .15s,color .15s}
.lh-nav-item:hover{background:rgba(34,211,255,.06);color:#e6f8ff}
.lh-nav-item.lh-on{background:linear-gradient(90deg,rgba(34,211,255,.18),rgba(34,211,255,.04));border-color:rgba(34,211,255,.45);color:#fff;box-shadow:inset 3px 0 0 var(--c),0 0 14px rgba(34,211,255,.15)}
.lh-nav-item .lh-ic{width:17px;height:17px;color:var(--c)}
.lh-nav-item .lh-lbl{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lh-badge{min-width:22px;height:18px;padding:0 6px;border-radius:5px;background:rgba(34,211,255,.14);border:1px solid rgba(34,211,255,.35);color:#9ff0ff;font-size:11px;display:grid;place-items:center}
.lh-voice{flex:none;align-items:center;padding:10px 10px 12px}
.lh-voice .lh-ph{align-self:stretch}
.lh-voice canvas{width:100%;height:clamp(26px,5.5vh,48px);display:block}
.lh-listen{font-size:13px;color:#bdeaff;margin:2px 0 6px;letter-spacing:.04em}
.lh-micbtn{width:clamp(44px,7vh,60px);height:clamp(44px,7vh,60px);border-radius:50%;display:grid;place-items:center;color:#e9fdff;position:relative;
  background:radial-gradient(circle at 50% 40%,#1fb8e6,#0b5f91 70%);border:1.5px solid #7fe9ff;
  box-shadow:0 0 18px rgba(34,211,255,.75),0 0 40px rgba(34,211,255,.35),inset 0 0 12px rgba(255,255,255,.25)}
.lh-micbtn::before{content:"";position:absolute;inset:-8px;border-radius:50%;border:1px solid rgba(34,211,255,.45);animation:lh-pulse 2.2s ease-out infinite}
.lh-micbtn .lh-ic{width:22px;height:22px}
.lh-tap{font-size:12px;color:var(--ts);margin-top:6px}
.lh-focus{flex:none;display:flex;align-items:center;justify-content:center;gap:8px;height:36px;border-radius:7px;border:1px solid var(--bd);background:var(--pb);color:#cdeeff;font-size:13px}
.lh-focus:hover,.lh-focus.lh-on{border-color:var(--bd2);color:#fff;box-shadow:0 0 14px rgba(34,211,255,.2)}
.lh-focus .lh-ic{color:var(--c)}

/* ---- Kopfzeile ---- */
.lh-top{grid-area:top;display:flex;align-items:center;gap:12px;min-width:0}
.lh-status{display:flex;align-items:center;gap:8px;height:34px;padding:0 14px;border-radius:7px;border:1px solid var(--bd);background:var(--pb);font-size:11px;letter-spacing:.14em;color:#bfe3f5;white-space:nowrap}
.lh-status b{color:var(--g);font-weight:700}
.lh-status .lh-dot{color:var(--g)}
.lh-clock{flex:1;text-align:center;min-width:0}
.lh-date{font-size:12px;color:var(--ts);letter-spacing:.06em}
.lh-time{font-family:var(--fh);font-weight:600;font-size:24px;letter-spacing:.06em;color:#eafcff;text-shadow:0 0 14px rgba(34,211,255,.6);line-height:1.1;white-space:nowrap}
.lh-time small{font-size:.62em;margin-left:4px;letter-spacing:.04em}
.lh-search{display:flex;align-items:center;gap:8px;height:34px;width:clamp(150px,15vw,260px);padding:0 10px;border-radius:7px;border:1px solid var(--bd);background:rgba(3,14,28,.75);color:var(--td)}
.lh-search input{flex:1;min-width:0;background:none;border:0;outline:0;color:var(--t);font:inherit;font-size:13px}
.lh-search input::placeholder{color:var(--td)}
.lh-search .lh-ic{width:15px;height:15px}
.lh-tbtn{width:34px;height:34px;border-radius:7px;border:1px solid var(--bd);background:var(--pb);display:grid;place-items:center;color:#bfe3f5;position:relative;flex:none}
.lh-tbtn:hover{border-color:var(--bd2);color:#fff}
.lh-tbtn .lh-ping{position:absolute;top:7px;right:8px;width:6px;height:6px;border-radius:50%;background:var(--o);box-shadow:0 0 6px var(--o)}
.lh-op{display:flex;align-items:center;gap:9px;height:38px;padding:0 4px 0 12px;border-radius:7px;border:1px solid var(--bd);background:var(--pb);white-space:nowrap}
.lh-op-n{font-size:13px;color:#eafcff;line-height:1.1;text-align:right}
.lh-op-r{font-size:11px;color:var(--ts);text-align:right}
.lh-av{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;border:1.5px solid var(--c);color:var(--c);background:rgba(34,211,255,.1);box-shadow:0 0 10px rgba(34,211,255,.35)}
.lh-close{width:38px;height:38px;border-radius:8px;border:1px solid rgba(34,211,255,.55);background:rgba(6,22,42,.85);display:grid;place-items:center;color:#bff4ff;flex:none;
  box-shadow:0 0 12px rgba(34,211,255,.25);transition:all .15s}
.lh-root :focus-visible{outline:1px solid var(--c);outline-offset:2px}
.lh-close .lh-ic{width:20px;height:20px}
.lh-close:hover{border-color:var(--r);color:#fff;background:rgba(255,77,97,.22);box-shadow:0 0 16px rgba(255,77,97,.55)}

/* ---- Hauptraster ---- */
.lh-main{grid-area:main;display:grid;grid-template-rows:1.42fr .92fr 1fr;gap:10px;min-height:0;min-width:0}
.lh-row{display:grid;gap:10px;min-height:0;min-width:0}
.lh-row1{grid-template-columns:1fr 3.35fr 1.42fr}
.lh-row2{grid-template-columns:2.5fr 1.25fr 1fr}
.lh-row3{grid-template-columns:1.05fr 1fr 1.85fr}

.lh-ov-list{display:flex;flex-direction:column;gap:5px;flex:1;min-height:0}
.lh-ov{display:flex;align-items:center;gap:9px;flex:1;min-height:0;padding:3px 7px;border-radius:6px;border:1px solid rgba(56,189,248,.16);background:rgba(8,32,58,.45)}
.lh-ov .lh-ibox{width:24px;height:24px}
.lh-ov .lh-ibox .lh-ic{width:13px;height:13px}
.lh-ov-l{font-size:13px;color:#e6f7ff;line-height:1.05}
.lh-ov-s{font-size:11px;line-height:1.1}

.lh-core{padding:0;overflow:hidden;border-color:rgba(56,189,248,.34)}
.lh-core canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.lh-core-txt{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center;pointer-events:none}
.lh-core-name{font-family:var(--fh);font-weight:800;font-size:clamp(26px,3.3vw,60px);letter-spacing:.16em;margin-right:-.16em;color:#effdff;
  text-shadow:0 0 6px #7fe9ff,0 0 22px rgba(34,211,255,.9),0 0 50px rgba(34,211,255,.5)}
.lh-core-sub{font-family:var(--fh);font-weight:600;font-size:clamp(10px,.9vw,15px);letter-spacing:.5em;margin-right:-.5em;color:#bdf1ff;margin-top:6px;text-shadow:0 0 10px rgba(34,211,255,.8)}
.lh-core-ver{font-size:clamp(9px,.75vw,12px);letter-spacing:.2em;color:var(--ts);margin-top:6px}

.lh-live{display:inline-flex;align-items:center;gap:5px;font-size:10px;letter-spacing:.12em;color:var(--g);border:1px solid rgba(59,232,160,.4);background:rgba(59,232,160,.08);border-radius:4px;padding:1px 6px}
.lh-live .lh-dot{width:5px;height:5px;animation:lh-blink 1.2s steps(2) infinite}
.lh-feed{display:flex;flex-direction:column;gap:4px;flex:1;min-height:0}
.lh-fi{display:flex;align-items:center;gap:8px;flex:1;min-height:0;padding:2px 6px;border-radius:6px;border:1px solid rgba(56,189,248,.12);background:rgba(8,32,58,.4)}
.lh-fi.lh-alert{border-color:rgba(255,77,97,.45);background:rgba(255,77,97,.1)}
.lh-fi .lh-ibox{width:22px;height:22px;border-radius:5px}
.lh-fi .lh-ibox .lh-ic{width:12px;height:12px}
.lh-fi-b{flex:1;min-width:0}
.lh-fi-t{font-size:12px;color:#eaf8ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.15}
.lh-fi-s{font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.15}
.lh-tag{font-size:9.5px;letter-spacing:.08em;padding:1px 5px;border-radius:3px;border:1px solid currentColor;flex:none;opacity:.95}
.lh-vt{flex:none;font-size:10.5px;padding:3px 7px;border-radius:4px;background:rgba(255,77,97,.25);border:1px solid rgba(255,77,97,.6);color:#ffd6db}
.lh-vt:hover{background:rgba(255,77,97,.45)}
.lh-feed-foot{text-align:right;margin-top:6px}

.lh-agents{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:1fr 1fr;gap:7px;flex:1;min-height:0}
.lh-ag{display:flex;align-items:center;gap:9px;padding:6px 9px;border-radius:6px;border:1px solid rgba(56,189,248,.18);background:rgba(8,32,58,.45);min-width:0;min-height:0}
.lh-ag.lh-act{border-color:rgba(56,189,248,.32)}
.lh-ag-b{min-width:0;flex:none}
.lh-ag-n{font-size:13px;color:#eaf8ff;white-space:nowrap}
.lh-ag-s{font-size:11px;display:flex;align-items:center;gap:5px}
.lh-ag-s .lh-dot{width:5px;height:5px}
.lh-ag canvas{flex:1;min-width:20px;height:26px;display:block}
.lh-ag-chk{flex:1;display:flex;justify-content:flex-end;color:var(--g)}
.lh-ag-chk .lh-ic{width:22px;height:22px;filter:drop-shadow(0 0 6px rgba(59,232,160,.7))}

.lh-sel{display:inline-flex;align-items:center;gap:3px;font-size:11px;color:var(--ts);border:1px solid var(--bd);border-radius:4px;padding:1px 6px}
.lh-sel .lh-ic{width:11px;height:11px}
.lh-tl{display:flex;flex-direction:column;flex:1;min-height:0;justify-content:space-between;position:relative;overflow:hidden}
.lh-tli{display:grid;grid-template-columns:40px 14px 1fr auto;align-items:center;gap:6px;position:relative}
.lh-tl-time{font-size:10.5px;color:var(--ts);line-height:1.05;text-align:right}
.lh-tl-dot{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--c);background:#05182c;justify-self:center;position:relative;z-index:1}
.lh-tli.lh-done .lh-tl-dot{background:var(--c);box-shadow:0 0 8px var(--c)}
.lh-tli.lh-warn .lh-tl-dot{border-color:var(--o)}
.lh-tl::before{content:"";position:absolute;left:52px;top:8px;bottom:8px;width:1px;background:linear-gradient(var(--c),rgba(34,211,255,.15))}
.lh-tl-title{font-size:12px;color:#e8f8ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.lh-tli.lh-warn .lh-tl-title{color:#ffc773}
.lh-tl-bar{height:2px;border-radius:2px;background:rgba(34,211,255,.18);margin-top:3px;overflow:hidden}
.lh-tl-bar i{display:block;height:100%;width:62%;background:linear-gradient(90deg,var(--c),#8ff0ff);box-shadow:0 0 6px var(--c)}
.lh-tl-st{font-size:11px;color:var(--ts);white-space:nowrap}
.lh-tli.lh-done .lh-tl-st{color:var(--g)}
.lh-tl-foot{text-align:center;margin-top:6px}

.lh-qc{display:flex;flex-direction:column;gap:6px;flex:1;min-height:0}
.lh-qb{display:flex;align-items:center;gap:10px;flex:1;min-height:0;padding:0 10px;border-radius:6px;border:1px solid rgba(56,189,248,.24);background:rgba(8,32,58,.5);font-size:13px;color:#e3f6ff;text-align:left;transition:all .15s}
.lh-qb .lh-ibox{width:24px;height:24px;border-radius:50%}
.lh-qb .lh-ibox .lh-ic{width:13px;height:13px}
.lh-qb:hover{border-color:var(--bd2);background:rgba(34,211,255,.12);box-shadow:0 0 14px rgba(34,211,255,.18);color:#fff}

.lh-gauges{display:flex;justify-content:space-around;align-items:center;flex:1;min-height:0;gap:6px}
.lh-gauge{position:relative;width:min(100%,92px);aspect-ratio:1;max-height:100%}
.lh-gauge svg{width:100%;height:100%;transform:rotate(-90deg);overflow:visible}
.lh-gauge .lh-gt{fill:none;stroke:rgba(34,211,255,.13);stroke-width:7}
.lh-gauge .lh-gv{fill:none;stroke:var(--c);stroke-width:7;stroke-linecap:round;filter:drop-shadow(0 0 4px rgba(34,211,255,.85));transition:stroke-dashoffset .8s ease}
.lh-gauge .lh-gk{fill:none;stroke:rgba(34,211,255,.35);stroke-width:1;stroke-dasharray:1 5}
.lh-gl{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.lh-gl span{font-size:11px;color:var(--ts);letter-spacing:.08em}
.lh-gl b{font-family:var(--fh);font-size:15px;font-weight:600;color:#eafcff}

.lh-mem{display:flex;gap:10px;flex:1;min-height:0}
.lh-mem canvas{flex:1.2;min-width:0;height:100%;display:block}
.lh-mem-stats{flex:1;display:flex;flex-direction:column;justify-content:center;gap:6px;min-width:0}
.lh-ms span{display:block;font-size:11px;color:var(--ts)}
.lh-ms b{font-family:var(--fh);font-size:16px;font-weight:600;color:#eafcff;text-shadow:0 0 8px rgba(34,211,255,.5)}
.lh-mem-foot{margin-top:4px}

.lh-llm-n{font-size:12px;color:var(--g);display:inline-flex;align-items:center;gap:6px}
.lh-llms{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);gap:6px;flex:1;min-height:0}
.lh-llm{display:flex;align-items:center;gap:9px;padding:0 9px;border-radius:6px;border:1px solid rgba(56,189,248,.16);background:rgba(8,32,58,.45);min-width:0;min-height:0}
.lh-llm .lh-ibox{width:24px;height:24px;border-radius:5px}
.lh-llm .lh-ibox .lh-ic{width:13px;height:13px}
.lh-llm-n2{font-size:12.5px;color:#eaf8ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.1}
.lh-llm-s{font-size:10.5px;color:var(--td);line-height:1.1}
.lh-llm.lh-on .lh-llm-s{color:var(--g)}
.lh-llm-foot{text-align:center;margin-top:6px}

/* ---- Fußleiste ---- */
.lh-bot{grid-area:bot;display:flex;align-items:center;gap:10px;min-width:0;position:relative}
.lh-wid{display:flex;align-items:center;gap:9px;height:46px;padding:0 12px;border-radius:7px;border:1px solid var(--bd);background:var(--pb);flex:none;min-width:0}
.lh-wid .lh-ic{color:var(--c);width:18px;height:18px}
.lh-wid-l{font-size:10.5px;color:var(--ts);line-height:1.1}
.lh-wid-v{font-size:13px;color:#eaf8ff;line-height:1.15;white-space:nowrap}
.lh-wave-wrap{flex:1;position:relative;height:100%;min-width:0;display:flex;align-items:center;justify-content:center}
.lh-wave-wrap canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.lh-talk{position:relative;z-index:1;height:48px;padding:0 44px;border-radius:24px;text-align:center;
  border:1.5px solid rgba(127,233,255,.85);background:linear-gradient(180deg,rgba(14,116,178,.55),rgba(5,40,72,.85));
  box-shadow:0 0 22px rgba(34,211,255,.55),inset 0 0 18px rgba(34,211,255,.25);transition:box-shadow .2s}
.lh-talk:hover{box-shadow:0 0 34px rgba(34,211,255,.85),inset 0 0 20px rgba(34,211,255,.35)}
.lh-talk-t{font-family:var(--fh);font-weight:700;font-size:15px;letter-spacing:.18em;color:#f0fdff;text-shadow:0 0 10px rgba(34,211,255,.9)}
.lh-talk-s{font-size:11px;color:#a9e6ff;letter-spacing:.06em}
.lh-cmd{display:flex;align-items:center;gap:8px;height:46px;padding:0 14px;border-radius:7px;border:1px solid var(--bd);background:var(--pb);color:#cfeeff;font-size:13px;flex:none}
.lh-cmd:hover{border-color:var(--bd2);color:#fff}
.lh-cmd .lh-ic{color:var(--c)}
.lh-kbd{font-size:10px;color:var(--ts);border:1px solid var(--bd);border-radius:3px;padding:0 4px}

.lh-toast{position:absolute;left:50%;bottom:78px;transform:translateX(-50%) translateY(10px);opacity:0;z-index:5;pointer-events:none;
  padding:8px 16px;border-radius:7px;border:1px solid var(--bd2);background:rgba(4,20,38,.95);color:#dff7ff;font-size:13px;letter-spacing:.04em;
  box-shadow:0 0 18px rgba(34,211,255,.3);transition:all .25s}
.lh-toast.lh-show{opacity:1;transform:translateX(-50%)}

@keyframes lh-spin{to{transform:rotate(360deg)}}
@keyframes lh-pulse{0%{transform:scale(.9);opacity:.9}100%{transform:scale(1.35);opacity:0}}
@keyframes lh-blink{50%{opacity:.2}}

/* ---- 3D-Schicht ----
   Cockpit-Anmutung: Seitenleiste und äußere Panels sind zum Betrachter hin
   eingeklappt, Kopf- und Fußleiste nach hinten gekippt, die ganze Bühne
   folgt leicht der Maus (siehe applyTilt). Panels/Kacheln bekommen eine
   Glas-Fase (Lichtkante oben, Schatten unten) statt flacher Flächen. */
.lh-stage{perspective:1500px;perspective-origin:50% 45%}
.lh-row{perspective:1300px}
.lh-side{transform:rotateY(8deg) scale(.95);transform-origin:100% 50%}
.lh-top{transform:rotateX(-9deg);transform-origin:50% 0}
.lh-bot{transform:rotateX(11deg);transform-origin:50% 100%}
.lh-row1>.lh-panel:first-child{--lh-tf:rotateY(7deg) scale(.98);transform-origin:100% 50%}
.lh-row1>.lh-panel:last-child,.lh-row2>.lh-panel:last-child{--lh-tf:rotateY(-7deg) scale(.97);transform-origin:0 50%}
.lh-panel{--lh-tf:none;--lh-lift:0px;transform:var(--lh-tf) translateY(var(--lh-lift));
  transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease;
  background:
    linear-gradient(118deg,rgba(255,255,255,.055) 0%,rgba(255,255,255,0) 32%),
    linear-gradient(180deg,rgba(22,68,112,.58) 0%,rgba(7,26,48,.82) 38%,rgba(3,12,26,.92) 100%);
  box-shadow:
    inset 0 1px 0 rgba(170,235,255,.22),inset 0 -2px 0 rgba(0,0,0,.45),
    inset 0 0 26px rgba(14,165,233,.08),
    0 2px 0 rgba(0,0,0,.45),0 14px 28px rgba(0,0,0,.55),0 30px 60px -20px rgba(0,0,0,.7),
    0 0 22px rgba(14,165,233,.07)}
.lh-panel:hover{--lh-lift:-3px;border-color:rgba(56,189,248,.42);
  box-shadow:
    inset 0 1px 0 rgba(170,235,255,.3),inset 0 -2px 0 rgba(0,0,0,.45),
    inset 0 0 30px rgba(14,165,233,.12),
    0 4px 0 rgba(0,0,0,.4),0 22px 40px rgba(0,0,0,.6),0 0 30px rgba(34,211,255,.16)}
.lh-core{background:radial-gradient(ellipse at 50% 45%,rgba(14,70,120,.35),rgba(3,12,26,.92) 70%)}
/* Kacheln innerhalb der Panels: leicht erhaben */
.lh-ov,.lh-fi,.lh-ag,.lh-llm,.lh-qb{
  background:linear-gradient(180deg,rgba(26,74,118,.5),rgba(8,30,54,.55) 55%,rgba(4,18,36,.6));
  box-shadow:inset 0 1px 0 rgba(170,235,255,.13),inset 0 -1px 0 rgba(0,0,0,.4),0 3px 6px rgba(0,0,0,.35);
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s}
.lh-ag:hover,.lh-llm:hover,.lh-ov:hover,.lh-fi:hover,.lh-qb:hover{transform:translateY(-1px);
  box-shadow:inset 0 1px 0 rgba(170,235,255,.2),inset 0 -1px 0 rgba(0,0,0,.4),0 6px 12px rgba(0,0,0,.45),0 0 12px rgba(34,211,255,.12)}
.lh-fi.lh-alert{background:linear-gradient(180deg,rgba(120,30,45,.45),rgba(60,12,24,.5))}
/* Icon-Kästchen als kleine Glas-Knöpfe */
.lh-ibox{background:radial-gradient(circle at 35% 25%,rgba(120,220,255,.28),rgba(14,116,178,.14) 55%,rgba(2,20,40,.4));
  box-shadow:inset 0 1px 0 rgba(200,245,255,.3),inset 0 -2px 3px rgba(0,0,0,.45),0 2px 4px rgba(0,0,0,.45),0 0 8px rgba(34,211,255,.12)}
.lh-ibox.lh-t-green{background:radial-gradient(circle at 35% 25%,rgba(120,255,200,.25),rgba(59,232,160,.08) 55%,rgba(2,30,24,.4))}
.lh-ibox.lh-t-orange{background:radial-gradient(circle at 35% 25%,rgba(255,210,140,.28),rgba(255,171,61,.08) 55%,rgba(40,20,2,.4))}
.lh-ibox.lh-t-red{background:radial-gradient(circle at 35% 25%,rgba(255,150,160,.3),rgba(255,77,97,.1) 55%,rgba(40,4,10,.4))}
.lh-ibox.lh-t-purple{background:radial-gradient(circle at 35% 25%,rgba(210,190,255,.3),rgba(169,139,255,.1) 55%,rgba(20,10,40,.4))}
/* Kopf-/Fußleisten-Elemente erhaben */
.lh-status,.lh-tbtn,.lh-op,.lh-wid,.lh-cmd,.lh-focus,.lh-search,.lh-close{
  box-shadow:inset 0 1px 0 rgba(170,235,255,.16),inset 0 -1px 0 rgba(0,0,0,.45),0 6px 14px rgba(0,0,0,.5)}
.lh-status,.lh-tbtn,.lh-op,.lh-wid,.lh-cmd,.lh-focus{background:linear-gradient(180deg,rgba(22,68,112,.55),rgba(5,20,40,.85))}
.lh-nav-item.lh-on{box-shadow:inset 3px 0 0 var(--c),inset 0 1px 0 rgba(170,235,255,.2),0 6px 14px rgba(0,0,0,.45),0 0 16px rgba(34,211,255,.18)}
/* Schriftzüge mit Extrusion */
.lh-core-name{text-shadow:
  0 1px 0 #9fe6f7,0 2px 0 #6ccbe6,0 3px 0 #3fa9cc,0 4px 0 #2387ad,0 5px 0 #146a8e,0 6px 0 #0b4f6d,
  0 10px 14px rgba(0,0,0,.7),0 0 24px rgba(34,211,255,.85),0 0 60px rgba(34,211,255,.45)}
.lh-brand-name{text-shadow:0 1px 0 #6ccbe6,0 2px 0 #2387ad,0 3px 0 #0b4f6d,0 5px 8px rgba(0,0,0,.6),0 0 12px rgba(34,211,255,.55)}
.lh-time{text-shadow:0 1px 0 #6ccbe6,0 2px 0 #2387ad,0 3px 0 #0b4f6d,0 6px 10px rgba(0,0,0,.6),0 0 16px rgba(34,211,255,.6)}
.lh-ms b,.lh-gl b{text-shadow:0 1px 0 #3fa9cc,0 2px 0 #0b4f6d,0 4px 6px rgba(0,0,0,.6),0 0 8px rgba(34,211,255,.5)}
/* Ringanzeigen: Tiefe durch Schattenkranz und Innenschein */
.lh-gauge{filter:drop-shadow(0 6px 8px rgba(0,0,0,.6))}
.lh-gauge::before{content:"";position:absolute;inset:16%;border-radius:50%;
  background:radial-gradient(circle at 40% 30%,rgba(60,160,220,.28),rgba(4,18,36,.85) 70%);
  box-shadow:inset 0 2px 4px rgba(170,235,255,.18),inset 0 -6px 10px rgba(0,0,0,.6)}
.lh-gauge .lh-gt{stroke:rgba(4,20,40,.9);stroke-width:9}
.lh-gauge svg{position:relative;z-index:1}.lh-gl{z-index:2}
/* Mikrofon und "Talk to Jarvis": gewölbt */
.lh-micbtn{background:radial-gradient(circle at 40% 28%,#8ff0ff 0%,#1fb8e6 28%,#0b5f91 68%,#063a5c 100%);
  box-shadow:0 0 18px rgba(34,211,255,.75),0 0 40px rgba(34,211,255,.35),0 8px 16px rgba(0,0,0,.6),inset 0 -6px 10px rgba(0,30,60,.6),inset 0 3px 6px rgba(255,255,255,.35)}
.lh-talk{background:linear-gradient(180deg,rgba(120,220,255,.45) 0%,rgba(14,116,178,.6) 35%,rgba(5,40,72,.92) 100%);
  box-shadow:0 0 22px rgba(34,211,255,.55),0 10px 20px rgba(0,0,0,.6),inset 0 2px 0 rgba(220,250,255,.45),inset 0 -6px 12px rgba(0,20,40,.6)}
/* Perspektivischer Gitterboden + Horizontlicht hinter der Bühne */
.lh-floor{position:absolute;left:-40%;right:-40%;bottom:-6%;height:62%;z-index:0;pointer-events:none;
  background-image:linear-gradient(rgba(56,189,248,.28) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,.28) 1px,transparent 1px);
  background-size:64px 64px;transform:perspective(420px) rotateX(64deg);transform-origin:50% 100%;
  mask-image:linear-gradient(0deg,#000 0%,rgba(0,0,0,.6) 45%,transparent 92%);-webkit-mask-image:linear-gradient(0deg,#000 0%,rgba(0,0,0,.6) 45%,transparent 92%);
  animation:lh-floor 6s linear infinite;opacity:.55}
.lh-horizon{position:absolute;left:0;right:0;top:48%;height:180px;transform:translateY(-50%);z-index:0;pointer-events:none;
  background:radial-gradient(ellipse 60% 50% at 50% 50%,rgba(34,180,255,.16),transparent 70%)}
@keyframes lh-floor{to{background-position:0 64px}}
html.jarvis-reduce-motion .lh-floor{animation:none}

/* Niedrige Fenster: Zeitleisten-Uhrzeit einzeilig, damit vier Termine passen. */
@media (max-height:800px){.lh-tl-time br{display:none}.lh-tl-time{white-space:nowrap}.lh-tli{grid-template-columns:52px 14px 1fr auto}.lh-tl::before{left:64px}.lh-tl-foot{margin-top:3px}}
`;

  // ------------------------------------------------------------ Markup
  function navHtml() {
    return NAV.map((n) => `<button type="button" class="lh-nav-item${n.active ? ' lh-on' : ''}" data-nav="${n.id}">${ic(n.icon)}<span class="lh-lbl">${n.label}</span>${n.badge ? `<span class="lh-badge" data-badge="${n.id}">${n.badge}</span>` : ''}</button>`).join('');
  }

  function gauge(id, label) {
    const r = 40, c = 2 * Math.PI * r;
    return `<div class="lh-gauge" data-gauge="${id}">
      <svg viewBox="0 0 100 100"><circle class="lh-gk" cx="50" cy="50" r="48"/><circle class="lh-gt" cx="50" cy="50" r="${r}"/>
      <circle class="lh-gv" cx="50" cy="50" r="${r}" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${c.toFixed(2)}"/></svg>
      <div class="lh-gl"><span>${label}</span><b>0%</b></div></div>`;
  }

  function fmtClock(d) {
    let h = d.getHours();
    const ap = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    const p2 = (n) => String(n).padStart(2, '0');
    return `${p2(h)}:${p2(d.getMinutes())}:${p2(d.getSeconds())}<small>${ap}</small>`;
  }
  function fmtDate(d) {
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    return `${days[d.getDay()]}, ${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
  }
  function fmtHm(d) {
    let h = d.getHours();
    const ap = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    return `${String(h).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')} <br>${ap}`;
  }
  function fmtIn(min) {
    if (min <= 0) return 'Done';
    const h = Math.floor(min / 60), m = min % 60;
    return h ? `in ${h}h ${m}m` : `in ${m}m`;
  }

  function timelineHtml() {
    const now = Date.now();
    return TIMELINE.map((e) => {
      // Startzeit auf volle 5 Minuten runden, Restzeit davon ableiten, damit
      // Uhrzeit und "in …" zusammenpassen.
      const at = new Date(Math.round((now + e.offset * 60000) / 300000) * 300000);
      const mins = Math.round((at.getTime() - now) / 60000);
      const cls = e.done ? ' lh-done' : e.warn ? ' lh-warn' : '';
      return `<div class="lh-tli${cls}"><div class="lh-tl-time">${fmtHm(at)}</div><span class="lh-tl-dot"></span>
        <div style="min-width:0"><div class="lh-tl-title">${e.title}</div>${e.progress ? '<div class="lh-tl-bar"><i></i></div>' : ''}</div>
        <span class="lh-tl-st">${e.done ? 'Done' : fmtIn(mins)}</span></div>`;
    }).join('');
  }

  function buildHtml() {
    const now = new Date();
    return `<div class="lh-horizon"></div><div class="lh-floor"></div><div class="lh-stage">
<aside class="lh-side">
  <div class="lh-brand">${LOGO}<div><div class="lh-brand-name">JARVIS</div><div class="lh-brand-sub">COMMAND CENTER</div></div></div>
  <nav class="lh-nav">${navHtml()}</nav>
  <section class="lh-panel lh-voice">
    <div class="lh-ph"><span class="lh-pt">Voice Status</span></div>
    <canvas data-wave="voice"></canvas>
    <div class="lh-listen">Listening...</div>
    <button type="button" class="lh-micbtn" data-act="voice" aria-label="Tap to Speak">${ic('mic')}</button>
    <div class="lh-tap">Tap to Speak</div>
  </section>
  <button type="button" class="lh-focus" data-act="focus">${ic('moon')}<span>Focus Mode</span></button>
</aside>

<header class="lh-top">
  <div class="lh-status"><span>SYSTEM STATUS</span><span class="lh-dot"></span><b>OPTIMAL</b></div>
  <div class="lh-clock"><div class="lh-date" data-date>${fmtDate(now)}</div><div class="lh-time" data-time>${fmtClock(now)}</div></div>
  <label class="lh-search">${ic('search')}<input type="text" placeholder="Search..." spellcheck="false"></label>
  <button type="button" class="lh-tbtn" aria-label="Apps">${ic('apps')}</button>
  <button type="button" class="lh-tbtn" aria-label="Notifications">${ic('bell')}<span class="lh-ping"></span></button>
  <button type="button" class="lh-tbtn" aria-label="Settings">${ic('gear')}</button>
  <div class="lh-op"><div><div class="lh-op-n">Operator</div><div class="lh-op-r">Commander</div></div><span class="lh-av">${ic('user')}</span></div>
  <button type="button" class="lh-close" data-act="close" aria-label="LARP-Modus schließen" title="LARP-Modus schließen (Esc)">${ic('x')}</button>
</header>

<main class="lh-main">
  <div class="lh-row lh-row1">
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">AI Core Overview</span></div>
      <div class="lh-ov-list">${OVERVIEW.map((o) => `<div class="lh-ov"><span class="lh-ibox">${ic(o.icon)}</span><div><div class="lh-ov-l">${o.label}</div><div class="lh-ov-s lh-t-${o.tone}"${o.key ? ` data-ov="${o.key}"` : ''}>${o.tone === 'green' || o.tone === 'orange' ? '<span class="lh-dot" style="width:5px;height:5px;margin-right:4px;vertical-align:1px"></span>' : ''}${o.status}</div></div></div>`).join('')}</div>
    </section>
    <section class="lh-panel lh-core">
      <canvas data-core></canvas>
      <div class="lh-core-txt"><div class="lh-core-name">JARVIS</div><div class="lh-core-sub">AI CORE</div><div class="lh-core-ver">v3.0.0</div></div>
    </section>
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">Live Intelligence Feed</span><span class="lh-sp"></span><span class="lh-live"><span class="lh-dot"></span>LIVE</span></div>
      <div class="lh-feed">${FEED.map((f) => `<div class="lh-fi${f.action ? ' lh-alert' : ''}"><span class="lh-ibox lh-t-${f.tone}">${ic(f.icon)}</span>
        <div class="lh-fi-b"><div class="lh-fi-t"${f.key ? ` data-feed="${f.key}"` : ''}>${f.title}</div><div class="lh-fi-s lh-t-${f.tone}">${f.sub}</div></div>
        ${f.action ? `<button type="button" class="lh-vt" data-act="tasks">${f.action}</button>` : `<span class="lh-tag lh-t-${f.tone}">${f.tag}</span>`}</div>`).join('')}</div>
      <div class="lh-feed-foot"><button type="button" class="lh-link">View All Intelligence ${ic('chevr')}</button></div>
    </section>
  </div>

  <div class="lh-row lh-row2">
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">Active Agents</span><span class="lh-sp"></span><button type="button" class="lh-link">View All ${ic('chevr')}</button></div>
      <div class="lh-agents">${AGENTS.map((a, i) => `<div class="lh-ag${a.active ? ' lh-act' : ''}"><span class="lh-ibox lh-t-${a.tone}">${ic(a.icon)}</span>
        <div class="lh-ag-b"><div class="lh-ag-n">${a.name}</div><div class="lh-ag-s ${a.active ? 'lh-t-green' : 'lh-t-dim'}"><span class="lh-dot"></span>${a.active ? 'Active' : 'Standby'}</div></div>
        ${a.check ? `<span class="lh-ag-chk">${ic('check')}</span>` : `<canvas data-wave="agent" data-i="${i}" data-tone="${a.tone}" data-active="${a.active ? 1 : 0}"></canvas>`}</div>`).join('')}</div>
    </section>
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">Mission Timeline</span><span class="lh-sp"></span><span class="lh-sel">Today ${ic('chevd')}</span></div>
      <div class="lh-tl" data-timeline>${timelineHtml()}</div>
      <div class="lh-tl-foot"><button type="button" class="lh-link">View Full Schedule ${ic('chevr')}</button></div>
    </section>
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">Quick Commands</span></div>
      <div class="lh-qc">${QUICK.map((q) => `<button type="button" class="lh-qb" data-act="${q.action || 'quick'}" data-label="${q.label}"><span class="lh-ibox">${ic(q.icon)}</span>${q.label}</button>`).join('')}</div>
    </section>
  </div>

  <div class="lh-row lh-row3">
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">System Monitor</span></div>
      <div class="lh-gauges">${gauge('cpu', 'CPU')}${gauge('ram', 'RAM')}${gauge('disk', 'Disk')}</div>
    </section>
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">Memory Insights</span></div>
      <div class="lh-mem"><canvas data-mem></canvas>
        <div class="lh-mem-stats">
          <div class="lh-ms"><span>Memories</span><b data-stat="memories">3,380</b></div>
          <div class="lh-ms"><span>Session Turns</span><b data-stat="turns">22</b></div>
          <div class="lh-ms"><span>Tool Calls</span><b data-stat="tools">14</b></div>
        </div></div>
      <div class="lh-mem-foot"><button type="button" class="lh-link">View Memory Map ${ic('chevr')}</button></div>
    </section>
    <section class="lh-panel">
      <div class="lh-ph"><span class="lh-pt">LLM Status</span><span class="lh-sp"></span><span class="lh-llm-n"><span class="lh-dot"></span>${LLMS.filter((l) => l.on).length} Connected</span></div>
      <div class="lh-llms">${LLMS.map((l) => `<div class="lh-llm${l.on ? ' lh-on' : ''}"><span class="lh-ibox${l.on ? '' : ' lh-t-dim'}">${ic(l.icon)}</span><div style="min-width:0"><div class="lh-llm-n2">${l.name}</div><div class="lh-llm-s">${l.on ? 'Connected' : 'Not Linked'}</div></div></div>`).join('')}</div>
      <div class="lh-llm-foot"><button type="button" class="lh-link">Manage Providers ${ic('chevr')}</button></div>
    </section>
  </div>
</main>

<footer class="lh-bot">
  <div class="lh-wid">${ic('music')}<div><div class="lh-wid-l">Now Playing</div><div class="lh-wid-v">Ambient Pads</div></div></div>
  <div class="lh-wid">${ic('cloud')}<div><div class="lh-wid-l">Weather</div><div class="lh-wid-v">28°C Overcast</div></div></div>
  <div class="lh-wid lh-opt">${ic('wifi')}<div><div class="lh-wid-l">Network</div><div class="lh-wid-v lh-t-green" data-net>Excellent</div></div></div>
  <div class="lh-wave-wrap"><canvas data-wave="bottom"></canvas>
    <button type="button" class="lh-talk" data-act="voice"><div class="lh-talk-t">TALK TO JARVIS</div><div class="lh-talk-s">I am listening...</div></button>
  </div>
  <button type="button" class="lh-cmd" data-act="close">${ic('command')}<span>Command Palette</span><span class="lh-kbd">Esc</span></button>
</footer>
<div class="lh-toast" data-toast></div>
</div>`;
  }

  // ------------------------------------------------------------ Zeichnen
  // Ein einziger requestAnimationFrame-Loop für Globus, Wellen und
  // Gedächtnis-Konstellation; läuft nur, solange das HUD offen ist.
  let root = null, styleEl = null, raf = 0, clockTimer = 0, statsTimer = 0, toastTimer = 0;
  let hooks = {};
  let canvases = [];
  const SPHERE = (() => {
    const pts = [], n = 720, ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
      pts.push([Math.cos(th) * r, y, Math.sin(th) * r]);
    }
    return pts;
  })();
  const SPARKS = Array.from({ length: 70 }, () => ({ a: Math.random() * Math.PI * 2, r: 1.05 + Math.random() * 0.9, s: (Math.random() - 0.5) * 0.004, z: Math.random() }));
  const MEM_NODES = Array.from({ length: 26 }, (_, i) => ({ x: Math.random(), y: Math.random(), p: Math.random() * 6.28, big: i % 7 === 0 }));

  function fitCanvas(cv) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return null;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  function drawCore(cv, t) {
    const f = fitCanvas(cv); if (!f) return;
    const { ctx, w, h } = f;
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2, R = Math.min(w * 0.3, h * 0.39);

    // Hintergrundschein
    let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 2.1);
    g.addColorStop(0, 'rgba(34,180,255,.32)'); g.addColorStop(.45, 'rgba(14,110,190,.14)'); g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

    // Lichtstrahlen
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < 2; i++) {
      const lg = ctx.createLinearGradient(0, cy, w, cy);
      lg.addColorStop(0, 'rgba(34,211,255,0)'); lg.addColorStop(.5, `rgba(120,230,255,${0.18 - i * 0.08})`); lg.addColorStop(1, 'rgba(34,211,255,0)');
      ctx.fillStyle = lg; ctx.fillRect(0, cy - (i ? 18 : 1), w, i ? 36 : 2);
    }
    ctx.restore();

    // Holo-Projektor: Sockel unter der Kugel und Lichtkegel nach oben
    const baseY = cy + R + Math.max(14, (h / 2 - R) * 0.62), baseRx = R * 0.95, baseRy = R * 0.13;
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    let cone = ctx.createLinearGradient(0, baseY, 0, cy);
    cone.addColorStop(0, 'rgba(34,211,255,.30)'); cone.addColorStop(1, 'rgba(34,211,255,0)');
    ctx.fillStyle = cone;
    ctx.beginPath(); ctx.moveTo(cx - baseRx, baseY); ctx.lineTo(cx - R * 0.98, cy + R * 0.2); ctx.lineTo(cx + R * 0.98, cy + R * 0.2); ctx.lineTo(cx + baseRx, baseY); ctx.closePath(); ctx.fill();
    for (let i = 0; i < 3; i++) {
      ctx.strokeStyle = `rgba(127,233,255,${0.55 - i * 0.15})`; ctx.lineWidth = 1.4 - i * 0.3;
      ctx.shadowColor = '#22d3ff'; ctx.shadowBlur = 12;
      ctx.beginPath(); ctx.ellipse(cx, baseY + i * 5, baseRx * (1 + i * 0.12), baseRy * (1 + i * 0.12), 0, 0, Math.PI * 2); ctx.stroke();
    }
    const pg = ctx.createRadialGradient(cx, baseY, 0, cx, baseY, baseRx);
    pg.addColorStop(0, 'rgba(160,240,255,.45)'); pg.addColorStop(1, 'rgba(34,211,255,0)');
    ctx.fillStyle = pg; ctx.beginPath(); ctx.ellipse(cx, baseY, baseRx, baseRy, 0, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    // Orbit-Ellipsen mit wandernden Lichtpunkten — die obere Hälfte liegt
    // "hinter" der Kugel und wird vor ihr gezeichnet, die untere danach
    // (siehe drawOrbits(true) weiter unten), damit die Ringe sie umschließen.
    const ORBITS = [[1.75, 0.3, -0.12, 1], [1.55, 0.22, 0.18, -1.4], [2.05, 0.38, 0.04, 0.7]];
    const drawOrbits = (front) => {
      ctx.save(); ctx.translate(cx, cy);
      ORBITS.forEach(([rx, ry, rot, sp], k) => {
        ctx.save(); ctx.rotate(rot);
        ctx.strokeStyle = `rgba(56,200,255,${(front ? 0.5 : 0.22) - k * 0.07})`; ctx.lineWidth = front ? 1.3 : 1;
        ctx.beginPath(); ctx.ellipse(0, 0, R * rx, R * ry, 0, front ? 0 : Math.PI, front ? Math.PI : Math.PI * 2); ctx.stroke();
        const a = t * 0.0004 * sp + k * 2;
        if ((Math.sin(a) >= 0) === front) {
          const px = Math.cos(a) * R * rx, py = Math.sin(a) * R * ry;
          ctx.fillStyle = front ? '#e4fbff' : 'rgba(150,220,255,.5)'; ctx.shadowColor = '#22d3ff'; ctx.shadowBlur = front ? 14 : 6;
          ctx.beginPath(); ctx.arc(px, py, front ? 2.6 : 1.6, 0, Math.PI * 2); ctx.fill();
        }
        ctx.restore();
      });
      ctx.restore();
    };
    drawOrbits(false);

    // Äußerer Skalenring (dreht langsam)
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * 0.00006);
    const Rt = R * 1.3;
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2, long = i % 10 === 0;
      ctx.strokeStyle = long ? 'rgba(127,233,255,.7)' : 'rgba(56,189,248,.3)'; ctx.lineWidth = long ? 1.4 : 1;
      ctx.beginPath(); ctx.moveTo(Math.cos(a) * Rt, Math.sin(a) * Rt); ctx.lineTo(Math.cos(a) * (Rt + (long ? 9 : 4)), Math.sin(a) * (Rt + (long ? 9 : 4))); ctx.stroke();
    }
    ctx.restore();
    // Bogensegmente (gegenläufig)
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(-t * 0.00015);
    ctx.lineWidth = 2.5; ctx.shadowColor = '#22d3ff'; ctx.shadowBlur = 10;
    [[0, .7], [1.2, 1.55], [2.3, 3.3], [3.9, 4.25], [4.9, 5.8]].forEach(([a0, a1], i) => {
      ctx.strokeStyle = i % 2 ? 'rgba(34,211,255,.75)' : 'rgba(127,233,255,.45)';
      ctx.beginPath(); ctx.arc(0, 0, R * 1.17, a0, a1); ctx.stroke();
    });
    ctx.shadowBlur = 0; ctx.lineWidth = 1; ctx.setLineDash([2, 6]); ctx.strokeStyle = 'rgba(56,189,248,.4)';
    ctx.beginPath(); ctx.arc(0, 0, R * 1.08, 0, Math.PI * 2); ctx.stroke();
    ctx.restore();

    // Kugel: dunkler Kern + Randschein
    g = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.3, R * 0.1, cx, cy, R);
    g.addColorStop(0, 'rgba(30,120,190,.55)'); g.addColorStop(.7, 'rgba(6,40,80,.75)'); g.addColorStop(1, 'rgba(4,24,50,.9)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();

    const rotY = t * 0.00018, tilt = 0.38;
    const cosY = Math.cos(rotY), sinY = Math.sin(rotY), cosX = Math.cos(tilt), sinX = Math.sin(tilt);
    const proj = (x, y, z) => {
      const x1 = x * cosY + z * sinY, z1 = -x * sinY + z * cosY;
      const y2 = y * cosX - z1 * sinX, z2 = y * sinX + z1 * cosX;
      return [cx + x1 * R, cy + y2 * R, z2];
    };
    // Längen- und Breitengrade
    ctx.lineWidth = 0.8;
    for (let m = 0; m < 12; m++) {
      const lon = (m / 12) * Math.PI;
      ctx.beginPath();
      let started = false;
      for (let s = 0; s <= 48; s++) {
        const la = (s / 48) * Math.PI * 2;
        const [px, py, pz] = proj(Math.cos(la) * Math.cos(lon), Math.sin(la), Math.cos(la) * Math.sin(lon));
        if (pz > -0.05) { started ? ctx.lineTo(px, py) : ctx.moveTo(px, py); started = true; } else started = false;
      }
      ctx.strokeStyle = 'rgba(56,200,255,.22)'; ctx.stroke();
    }
    for (let l = 1; l < 8; l++) {
      const lat = -Math.PI / 2 + (l / 8) * Math.PI, y = Math.sin(lat), rr = Math.cos(lat);
      ctx.beginPath(); let started = false;
      for (let s = 0; s <= 64; s++) {
        const a = (s / 64) * Math.PI * 2;
        const [px, py, pz] = proj(Math.cos(a) * rr, y, Math.sin(a) * rr);
        if (pz > -0.05) { started ? ctx.lineTo(px, py) : ctx.moveTo(px, py); started = true; } else started = false;
      }
      ctx.strokeStyle = 'rgba(56,200,255,.18)'; ctx.stroke();
    }
    // Punktwolke
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    for (const [x, y, z] of SPHERE) {
      const [px, py, pz] = proj(x, y, z);
      const a = pz > 0 ? 0.25 + pz * 0.6 : 0.06 + (1 + pz) * 0.08;
      ctx.fillStyle = `rgba(120,225,255,${a.toFixed(3)})`;
      const s = pz > 0 ? 1 + pz * 0.9 : 0.8;
      ctx.fillRect(px - s / 2, py - s / 2, s, s);
    }
    ctx.restore();
    // Randschein
    ctx.save(); ctx.shadowColor = '#22d3ff'; ctx.shadowBlur = 24; ctx.strokeStyle = 'rgba(127,233,255,.85)'; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    // Abdunklung hinter dem Schriftzug
    g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.75);
    g.addColorStop(0, 'rgba(2,14,30,.55)'); g.addColorStop(1, 'rgba(2,14,30,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();

    // Volumen: Glanzlicht oben links, Eigenschatten unten rechts
    g = ctx.createRadialGradient(cx + R * 0.35, cy + R * 0.4, R * 0.2, cx + R * 0.1, cy + R * 0.1, R * 1.05);
    g.addColorStop(0, 'rgba(0,6,16,0)'); g.addColorStop(.75, 'rgba(0,6,16,.28)'); g.addColorStop(1, 'rgba(0,6,16,.5)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    g = ctx.createRadialGradient(cx - R * 0.42, cy - R * 0.48, 0, cx - R * 0.42, cy - R * 0.48, R * 0.6);
    g.addColorStop(0, 'rgba(190,245,255,.22)'); g.addColorStop(1, 'rgba(190,245,255,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    drawOrbits(true);

    // Funken
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    for (const sp of SPARKS) {
      sp.a += sp.s;
      const px = cx + Math.cos(sp.a) * R * sp.r * 1.25, py = cy + Math.sin(sp.a) * R * sp.r * 0.55;
      const tw = 0.35 + 0.65 * Math.abs(Math.sin(t * 0.002 + sp.z * 9));
      ctx.fillStyle = `rgba(160,235,255,${(0.5 * tw).toFixed(3)})`;
      ctx.fillRect(px, py, 1.6, 1.6);
    }
    ctx.restore();

    // HUD-Ecken im Panel
    ctx.strokeStyle = 'rgba(56,189,248,.45)'; ctx.lineWidth = 1;
    const m = 14, L = 26;
    [[m, m, 1, 1], [w - m, m, -1, 1], [m, h - m, 1, -1], [w - m, h - m, -1, -1]].forEach(([x, y, dx, dy]) => {
      ctx.beginPath(); ctx.moveTo(x, y + dy * L); ctx.lineTo(x, y); ctx.lineTo(x + dx * L, y); ctx.stroke();
    });
  }

  const TONE = { cyan: [34, 211, 255], green: [59, 232, 160], orange: [255, 171, 61], purple: [169, 139, 255] };

  function drawWave(cv, t) {
    const f = fitCanvas(cv); if (!f) return;
    const { ctx, w, h } = f;
    ctx.clearRect(0, 0, w, h);
    const kind = cv.dataset.wave;
    const mid = h / 2;
    if (kind === 'agent') {
      const [r, g, b] = TONE[cv.dataset.tone] || TONE.cyan;
      const act = cv.dataset.active === '1', i = Number(cv.dataset.i) || 0;
      const amp = (act ? 0.42 : 0.16) * h;
      ctx.lineWidth = 1.3; ctx.strokeStyle = `rgba(${r},${g},${b},.95)`; ctx.shadowColor = `rgb(${r},${g},${b})`; ctx.shadowBlur = 6;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 1.5) {
        const k = x / w, env = Math.sin(k * Math.PI);
        const y = mid + env * amp * (Math.sin(k * 26 + t * 0.006 + i) * 0.6 + Math.sin(k * 61 - t * 0.009 + i * 2) * 0.4);
        x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
      return;
    }
    // Sprach-Wellen: mehrere überlagerte Sinuslinien
    const lines = kind === 'bottom' ? 5 : 4;
    for (let l = 0; l < lines; l++) {
      const alpha = l === 0 ? 0.95 : 0.45 - l * 0.07;
      ctx.lineWidth = l === 0 ? 1.6 : 1;
      ctx.strokeStyle = `rgba(${l % 2 ? '127,233,255' : '34,211,255'},${alpha})`;
      ctx.shadowColor = '#22d3ff'; ctx.shadowBlur = l === 0 ? 8 : 0;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 2) {
        const k = x / w;
        let env;
        if (kind === 'bottom') {
          // Mitte (hinter dem Knopf) flach, nach außen ausklingend
          const d = Math.abs(k - 0.5) * 2;
          env = d < 0.18 ? 0 : Math.sin(Math.min(1, (d - 0.18) / 0.82) * Math.PI) * 0.9;
        } else env = Math.pow(Math.sin(k * Math.PI), 1.4);
        const y = mid + env * h * 0.38 * (
          Math.sin(k * (18 + l * 5) + t * (0.004 + l * 0.001) + l) * 0.55 +
          Math.sin(k * (47 - l * 3) - t * 0.007 + l * 1.7) * 0.3 +
          Math.sin(t * 0.003 + l) * 0.15);
        x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
    }
  }

  function drawMem(cv, t) {
    const f = fitCanvas(cv); if (!f) return;
    const { ctx, w, h } = f;
    ctx.clearRect(0, 0, w, h);
    const pts = MEM_NODES.map((n) => [
      8 + (n.x * (w - 16)) + Math.sin(t * 0.0006 + n.p) * 4,
      8 + (n.y * (h - 16)) + Math.cos(t * 0.0005 + n.p) * 4,
      n,
    ]);
    ctx.lineWidth = 0.8;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i][0] - pts[j][0], dy = pts[i][1] - pts[j][1], d = Math.hypot(dx, dy);
        const lim = Math.min(w, h) * 0.42;
        if (d < lim) {
          ctx.strokeStyle = `rgba(56,200,255,${(0.42 * (1 - d / lim)).toFixed(3)})`;
          ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke();
        }
      }
    }
    for (const [x, y, n] of pts) {
      const pulse = 0.6 + 0.4 * Math.sin(t * 0.003 + n.p);
      ctx.fillStyle = n.big ? `rgba(200,245,255,${pulse})` : `rgba(90,215,255,${0.5 + pulse * 0.4})`;
      ctx.shadowColor = '#22d3ff'; ctx.shadowBlur = n.big ? 10 : 4;
      ctx.beginPath(); ctx.arc(x, y, n.big ? 2.6 : 1.5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  function frame(t) {
    if (!root) return;
    for (const cv of canvases) {
      if (cv.hasAttribute('data-core')) drawCore(cv, t);
      else if (cv.hasAttribute('data-mem')) drawMem(cv, t);
      else drawWave(cv, t);
    }
    applyTilt(false);
    raf = requestAnimationFrame(frame);
  }

  // ------------------------------------------------------- Live-Werte
  function setGauge(id, pct) {
    if (!root || pct == null || isNaN(pct)) return;
    const el = root.querySelector(`[data-gauge="${id}"]`); if (!el) return;
    const v = Math.max(0, Math.min(100, Math.round(pct)));
    const c = el.querySelector('.lh-gv');
    const len = parseFloat(c.getAttribute('stroke-dasharray'));
    c.setAttribute('stroke-dashoffset', (len * (1 - v / 100)).toFixed(2));
    el.querySelector('b').textContent = v + '%';
  }

  // Startwerte wie im Vorbild; echte Werte von /system/stats überschreiben
  // sie, sobald sie da sind. Ohne Backend-Werte (z.B. psutil fehlt) bleibt
  // CPU/RAM sanft um die Vorbildwerte schwankend.
  const demo = { cpu: 15, ram: 54, disk: 40 };
  async function pollStats() {
    let s = null;
    try {
      const r = await fetch('/system/stats', { cache: 'no-store' });
      if (r.ok) s = await r.json();
    } catch (e) {}
    const jitter = (base) => Math.max(1, Math.min(99, base + Math.round((Math.random() - 0.5) * 6)));
    const cpu = s && s.cpu != null ? s.cpu : jitter(demo.cpu);
    const ram = s && s.ram != null ? s.ram : jitter(demo.ram);
    const disk = s && s.disk != null ? s.disk : demo.disk;
    setGauge('cpu', cpu); setGauge('ram', ram); setGauge('disk', disk);
    const feed = root && root.querySelector('[data-feed="cpu"]');
    if (feed) feed.textContent = `CPU usage at ${Math.round(cpu)}%`;
    const sub = feed && feed.nextElementSibling;
    if (sub) sub.textContent = cpu > 85 ? 'System load high' : 'System load nominal';
  }

  async function loadCounts() {
    try {
      const r = await fetch('/conversations', { cache: 'no-store' });
      if (!r.ok) return;
      const j = await r.json();
      const n = Array.isArray(j.conversations) ? j.conversations.length : null;
      const b = root && root.querySelector('[data-badge="conversations"]');
      if (b && n != null) b.textContent = String(n);
    } catch (e) {}
    try {
      const st = hooks.getState ? hooks.getState() : null;
      if (st && st.turns != null && root) {
        const el = root.querySelector('[data-stat="turns"]');
        if (el && st.turns > 0) el.textContent = String(st.turns);
      }
    } catch (e) {}
  }

  function tickClock() {
    if (!root) return;
    const d = new Date();
    root.querySelector('[data-time]').innerHTML = fmtClock(d);
    root.querySelector('[data-date]').textContent = fmtDate(d);
  }

  function toast(text) {
    const el = root && root.querySelector('[data-toast]'); if (!el) return;
    el.textContent = text;
    el.classList.add('lh-show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('lh-show'), 1800);
  }

  // Kleine Fenster: statt das Raster umzubrechen, wird die ganze Bühne mit
  // fester Designgröße proportional verkleinert — das Layout bleibt so exakt
  // wie im Vorbild, nur kleiner.
  const DESIGN_W = 1280, DESIGN_H = 720;
  // stageBase/-W/-H merken die Skalierung, applyTilt() setzt die Maus-
  // Neigung um die Bühnenmitte darauf.
  let stageBase = '', stageW = 0, stageH = 0;
  function fitStage() {
    const stage = root && root.querySelector('.lh-stage');
    if (!stage) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    if (vw >= 1180 && vh >= 640) {
      stage.classList.remove('lh-scaled');
      stage.style.width = stage.style.height = '';
      stageBase = ''; stageW = vw; stageH = vh;
    } else {
      const k = Math.min(vw / DESIGN_W, vh / DESIGN_H);
      stage.classList.add('lh-scaled');
      stage.style.width = DESIGN_W + 'px';
      stage.style.height = DESIGN_H + 'px';
      stageBase = `translate(${((vw - DESIGN_W * k) / 2).toFixed(1)}px,${((vh - DESIGN_H * k) / 2).toFixed(1)}px) scale(${k.toFixed(4)})`;
      stageW = DESIGN_W; stageH = DESIGN_H;
    }
    applyTilt(true);
  }

  // Maus-Parallax: die Bühne neigt sich höchstens ~2,5° zur Maus hin,
  // geglättet pro Frame; bei "Bewegung reduzieren" bleibt sie gerade.
  const TILT_MAX = 2.4;
  let tiltX = 0, tiltY = 0, tiltTX = 0, tiltTY = 0;
  function onPointerMove(e) {
    if (document.documentElement.classList.contains('jarvis-reduce-motion')) { tiltTX = tiltTY = 0; return; }
    tiltTY = ((e.clientX / window.innerWidth) - 0.5) * 2 * TILT_MAX;
    tiltTX = -((e.clientY / window.innerHeight) - 0.5) * 2 * TILT_MAX;
  }
  function applyTilt(force) {
    const stage = root && root.querySelector('.lh-stage');
    if (!stage) return;
    const dx = tiltTX - tiltX, dy = tiltTY - tiltY;
    if (!force && Math.abs(dx) < 0.003 && Math.abs(dy) < 0.003) return;
    tiltX += dx * 0.08; tiltY += dy * 0.08;
    const hw = (stageW / 2).toFixed(1), hh = (stageH / 2).toFixed(1);
    stage.style.transform = `${stageBase} translate(${hw}px,${hh}px) perspective(2200px) rotateX(${tiltX.toFixed(3)}deg) rotateY(${tiltY.toFixed(3)}deg) translate(-${hw}px,-${hh}px)`;
  }

  // ------------------------------------------------------------ Aktionen
  function onClick(e) {
    const nav = e.target.closest('[data-nav]');
    if (nav) {
      root.querySelectorAll('.lh-nav-item').forEach((n) => n.classList.toggle('lh-on', n === nav));
      return;
    }
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'close') { close(); return; }
    if (act === 'focus') { btn.classList.toggle('lh-on'); toast(btn.classList.contains('lh-on') ? 'Focus Mode engaged' : 'Focus Mode disengaged'); return; }
    if (act === 'voice') {
      if (hooks.voice) { close(); hooks.voice(); } else toast('Voice channel standing by');
      return;
    }
    if (act === 'newChat') {
      if (hooks.newChat) { close(); hooks.newChat(); } else toast('New task initialised');
      return;
    }
    if (act === 'tasks') { toast('Opening task board…'); return; }
    toast(`${btn.dataset.label || 'Command'} — acknowledged`);
  }

  // Escape schließt das HUD — in der Capture-Phase, damit es nicht noch
  // zusätzlich ein Menü der darunterliegenden Oberfläche schließt.
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  }

  function open(h) {
    hooks = h || {};
    if (root) return;
    if (!styleEl) {
      styleEl = document.createElement('style');
      styleEl.id = 'jarvis-larp-style';
      styleEl.textContent = CSS;
      document.head.appendChild(styleEl);
    }
    root = document.createElement('div');
    root.className = 'lh-root';
    // Feste id: claude-app.js blendet alle unbekannten <body>-Kinder aus und
    // nimmt nur bekannte Overlays (darunter #jarvisLarp) davon aus.
    root.id = 'jarvisLarp';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-label', 'JARVIS Command Center');
    root.innerHTML = buildHtml();
    document.body.appendChild(root);
    canvases = Array.from(root.querySelectorAll('canvas'));
    root.addEventListener('click', onClick);
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', fitStage);
    window.addEventListener('pointermove', onPointerMove);
    tiltX = tiltY = tiltTX = tiltTY = 0;
    fitStage();
    requestAnimationFrame(() => root && root.classList.add('lh-in'));
    raf = requestAnimationFrame(frame);
    clockTimer = setInterval(tickClock, 1000);
    setGauge('cpu', demo.cpu); setGauge('ram', demo.ram); setGauge('disk', demo.disk);
    pollStats();
    statsTimer = setInterval(pollStats, 3000);
    loadCounts();
    const closeBtn = root.querySelector('.lh-close');
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function close() {
    if (!root) return;
    const el = root;
    root = null;
    cancelAnimationFrame(raf); raf = 0;
    clearInterval(clockTimer); clearInterval(statsTimer); clearTimeout(toastTimer);
    window.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', fitStage);
    window.removeEventListener('pointermove', onPointerMove);
    canvases = [];
    el.classList.remove('lh-in');
    setTimeout(() => el.remove(), 320);
    if (hooks.onClose) { try { hooks.onClose(); } catch (e) {} }
  }

  window.JarvisLarp = { open, close, isOpen: () => !!root };
})();
