// JARVIS — "/larp"-Modus: ein holografisches Werkstatt-Cockpit im Stil des
// Iron-Man-JARVIS, das sich im Querformat (feste 1920×1080-Bühne, auf jedes
// Fenster skaliert) über die normale Oberfläche legt. Eigenständiges Modul:
// es bringt sein eigenes CSS und lokal abgelegte Schriften (Michroma, Chakra
// Petch, Share Tech Mono, siehe assets/fonts/larp/) mit und wird über
// window.JarvisLarp.open(hooks) / .close() gesteuert.
//
// Echte Daten: /system/stats (CPU pro Kern, RAM, Swap, Festplatte, Netz,
// Akku, Uptime, NVIDIA-GPU), /hud/weather (Open-Meteo), /models (aktives
// Modell), dazu FPS/Frame-Zeit und der WebGL-Grafikchip aus dem Browser.
// Die Konsole beantwortet Hardware-Fragen direkt aus diesen Werten und
// schickt alles andere über POST /chat an das echte Modell. Rüstung, Radar,
// Tracking und Reaktor sind Kulisse und als SIM markiert.
// hooks (aus claude-app.js): voice() = Sprachmodus, speak(text) = Jarvis-
// Stimme, onClose(). Geschlossen wird über das Kreuz oben rechts oder Esc.
(() => {
  'use strict';

  const SCRIPT_SRC = (document.currentScript && document.currentScript.src) || '/static/larp-hud.js';
  const FONT_BASE = SCRIPT_SRC.replace(/\/[^/]*$/, '') + '/assets/fonts/larp';
  const W = 1920, H = 1080;
  const C = { holo: '104,220,255', hi: '223,248,255', amber: '255,178,74', alert: '255,91,79', ok: '125,255,196', dim: '74,139,166' };
  const MONO = '"LH Mono", "Share Tech Mono", Consolas, monospace';
  const RAD = Math.PI / 180;
  const rgba = (c, a) => `rgba(${c},${a})`;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, k) => a + (b - a) * k;
  const fmtBytes = (b, digits) => {
    if (b == null) return 'n/a';
    const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return (digits != null ? b.toFixed(digits) : b < 10 ? b.toFixed(1) : Math.round(b)) + ' ' + u[i];
  };
  const fmtRate = (bps) => bps == null ? 'n/a' : (bps * 8 >= 1e6 ? (bps * 8 / 1e6).toFixed(1) + ' Mb/s' : (bps * 8 / 1e3).toFixed(0) + ' kb/s');
  const fmtDur = (s) => { s = Math.floor(s); const d = Math.floor(s / 86400), h = Math.floor(s / 3600) % 24, m = Math.floor(s / 60) % 60; return (d ? d + 'd ' : '') + String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };

  // ================================================================ CSS
  const CSS = `
@font-face{font-family:'LH Display';src:url('${FONT_BASE}/michroma-latin-400-normal.woff2') format('woff2');font-display:swap}
@font-face{font-family:'LH Mono';src:url('${FONT_BASE}/share-tech-mono-latin-400-normal.woff2') format('woff2');font-display:swap}
@font-face{font-family:'LH UI';src:url('${FONT_BASE}/chakra-petch-latin-400-normal.woff2') format('woff2');font-weight:400;font-display:swap}
@font-face{font-family:'LH UI';src:url('${FONT_BASE}/chakra-petch-latin-500-normal.woff2') format('woff2');font-weight:500;font-display:swap}
@font-face{font-family:'LH UI';src:url('${FONT_BASE}/chakra-petch-latin-600-normal.woff2') format('woff2');font-weight:600;font-display:swap}
#jarvisLarp{
  --void:#02060c;--glass:rgba(8,28,44,.46);--holo:#68dcff;--holo-hi:#dff8ff;--holo-dim:#4a8ba6;
  --line:rgba(104,220,255,.26);--amber:#ffb24a;--alert:#ff5b4f;--ok:#7dffc4;
  --f-display:'LH Display','Michroma','Eurostile','Segoe UI',sans-serif;
  --f-ui:'LH UI','Chakra Petch','Segoe UI',system-ui,sans-serif;
  --f-data:'LH Mono','Share Tech Mono',Consolas,monospace;
  position:fixed;inset:0;z-index:2147483000;overflow:hidden;background:var(--void);color:var(--holo);
  font-family:var(--f-ui);-webkit-font-smoothing:antialiased;opacity:0;transition:opacity .35s ease;user-select:none}
#jarvisLarp.lh-in{opacity:1}
#jarvisLarp *,#jarvisLarp *::before,#jarvisLarp *::after{box-sizing:border-box}
#jarvisLarp::before{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(ellipse 60% 50% at 50% 42%,rgba(40,140,200,.2),transparent 70%),
             radial-gradient(ellipse 120% 60% at 50% 110%,rgba(20,90,140,.22),transparent 60%)}
#jarvisLarp button,#jarvisLarp input{font:inherit;color:inherit;margin:0}
#jarvisLarp h2,#jarvisLarp ul,#jarvisLarp dl,#jarvisLarp dd,#jarvisLarp p{margin:0;padding:0}
#jarvisLarp ul{list-style:none}
#jarvisLarp canvas{display:block}
#jarvisLarp :focus-visible{outline:1px solid var(--holo-hi);outline-offset:3px}
.lh-stage{position:absolute;left:0;top:0;width:${W}px;height:${H}px;transform-origin:0 0;
  display:grid;gap:14px;padding:14px 18px 22px;grid-template-columns:450px minmax(0,1fr) 450px;grid-template-rows:62px minmax(0,1fr) 250px;
  grid-template-areas:"top top top" "left core right" "deck deck deck";font-size:15px;line-height:1.3;perspective:2000px}
.lh-stage::after{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(180deg,rgba(150,230,255,.03) 0 1px,transparent 1px 3px)}
.lh-hint{position:absolute;left:16px;right:16px;bottom:16px;text-align:center;font-family:var(--f-data);font-size:12px;letter-spacing:.18em;color:var(--holo-dim)}

.lh-top{grid-area:top;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:20px;border-bottom:1px solid var(--line)}
.lh-brand{display:flex;align-items:baseline;gap:14px;min-width:0}
.lh-brand b{font-family:var(--f-display);font-weight:400;font-size:24px;letter-spacing:.32em;color:var(--holo-hi);text-shadow:0 0 14px rgba(104,220,255,.8)}
.lh-brand span{font-family:var(--f-data);font-size:13px;letter-spacing:.2em;color:var(--holo-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lh-clock{text-align:center;font-variant-numeric:tabular-nums}
.lh-clock .lh-t{font-family:var(--f-display);font-size:30px;letter-spacing:.12em;color:var(--holo-hi);text-shadow:0 0 16px rgba(104,220,255,.7)}
.lh-clock .lh-d{font-family:var(--f-data);font-size:12px;letter-spacing:.2em;color:var(--holo-dim)}
.lh-chips{display:flex;gap:8px;justify-content:flex-end;align-items:center;min-width:0}
.lh-chip{font-family:var(--f-data);font-size:12px;letter-spacing:.1em;padding:6px 10px;border:1px solid var(--line);white-space:nowrap;
  clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px);background:rgba(104,220,255,.06);flex:none}
.lh-chip[data-chip="llm"]{max-width:260px;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto}
.lh-chip i{font-style:normal;color:var(--ok)}
.lh-chip.lh-warn i{color:var(--amber)} .lh-chip.lh-bad i{color:var(--alert)}
.lh-voice{cursor:pointer}
.lh-voice[aria-pressed="true"]{background:rgba(104,220,255,.22);color:var(--holo-hi)}
.lh-close{width:40px;height:40px;flex:none;display:grid;place-items:center;cursor:pointer;border:1px solid var(--holo);background:rgba(104,220,255,.1);
  color:var(--holo-hi);clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px);transition:background .15s,color .15s,border-color .15s}
.lh-close svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round}
.lh-close:hover{background:rgba(255,91,79,.28);border-color:var(--alert);color:#fff}

.lh-wing{display:flex;flex-direction:column;gap:14px;min-height:0}
.lh-left{grid-area:left;transform:rotateY(9deg) scale(.95);transform-origin:100% 50%}
.lh-right{grid-area:right;transform:rotateY(-9deg) scale(.95);transform-origin:0 50%}
.lh-panel{position:relative;flex:1;min-height:0;min-width:0;display:flex;flex-direction:column;gap:8px;padding:12px 15px;background:var(--glass);
  border:1px solid var(--line);clip-path:polygon(14px 0,100% 0,100% calc(100% - 14px),calc(100% - 14px) 100%,0 100%,0 14px);
  box-shadow:inset 0 0 40px rgba(104,220,255,.06);transition:background .3s,border-color .3s}
.lh-panel::before{content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(135deg,rgba(104,220,255,.55) 0 1px,transparent 1px) top left/20px 20px no-repeat,
             linear-gradient(315deg,rgba(104,220,255,.55) 0 1px,transparent 1px) bottom right/20px 20px no-repeat}
.lh-panel.lh-flash{background:rgba(104,220,255,.17);border-color:var(--holo)}
.lh-ph{display:flex;align-items:center;gap:10px;min-width:0}
.lh-ph h2{font-family:var(--f-display);font-weight:400;font-size:12px;letter-spacing:.2em;color:var(--holo-hi);white-space:nowrap}
.lh-sub{font-family:var(--f-data);font-size:12px;letter-spacing:.1em;color:var(--holo-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.lh-src{margin-left:auto;font-family:var(--f-data);font-size:10.5px;letter-spacing:.16em;padding:1px 6px;border:1px solid currentColor;flex:none;cursor:help;white-space:nowrap}
.lh-src.lh-live{color:var(--ok)} .lh-src.lh-sim{color:var(--amber)} .lh-src.lh-mix{color:var(--holo)} .lh-src.lh-off{color:var(--alert)}
.lh-row{display:flex;gap:14px;align-items:center;min-height:0}
.lh-ring{width:96px;height:96px;flex:none}
.lh-kv{flex:1;min-width:0;display:grid;grid-template-columns:auto 1fr;gap:1px 12px;font-family:var(--f-data);font-size:13px;align-content:center}
.lh-kv dt{color:var(--holo-dim);letter-spacing:.08em;white-space:nowrap}
.lh-kv dd{text-align:right;color:var(--holo-hi);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lh-kv dd.lh-w{color:var(--amber)} .lh-kv dd.lh-g{color:var(--ok)} .lh-kv dd.lh-b{color:var(--alert)}
.lh-fill{flex:1 1 0;min-height:40px;width:100%}
.lh-row .lh-fill{width:auto;min-width:0;height:100%}

.lh-wx-now{display:flex;gap:14px;align-items:center}
.lh-wx-icon{width:96px;height:72px;flex:none}
.lh-wx-temp{font-family:var(--f-data);font-size:46px;color:var(--holo-hi);text-shadow:0 0 16px rgba(104,220,255,.6);line-height:1}
.lh-wx-cond{font-family:var(--f-data);font-size:14px;letter-spacing:.08em;margin-top:6px}
.lh-wx-feel{font-family:var(--f-data);font-size:12px;color:var(--holo-dim);letter-spacing:.08em}
.lh-wx-compass{width:72px;height:72px;margin-left:auto;flex:none}
.lh-wx-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;font-family:var(--f-data)}
.lh-wx-grid div{border:1px solid rgba(104,220,255,.16);padding:3px 7px;background:rgba(104,220,255,.04);min-width:0}
.lh-wx-grid span{display:block;font-size:10.5px;letter-spacing:.14em;color:var(--holo-dim)}
.lh-wx-grid b{font-weight:400;font-size:15px;color:var(--holo-hi);font-variant-numeric:tabular-nums;white-space:nowrap}
.lh-sunline{display:flex;justify-content:space-between;font-family:var(--f-data);font-size:12.5px;color:var(--holo-dim);letter-spacing:.06em}
.lh-sunline b{font-weight:400;color:var(--holo-hi)}
.lh-city{cursor:pointer;border:0;background:none;padding:0;font-family:var(--f-data);font-size:12px;letter-spacing:.1em;color:var(--holo-dim);text-decoration:underline dotted;text-underline-offset:3px}
.lh-city:hover{color:var(--holo-hi)}
.lh-city-input{width:180px;background:rgba(104,220,255,.08);border:1px solid var(--holo);color:var(--holo-hi);font-family:var(--f-data);font-size:12px;padding:2px 6px}

.lh-wc{display:grid;grid-template-columns:1fr 1fr;gap:3px 18px;font-family:var(--f-data);font-size:14px}
.lh-wc li{display:grid;grid-template-columns:10px 1fr auto;gap:8px;align-items:center}
.lh-wc i{width:8px;height:8px;border-radius:50%;background:var(--amber);box-shadow:0 0 6px var(--amber)}
.lh-wc i.lh-night{background:var(--holo-dim);box-shadow:none}
.lh-wc b{font-weight:400;color:var(--holo-hi);font-variant-numeric:tabular-nums}

.lh-core{grid-area:core;position:relative;min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
.lh-core-wrap{position:relative;height:calc(100% - 44px);aspect-ratio:1;max-width:100%}
.lh-core-wrap canvas{position:absolute;inset:0;width:100%;height:100%;cursor:pointer}
.lh-core-cap{text-align:center}
.lh-core-cap b{display:block;font-family:var(--f-display);font-weight:400;font-size:22px;letter-spacing:.5em;margin-right:-.5em;color:var(--holo-hi);text-shadow:0 0 14px rgba(104,220,255,.9)}
.lh-core-cap span{font-family:var(--f-data);font-size:11.5px;letter-spacing:.26em;color:var(--holo-dim)}
.lh-node{position:absolute;width:92px;height:92px;margin:-46px 0 0 -46px;border-radius:50%;border:1px solid var(--line);padding:0;cursor:pointer;
  background:radial-gradient(circle,rgba(104,220,255,.14),rgba(2,6,12,.65) 70%);display:grid;place-items:center;align-content:center;gap:3px;
  transition:background .2s,border-color .2s,box-shadow .2s;color:var(--holo)}
.lh-node svg{width:24px;height:24px;stroke:currentColor;fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.lh-node span{font-family:var(--f-data);font-size:11px;letter-spacing:.2em}
.lh-node:hover,.lh-node.lh-on{background:radial-gradient(circle,rgba(104,220,255,.36),rgba(2,6,12,.6) 72%);border-color:var(--holo);box-shadow:0 0 18px rgba(104,220,255,.45);color:var(--holo-hi)}

.lh-deck{grid-area:deck;display:grid;grid-template-columns:330px 300px minmax(0,1fr) 330px 300px;gap:14px;min-height:0;transform:rotateX(7deg);transform-origin:50% 100%}
.lh-list{display:grid;gap:3px;font-family:var(--f-data);font-size:12.5px}
.lh-contacts li{display:grid;grid-template-columns:12px 1fr auto;gap:8px;align-items:center}
.lh-contacts li::before{content:"";width:6px;height:6px;border:1px solid currentColor;transform:rotate(45deg)}
.lh-contacts .lh-r{color:var(--holo-dim)} .lh-contacts .lh-unk{color:var(--amber)}
.lh-con-body{display:grid;grid-template-columns:140px minmax(0,1fr);gap:14px;flex:1;min-height:0}
.lh-wave{display:flex;flex-direction:column;gap:6px;min-height:0}
.lh-wave canvas{width:100%;flex:1;min-height:0}
.lh-wave small{font-family:var(--f-data);font-size:11px;letter-spacing:.18em;color:var(--holo-dim)}
.lh-talk{display:flex;flex-direction:column;gap:8px;min-width:0;min-height:0}
.lh-log{flex:1;min-height:0;overflow-y:auto;font-family:var(--f-data);font-size:14px;display:flex;flex-direction:column;gap:3px;
  scrollbar-width:thin;scrollbar-color:var(--line) transparent;padding-right:6px;user-select:text}
.lh-log p{overflow-wrap:anywhere;white-space:pre-wrap}
.lh-log .lh-who{color:var(--holo-dim);letter-spacing:.14em;margin-right:8px}
.lh-log .lh-me{color:var(--holo-hi)} .lh-log .lh-j{color:var(--holo)} .lh-log .lh-sys{color:var(--holo-dim)}
.lh-ask{display:flex;gap:8px}
.lh-ask input{flex:1;min-width:0;background:rgba(104,220,255,.05);border:1px solid var(--line);padding:9px 12px;color:var(--holo-hi);font-family:var(--f-data);font-size:14px;outline:none;user-select:text}
.lh-ask input:focus{border-color:var(--holo)}
.lh-ask input::placeholder{color:var(--holo-dim)}
.lh-ask button{cursor:pointer;border:1px solid var(--holo);background:rgba(104,220,255,.14);padding:0 18px;font-family:var(--f-display);font-size:12px;letter-spacing:.24em;color:var(--holo-hi)}
.lh-ask button:hover{background:rgba(104,220,255,.3)}
.lh-ask .lh-mic{padding:0 12px;display:grid;place-items:center}
.lh-ask .lh-mic svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round}
.lh-bar{height:4px;background:rgba(104,220,255,.14);overflow:hidden}
.lh-bar b{display:block;height:100%;background:var(--holo);box-shadow:0 0 6px var(--holo);transition:width .6s}
.lh-bar.lh-warnbar b{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.lh-pw{display:flex;justify-content:space-between;font-family:var(--f-data);font-size:12.5px;color:var(--holo-dim);letter-spacing:.06em;gap:10px}
.lh-pw b{font-weight:400;color:var(--holo-hi);white-space:nowrap}
.lh-ticker{position:absolute;left:18px;right:18px;bottom:3px;overflow:hidden;white-space:nowrap;font-family:var(--f-data);font-size:10.5px;letter-spacing:.2em;color:var(--holo-dim);
  mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent);-webkit-mask-image:linear-gradient(90deg,transparent,#000 6%,#000 94%,transparent)}
.lh-ticker div{display:inline-block;padding-left:100%;animation:lh-tick 70s linear infinite}
@keyframes lh-tick{to{transform:translateX(-100%)}}
html.jarvis-reduce-motion #jarvisLarp .lh-ticker div{animation:none;padding-left:0}
@media (prefers-reduced-motion:reduce){#jarvisLarp .lh-ticker div{animation:none;padding-left:0}}
`;

  // ================================================================ Markup
  const ICON = {
    cpu: '<rect x="6" y="6" width="12" height="12" rx="1.5"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    gpu: '<rect x="3" y="7" width="18" height="10" rx="1.5"/><circle cx="9" cy="12" r="2.5"/><circle cx="16" cy="12" r="2.5"/><path d="M6 17v3"/>',
    weather: '<circle cx="9" cy="9" r="3.5"/><path d="M9 2.5v1.5M2.5 9H4M4.4 4.4l1 1M13.6 4.4l-1 1"/><path d="M8 19h10a3.5 3.5 0 0 0 0-7 5 5 0 0 0-9.6 1.5A2.8 2.8 0 0 0 8 19z"/>',
    net: '<path d="M2 9a15 15 0 0 1 20 0M5 13a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0"/><circle cx="12" cy="20" r="1"/>',
    suit: '<path d="M12 3l5 2v5c0 4-2.5 7-5 9-2.5-2-5-5-5-9V5z"/><path d="M9.5 11h5"/>',
    comms: '<path d="M4 6h16v10H9l-5 4z"/>',
  };
  const NODES = [['cpu', 'CPU'], ['gpu', 'GPU'], ['weather', 'WETTER'], ['net', 'NETZ'], ['suit', 'SUIT'], ['comms', 'COMMS']];
  const kv = (rows) => `<dl class="lh-kv">${rows.map(([k, id]) => `<dt>${k}</dt><dd data-k="${id}">—</dd>`).join('')}</dl>`;
  const src = (id, cls, txt, title) => `<span class="lh-src lh-${cls}" data-src="${id}" title="${title}">${txt}</span>`;

  function buildHtml() {
    return `
<div class="lh-stage">
  <header class="lh-top">
    <div class="lh-brand"><b>J.A.R.V.I.S.</b><span data-k="host">WORKSHOP · MK-OS</span></div>
    <div class="lh-clock"><div class="lh-t" data-k="clock">--:--:--</div><div class="lh-d" data-k="date">—</div></div>
    <div class="lh-chips">
      <span class="lh-chip" data-chip="llm">LLM <i data-k="llm">—</i></span>
      <span class="lh-chip" data-chip="sys">SYSTEM <i data-k="sys">NOMINAL</i></span>
      <span class="lh-chip" data-chip="net">UPLINK <i data-k="uplink">—</i></span>
      <span class="lh-chip">UPTIME <i data-k="uptime">—</i></span>
      <button type="button" class="lh-chip lh-voice" data-act="voiceToggle" aria-pressed="false" title="Antworten in der Konsole mit Jarvis' Stimme vorlesen">VOICE OFF</button>
      <button type="button" class="lh-close" data-act="close" aria-label="LARP-Modus schließen" title="LARP-Modus schließen (Esc)"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
  </header>

  <section class="lh-wing lh-left">
    <article class="lh-panel" data-panel="cpu">
      <div class="lh-ph"><h2>CPU</h2><span class="lh-sub" data-k="cpuSub">—</span>${src('cpu', 'live', 'LIVE', 'Gesamtlast und Last pro Kern vom Backend (psutil)')}</div>
      <div class="lh-row"><canvas class="lh-ring" data-c="cpuRing"></canvas>${kv([['LOAD', 'cpuLoad'], ['CORES', 'cpuCores'], ['CLOCK', 'cpuClock'], ['TEMP', 'cpuTemp'], ['PROCESSES', 'procs']])}</div>
      <canvas class="lh-fill" data-c="cpuBars" aria-label="Last pro Kern und Verlauf"></canvas>
    </article>
    <article class="lh-panel" data-panel="mem">
      <div class="lh-ph"><h2>MEMORY</h2><span class="lh-sub" data-k="memSub">—</span>${src('mem', 'live', 'LIVE', 'Arbeitsspeicher und Swap vom Backend (psutil)')}</div>
      <div class="lh-row"><canvas class="lh-ring" data-c="memRing"></canvas>${kv([['IN USE', 'memUse'], ['TOTAL', 'memTotal'], ['FREE', 'memFree'], ['SWAP', 'memSwap'], ['HUD HEAP', 'memHeap']])}</div>
      <canvas class="lh-fill" data-c="memSpark" aria-label="Speicherverlauf"></canvas>
    </article>
    <article class="lh-panel" data-panel="gpu">
      <div class="lh-ph"><h2>GPU</h2><span class="lh-sub" data-k="gpuName">—</span>${src('gpu', 'mix', 'LIVE', 'NVIDIA-Werte über nvidia-smi; ohne NVIDIA-Treiber Name aus WebGL und Last aus der Frame-Zeit geschätzt')}</div>
      <div class="lh-row"><canvas class="lh-ring" data-c="gpuRing"></canvas>${kv([['UTIL', 'gpuUtil'], ['VRAM', 'gpuVram'], ['TEMP', 'gpuTemp'], ['HUD FPS', 'gpuFps'], ['FRAME', 'gpuFrame']])}</div>
      <canvas class="lh-fill" data-c="gpuChart" aria-label="GPU-Verlauf"></canvas>
    </article>
  </section>

  <section class="lh-core">
    <div class="lh-core-wrap" data-k="coreWrap"><canvas data-c="core" aria-label="Arc-Reaktor-Kern. Klicken für einen Statusbericht"></canvas></div>
    <div class="lh-core-cap"><b>J.A.R.V.I.S.</b><span>JUST A RATHER VERY INTELLIGENT SYSTEM</span></div>
  </section>

  <section class="lh-wing lh-right">
    <article class="lh-panel" data-panel="weather" style="flex:1.55">
      <div class="lh-ph"><h2>WEATHER</h2><button type="button" class="lh-city" data-act="city" title="Stadt ändern">—</button>${src('wx', 'live', 'LIVE', 'Open-Meteo; Sonnenstand und Mondphase berechnet')}</div>
      <div class="lh-wx-now">
        <canvas class="lh-wx-icon" data-c="wxIcon"></canvas>
        <div style="min-width:0"><div class="lh-wx-temp" data-k="wxTemp">--°</div><div class="lh-wx-cond" data-k="wxCond">—</div><div class="lh-wx-feel" data-k="wxFeel">—</div></div>
        <canvas class="lh-wx-compass" data-c="wxCompass" aria-label="Windrichtung"></canvas>
      </div>
      <div class="lh-wx-grid">
        <div><span>WIND</span><b data-k="wxWind">—</b></div><div><span>HUMIDITY</span><b data-k="wxHum">—</b></div>
        <div><span>PRESSURE</span><b data-k="wxPres">—</b></div><div><span>UV INDEX</span><b data-k="wxUv">—</b></div>
        <div><span>VISIBILITY</span><b data-k="wxVis">—</b></div><div><span>CLOUDS</span><b data-k="wxCloud">—</b></div>
        <div><span>SUN ELEV.</span><b data-k="wxElev">—</b></div><div><span>MOON</span><b data-k="wxMoon">—</b></div>
      </div>
      <canvas class="lh-fill" style="min-height:64px" data-c="wxForecast" aria-label="Temperaturvorhersage nächste 12 Stunden"></canvas>
      <div class="lh-sunline"><span>SUNRISE <b data-k="sunRise">—</b></span><span>SUNSET <b data-k="sunSet">—</b></span><span>DAYLIGHT <b data-k="sunLen">—</b></span></div>
    </article>
    <article class="lh-panel" data-panel="net" style="flex:.72">
      <div class="lh-ph"><h2>NETWORK</h2><span class="lh-sub" data-k="netSub">—</span>${src('net', 'live', 'LIVE', 'Durchsatz aller Netzwerkkarten vom Backend (psutil)')}</div>
      <div class="lh-row" style="align-items:stretch;flex:1">
        <dl class="lh-kv" style="flex:none;width:190px"><dt>STATUS</dt><dd data-k="netStatus">—</dd><dt>DOWN</dt><dd data-k="netDown">—</dd><dt>UP</dt><dd data-k="netUp">—</dd><dt>PEAK</dt><dd data-k="netPeak">—</dd></dl>
        <canvas class="lh-fill" data-c="netChart" aria-label="Durchsatz up und down"></canvas>
      </div>
    </article>
    <article class="lh-panel" data-panel="wc" style="flex:.58">
      <div class="lh-ph"><h2>WORLD TIME</h2><span class="lh-sub" data-k="tzLocal">—</span>${src('wc', 'live', 'LIVE', 'Ortszeiten aus der Zeitzonen-Datenbank des Browsers')}</div>
      <ul class="lh-wc" data-k="wc"></ul>
    </article>
  </section>

  <section class="lh-deck">
    <article class="lh-panel" data-panel="suit">
      <div class="lh-ph"><h2>SUIT</h2><span class="lh-sub">MK · PROTOTYPE</span>${src('suit', 'sim', 'SIM', 'Kulisse')}</div>
      <div class="lh-row" style="flex:1;align-items:stretch"><canvas data-c="armor" style="width:120px" aria-label="Rüstung als Drahtgitter"></canvas><ul class="lh-list" data-k="suitList" style="flex:1;align-content:center"></ul></div>
    </article>
    <article class="lh-panel" data-panel="scan">
      <div class="lh-ph"><h2>THREAT SCAN</h2><span class="lh-sub">40 KM</span>${src('scan', 'sim', 'SIM', 'Kulisse')}</div>
      <canvas class="lh-fill" data-c="radar" aria-label="Radar"></canvas>
      <ul class="lh-list lh-contacts"><li><span>CIV-AIR · Cessna 172</span><span class="lh-r">12.4 km</span></li><li class="lh-unk"><span>UNIDENTIFIED · low alt.</span><span class="lh-r">27.9 km</span></li></ul>
    </article>
    <article class="lh-panel" data-panel="con">
      <div class="lh-ph"><h2>JARVIS CONSOLE</h2><span class="lh-sub">cpu · ram · gpu · netz · akku · wetter · sonne · zeit · status — alles andere geht ans Modell</span></div>
      <div class="lh-con-body">
        <div class="lh-wave"><canvas data-c="wave" aria-hidden="true"></canvas><small data-k="waveLbl">AUDIO · STANDBY</small></div>
        <div class="lh-talk">
          <div class="lh-log" data-k="log" aria-live="polite"></div>
          <form class="lh-ask" data-k="ask" autocomplete="off">
            <input data-k="askInput" type="text" placeholder="Sprich mit JARVIS … z. B. „Wie ist die CPU-Last?“" aria-label="Nachricht an JARVIS">
            <button type="submit">SEND</button>
            <button type="button" class="lh-mic" data-act="voice" title="HUD schließen und Sprachmodus starten" aria-label="Sprachmodus"><svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>
          </form>
        </div>
      </div>
    </article>
    <article class="lh-panel" data-panel="pow">
      <div class="lh-ph"><h2>POWER &amp; STORAGE</h2>${src('pow', 'mix', 'LIVE · SIM', 'Akku und Festplatte live vom Backend, Reaktor ist Kulisse')}</div>
      <div class="lh-row"><canvas class="lh-ring" data-c="batRing" style="width:90px;height:90px"></canvas>${kv([['BATTERY', 'batLvl'], ['STATE', 'batState'], ['REACTOR', 'reactor']])}</div>
      <div class="lh-pw"><span data-k="diskLbl">DISK</span><b data-k="diskTxt">—</b></div>
      <div class="lh-bar" data-k="diskBar"><b style="width:0%"></b></div>
      <canvas class="lh-fill" data-c="powSpark" aria-label="Reaktorleistung"></canvas>
    </article>
    <article class="lh-panel" data-panel="globe">
      <div class="lh-ph"><h2>TRACKING</h2><span class="lh-sub">SAT 14/14</span>${src('globe', 'sim', 'SIM', 'Kulisse; der weiße Punkt ist deine Wetter-Stadt')}</div>
      <canvas class="lh-fill" data-c="globe" aria-label="Globus mit verfolgten Orten"></canvas>
    </article>
  </section>
  <div class="lh-ticker" aria-hidden="true"><div data-k="ticker"></div></div>
</div>
<div class="lh-hint" data-k="hint" hidden>QUERFORMAT FÜR DIE VOLLE ANSICHT</div>`;
  }

  // ================================================================ state
  let root = null, stage = null, hooks = {}, raf = 0, timers = [], scaleK = 1;
  const $ = (sel) => root.querySelector(sel);
  const K = (k) => root.querySelector(`[data-k="${k}"]`);
  const CV = (c) => root.querySelector(`[data-c="${c}"]`);
  const reduce = () => document.documentElement.classList.contains('jarvis-reduce-motion') || matchMedia('(prefers-reduced-motion: reduce)').matches;
  let SPEED = 1;

  const T = {}; // live telemetry, filled by pollStats()/frame()
  const S = { reactor: 3.2 };
  const HIST = {};
  let WX = null, wxCity = 'Malibu', wxError = null;
  let voiceLevel = 0, typing = false, voiceOn = false, chatBusy = false;
  let chatHistory = [];
  const queue = [];

  function resetState() {
    Object.assign(T, {
      stats: null, cpu: 8, cores: [], fps: 60, frameMs: 16.7, lag: 0, gpuName: null, online: navigator.onLine,
      peakDown: 0, t0: performance.now(), model: null, modelOk: null,
    });
    Object.assign(HIST, { cpu: Array(120).fill(0), mem: Array(120).fill(0), gpu: Array(120).fill(0), down: Array(80).fill(0), up: Array(80).fill(0), pow: Array(80).fill(3.2) });
    chatHistory = []; queue.length = 0; typing = false; chatBusy = false; voiceLevel = 0;
  }
  const push = (a, v) => { a.push(v); a.shift(); };

  function every(ms, fn) { timers.push(setInterval(fn, ms)); }

  // ================================================================ scaling
  function fitStage() {
    if (!root) return;
    const vw = innerWidth, vh = innerHeight;
    scaleK = Math.min(vw / W, vh / H);
    stage.style.transform = `translate(${(vw - W * scaleK) / 2}px,${(vh - H * scaleK) / 2}px) scale(${scaleK})`;
    K('hint').hidden = !(vh > vw * 1.1);
    placeNodes(); drawForecast();
  }
  function fit(cv) {
    if (!cv) return null;
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return null;
    const dpr = clamp((window.devicePixelRatio || 1) * scaleK, 0.75, 2);
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    return { ctx, w, h };
  }

  // ================================================================ telemetry
  function detectGpuName() {
    try {
      const gl = document.createElement('canvas').getContext('webgl');
      if (!gl) return null;
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      let r = String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
      const m = /ANGLE \(([^,]+),\s*([^,]+?)(?:\s+(?:Direct3D|OpenGL|Metal|Vulkan)[^,]*)?(?:,|\))/.exec(r);
      if (m) r = m[2];
      return r.replace(/\(R\)|\(TM\)|, or similar/g, '').replace(/\s+/g, ' ').trim();
    } catch (e) { return null; }
  }
  async function pollStats() {
    try {
      const r = await fetch('/system/stats', { cache: 'no-store' });
      if (r.ok) T.stats = await r.json();
    } catch (e) { T.stats = null; }
    T.online = navigator.onLine;
  }
  async function pollModel() {
    try {
      const [m, h] = await Promise.all([fetch('/models').then((r) => r.json()), fetch('/model/health').then((r) => r.json())]);
      T.model = m.current || null; T.modelOk = !!h.healthy;
    } catch (e) { T.modelOk = false; }
  }

  // ================================================================ sun / moon (SunCalc formulas)
  const OBL = RAD * 23.4397;
  const toDays = (d) => d.valueOf() / 86400000 - 0.5 + 2440588 - 2451545;
  const meanAnom = (d) => RAD * (357.5291 + 0.98560028 * d);
  const eclLng = (M) => M + RAD * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M)) + RAD * 102.9372 + Math.PI;
  function sunElevation(date, lat, lng) {
    const d = toDays(date), L = eclLng(meanAnom(d));
    const dec = Math.asin(Math.sin(OBL) * Math.sin(L)), ra = Math.atan2(Math.sin(L) * Math.cos(OBL), Math.cos(L));
    const H = RAD * (280.16 + 360.9856235 * d) - RAD * -lng - ra, phi = RAD * lat;
    return Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H)) / RAD;
  }
  function moon(date) {
    const syn = 29.530588853, age = (((date - Date.UTC(2000, 0, 6, 18, 14)) / 86400000) % syn + syn) % syn;
    return { illum: (1 - Math.cos((age / syn) * 2 * Math.PI)) / 2, waxing: age < syn / 2 };
  }

  // ================================================================ weather (Open-Meteo via backend)
  const WMO = {
    0: 'Klar', 1: 'Überwiegend klar', 2: 'Teils bewölkt', 3: 'Bedeckt', 45: 'Nebel', 48: 'Reifnebel',
    51: 'Leichter Niesel', 53: 'Niesel', 55: 'Starker Niesel', 56: 'Gefrierender Niesel', 57: 'Gefrierender Niesel',
    61: 'Leichter Regen', 63: 'Regen', 65: 'Starker Regen', 66: 'Gefrierender Regen', 67: 'Gefrierender Regen',
    71: 'Leichter Schnee', 73: 'Schnee', 75: 'Starker Schnee', 77: 'Schneegriesel', 80: 'Regenschauer', 81: 'Regenschauer', 82: 'Heftige Schauer',
    85: 'Schneeschauer', 86: 'Schneeschauer', 95: 'Gewitter', 96: 'Gewitter mit Hagel', 99: 'Gewitter mit Hagel',
  };
  const wxKind = (code) => code <= 1 ? 'clear' : code <= 3 ? 'cloud' : code <= 48 ? 'fog' : code <= 67 || (code >= 80 && code <= 82) ? 'rain' : code <= 86 ? 'snow' : 'storm';
  const hhmm = (iso) => (iso || '').slice(11, 16) || '—';
  function cityLocalNow() { return WX ? new Date(Date.now() + (WX.utc_offset_seconds || 0) * 1000).toISOString().slice(11, 16) : '—'; }
  function loadCity() { try { return localStorage.getItem('jarvisLarpCity') || 'Malibu'; } catch (e) { return 'Malibu'; } }
  function saveCity(c) { try { localStorage.setItem('jarvisLarpCity', c); } catch (e) {} }
  async function loadWeather() {
    try {
      const r = await fetch('/hud/weather?city=' + encodeURIComponent(wxCity), { cache: 'no-store' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || 'Wetter nicht verfügbar');
      WX = j; wxError = null;
    } catch (e) { wxError = String(e.message || e); }
    renderWeather();
  }
  function renderWeather() {
    if (!root) return;
    const tag = root.querySelector('[data-src="wx"]');
    const cityBtn = $('.lh-city');
    if (cityBtn) cityBtn.textContent = WX ? `${WX.city.toUpperCase()}${WX.country ? ', ' + WX.country : ''} · ${WX.lat.toFixed(2)}° ${WX.lon.toFixed(2)}°` : wxCity.toUpperCase();
    if (!WX) {
      tag.textContent = 'OFFLINE'; tag.className = 'lh-src lh-off'; tag.title = wxError || '';
      K('wxCond').textContent = wxError ? 'KEINE WETTERDATEN' : 'LADE …';
      K('wxFeel').textContent = wxError || '';
      return;
    }
    tag.textContent = wxError ? 'CACHE' : 'LIVE'; tag.className = 'lh-src ' + (wxError ? 'lh-mix' : 'lh-live'); tag.title = wxError || 'Open-Meteo; Sonnenstand und Mondphase berechnet';
    const c = WX.current || {}, now = new Date();
    const elev = sunElevation(now, WX.lat, WX.lon), mo = moon(now);
    const set = (k, v) => { K(k).textContent = v; };
    set('wxTemp', c.temperature_2m != null ? c.temperature_2m.toFixed(1) + '°' : '--°');
    set('wxCond', (WMO[c.weather_code] || '—').toUpperCase());
    set('wxFeel', `GEFÜHLT ${c.apparent_temperature != null ? c.apparent_temperature.toFixed(1) + '°' : '—'} · ORTSZEIT ${cityLocalNow()}`);
    const dirs = ['N', 'NO', 'O', 'SO', 'S', 'SW', 'W', 'NW'];
    set('wxWind', c.wind_speed_10m != null ? `${Math.round(c.wind_speed_10m)} kn ${dirs[Math.round((c.wind_direction_10m || 0) / 45) % 8]}` : '—');
    set('wxHum', c.relative_humidity_2m != null ? c.relative_humidity_2m + ' %' : '—');
    set('wxPres', c.pressure_msl != null ? Math.round(c.pressure_msl) + ' hPa' : '—');
    set('wxUv', c.uv_index != null ? c.uv_index.toFixed(1) : '—');
    set('wxVis', c.visibility != null ? (c.visibility / 1000).toFixed(c.visibility < 10000 ? 1 : 0) + ' km' : '—');
    set('wxCloud', c.cloud_cover != null ? c.cloud_cover + ' %' : '—');
    set('wxElev', elev.toFixed(1) + '°');
    set('wxMoon', Math.round(mo.illum * 100) + '% ' + (mo.waxing ? '↑' : '↓'));
    const d = WX.daily || {}, rise = (d.sunrise || [])[0], sset = (d.sunset || [])[0];
    set('sunRise', hhmm(rise)); set('sunSet', hhmm(sset));
    if (rise && sset) { const len = (Date.parse(sset) - Date.parse(rise)) / 60000; set('sunLen', `${Math.floor(len / 60)}h ${String(Math.round(len % 60)).padStart(2, '0')}m`); }
    WX.elev = elev;
    drawForecast();
  }
  function editCity() {
    const btn = $('.lh-city');
    const inp = document.createElement('input');
    inp.className = 'lh-city-input'; inp.value = wxCity; inp.setAttribute('aria-label', 'Stadt für das Wetter');
    btn.replaceWith(inp); inp.focus(); inp.select();
    const done = (ok) => {
      if (!inp.isConnected) return;
      inp.replaceWith(btn);
      const v = inp.value.trim();
      if (ok && v && v.toLowerCase() !== wxCity.toLowerCase()) setCity(v);
      else renderWeather();
    };
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); done(true); } if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); } });
    inp.addEventListener('blur', () => done(true));
  }
  function setCity(c) { wxCity = c; saveCity(c); WX = null; wxError = null; renderWeather(); loadWeather(); }

  // ================================================================ drawing
  function ring(c, pct, label, col = C.holo) {
    const f = fit(CV(c)); if (!f) return;
    const { ctx, w, h } = f;
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 10, p = clamp(pct ?? 0, 0, 100) / 100;
    ctx.strokeStyle = rgba(C.holo, 0.3); ctx.lineWidth = 1;
    for (let i = 0; i < 60; i++) { const a = (i / 60) * Math.PI * 2, o = i % 5 ? 7 : 9; ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * (R + 4), cy + Math.sin(a) * (R + 4)); ctx.lineTo(cx + Math.cos(a) * (R + o), cy + Math.sin(a) * (R + o)); ctx.stroke(); }
    ctx.lineWidth = 8; ctx.strokeStyle = rgba(C.holo, 0.12); ctx.beginPath(); ctx.arc(cx, cy, R - 4, 0, Math.PI * 2); ctx.stroke();
    if (pct != null) {
      ctx.strokeStyle = rgba(col, 0.95); ctx.shadowColor = rgba(col, 1); ctx.shadowBlur = 10; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.arc(cx, cy, R - 4, -Math.PI / 2, -Math.PI / 2 + Math.max(0.001, p) * Math.PI * 2); ctx.stroke(); ctx.shadowBlur = 0; ctx.lineCap = 'butt';
    }
    ctx.fillStyle = rgba(C.hi, 1); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `${Math.round(R * 0.46)}px ${MONO}`; ctx.fillText(pct == null ? '--' : Math.round(pct) + '%', cx, cy + 3);
    ctx.font = `${Math.round(R * 0.22)}px ${MONO}`; ctx.fillStyle = rgba(C.dim, 1); ctx.fillText(label, cx, cy - R * 0.42);
  }
  function spark(c, arr, lo, hi, col, opts = {}) {
    const f = fit(CV(c)); if (!f) return;
    const { ctx, w, h } = f;
    const padL = opts.axis ? 38 : 2, padB = 2;
    const X = (i) => padL + (i / (arr.length - 1)) * (w - padL - 4), Y = (v) => 3 + (1 - (clamp(v, lo, hi) - lo) / (hi - lo)) * (h - padB - 6);
    if (opts.axis) {
      ctx.font = `10px ${MONO}`; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      opts.axis.forEach((v) => { ctx.strokeStyle = rgba(C.holo, 0.12); ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w, Y(v)); ctx.stroke(); ctx.fillStyle = rgba(C.dim, 1); ctx.fillText(opts.fmt(v), padL - 6, Y(v)); });
    }
    if (opts.line != null) { ctx.setLineDash([4, 4]); ctx.strokeStyle = rgba(C.amber, 0.6); ctx.beginPath(); ctx.moveTo(padL, Y(opts.line)); ctx.lineTo(w, Y(opts.line)); ctx.stroke(); ctx.setLineDash([]); }
    ctx.beginPath(); arr.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.strokeStyle = rgba(col === C.holo ? C.hi : col, 0.9); ctx.lineWidth = 1.4; ctx.stroke();
    ctx.lineTo(X(arr.length - 1), h - padB); ctx.lineTo(X(0), h - padB); ctx.closePath();
    const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, rgba(col, 0.25)); g.addColorStop(1, rgba(col, 0)); ctx.fillStyle = g; ctx.fill();
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(X(arr.length - 1), Y(arr[arr.length - 1]), 2.5, 0, Math.PI * 2); ctx.fill();
  }
  function drawCpuBars() {
    const f = fit(CV('cpuBars')); if (!f) return;
    const { ctx, w, h } = f;
    const cores = T.cores.length ? T.cores : [T.cpu];
    const n = cores.length, barH = h * 0.42, gap = n > 24 ? 1 : 3, bw = (w - gap * (n - 1)) / n;
    cores.forEach((v, i) => {
      const x = i * (bw + gap), bh = (v / 100) * barH;
      ctx.fillStyle = rgba(C.holo, 0.1); ctx.fillRect(x, 0, bw, barH);
      ctx.fillStyle = rgba(v > 85 ? C.amber : C.holo, 0.85); ctx.fillRect(x, barH - bh, bw, bh);
    });
    const top = barH + 10, hh = h - top - 2, arr = HIST.cpu;
    ctx.strokeStyle = rgba(C.holo, 0.12); [0, 0.5, 1].forEach((k) => { ctx.beginPath(); ctx.moveTo(0, top + hh * k); ctx.lineTo(w, top + hh * k); ctx.stroke(); });
    ctx.beginPath(); arr.forEach((v, i) => { const x = (i / (arr.length - 1)) * w, y = top + hh * (1 - v / 100); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = rgba(C.hi, 0.9); ctx.lineWidth = 1.3; ctx.stroke();
    ctx.lineTo(w, top + hh); ctx.lineTo(0, top + hh); ctx.closePath(); ctx.fillStyle = rgba(C.holo, 0.12); ctx.fill();
    ctx.fillStyle = rgba(C.dim, 1); ctx.font = `10px ${MONO}`; ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillText('LAST 2 MIN', 2, top + 3);
  }
  function drawNet() {
    const f = fit(CV('netChart')); if (!f) return;
    const { ctx, w, h } = f;
    const max = Math.max(1024, ...HIST.down, ...HIST.up) * 1.15, n = HIST.down.length;
    const X = (i) => (i / (n - 1)) * w, Yu = (v) => h * 0.5 - (v / max) * (h * 0.46), Yd = (v) => h * 0.5 + (v / max) * (h * 0.46);
    ctx.strokeStyle = rgba(C.holo, 0.2); ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
    const area = (arr, fy, col) => { ctx.beginPath(); ctx.moveTo(0, h / 2); arr.forEach((v, i) => ctx.lineTo(X(i), fy(v))); ctx.lineTo(w, h / 2); ctx.closePath(); ctx.fillStyle = rgba(col, 0.28); ctx.fill(); ctx.beginPath(); arr.forEach((v, i) => (i ? ctx.lineTo(X(i), fy(v)) : ctx.moveTo(X(i), fy(v)))); ctx.strokeStyle = rgba(col, 0.95); ctx.lineWidth = 1.2; ctx.stroke(); };
    area(HIST.down, Yu, C.holo); area(HIST.up, Yd, C.amber);
    ctx.font = `10px ${MONO}`; ctx.textAlign = 'right';
    ctx.textBaseline = 'top'; ctx.fillStyle = rgba(C.holo, 1); ctx.fillText('▼ DOWN', w - 2, 2);
    ctx.textBaseline = 'bottom'; ctx.fillStyle = rgba(C.amber, 1); ctx.fillText('▲ UP', w - 2, h - 2);
  }
  function drawWxIcon(t) {
    const f = fit(CV('wxIcon')); if (!f || !WX) return;
    const { ctx, w, h } = f;
    const c = WX.current || {}, kind = wxKind(c.weather_code ?? 0), day = c.is_day !== 0;
    const sx = w * 0.42, sy = h * 0.42;
    if (day) {
      ctx.save(); ctx.translate(sx, sy); ctx.rotate(t * 0.0003 * SPEED);
      ctx.strokeStyle = rgba(C.amber, 0.85); ctx.lineWidth = 2;
      for (let i = 0; i < 12; i++) { const a = (i / 12) * Math.PI * 2; ctx.beginPath(); ctx.moveTo(Math.cos(a) * 21, Math.sin(a) * 21); ctx.lineTo(Math.cos(a) * 28, Math.sin(a) * 28); ctx.stroke(); }
      ctx.restore();
      ctx.fillStyle = rgba(C.amber, 0.9); ctx.shadowColor = rgba(C.amber, 1); ctx.shadowBlur = 16;
      ctx.beginPath(); ctx.arc(sx, sy, 16, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
    } else {
      ctx.fillStyle = rgba(C.hi, 0.9); ctx.beginPath(); ctx.arc(sx, sy, 16, 0, Math.PI * 2); ctx.fill();
      ctx.globalCompositeOperation = 'destination-out'; ctx.beginPath(); ctx.arc(sx + 7, sy - 5, 14, 0, Math.PI * 2); ctx.fill(); ctx.globalCompositeOperation = 'source-over';
    }
    if (kind === 'clear') return;
    const cx = w * 0.6 + Math.sin(t * 0.0006 * SPEED) * 4, cy = h * 0.58;
    ctx.fillStyle = 'rgba(8,28,44,.95)'; ctx.strokeStyle = rgba(C.holo, 0.9); ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(cx - 18, cy, 12, Math.PI * 0.5, Math.PI * 1.5); ctx.arc(cx - 4, cy - 10, 15, Math.PI, Math.PI * 1.9); ctx.arc(cx + 16, cy - 2, 12, Math.PI * 1.3, Math.PI * 0.5); ctx.closePath();
    ctx.fill(); ctx.stroke();
    ctx.strokeStyle = rgba(C.hi, 0.85); ctx.lineWidth = 1.5;
    if (kind === 'rain') for (let i = 0; i < 4; i++) { const x = cx - 18 + i * 11, y = cy + 14 + ((t * 0.04 * SPEED + i * 7) % 12); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 3, y + 6); ctx.stroke(); }
    if (kind === 'snow') for (let i = 0; i < 4; i++) { ctx.fillStyle = rgba(C.hi, 0.9); ctx.beginPath(); ctx.arc(cx - 18 + i * 11, cy + 16 + ((t * 0.02 * SPEED + i * 5) % 10), 1.8, 0, Math.PI * 2); ctx.fill(); }
    if (kind === 'storm') { ctx.strokeStyle = rgba(C.amber, 0.95); ctx.beginPath(); ctx.moveTo(cx, cy + 10); ctx.lineTo(cx - 6, cy + 20); ctx.lineTo(cx + 2, cy + 20); ctx.lineTo(cx - 4, cy + 30); ctx.stroke(); }
    if (kind === 'fog') { ctx.strokeStyle = rgba(C.holo, 0.7); for (let i = 0; i < 3; i++) { ctx.beginPath(); ctx.moveTo(cx - 28, cy + 14 + i * 5); ctx.lineTo(cx + 26, cy + 14 + i * 5); ctx.stroke(); } }
  }
  function drawCompass(t) {
    const f = fit(CV('wxCompass')); if (!f) return;
    const { ctx, w, h } = f;
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 10;
    ctx.strokeStyle = rgba(C.holo, 0.35); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
    for (let i = 0; i < 36; i++) { const a = (i / 36) * Math.PI * 2, l = i % 9 === 0 ? 6 : 3; ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); ctx.lineTo(cx + Math.cos(a) * (R - l), cy + Math.sin(a) * (R - l)); ctx.stroke(); }
    ctx.fillStyle = rgba(C.dim, 1); ctx.font = `9px ${MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    [['N', 0], ['O', 90], ['S', 180], ['W', 270]].forEach(([l, d]) => { const a = (d - 90) * RAD; ctx.fillText(l, cx + Math.cos(a) * (R + 7), cy + Math.sin(a) * (R + 7)); });
    const dir = WX && WX.current && WX.current.wind_direction_10m != null ? WX.current.wind_direction_10m : null;
    if (dir == null) return;
    const a = (dir + 90 + Math.sin(t * 0.002) * 2) * RAD; // Pfeil zeigt, wohin der Wind weht
    const tip = [cx + Math.cos(a) * R * 0.85, cy + Math.sin(a) * R * 0.85];
    ctx.strokeStyle = rgba(C.hi, 0.95); ctx.fillStyle = rgba(C.hi, 0.95); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(cx - Math.cos(a) * R * 0.7, cy - Math.sin(a) * R * 0.7); ctx.lineTo(cx + Math.cos(a) * R * 0.55, cy + Math.sin(a) * R * 0.55); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(...tip);
    ctx.lineTo(tip[0] - Math.cos(a - 0.45) * R * 0.38, tip[1] - Math.sin(a - 0.45) * R * 0.38);
    ctx.lineTo(tip[0] - Math.cos(a + 0.45) * R * 0.38, tip[1] - Math.sin(a + 0.45) * R * 0.38); ctx.fill();
  }
  function drawForecast() {
    if (!root) return;
    const f = fit(CV('wxForecast')); if (!f || !WX || !WX.hourly || !WX.hourly.time) return;
    const { ctx, w, h } = f;
    const hr = WX.hourly, nowKey = (WX.current && WX.current.time || '').slice(0, 13);
    let start = hr.time.findIndex((tm) => tm.slice(0, 13) >= nowKey); if (start < 0) start = 0;
    const pts = hr.time.slice(start, start + 13).map((tm, i) => [tm, hr.temperature_2m[start + i], hr.is_day ? hr.is_day[start + i] : 1]);
    if (pts.length < 2) return;
    const temps = pts.map((p) => p[1]);
    const lo = Math.floor(Math.min(...temps) - 1), hi = Math.ceil(Math.max(...temps) + 1), n = pts.length - 1;
    const padL = 30, padB = 16, X = (i) => padL + (i / n) * (w - padL - 8), Y = (v) => 6 + (1 - (v - lo) / (hi - lo)) * (h - padB - 10);
    pts.forEach(([, , day], i) => { if (i < n) { ctx.fillStyle = day ? rgba(C.amber, 0.07) : rgba(C.holo, 0.02); ctx.fillRect(X(i), 4, X(i + 1) - X(i), h - padB - 4); } });
    ctx.font = `10px ${MONO}`; ctx.textBaseline = 'middle';
    [lo, (lo + hi) / 2, hi].forEach((v) => { ctx.strokeStyle = rgba(C.holo, 0.12); ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w - 8, Y(v)); ctx.stroke(); ctx.fillStyle = rgba(C.dim, 1); ctx.textAlign = 'right'; ctx.fillText(v.toFixed(0) + '°', padL - 6, Y(v)); });
    ctx.beginPath(); pts.forEach(([, v], i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.strokeStyle = rgba(C.hi, 0.9); ctx.lineWidth = 1.6; ctx.stroke();
    ctx.lineTo(X(n), h - padB); ctx.lineTo(X(0), h - padB); ctx.closePath();
    const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, rgba(C.holo, 0.25)); g.addColorStop(1, rgba(C.holo, 0)); ctx.fillStyle = g; ctx.fill();
    ctx.textAlign = 'center'; ctx.fillStyle = rgba(C.dim, 1);
    pts.forEach(([tm], i) => { if (i % 3 === 0) ctx.fillText(i === 0 ? 'JETZT' : hhmm(tm), X(i), h - 6); });
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(X(0), Y(pts[0][1]), 3, 0, Math.PI * 2); ctx.fill();
    ctx.textAlign = 'right'; ctx.textBaseline = 'top'; ctx.fillStyle = rgba(C.amber, 0.8); ctx.fillText('▮ TAG', w - 8, 4);
  }

  // --- arc reactor core + radial menu
  function placeNodes() {
    const wrap = K('coreWrap'); if (!wrap) return;
    const s = wrap.clientWidth;
    wrap.querySelectorAll('.lh-node').forEach((b, i) => {
      const a = -Math.PI / 2 + (i / NODES.length) * Math.PI * 2 + Math.PI / NODES.length;
      const r = Math.min(s * 0.47, s / 2 - 48);
      b.style.left = (s / 2 + Math.cos(a) * r) + 'px'; b.style.top = (s / 2 + Math.sin(a) * r) + 'px';
    });
  }
  function drawCore(t) {
    const f = fit(CV('core')); if (!f) return;
    const { ctx, w, h } = f;
    const cx = w / 2, cy = h / 2, Sz = Math.min(w, h), v = voiceLevel, tt = t * SPEED;
    let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Sz * 0.5);
    g.addColorStop(0, rgba(C.holo, 0.22 + v * 0.15)); g.addColorStop(0.5, rgba(C.holo, 0.05)); g.addColorStop(1, rgba(C.holo, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = rgba(C.holo, 0.12); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx - Sz * 0.5, cy); ctx.lineTo(cx - Sz * 0.18, cy); ctx.moveTo(cx + Sz * 0.18, cy); ctx.lineTo(cx + Sz * 0.5, cy);
    ctx.moveTo(cx, cy - Sz * 0.5); ctx.lineTo(cx, cy - Sz * 0.18); ctx.moveTo(cx, cy + Sz * 0.18); ctx.lineTo(cx, cy + Sz * 0.5); ctx.stroke();
    ctx.save(); ctx.translate(cx, cy);
    const r1 = Sz * 0.37;
    ctx.save(); ctx.rotate(tt * 0.00004);
    for (let i = 0; i < 180; i++) {
      const a = (i / 180) * Math.PI * 2, long = i % 15 === 0, mid = i % 5 === 0, len = long ? 13 : mid ? 7 : 3.5;
      ctx.strokeStyle = rgba(long ? C.hi : C.holo, long ? 0.85 : mid ? 0.5 : 0.25); ctx.lineWidth = long ? 1.4 : 1;
      ctx.beginPath(); ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); ctx.lineTo(Math.cos(a) * (r1 - len), Math.sin(a) * (r1 - len)); ctx.stroke();
    }
    ctx.fillStyle = rgba(C.holo, 0.6); ctx.font = `${Math.max(9, Sz * 0.016)}px ${MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (let d = 0; d < 360; d += 30) { ctx.save(); ctx.rotate(d * RAD); ctx.fillText(String(d).padStart(3, '0'), 0, -(r1 + Sz * 0.022)); ctx.restore(); }
    ctx.restore();
    const rOut = r1 + Sz * 0.045;
    ctx.strokeStyle = rgba(C.holo, 0.35); ctx.beginPath(); ctx.arc(0, 0, rOut, 0, Math.PI * 2); ctx.stroke();
    // live gauges on the outer ring: CPU (lower left), GPU (lower right)
    const cpuP = clamp(T.cpu / 100, 0, 1), gpuP = clamp(gpuUtil() / 100, 0, 1);
    ctx.lineWidth = 4; ctx.shadowBlur = 8;
    ctx.shadowColor = rgba(C.holo, 1); ctx.strokeStyle = rgba(C.hi, 0.85); ctx.beginPath(); ctx.arc(0, 0, rOut, Math.PI * 0.56, Math.PI * (0.56 + 0.4 * cpuP)); ctx.stroke();
    ctx.shadowColor = rgba(C.amber, 1); ctx.strokeStyle = rgba(C.amber, 0.85); ctx.beginPath(); ctx.arc(0, 0, rOut, Math.PI * 0.44, Math.PI * (0.44 - 0.4 * gpuP), true); ctx.stroke();
    ctx.shadowBlur = 0;
    const r2 = Sz * 0.32;
    ctx.save(); ctx.rotate(tt * 0.00018); ctx.lineWidth = Sz * 0.012; ctx.shadowColor = rgba(C.holo, 1); ctx.shadowBlur = 10;
    for (let i = 0; i < 12; i++) { const a0 = (i / 12) * Math.PI * 2 + 0.04; ctx.strokeStyle = rgba(i % 4 === 0 ? C.hi : C.holo, i % 4 === 0 ? 0.9 : 0.45); ctx.beginPath(); ctx.arc(0, 0, r2, a0, a0 + Math.PI / 6 - 0.1); ctx.stroke(); }
    ctx.restore();
    ctx.save(); ctx.rotate(-tt * 0.00032); ctx.setLineDash([Sz * 0.006, Sz * 0.012]); ctx.strokeStyle = rgba(C.holo, 0.55); ctx.lineWidth = Sz * 0.018;
    ctx.beginPath(); ctx.arc(0, 0, Sz * 0.288, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    const r4 = Sz * 0.243;
    for (let i = 0; i < 96; i++) {
      const a = (i / 96) * Math.PI * 2 + tt * 0.0001;
      const n = Math.abs(Math.sin(i * 1.7 + tt * 0.004) * 0.6 + Math.sin(i * 0.37 - tt * 0.006) * 0.4);
      const len = Sz * (0.008 + n * (0.012 + v * 0.05 + cpuP * 0.02));
      ctx.strokeStyle = rgba(v > 0.2 && n > 0.6 ? C.hi : C.holo, 0.35 + n * 0.5); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(Math.cos(a) * r4, Math.sin(a) * r4); ctx.lineTo(Math.cos(a) * (r4 + len), Math.sin(a) * (r4 + len)); ctx.stroke();
    }
    const r5 = Sz * 0.205;
    ctx.save(); ctx.rotate(tt * 0.0009); ctx.lineWidth = 2; ctx.shadowColor = rgba(C.holo, 1); ctx.shadowBlur = 14;
    for (let i = 0; i < 3; i++) { ctx.strokeStyle = rgba(C.hi, 0.85); ctx.beginPath(); ctx.arc(0, 0, r5, i * 2.094, i * 2.094 + 0.9); ctx.stroke(); }
    ctx.restore();
    const r6 = Sz * 0.165, pulse = 0.85 + Math.sin(tt * 0.003) * 0.08 + v * 0.25;
    g = ctx.createRadialGradient(0, 0, 0, 0, 0, r6 * 1.25);
    g.addColorStop(0, 'rgba(255,255,255,.95)'); g.addColorStop(0.35, rgba(C.hi, 0.75 * pulse)); g.addColorStop(0.7, rgba(C.holo, 0.35 * pulse)); g.addColorStop(1, rgba(C.holo, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, r6 * 1.25, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(2,10,20,.55)'; ctx.beginPath(); ctx.arc(0, 0, r6 * 0.98, 0, Math.PI * 2); ctx.arc(0, 0, r6 * 0.55, 0, Math.PI * 2, true); ctx.fill();
    for (let i = 0; i < 10; i++) {
      const a0 = (i / 10) * Math.PI * 2 + 0.07, a1 = a0 + Math.PI / 5 - 0.14;
      ctx.fillStyle = rgba(C.hi, 0.55 + 0.35 * pulse * (i % 2 ? 0.8 : 1));
      ctx.beginPath(); ctx.arc(0, 0, r6 * 0.93, a0, a1); ctx.arc(0, 0, r6 * 0.62, a1, a0, true); ctx.closePath(); ctx.fill();
    }
    ctx.strokeStyle = rgba(C.hi, 0.9); ctx.lineWidth = 1.5; ctx.shadowColor = rgba(C.holo, 1); ctx.shadowBlur = 16;
    ctx.beginPath(); ctx.arc(0, 0, r6, 0, Math.PI * 2); ctx.stroke(); ctx.beginPath(); ctx.arc(0, 0, r6 * 0.55, 0, Math.PI * 2); ctx.stroke();
    g = ctx.createRadialGradient(0, 0, 0, 0, 0, r6 * 0.5); g.addColorStop(0, '#fff'); g.addColorStop(1, rgba(C.hi, 0.2 + v * 0.4));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, r6 * 0.5, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
    const st = T.stats || {};
    ctx.font = `${Math.max(11, Sz * 0.019)}px ${MONO}`; ctx.fillStyle = rgba(C.holo, 0.8); ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.fillText(`CPU  ${Math.round(T.cpu)}%`, -Sz * 0.49, -Sz * 0.47); ctx.fillText(`RAM  ${st.ram != null ? Math.round(st.ram) + '%' : '--'}`, -Sz * 0.49, -Sz * 0.44);
    ctx.fillText(`OUT  ${S.reactor.toFixed(2)} GJ/s`, -Sz * 0.49, Sz * 0.44); ctx.fillText(`CORE ${(311 + Math.sin(tt * 0.0005) * 2).toFixed(1)} K`, -Sz * 0.49, Sz * 0.47);
    ctx.textAlign = 'right';
    ctx.fillText(`GPU  ${Math.round(gpuUtil())}%`, Sz * 0.49, -Sz * 0.47); ctx.fillText(`${Math.round(T.fps)} FPS`, Sz * 0.49, -Sz * 0.44);
    const wc = WX && WX.current;
    ctx.fillText(wc ? `WX ${wc.temperature_2m.toFixed(1)}°C` : 'WX --', Sz * 0.49, Sz * 0.44);
    ctx.fillText(T.online ? 'UPLINK OK' : 'OFFLINE', Sz * 0.49, Sz * 0.47);
    ctx.restore();
  }

  // --- suit / radar / globe / wave (Kulisse)
  const HALF = [
    [[0.44, 0.02], [0.5, 0.012], [0.5, 0.165], [0.46, 0.16], [0.42, 0.13], [0.41, 0.07]], [[0.47, 0.165], [0.5, 0.165], [0.5, 0.195], [0.47, 0.195]],
    [[0.36, 0.195], [0.5, 0.195], [0.5, 0.5], [0.42, 0.5], [0.39, 0.44], [0.34, 0.3]], [[0.28, 0.19], [0.36, 0.195], [0.35, 0.27], [0.27, 0.27]],
    [[0.27, 0.275], [0.34, 0.275], [0.32, 0.4], [0.26, 0.4]], [[0.258, 0.408], [0.318, 0.408], [0.308, 0.53], [0.248, 0.53]],
    [[0.245, 0.537], [0.31, 0.537], [0.305, 0.59], [0.25, 0.59]], [[0.42, 0.505], [0.5, 0.505], [0.5, 0.6], [0.4, 0.56]],
    [[0.41, 0.575], [0.493, 0.605], [0.48, 0.76], [0.42, 0.76]], [[0.42, 0.768], [0.48, 0.768], [0.476, 0.928], [0.426, 0.928]],
    [[0.41, 0.936], [0.48, 0.936], [0.484, 0.982], [0.4, 0.982]],
  ];
  function drawArmor(t) {
    const f = fit(CV('armor')); if (!f) return;
    const { ctx, w, h } = f;
    const s = Math.min(h * 0.98, w / 0.56), ox = w / 2 - 0.5 * s, oy = (h - s) / 2;
    const P = (x, y) => [ox + x * s, oy + y * s];
    const poly = (pts, warn) => {
      ctx.beginPath(); pts.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.closePath();
      const col = warn ? C.amber : C.holo; ctx.fillStyle = rgba(col, warn ? 0.18 : 0.06); ctx.fill();
      ctx.strokeStyle = rgba(col, 0.85); ctx.lineWidth = 1; ctx.stroke();
    };
    HALF.forEach((p, i) => { poly(p, i === 6); poly(p.map(([x, y]) => [1 - x, y]), false); });
    const [rx, ry] = P(0.5, 0.27); const rg = ctx.createRadialGradient(rx, ry, 0, rx, ry, s * 0.05); rg.addColorStop(0, '#fff'); rg.addColorStop(1, rgba(C.holo, 0));
    ctx.fillStyle = rg; ctx.beginPath(); ctx.arc(rx, ry, s * 0.05, 0, Math.PI * 2); ctx.fill();
    const scan = ((t * 0.00025 * SPEED) % 1.2) - 0.1;
    if (scan > 0 && scan < 1) { const [, sy] = P(0, scan); ctx.strokeStyle = rgba(C.hi, 0.8); ctx.beginPath(); ctx.moveTo(ox + 0.2 * s, sy); ctx.lineTo(ox + 0.8 * s, sy); ctx.stroke(); }
  }
  const SUIT = [['HELMET', 100], ['REPULSORS', 97], ['FLIGHT STAB.', 93], ['LIFE SUPPORT', 100], ['GAUNTLET L', 82, true], ['UNIBEAM', 64], ['FLARES', 12, true]];
  const BLIPS = [[0.31, 0.6, C.holo], [1.9, 0.7, C.amber], [3.6, 0.83, C.holo], [5.0, 0.4, C.holo]];
  function drawRadar(t) {
    const f = fit(CV('radar')); if (!f) return;
    const { ctx, w, h } = f;
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.47, sw = (t * 0.0012 * SPEED) % (Math.PI * 2);
    ctx.strokeStyle = rgba(C.holo, 0.22); ctx.lineWidth = 1;
    [0.33, 0.66, 1].forEach((k) => { ctx.beginPath(); ctx.arc(cx, cy, R * k, 0, Math.PI * 2); ctx.stroke(); });
    ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
    for (let i = 0; i < 40; i++) { const a = sw - i * 0.02; ctx.fillStyle = rgba(C.holo, 0.22 * (1 - i / 40)); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, R, a - 0.02, a); ctx.closePath(); ctx.fill(); }
    ctx.strokeStyle = rgba(C.hi, 0.9); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.cos(sw) * R, cy + Math.sin(sw) * R); ctx.stroke();
    BLIPS.forEach(([a, d, col]) => { let since = sw - a; if (since < 0) since += Math.PI * 2; ctx.fillStyle = rgba(col, Math.max(0.12, 1 - since / 4)); ctx.beginPath(); ctx.arc(cx + Math.cos(a) * R * d, cy + Math.sin(a) * R * d, 3, 0, Math.PI * 2); ctx.fill(); });
  }
  const SPHERE = (() => { const p = [], n = 420, ga = Math.PI * (3 - Math.sqrt(5)); for (let i = 0; i < n; i++) { const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i; p.push([Math.cos(th) * r, y, Math.sin(th) * r]); } return p; })();
  const CITIES = [['NEW YORK', 40.71, -74.0], ['LONDON', 51.5, -0.12], ['DUBAI', 25.2, 55.27], ['TOKYO', 35.68, 139.69]];
  const ll = (la, lo) => [Math.cos(la * RAD) * Math.sin(lo * RAD), -Math.sin(la * RAD), Math.cos(la * RAD) * Math.cos(lo * RAD)];
  function drawGlobe(t) {
    const f = fit(CV('globe')); if (!f) return;
    const { ctx, w, h } = f;
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.44, rot = t * 0.00015 * SPEED, tilt = 0.35;
    const cr = Math.cos(rot), sr = Math.sin(rot), ct = Math.cos(tilt), st = Math.sin(tilt);
    const pr = ([x, y, z]) => { const x1 = x * cr + z * sr, z1 = -x * sr + z * cr; return [cx + x1 * R, cy + (y * ct - z1 * st) * R, y * st + z1 * ct]; };
    for (const p of SPHERE) { const [x, y, z] = pr(p); if (z < 0) continue; ctx.fillStyle = rgba(C.holo, 0.15 + z * 0.55); ctx.fillRect(x - 0.7, y - 0.7, 1.4, 1.4); }
    ctx.strokeStyle = rgba(C.hi, 0.55); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
    const homeName = WX ? WX.city.toUpperCase() : 'MALIBU', home = WX ? [WX.lat, WX.lon] : [34.03, -118.78];
    const hv = ll(home[0], home[1]);
    CITIES.forEach(([, la, lo], k) => {
      const b = ll(la, lo); ctx.beginPath(); let on = false;
      for (let i = 0; i <= 30; i++) { const u = i / 30, lift = 1 + Math.sin(u * Math.PI) * 0.2; let v = hv.map((c, j) => c * (1 - u) + b[j] * u); const n = Math.hypot(...v) || 1; v = v.map((c) => (c / n) * lift); const [x, y, z] = pr(v); if (z >= -0.05) { on ? ctx.lineTo(x, y) : ctx.moveTo(x, y); on = true; } else on = false; }
      ctx.strokeStyle = rgba(k === 2 ? C.amber : C.holo, 0.6); ctx.stroke();
    });
    ctx.font = `10px ${MONO}`; ctx.textBaseline = 'middle';
    [[homeName, home[0], home[1], true], ...CITIES].forEach(([name, la, lo, isHome]) => { const [x, y, z] = pr(ll(la, lo)); if (z < 0) return; ctx.fillStyle = rgba(isHome ? C.hi : C.holo, 1); ctx.beginPath(); ctx.arc(x, y, isHome ? 3 : 2.2, 0, Math.PI * 2); ctx.fill(); ctx.textAlign = x > cx ? 'left' : 'right'; ctx.fillText(name, x + (x > cx ? 6 : -6), y); });
  }
  function drawWave(t) {
    const f = fit(CV('wave')); if (!f) return;
    const { ctx, w, h } = f;
    const mid = h / 2, amp = h * (0.06 + voiceLevel * 0.4);
    for (let l = 0; l < 3; l++) {
      ctx.beginPath();
      for (let x = 0; x <= w; x += 2) { const k = x / w, env = Math.sin(k * Math.PI); const y = mid + env * amp * (Math.sin(k * (22 + l * 7) + t * 0.008 * SPEED + l) * 0.6 + Math.sin(k * 57 - t * 0.012 * SPEED) * 0.4); x ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.strokeStyle = rgba(l ? C.holo : C.hi, l ? 0.35 : 0.9); ctx.lineWidth = l ? 1 : 1.5; ctx.stroke();
    }
  }

  // ================================================================ readouts (4×/s)
  const gpuInfo = () => (T.stats && T.stats.gpus && T.stats.gpus[0]) || null;
  const gpuUtil = () => { const g = gpuInfo(); return g && g.util != null ? g.util : clamp((T.frameMs / 16.7) * 18, 2, 100); };
  function setK(k, txt, cls) { const el = K(k); if (!el) return; el.textContent = txt; if (cls !== undefined) el.className = cls; }
  function setSrc(id, live, txtLive = 'LIVE', txtEst = 'EST') {
    const el = root.querySelector(`[data-src="${id}"]`); if (!el) return;
    el.textContent = live ? txtLive : txtEst; el.className = 'lh-src ' + (live ? 'lh-live' : 'lh-mix');
  }
  function updateReadouts() {
    if (!root) return;
    const st = T.stats || {}, now = performance.now();
    // CPU — real from psutil; without it: estimate from this tab's frame time
    const cpuLive = st.cpu != null;
    T.cpu = cpuLive ? lerp(T.cpu, st.cpu, 0.5) : lerp(T.cpu, clamp(4 + Math.max(0, T.frameMs - 17) * 2.2, 1, 100), 0.3);
    T.cores = st.cpu_cores || [];
    push(HIST.cpu, T.cpu);
    setSrc('cpu', cpuLive);
    setK('cpuSub', `${st.cpu_count || navigator.hardwareConcurrency || '?'} THREADS`);
    setK('cpuLoad', T.cpu.toFixed(1) + ' %', T.cpu > 85 ? 'lh-w' : '');
    setK('cpuCores', String(st.cpu_count || navigator.hardwareConcurrency || 'n/a'));
    setK('cpuClock', st.cpu_freq_mhz ? (st.cpu_freq_mhz / 1000).toFixed(2) + ' GHz' : 'n/a');
    setK('cpuTemp', st.cpu_temp != null ? Math.round(st.cpu_temp) + ' °C' : 'n/a', st.cpu_temp > 85 ? 'lh-w' : '');
    setK('procs', st.processes != null ? String(st.processes) : 'n/a');
    // memory
    push(HIST.mem, st.ram ?? 0);
    setSrc('mem', st.ram != null, 'LIVE', 'N/A');
    setK('memSub', st.ram_total ? fmtBytes(st.ram_total, 0) + ' RAM' : 'psutil fehlt');
    setK('memUse', st.ram_used != null ? fmtBytes(st.ram_used, 1) : 'n/a', st.ram > 90 ? 'lh-w' : '');
    setK('memTotal', st.ram_total ? fmtBytes(st.ram_total, 1) : 'n/a');
    setK('memFree', st.ram_total ? fmtBytes(st.ram_total - st.ram_used, 1) : 'n/a');
    setK('memSwap', st.swap_used != null ? `${fmtBytes(st.swap_used, 1)} · ${Math.round(st.swap)}%` : 'n/a');
    setK('memHeap', performance.memory ? fmtBytes(performance.memory.usedJSHeapSize) : 'n/a');
    // GPU — nvidia-smi if present, else WebGL name + frame-time estimate
    const g = gpuInfo();
    push(HIST.gpu, gpuUtil());
    setSrc('gpu', !!g, 'LIVE', 'LIVE · EST');
    setK('gpuName', g ? g.name : (T.gpuName || 'nicht auslesbar'));
    setK('gpuUtil', Math.round(gpuUtil()) + ' %' + (g ? '' : ' (est.)'));
    setK('gpuVram', g && g.mem_total ? `${fmtBytes(g.mem_used, 1)} / ${fmtBytes(g.mem_total, 0)}` : 'n/a');
    setK('gpuTemp', g && g.temp != null ? Math.round(g.temp) + ' °C' : 'n/a', g && g.temp > 85 ? 'lh-w' : '');
    setK('gpuFps', Math.round(T.fps) + ' fps', T.fps < 30 ? 'lh-w' : 'lh-g');
    setK('gpuFrame', T.frameMs.toFixed(1) + ' ms');
    // network
    const netLive = st.net_down != null;
    push(HIST.down, st.net_down || 0); push(HIST.up, st.net_up || 0);
    T.peakDown = Math.max(T.peakDown, st.net_down || 0);
    setSrc('net', netLive, 'LIVE', 'N/A');
    setK('netSub', st.host ? `${st.host.toUpperCase()} · ${st.os || ''}` : '—');
    setK('netStatus', T.online ? 'ONLINE' : 'OFFLINE', T.online ? 'lh-g' : 'lh-b');
    setK('netDown', fmtRate(st.net_down)); setK('netUp', fmtRate(st.net_up)); setK('netPeak', fmtRate(T.peakDown || null));
    // power & storage
    S.reactor = 3.19 + Math.sin(now * 0.0006) * 0.03 + (Math.random() - 0.5) * 0.02 + voiceLevel * 0.05;
    push(HIST.pow, S.reactor);
    setK('reactor', S.reactor.toFixed(2) + ' GJ/s');
    setK('batLvl', st.battery != null ? Math.round(st.battery) + ' %' : 'kein Akku');
    setK('batState', st.battery != null ? (st.plugged ? 'NETZTEIL' : 'AKKU') : 'NETZ / ARC');
    if (st.disk_total) {
      setK('diskTxt', `${fmtBytes(st.disk_used, 0)} / ${fmtBytes(st.disk_total, 0)} · ${Math.round(st.disk)}%`);
      const bar = K('diskBar'); bar.querySelector('b').style.width = st.disk + '%'; bar.className = 'lh-bar' + (st.disk > 90 ? ' lh-warnbar' : '');
    } else setK('diskTxt', 'n/a');
    // top bar
    setK('host', `WORKSHOP · ${(st.host || 'LOCAL').toUpperCase()}`);
    setK('uptime', st.uptime_s != null ? fmtDur(st.uptime_s) : fmtDur((now - T.t0) / 1000));
    setK('uplink', T.online ? 'ONLINE' : 'OFFLINE'); root.querySelector('[data-chip="net"]').className = 'lh-chip' + (T.online ? '' : ' lh-bad');
    const hot = T.cpu > 90 || (st.ram || 0) > 92;
    setK('sys', hot ? 'LOAD HIGH' : 'NOMINAL'); root.querySelector('[data-chip="sys"]').className = 'lh-chip' + (hot ? ' lh-warn' : '');
    const model = T.model ? T.model.replace(/^.*\//, '') : '—';
    setK('llm', T.modelOk === false ? 'OFFLINE' : model); root.querySelector('[data-chip="llm"]').className = 'lh-chip' + (T.modelOk === false ? ' lh-bad' : '');
    root.querySelector('[data-chip="llm"]').title = T.model || '';
  }

  // ================================================================ JARVIS console
  function addLine(cls, who, text) {
    const log = K('log'); const p = document.createElement('p');
    p.innerHTML = `<span class="lh-who">${who}</span><span class="${cls}"></span>`; p.lastChild.textContent = text;
    log.appendChild(p); log.scrollTop = log.scrollHeight; return p.lastChild;
  }
  function say(text, opts = {}) { queue.push([text, opts]); if (!typing) nextLine(); }
  function nextLine() {
    if (!root) return;
    const it = queue.shift();
    if (!it) { typing = false; setK('waveLbl', 'AUDIO · STANDBY'); return; }
    const [text, opts] = it; typing = true;
    const span = addLine('lh-j', 'JARVIS', '');
    if (voiceOn && !opts.silent && hooks.speak) { try { hooks.speak(text); } catch (e) {} }
    if (opts.instant || reduce()) { span.textContent = text; K('log').scrollTop = K('log').scrollHeight; setTimeout(nextLine, 60); return; }
    setK('waveLbl', 'AUDIO · TRANSMITTING');
    let i = 0;
    const step = () => {
      if (!root) return;
      i += text.length > 400 ? 4 : 1 + (Math.random() < 0.3 ? 1 : 0);
      span.textContent = text.slice(0, i); K('log').scrollTop = K('log').scrollHeight;
      if (i < text.length) setTimeout(step, 18); else setTimeout(nextLine, 300);
    };
    step();
  }
  const pct = (v) => Math.round(v) + ' Prozent';
  const ANSWERS = {
    cpu: () => { const st = T.stats || {}; return st.cpu != null ? `CPU-Last ${pct(T.cpu)} über ${st.cpu_count} Threads${st.cpu_freq_mhz ? ', Takt ' + (st.cpu_freq_mhz / 1000).toFixed(1) + ' Gigahertz' : ''}${st.cpu_temp != null ? ', ' + Math.round(st.cpu_temp) + ' Grad' : ''}. ${st.processes} Prozesse laufen.` : 'Ohne psutil sehe ich die echte CPU-Last nicht, Sir. Ich schätze sie aus meiner eigenen Bildrate.'; },
    ram: () => { const st = T.stats || {}; return st.ram != null ? `Arbeitsspeicher zu ${pct(st.ram)} belegt, ${fmtBytes(st.ram_used, 1)} von ${fmtBytes(st.ram_total, 0)}. Swap bei ${fmtBytes(st.swap_used, 1)}.` : 'Den Arbeitsspeicher kann ich ohne psutil nicht auslesen, Sir.'; },
    gpu: () => { const g = gpuInfo(); return g ? `${g.name}: Auslastung ${pct(g.util ?? 0)}, ${fmtBytes(g.mem_used, 1)} von ${fmtBytes(g.mem_total, 0)} Grafikspeicher${g.temp != null ? ', ' + Math.round(g.temp) + ' Grad' : ''}.` : `Grafik: ${T.gpuName || 'nicht auslesbar'}. Genauere Werte liefert nur eine NVIDIA-Karte. Ich rendere mit ${Math.round(T.fps)} Bildern pro Sekunde.`; },
    net: () => { const st = T.stats || {}; return T.online ? `Uplink steht. Aktuell ${fmtRate(st.net_down)} herunter und ${fmtRate(st.net_up)} hoch.` : 'Sir, wir sind offline.'; },
    bat: () => { const st = T.stats || {}; return st.battery != null ? `Akku bei ${pct(st.battery)}, ${st.plugged ? 'am Netzteil' : 'im Akkubetrieb'}.` : 'Dieser Rechner meldet keinen Akku. Ich nehme an, Sie hängen am Reaktor.'; },
    disk: () => { const st = T.stats || {}; return st.disk_total ? `Systemlaufwerk zu ${pct(st.disk)} belegt, ${fmtBytes(st.disk_total - st.disk_used, 0)} frei.` : 'Das Laufwerk kann ich nicht auslesen.'; },
    weather: () => { if (!WX) return wxError ? `Keine Wetterdaten: ${wxError}` : 'Wetterdaten laden noch, Sir.'; const c = WX.current; return `${WX.city}: ${c.temperature_2m.toFixed(0)} Grad, ${(WMO[c.weather_code] || '').toLowerCase()}, Wind ${Math.round(c.wind_speed_10m)} Knoten, Luftfeuchte ${c.relative_humidity_2m} Prozent.`; },
    sun: () => { if (!WX) return 'Dafür brauche ich erst die Wetterdaten, Sir.'; const d = WX.daily || {}; return `In ${WX.city} geht die Sonne um ${hhmm((d.sunrise || [])[0])} auf und um ${hhmm((d.sunset || [])[0])} unter. Sie steht gerade bei ${WX.elev.toFixed(0)} Grad.`; },
    time: () => `Es ist ${new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })} Uhr${WX ? ', in ' + WX.city + ' ' + cityLocalNow() : ''}.`,
    status: () => { const st = T.stats || {}; return `Systeme ${T.cpu > 90 ? 'unter hoher Last' : 'nominal'}. CPU ${pct(T.cpu)}${st.ram != null ? ', RAM ' + pct(st.ram) : ''}, ${T.online ? 'Uplink stabil' : 'kein Uplink'}${T.model ? ', Modell ' + T.model.replace(/^.*\//, '') + (T.modelOk === false ? ' nicht erreichbar' : ' bereit') : ''}.`; },
    suit: () => 'Die Rüstung ist einsatzbereit, Sir. Der linke Handschuh meldet 82 Prozent, die Gegenmaßnahmen stehen bei 12 Prozent.',
  };
  const RULES = [
    [/\b(cpu|prozessor|kerne?|threads?)\b/, 'cpu'], [/\b(ram|arbeitsspeicher|memory|swap)\b/, 'ram'], [/\b(gpu|grafik\w*|vram|fps)\b/, 'gpu'],
    [/\b(netz\w*|internet|wlan|wifi|uplink|bandbreite)\b/, 'net'], [/\b(akku|batterie)\b/, 'bat'], [/\b(festplatte|laufwerk|disk|ssd|speicherplatz)\b/, 'disk'],
    [/sonnen(auf|unter)gang|\bsonne\b|dämmerung/, 'sun'], [/\b(wetter|temperatur|regen|wind)\b/, 'weather'],
    [/^(uhrzeit|wie spät|zeit)\b|wie spät/, 'time'], [/\b(status|systembericht|diagnose)\b/, 'status'], [/\b(anzug|rüstung|suit)\b/, 'suit'],
  ];
  function localAnswer(q) {
    const s = q.toLowerCase().trim();
    const city = /^(?:wetter|stadt)\s+(?:in|für)\s+(.+?)[?.!]*$/.exec(s);
    if (city) { setCity(city[1].replace(/\b\w/g, (c) => c.toUpperCase())); return `Ich schalte das Wetter auf ${city[1]} um, Sir.`; }
    if (s.split(/\s+/).length > 7) return null; // längere Fragen gehören dem Modell
    for (const [re, k] of RULES) if (re.test(s)) return ANSWERS[k]();
    return null;
  }
  async function askModel(q) {
    chatBusy = true;
    const wait = addLine('lh-sys', 'JARVIS', 'denkt nach …');
    try {
      const r = await fetch('/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: q, history: chatHistory.slice(-12), mode: 'chat' }),
      });
      const j = await r.json();
      const reply = String(j.reply || 'Keine Antwort erhalten, Sir.').trim();
      chatHistory.push({ role: 'user', content: q }, { role: 'assistant', content: reply });
      if (wait.parentElement) wait.parentElement.remove();
      say(reply);
    } catch (e) {
      if (wait.parentElement) wait.parentElement.remove();
      say('Ich erreiche das Modell gerade nicht, Sir.');
    } finally { chatBusy = false; }
  }
  function onAsk(e) {
    e.preventDefault();
    const inp = K('askInput'), q = inp.value.trim(); if (!q) return;
    inp.value = '';
    addLine('lh-me', 'SIR', q);
    const local = localAnswer(q);
    if (local) { setTimeout(() => say(local), 200); return; }
    if (chatBusy) { say('Einen Moment, Sir, ich bin noch bei der letzten Frage.'); return; }
    askModel(q);
  }

  // ================================================================ interaction
  const NODE_PANEL = { cpu: 'cpu', gpu: 'gpu', weather: 'weather', net: 'net', suit: 'suit', comms: 'con' };
  function flash(panel) { const el = root.querySelector(`[data-panel="${panel}"]`); if (!el) return; el.classList.add('lh-flash'); setTimeout(() => el.classList.remove('lh-flash'), 900); }
  function onClick(e) {
    const node = e.target.closest('.lh-node');
    if (node) {
      root.querySelectorAll('.lh-node').forEach((x) => x.classList.toggle('lh-on', x === node));
      const id = node.dataset.node; flash(NODE_PANEL[id]);
      if (id === 'comms') { K('askInput').focus(); say('Ich höre, Sir.', { silent: true }); } else say(ANSWERS[id]());
      return;
    }
    if (e.target.matches('[data-c="core"]')) { say(ANSWERS.status()); return; }
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'close') close();
    else if (act === 'voice') { close(); if (hooks.voice) hooks.voice(); }
    else if (act === 'city') editCity();
    else if (act === 'voiceToggle') {
      voiceOn = !voiceOn; btn.setAttribute('aria-pressed', String(voiceOn)); btn.textContent = voiceOn ? 'VOICE ON' : 'VOICE OFF';
      if (voiceOn) { if (hooks.speak) say('Sprachausgabe aktiviert, Sir.'); else say('Die Jarvis-Stimme ist hier nicht verfügbar.', { silent: true }); }
    }
  }
  // Escape schließt das HUD — in der Capture-Phase, damit nicht zusätzlich
  // ein Menü der darunterliegenden Oberfläche zugeht.
  function onKey(e) {
    if (e.key !== 'Escape' || !root) return;
    if (e.target && e.target.classList && e.target.classList.contains('lh-city-input')) return;
    e.preventDefault(); e.stopPropagation(); close();
  }

  // ================================================================ clock / world time
  const ZONES = [['MALIBU', 'America/Los_Angeles'], ['NEW YORK', 'America/New_York'], ['LONDON', 'Europe/London'], ['BERLIN', 'Europe/Berlin'],
    ['DUBAI', 'Asia/Dubai'], ['MUMBAI', 'Asia/Kolkata'], ['TOKYO', 'Asia/Tokyo'], ['SYDNEY', 'Australia/Sydney']];
  let ZFMT = null;
  function isoWeek(d) { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day); return Math.ceil(((t - new Date(Date.UTC(t.getUTCFullYear(), 0, 1))) / 86400000 + 1) / 7); }
  function tickClock() {
    if (!root) return;
    const d = new Date();
    setK('clock', d.toLocaleTimeString('de-DE'));
    setK('date', d.toLocaleDateString('en-GB', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase() + ' · KW ' + isoWeek(d));
    if (!ZFMT) ZFMT = ZONES.map(([, tz]) => [new Intl.DateTimeFormat('de-DE', { timeZone: tz, hour: '2-digit', minute: '2-digit' }), new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: false })]);
    K('wc').querySelectorAll('li').forEach((li, i) => {
      li.querySelector('b').textContent = ZFMT[i][0].format(d);
      const h = +ZFMT[i][1].format(d) % 24;
      li.querySelector('i').className = h >= 7 && h < 19 ? '' : 'lh-night';
    });
    if (WX) K('wxFeel').textContent = K('wxFeel').textContent.replace(/ORTSZEIT .*$/, 'ORTSZEIT ' + cityLocalNow());
  }

  // ================================================================ main loop
  let last = 0, fpsN = 0, fpsT = 0;
  function frame(t) {
    if (!root) return;
    SPEED = reduce() ? 0.15 : 1;
    const dt = last ? t - last : 16.7; last = t;
    T.frameMs = lerp(T.frameMs, clamp(dt, 1, 250), 0.08);
    fpsN++; if (!fpsT) fpsT = t; if (t - fpsT >= 500) { T.fps = (fpsN * 1000) / (t - fpsT); fpsN = 0; fpsT = t; }
    voiceLevel += ((typing ? 0.55 + Math.random() * 0.45 : 0) - voiceLevel) * 0.12;
    const st = T.stats || {};
    drawCore(t); drawArmor(t); drawRadar(t); drawGlobe(t); drawWave(t); drawWxIcon(t); drawCompass(t);
    ring('cpuRing', T.cpu, 'LOAD'); ring('memRing', st.ram, 'RAM'); ring('gpuRing', gpuUtil(), gpuInfo() ? 'GPU' : 'GPU EST');
    ring('batRing', st.battery != null ? st.battery : 100, st.battery != null ? 'BATT' : 'ARC', st.battery != null && st.battery < 20 ? C.alert : C.ok);
    drawCpuBars();
    spark('memSpark', HIST.mem, 0, 100, C.holo, { axis: [0, 50, 100], fmt: (v) => v + '%' });
    spark('gpuChart', HIST.gpu, 0, 100, C.amber, { axis: [0, 50, 100], fmt: (v) => v + '%' });
    spark('powSpark', HIST.pow, 3.1, 3.3, C.ok);
    drawNet();
    raf = requestAnimationFrame(frame);
  }

  // ================================================================ open / close
  function open(h) {
    hooks = h || {};
    if (root) return;
    if (!document.getElementById('jarvis-larp-style')) {
      const style = document.createElement('style'); style.id = 'jarvis-larp-style'; style.textContent = CSS; document.head.appendChild(style);
    }
    resetState();
    T.gpuName = detectGpuName();
    wxCity = loadCity();
    root = document.createElement('div');
    // Feste id: claude-app.js blendet alle unbekannten <body>-Kinder aus und
    // nimmt nur bekannte Overlays (darunter #jarvisLarp) davon aus.
    root.id = 'jarvisLarp';
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'JARVIS Command Center');
    root.innerHTML = buildHtml();
    document.body.appendChild(root);
    stage = root.querySelector('.lh-stage');
    const wrap = K('coreWrap');
    NODES.forEach(([id, label]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'lh-node'; b.dataset.node = id; b.setAttribute('aria-label', label);
      b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[id]}</svg><span>${label}</span>`;
      wrap.appendChild(b);
    });
    K('suitList').innerHTML = SUIT.map(([n, v, warn]) => `<li><div class="lh-pw"><span>${n}</span><b style="color:var(${warn ? '--amber' : '--holo-hi'})">${v}%</b></div><div class="lh-bar${warn ? ' lh-warnbar' : ''}"><b style="width:${v}%"></b></div></li>`).join('');
    K('wc').innerHTML = ZONES.map(([n]) => `<li><i></i><span>${n}</span><b>--:--</b></li>`).join('');
    setK('tzLocal', 'LOCAL · ' + (Intl.DateTimeFormat().resolvedOptions().timeZone || 'local').toUpperCase());
    const hex = () => Math.floor(Math.random() * 0xffff).toString(16).toUpperCase().padStart(4, '0');
    K('ticker').textContent = Array.from({ length: 30 }, (_, i) => ['SYNC', 'GRID', 'NODE', 'CORE', 'SAT', 'SERVO', 'FLUX', 'VRAM', 'NET'][i % 9] + ' ' + hex() + '·' + hex() + '  ▸  ').join('');

    root.addEventListener('click', onClick);
    K('ask').addEventListener('submit', onAsk);
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', fitStage);
    fitStage();
    requestAnimationFrame(() => root && root.classList.add('lh-in'));

    tickClock(); every(1000, tickClock);
    pollStats().then(updateReadouts); every(1000, pollStats);
    updateReadouts(); every(250, updateReadouts);
    pollModel(); every(30000, pollModel);
    renderWeather(); loadWeather(); every(600000, loadWeather);
    every(60000, renderWeather);
    const EVENTS = ['Routine-Scan abgeschlossen. Keine Anomalien.', 'Satellitenverbindung neu ausgerichtet.', 'Werkstatt-Klima auf 21 Grad geregelt.',
      'Backup des Rüstungsprotokolls gesichert.', 'Perimeter ruhig.', 'Fertigungsroboter im Standby.'];
    let ev = 0; every(25000, () => { if (!typing && root) addLine('lh-sys', 'SYS', EVENTS[ev++ % EVENTS.length]); });

    addLine('lh-sys', 'SYS', 'MK-OS gebootet · Telemetrie verbunden.');
    say('Systeme hochgefahren. Ich lese Ihre Hardware live aus, Sir.', { instant: true, silent: true });
    timers.push(setTimeout(() => root && say(ANSWERS.status(), { silent: true }), 1500));
    last = 0; fpsT = 0; fpsN = 0;
    raf = requestAnimationFrame(frame);
    const closeBtn = root.querySelector('.lh-close'); if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function close() {
    if (!root) return;
    const el = root;
    root = null; stage = null;
    cancelAnimationFrame(raf); raf = 0;
    timers.forEach((id) => { clearInterval(id); clearTimeout(id); }); timers = [];
    window.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', fitStage);
    queue.length = 0; typing = false;
    el.classList.remove('lh-in');
    setTimeout(() => el.remove(), 320);
    if (hooks.onClose) { try { hooks.onClose(); } catch (e) {} }
  }

  window.JarvisLarp = { open, close, isOpen: () => !!root };
})();
