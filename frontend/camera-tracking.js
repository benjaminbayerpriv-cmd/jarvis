// JARVIS — Kamera-Panel mit Hand- und Körperskelett-Tracking.
//
// Eigenständiges Modul: claude-app.js baut nur die leere, aufschiebbare
// Seitenleiste (.js-cam-panel) und den Kamera-Button im Composer und ruft
// dann JarvisCamera.mount(panel, …) / .start() / .stop(). Alles andere —
// Kamerazugriff, Kamerawahl, MediaPipe laden, Erkennung, Zeichnen — lebt hier.
//
// Erkennung: MediaPipe Tasks Vision, komplett im Browser (kein Kamerabild
// verlässt den Rechner). HandLandmarker liefert 21 Punkte pro Hand (bis zu 2
// Hände), PoseLandmarker (lite) 33 Körperpunkte, von denen hier nur Rumpf,
// Arme und Beine gezeichnet werden (Gesichtspunkte 0–10 bewusst nicht).
// Bibliothek, WASM und Modelle kommen von jsDelivr/Google (fest gepinnte
// Version, einmalig ~25 MB, danach aus dem Browser-Cache). Ohne Internet läuft
// die Kamera trotzdem, nur ohne Skelett, mit Hinweis und "Erneut versuchen".
//
// Die Erkennung läuft normalerweise in einem eigenen Hintergrund-Thread
// (camera-tracking-worker.js): beide Modelle bei jedem Kamerabild, ohne die
// Oberfläche zu bremsen. Startet der Worker nicht oder fällt er aus, geht es
// automatisch im Haupt-Thread weiter (gedrosselt, Modelle abwechselnd).
// Die Punkte werden zusätzlich geglättet (One-Euro-Filter): ruhig, wenn die
// Hand stillhält, ohne spürbare Verzögerung, wenn sie sich schnell bewegt.
(() => {
  'use strict';

  // Fest gepinnt: ein neues MediaPipe-Release darf die API nicht unbemerkt
  // unter uns wegziehen. Modelle ebenfalls über ihren versionierten Pfad
  // ("/1/"), nicht über "latest".
  const MP_BASE = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35';
  const TASK_CONFIG = {
    hands: {
      className: 'HandLandmarker',
      modelUrl: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
      options: { numHands: 2, minHandDetectionConfidence: 0.5, minHandPresenceConfidence: 0.5, minTrackingConfidence: 0.5 },
    },
    body: {
      className: 'PoseLandmarker',
      modelUrl: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
      options: { numPoses: 1, minPoseDetectionConfidence: 0.5, minPosePresenceConfidence: 0.5, minTrackingConfidence: 0.5 },
    },
  };
  const TASK_KEYS = ['hands', 'body'];

  // Worker-Skript neben diesem Skript, mit demselben ?v=-Build-Stempel
  // (sonst könnte ein Browser eine alte Worker-Version aus dem Cache nehmen).
  const WORKER_URL = (() => {
    try {
      const scriptUrl = new URL(document.currentScript.src);
      const url = new URL('camera-tracking-worker.js', scriptUrl);
      url.search = scriptUrl.search;
      return url.href;
    } catch (e) {
      return '/static/camera-tracking-worker.js';
    }
  })();

  const PREFS_KEY = 'jarvis_camera_prefs';
  const DEFAULT_PREFS = { deviceId: '', hands: true, body: true, mirror: true };
  // Unterhalb dieser Sichtbarkeit rät das Pose-Modell nur (typisch: Beine
  // unter dem Schreibtisch) — solche Punkte/Linien nicht zeichnen.
  const MIN_VISIBILITY = 0.5;
  const HAND_COLORS = ['#4fc3f7', '#ffb74d'];
  const BODY_COLOR = '#81c784';

  // Handskelett: Handgelenk (0), dann je Finger vier Punkte, plus Handfläche.
  const HAND_CONNECTIONS = [
    [0, 1], [1, 2], [2, 3], [3, 4],
    [0, 5], [5, 6], [6, 7], [7, 8],
    [5, 9], [9, 10], [10, 11], [11, 12],
    [9, 13], [13, 14], [14, 15], [15, 16],
    [13, 17], [17, 18], [18, 19], [19, 20],
    [0, 17],
  ];
  // Körperskelett ohne Gesicht: Schultern, Arme (bis Hand), Rumpf, Beine, Füße.
  const BODY_CONNECTIONS = [
    [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
    [15, 17], [15, 19], [15, 21], [17, 19],
    [16, 18], [16, 20], [16, 22], [18, 20],
    [11, 23], [12, 24], [23, 24],
    [23, 25], [25, 27], [27, 29], [29, 31], [27, 31],
    [24, 26], [26, 28], [28, 30], [30, 32], [28, 32],
  ];
  const BODY_POINTS = [...new Set(BODY_CONNECTIONS.flat())];

  // Glättung (One-Euro-Filter, Koordinaten in 0…1): minCutoff bestimmt, wie
  // ruhig ein stillstehender Punkt ist, beta, wie schnell der Filter bei
  // Bewegung "aufmacht". Werte für 30-fps-Kameras abgestimmt.
  const HAND_FILTER = { minCutoff: 1.5, beta: 15 };
  const BODY_FILTER = { minCutoff: 1.0, beta: 10 };
  const DERIVATIVE_CUTOFF = 1.0;
  // Weiter als das darf ein Handgelenk zwischen zwei Bildern nicht springen,
  // um noch als "dieselbe Hand" zu gelten (sonst neue Spur, neuer Filter).
  const HAND_MATCH_DIST = 0.25;

  // ------------------------------------------------------------ Zustand
  let panel = null;          // Container aus claude-app.js
  let els = {};              // Referenzen auf die eigenen Elemente
  let onRequestClose = null;
  let prefs = loadPrefs();

  let active = false;        // soll die Kamera gerade laufen (Panel offen)?
  let session = 0;           // hochgezählt bei jedem start/stop — verwirft veraltete async-Ergebnisse
  let stream = null;
  let frameHandle = null;    // { kind: 'vfc' | 'raf', id }
  let lastTs = 0;
  let fpsSince = 0, fps = 0, fpsWarm = false;
  const fpsCounts = { hands: 0, body: 0 };
  let avgDetectCost = 0;

  // Geglättete, zeichenfertige Ergebnisse:
  //   hands: [{ slot, points: [{x,y}×21] }]   body: [{x,y,visibility}×33]
  let handsState = null, bodyState = null;
  let handTracks = [];       // [{ slot, filters, raw }] — eine Spur pro Hand
  let bodyFilters = [];

  // Wo die Modelle laufen: 'worker' (Standard) oder 'main' (Rückfall).
  let engine = 'worker';
  let worker = null;
  let workerReqId = 0;
  const workerLoads = new Map();   // id -> { resolve, reject }
  let inFlight = null;             // gerade an den Worker geschicktes Bild
  // Antwortet der Worker so lange nicht auf ein Bild, gilt er als hängend.
  // Großzügig, weil der allererste Aufruf je Modell Shader kompiliert.
  const WORKER_STALL_MS = 5000;

  // Rückfall im Haupt-Thread (gemessen auf RTX 4070 Ti SUPER: ~12 ms pro
  // Modell und Bild auf der GPU, ~25 ms auf der CPU): Hand- und
  // Körpermodell laufen abwechselnd, und der Abstand zwischen zwei
  // Durchgängen passt sich den Kosten an — höchstens ~45 % der Zeit fürs
  // Tracking, damit Chat, Terminal und Tippen nicht ruckeln.
  const MIN_DETECT_INTERVAL = 1000 / 30;
  const MAX_DETECT_SHARE = 0.45;
  // Kamerabilder kommen nicht auf die Millisekunde genau — ohne Toleranz
  // fiele bei 30 fps jedes zweite Bild knapp unter das Mindestintervall.
  const FRAME_JITTER_MS = 5;
  let lastDetectAt = 0, nextTask = 'hands';
  let visionPromise = null;
  const mainInstances = { hands: null, body: null };

  // Modelle bleiben über Start/Stop hinweg geladen (Wiederöffnen soll nicht
  // jedes Mal neu initialisieren). ready = im aktuellen engine einsatzbereit.
  const tasks = {
    hands: { ready: false, promise: null, failed: false, forceCpu: false, error: '' },
    body: { ready: false, promise: null, failed: false, forceCpu: false, error: '' },
  };

  function loadPrefs() {
    try {
      const raw = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
      return { ...DEFAULT_PREFS, ...(raw && typeof raw === 'object' ? raw : {}) };
    } catch (e) {
      return { ...DEFAULT_PREFS };
    }
  }

  function savePrefs() {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (e) {}
  }

  // ------------------------------------------------------------ Aufbau
  const SVG_CLOSE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';

  function injectCss() {
    if (document.getElementById('jsCamCss')) return;
    const s = document.createElement('style');
    s.id = 'jsCamCss';
    s.textContent = `
      .jcam { width:100%; height:100%; box-sizing:border-box; display:flex; flex-direction:column; gap:10px; padding:0 12px 12px; font-family:var(--font-anthropic-sans, system-ui, sans-serif); color:var(--jsText); overflow-y:auto; }
      .jcam-head { display:flex; align-items:center; gap:8px; padding:10px 0 4px; cursor:move; user-select:none; }
      .jcam-title { font-size:14px; font-weight:600; flex:1; }
      .jcam-status { display:inline-flex; align-items:center; gap:6px; font-size:11px; color:var(--jsTextDim); }
      .jcam-dot { width:8px; height:8px; border-radius:50%; background:#8a8680; display:inline-block; }
      .jcam-dot.live { background:#4caf50; }
      .jcam-dot.busy { background:#e5a50a; }
      .jcam-dot.err { background:#e5735f; }
      .jcam-close { width:28px; height:28px; border-radius:8px; background:none; border:none; color:var(--jsTextSoft); cursor:pointer; display:inline-flex; align-items:center; justify-content:center; }
      .jcam-close:hover { background:var(--jsBgHover); color:var(--jsText); }
      .jcam-stage { position:relative; width:100%; aspect-ratio:16 / 9; background:#000; border-radius:12px; overflow:hidden; flex:0 0 auto; }
      .jcam-flip { position:absolute; inset:0; }
      .jcam-flip.mirror { transform:scaleX(-1); }
      .jcam-video, .jcam-canvas { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; display:block; }
      .jcam-overlay { position:absolute; inset:0; display:none; flex-direction:column; align-items:center; justify-content:center; gap:10px; padding:16px; text-align:center; font-size:12.5px; line-height:1.5; color:#e8e6df; background:rgba(0,0,0,.55); }
      .jcam-overlay.show { display:flex; }
      .jcam-btn { padding:6px 12px; border:1px solid var(--jsBorder); border-radius:8px; background:var(--jsBgSurface3); color:var(--jsText); font-size:12px; cursor:pointer; font-family:inherit; }
      .jcam-btn:hover { border-color:var(--jsBorderStrong); }
      .jcam-info { font-size:12px; color:var(--jsTextSoft); min-height:16px; }
      .jcam-note { font-size:11.5px; color:#e5a50a; line-height:1.45; }
      .jcam-note:empty { display:none; }
      .jcam-settings { margin-top:auto; display:flex; flex-direction:column; gap:10px; padding-top:12px; border-top:1px solid var(--jsBorder); }
      .jcam-label { font-size:12px; color:var(--jsTextSoft); }
      .jcam-select { width:100%; box-sizing:border-box; padding:8px 10px; background:var(--jsBg); border:1px solid var(--jsBorder); border-radius:8px; color:var(--jsText); font-size:13px; font-family:inherit; outline:none; }
      .jcam-select:disabled { opacity:.55; }
      .jcam-toggles { display:flex; flex-wrap:wrap; gap:6px; }
      .jcam-toggle { padding:6px 11px; border-radius:999px; border:1px solid var(--jsBorder); background:none; color:var(--jsTextSoft); font-size:12px; cursor:pointer; font-family:inherit; }
      .jcam-toggle.on { background:var(--jsAccentTint); border-color:var(--jsAccent); color:var(--jsText); }
      .jcam button:focus-visible, .jcam select:focus-visible { outline:2px solid var(--jsAccent); outline-offset:2px; }
    `;
    document.head.appendChild(s);
  }

  function mount(container, opts = {}) {
    if (!container || panel === container) return;
    injectCss();
    panel = container;
    onRequestClose = typeof opts.onRequestClose === 'function' ? opts.onRequestClose : null;
    panel.innerHTML = `
      <div class="jcam">
        <div class="jcam-head js-camwin-drag">
          <span class="jcam-title">Kamera</span>
          <span class="jcam-status"><span class="jcam-dot"></span><span class="jcam-status-label">aus</span></span>
          <button class="jcam-close" title="Kamera schließen">${SVG_CLOSE}</button>
        </div>
        <div class="jcam-stage">
          <div class="jcam-flip">
            <video class="jcam-video" autoplay muted playsinline></video>
            <canvas class="jcam-canvas"></canvas>
          </div>
          <div class="jcam-overlay">
            <span class="jcam-overlay-text"></span>
            <button class="jcam-btn jcam-retry" style="display:none;">Erneut versuchen</button>
          </div>
        </div>
        <div class="jcam-info"></div>
        <div class="jcam-note"></div>
        <div class="jcam-settings">
          <label class="jcam-label" for="jcamDevice">Kamera</label>
          <select class="jcam-select" id="jcamDevice"><option value="">Standardkamera</option></select>
          <div class="jcam-label">Anzeige</div>
          <div class="jcam-toggles">
            <button class="jcam-toggle" data-pref="hands" title="Handskelett (21 Punkte pro Hand) ein/aus">Hände</button>
            <button class="jcam-toggle" data-pref="body" title="Körperskelett (Arme, Rumpf, Beine) ein/aus">Körper</button>
            <button class="jcam-toggle" data-pref="mirror" title="Bild spiegeln wie in einem Spiegel">Spiegeln</button>
          </div>
        </div>
      </div>
    `;
    const q = (s) => panel.querySelector(s);
    els = {
      dot: q('.jcam-dot'), statusLabel: q('.jcam-status-label'), close: q('.jcam-close'),
      stage: q('.jcam-stage'), flip: q('.jcam-flip'), video: q('.jcam-video'), canvas: q('.jcam-canvas'),
      overlay: q('.jcam-overlay'), overlayText: q('.jcam-overlay-text'), retry: q('.jcam-retry'),
      info: q('.jcam-info'), note: q('.jcam-note'), device: q('.jcam-select'),
      toggles: panel.querySelectorAll('.jcam-toggle'),
    };
    els.ctx = els.canvas.getContext('2d');

    els.close.addEventListener('click', () => { if (onRequestClose) onRequestClose(); else stop(); });
    els.retry.addEventListener('click', () => {
      resetFailedTasks();
      start();
    });
    els.device.addEventListener('change', () => {
      prefs.deviceId = els.device.value;
      savePrefs();
      if (active) start();
    });
    els.toggles.forEach((btn) => btn.addEventListener('click', () => {
      const key = btn.dataset.pref;
      prefs[key] = !prefs[key];
      savePrefs();
      applyPrefsToUi();
      // Beim Ausschalten das letzte Ergebnis samt Glättung verwerfen, damit
      // beim Wiedereinschalten kein veraltetes Skelett kurz aufblitzt.
      if (key === 'hands' && !prefs.hands) resetSmoothing('hands');
      if (key === 'body' && !prefs.body) resetSmoothing('body');
      if (active && (key === 'hands' || key === 'body') && prefs[key]) ensureTask(key);
      render();
      updateNote();
    }));
    if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
      navigator.mediaDevices.addEventListener('devicechange', () => { if (active) refreshDevices(); });
    }
    applyPrefsToUi();
  }

  function applyPrefsToUi() {
    if (!panel) return;
    els.toggles.forEach((btn) => {
      const on = !!prefs[btn.dataset.pref];
      btn.classList.toggle('on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    els.flip.classList.toggle('mirror', !!prefs.mirror);
  }

  // ------------------------------------------------------------ Statusanzeige
  function setStatus(kind, label) {
    if (!panel) return;
    els.dot.className = 'jcam-dot' + (kind ? ' ' + kind : '');
    els.statusLabel.textContent = label;
  }

  // Bei laufender Kamera: "lädt Modelle…" solange noch ein Modell lädt, sonst "live".
  function refreshLiveStatus() {
    if (!panel || !active || !stream) return;
    if (tasks.hands.promise || tasks.body.promise) setStatus('busy', 'lädt Modelle…');
    else setStatus('live', 'live');
  }

  function resetFailedTasks() {
    for (const t of Object.values(tasks)) {
      if (t.ready || t.promise) continue;
      t.failed = false;
      t.error = '';
      t.forceCpu = false;
    }
    // Ist gerade gar nichts geladen oder im Laden, darf ein neuer Versuch
    // auch wieder mit dem Worker beginnen (z. B. war er nur offline gescheitert).
    if (TASK_KEYS.every((k) => !tasks[k].ready && !tasks[k].promise)) engine = 'worker';
  }

  function showOverlay(text, withRetry = false) {
    if (!panel) return;
    els.overlayText.textContent = text;
    els.retry.style.display = withRetry ? '' : 'none';
    els.overlay.classList.add('show');
  }

  function hideOverlay() {
    if (panel) els.overlay.classList.remove('show');
  }

  function updateNote() {
    if (!panel) return;
    const notes = [];
    for (const [key, label] of [['hands', 'Handtracking'], ['body', 'Körpertracking']]) {
      const t = tasks[key];
      if (prefs[key] && t.failed) notes.push(`${label} konnte nicht geladen werden${t.error ? ` (${t.error})` : ''}.`);
    }
    if (notes.length) notes.push('Das Kamerabild läuft trotzdem. Ohne Internetverbindung lassen sich die Modelle beim ersten Mal nicht laden.');
    els.note.textContent = notes.join(' ');
    // Retry-Knopf auch ohne Overlay erreichbar machen: bei reinem Modellfehler
    // bleibt das Kamerabild sichtbar, also den Knopf unter den Hinweis setzen.
    if (notes.length && !els.overlay.classList.contains('show')) {
      const btn = document.createElement('button');
      btn.className = 'jcam-btn';
      btn.textContent = 'Modelle erneut laden';
      btn.style.marginLeft = '6px';
      btn.addEventListener('click', () => {
        resetFailedTasks();
        updateNote();
        if (active) {
          if (prefs.hands) ensureTask('hands');
          if (prefs.body) ensureTask('body');
          refreshLiveStatus();
        }
      });
      els.note.appendChild(btn);
    }
  }

  function cameraErrorText(err) {
    const name = err && err.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'Kamerazugriff wurde verweigert. Erlaube die Kamera für diese Seite (Schloss-Symbol in der Adressleiste bzw. Windows-Einstellungen → Datenschutz → Kamera) und versuch es erneut.';
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'Keine Kamera gefunden. Schließ eine Kamera an und versuch es erneut.';
    if (name === 'NotReadableError' || name === 'TrackStartError') return 'Die Kamera wird gerade von einem anderen Programm benutzt (z. B. Teams, Zoom, OBS). Schließ es und versuch es erneut.';
    if (name === 'OverconstrainedError') return 'Die gewählte Kamera unterstützt die angeforderten Einstellungen nicht.';
    return `Kamera konnte nicht gestartet werden${err && err.message ? `: ${err.message}` : '.'}`;
  }

  // ------------------------------------------------------------ Kamera
  async function openStream(deviceId) {
    const base = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } };
    const video = deviceId ? { ...base, deviceId: { exact: deviceId } } : base;
    try {
      return await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch (err) {
      // Gemerkte Kamera nicht mehr da (abgesteckt, andere ID nach Neustart):
      // still auf die Standardkamera zurückfallen statt hängen zu bleiben.
      if (deviceId && (err.name === 'OverconstrainedError' || err.name === 'NotFoundError')) {
        prefs.deviceId = '';
        savePrefs();
        return navigator.mediaDevices.getUserMedia({ video: base, audio: false });
      }
      throw err;
    }
  }

  function releaseStream() {
    cancelFrameLoop();
    // Ein noch unterwegs befindliches Bild gehört zur alten Sitzung — seine
    // Antwort wird über die geänderte Anfrage-ID verworfen.
    inFlight = null;
    // Kein altes Skelett über ein neues Kamerabild legen.
    resetSmoothing('hands');
    resetSmoothing('body');
    lastDetectAt = 0;
    fps = 0;
    if (stream) {
      for (const track of stream.getTracks()) {
        track.onended = null;
        try { track.stop(); } catch (e) {}
      }
      stream = null;
    }
    if (panel) {
      try { els.video.pause(); } catch (e) {}
      els.video.srcObject = null;
      clearCanvas();
      els.info.textContent = '';
    }
  }

  async function refreshDevices() {
    if (!panel || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    let devices = [];
    try {
      devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
    } catch (e) {
      return;
    }
    const currentId = stream && stream.getVideoTracks()[0] && stream.getVideoTracks()[0].getSettings().deviceId;
    const wanted = prefs.deviceId || currentId || '';
    els.device.innerHTML = '';
    const def = document.createElement('option');
    def.value = '';
    def.textContent = 'Standardkamera';
    els.device.appendChild(def);
    devices.forEach((d, i) => {
      if (!d.deviceId) return; // ohne Berechtigung liefert der Browser leere IDs
      const opt = document.createElement('option');
      opt.value = d.deviceId;
      opt.textContent = d.label || `Kamera ${i + 1}`;
      els.device.appendChild(opt);
    });
    els.device.value = [...els.device.options].some((o) => o.value === wanted) ? wanted : '';
    els.device.disabled = devices.length === 0;
  }

  async function start() {
    if (!panel) return;
    active = true;
    const my = ++session;
    releaseStream();

    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('err', 'nicht verfügbar');
      showOverlay('Der Browser erlaubt hier keinen Kamerazugriff. Öffne Jarvis über http://127.0.0.1:8000 bzw. http://localhost:8000 oder im Jarvis-App-Fenster.');
      return;
    }

    setStatus('busy', 'startet…');
    showOverlay('Kamera wird gestartet…');
    // Modelle parallel zur Kamera laden — das Bild erscheint sofort, das
    // Skelett, sobald die Modelle bereit sind.
    if (prefs.hands) ensureTask('hands');
    if (prefs.body) ensureTask('body');

    let s;
    try {
      s = await openStream(prefs.deviceId);
    } catch (err) {
      if (my !== session) return;
      setStatus('err', 'Fehler');
      showOverlay(cameraErrorText(err), true);
      refreshDevices();
      return;
    }
    // Panel wurde inzwischen geschlossen oder neu gestartet: diesen Stream
    // sofort wieder freigeben, sonst bliebe die Kamera-LED an.
    if (my !== session) {
      s.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} });
      return;
    }
    stream = s;
    const track = stream.getVideoTracks()[0];
    if (track) {
      track.onended = () => {
        if (my !== session) return;
        releaseStream();
        setStatus('err', 'getrennt');
        showOverlay('Die Kamera wurde getrennt.', true);
        refreshDevices();
      };
    }

    els.video.srcObject = stream;
    try {
      await els.video.play();
    } catch (err) {
      // play() wird bei einem schnellen Stop/Start mit AbortError abgebrochen —
      // das ist dann kein echter Fehler, der neue Durchlauf übernimmt.
      if (my !== session) return;
      if (err && err.name !== 'AbortError') {
        setStatus('err', 'Fehler');
        showOverlay(cameraErrorText(err), true);
        return;
      }
    }
    if (my !== session) return;
    await waitForVideoSize(my);
    if (my !== session) return;

    const vw = els.video.videoWidth || 16, vh = els.video.videoHeight || 9;
    els.stage.style.aspectRatio = `${vw} / ${vh}`;
    els.canvas.width = vw;
    els.canvas.height = vh;
    hideOverlay();
    refreshLiveStatus();
    refreshDevices();
    updateNote();
    fpsCounts.hands = 0; fpsCounts.body = 0; fpsSince = performance.now(); fps = 0; fpsWarm = false;
    scheduleFrame(my);
  }

  function waitForVideoSize(my) {
    if (els.video.videoWidth > 0) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => { els.video.removeEventListener('loadedmetadata', done); clearTimeout(timer); resolve(); };
      const timer = setTimeout(done, 3000);
      els.video.addEventListener('loadedmetadata', done);
      if (my !== session) done();
    });
  }

  function stop() {
    active = false;
    session++;
    releaseStream();
    setStatus('', 'aus');
    hideOverlay();
  }

  // ------------------------------------------------------------ Modelle laden
  function ensureTask(key) {
    const t = tasks[key];
    if (t.ready || t.promise || t.failed) return;
    t.promise = loadTask(key)
      .then(() => { t.ready = true; t.error = ''; })
      .catch((err) => {
        t.failed = true;
        t.error = shortError(err);
        console.warn(`[camera] ${key}-Modell konnte nicht geladen werden:`, err);
      })
      .finally(() => {
        t.promise = null;
        // Bewusst nicht an eine Sitzung gebunden: Modelle überleben ein
        // Zu-/Aufklappen, und ein in einer früheren Sitzung gestarteter
        // Ladevorgang muss die Anzeige der aktuellen trotzdem auf "live"
        // bringen — sonst bliebe sie auf "lädt Modelle…" hängen.
        if (!panel || !active) return;
        updateNote();
        refreshLiveStatus();
      });
    refreshLiveStatus();
  }

  async function loadTask(key) {
    if (engine === 'worker') {
      try {
        await workerLoad(key);
        return;
      } catch (err) {
        // Worker unbrauchbar (startet nicht, Modell lädt dort nicht, …):
        // für diese Seitensitzung komplett auf den Haupt-Thread umschalten.
        switchToMainThread(err);
      }
    }
    mainInstances[key] = await createMainTask(key);
  }

  function shortError(err) {
    const msg = String((err && err.message) || err || '').trim();
    if (/fetch|network|load/i.test(msg)) return 'keine Verbindung';
    return msg.length > 80 ? msg.slice(0, 77) + '…' : msg;
  }

  // Ein Modell ist beim Erkennen ausgefallen (z. B. WebGL-Kontext verloren):
  // einmal auf CPU neu aufbauen, beim zweiten Mal als fehlgeschlagen melden,
  // statt jedes Bild erneut in denselben Fehler zu laufen.
  function dropTask(key, err) {
    const t = tasks[key];
    console.warn(`[camera] ${key}-Tracking abgebrochen:`, err);
    const inst = mainInstances[key];
    mainInstances[key] = null;
    if (inst) {
      try { inst.close(); } catch (e) {}
    }
    t.ready = false;
    resetSmoothing(key);
    if (t.forceCpu) {
      t.failed = true;
      t.error = shortError(err);
      updateNote();
    } else {
      t.forceCpu = true;
      ensureTask(key);
    }
  }

  // --- Worker
  function getWorker() {
    if (worker) return worker;
    const w = new Worker(WORKER_URL, { type: 'module' });
    w.onmessage = (event) => onWorkerMessage(w, event.data || {});
    w.onerror = (event) => {
      if (event && event.preventDefault) event.preventDefault();
      if (w === worker) switchToMainThread(new Error((event && event.message) || 'Tracking-Worker ist abgestürzt'));
    };
    w.onmessageerror = () => {
      if (w === worker) switchToMainThread(new Error('Tracking-Worker: Nachricht nicht lesbar'));
    };
    worker = w;
    return w;
  }

  function workerLoad(key) {
    return new Promise((resolve, reject) => {
      let w;
      try {
        w = getWorker();
      } catch (err) {
        reject(err);
        return;
      }
      const id = ++workerReqId;
      workerLoads.set(id, { resolve, reject });
      w.postMessage({ type: 'load', id, key, base: MP_BASE, config: TASK_CONFIG[key], forceCpu: tasks[key].forceCpu });
    });
  }

  function onWorkerMessage(w, msg) {
    if (w !== worker) return;
    if (msg.type === 'loaded') {
      const pending = workerLoads.get(msg.id);
      if (!pending) return;
      workerLoads.delete(msg.id);
      if (msg.ok) pending.resolve();
      else pending.reject(new Error(msg.error || 'Modell konnte im Worker nicht geladen werden'));
    } else if (msg.type === 'result') {
      onWorkerResult(msg);
    } else if (msg.type === 'fatal') {
      switchToMainThread(new Error(msg.error || 'Tracking-Worker-Fehler'));
    }
  }

  // Worker verwerfen und alles Weitere im Haupt-Thread erledigen. Modelle, die
  // im Worker schon bereit waren, werden dort neu geladen.
  function switchToMainThread(err) {
    if (engine !== 'worker') return;
    console.warn('[camera] Tracking läuft ab jetzt im Haupt-Thread:', err);
    engine = 'main';
    const w = worker;
    worker = null;
    inFlight = null;
    if (w) {
      try { w.terminate(); } catch (e) {}
    }
    for (const pending of workerLoads.values()) pending.reject(err);
    workerLoads.clear();
    for (const key of TASK_KEYS) {
      if (tasks[key].ready) {
        tasks[key].ready = false;
        ensureTask(key);
      }
    }
  }

  // --- Haupt-Thread (Rückfall)
  function loadVision() {
    if (!visionPromise) {
      visionPromise = (async () => {
        const mod = await import(`${MP_BASE}/vision_bundle.mjs`);
        const fileset = await mod.FilesetResolver.forVisionTasks(`${MP_BASE}/wasm`);
        return { mod, fileset };
      })();
      // Bei Fehlschlag (offline) nicht für immer den kaputten Promise cachen.
      visionPromise.catch(() => { visionPromise = null; });
    }
    return visionPromise;
  }

  async function createMainTask(key) {
    const { mod, fileset } = await loadVision();
    const config = TASK_CONFIG[key];
    const Cls = mod[config.className];
    // GPU zuerst (deutlich schneller), CPU als Rückfall — z. B. wenn WebGL
    // im eingebetteten Fenster nicht verfügbar ist.
    const delegates = tasks[key].forceCpu ? ['CPU'] : ['GPU', 'CPU'];
    let lastErr = null;
    for (const delegate of delegates) {
      try {
        return await Cls.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: config.modelUrl, delegate },
          runningMode: 'VIDEO',
          ...config.options,
        });
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error('unbekannter Fehler');
  }

  // ------------------------------------------------------------ Bildschleife
  function scheduleFrame(my) {
    if (my !== session || !stream) return;
    const video = els.video;
    // requestVideoFrameCallback feuert genau einmal pro neuem Kamerabild —
    // kein doppeltes Erkennen desselben Bilds bei 60/120-Hz-Monitoren.
    if (typeof video.requestVideoFrameCallback === 'function') {
      frameHandle = { kind: 'vfc', id: video.requestVideoFrameCallback(() => onFrame(my)) };
    } else {
      frameHandle = { kind: 'raf', id: requestAnimationFrame(() => onFrame(my)) };
    }
  }

  function cancelFrameLoop() {
    if (!frameHandle) return;
    try {
      if (frameHandle.kind === 'vfc') els.video.cancelVideoFrameCallback(frameHandle.id);
      else cancelAnimationFrame(frameHandle.id);
    } catch (e) {}
    frameHandle = null;
  }

  // MediaPipe verlangt im VIDEO-Modus streng steigende Zeitstempel.
  function nextTimestamp() {
    let ts = performance.now();
    if (ts <= lastTs) ts = lastTs + 1;
    lastTs = ts;
    return ts;
  }

  function enabledReadyKeys() {
    return TASK_KEYS.filter((k) => prefs[k] && tasks[k].ready);
  }

  function onFrame(my) {
    frameHandle = null;
    if (my !== session || !stream) return;
    const video = els.video;
    if (video.readyState >= 2 && video.videoWidth > 0) {
      if (els.canvas.width !== video.videoWidth || els.canvas.height !== video.videoHeight) {
        els.canvas.width = video.videoWidth;
        els.canvas.height = video.videoHeight;
        els.stage.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
      }
      if (engine === 'worker') submitToWorker(my, video);
      else detectOnMainThread(video);
      if (my !== session) return;
      render();
    }
    scheduleFrame(my);
  }

  // Worker-Weg: immer nur ein Bild gleichzeitig unterwegs. Ist der Worker
  // noch beschäftigt, wird dieses Kamerabild ausgelassen (kein Rückstau,
  // das Skelett hinkt nie hinterher).
  function submitToWorker(my, video) {
    const keys = enabledReadyKeys();
    if (!keys.length || !worker) return;
    if (inFlight) {
      if (performance.now() - inFlight.sentAt > WORKER_STALL_MS) {
        switchToMainThread(new Error('Tracking-Worker antwortet nicht mehr'));
      }
      return;
    }
    const req = { id: ++workerReqId, sentAt: performance.now(), session: my, keys };
    const ts = nextTimestamp();
    inFlight = req;
    createImageBitmap(video).then((bitmap) => {
      if (inFlight !== req || my !== session || !worker) {
        bitmap.close();
        if (inFlight === req) inFlight = null;
        return;
      }
      worker.postMessage({ type: 'detect', id: req.id, bitmap, ts, keys }, [bitmap]);
    }).catch(() => {
      if (inFlight === req) inFlight = null;
    });
  }

  function onWorkerResult(msg) {
    if (!inFlight || msg.id !== inFlight.id) return; // veraltet (Sitzung gewechselt)
    const req = inFlight;
    inFlight = null;
    if (req.session !== session || !stream) return;
    for (const key of Object.keys(msg.errors || {})) dropTask(key, new Error(msg.errors[key]));
    const updated = [];
    if (req.keys.includes('hands') && !(msg.errors && msg.errors.hands) && prefs.hands) {
      applyHands(msg.hands || [], msg.ts);
      updated.push('hands');
    }
    if (req.keys.includes('body') && !(msg.errors && msg.errors.body) && prefs.body) {
      applyBody(msg.body || [], msg.ts);
      updated.push('body');
    }
    if (typeof msg.cost === 'number' && msg.cost < 250) {
      avgDetectCost = avgDetectCost ? avgDetectCost * 0.8 + msg.cost * 0.2 : msg.cost;
    }
    countUpdates(updated);
    render();
  }

  // Haupt-Thread-Weg: gedrosselt, Modelle abwechselnd (siehe oben).
  function detectOnMainThread(video) {
    const now = performance.now();
    const interval = Math.max(MIN_DETECT_INTERVAL, avgDetectCost / MAX_DETECT_SHARE);
    if (now - lastDetectAt < interval - FRAME_JITTER_MS) return;
    const key = pickTask();
    if (!key || !mainInstances[key]) return;
    const ts = nextTimestamp();
    try {
      const r = mainInstances[key].detectForVideo(video, ts);
      if (key === 'hands') {
        applyHands((r.landmarks || []).map((pts) => ({ points: pts })), ts);
      } else {
        applyBody((r.landmarks && r.landmarks[0]) || [], ts);
      }
      countUpdates([key]);
    } catch (err) {
      dropTask(key, err);
    }
    const cost = performance.now() - now;
    // Der erste Aufruf eines Modells ist Aufwärmen (gemessen ~300 ms) —
    // nicht in den Mittelwert, sonst bremst er die ersten Sekunden aus.
    if (cost < 250) avgDetectCost = avgDetectCost ? avgDetectCost * 0.8 + cost * 0.2 : cost;
    // Vom Start des Durchgangs aus messen (nicht vom Ende), sonst
    // verschluckt die Rechenzeit selbst bei 30 fps jedes zweite Bild.
    lastDetectAt = now;
  }

  // Welches Modell ist im Haupt-Thread dran? Abwechselnd, soweit beide
  // eingeschaltet und geladen sind; sonst das eine, das bereit ist.
  function pickTask() {
    const ready = (k) => prefs[k] && tasks[k].ready && mainInstances[k];
    const other = nextTask === 'hands' ? 'body' : 'hands';
    const key = ready(nextTask) ? nextTask : (ready(other) ? other : null);
    if (key) nextTask = key === 'hands' ? 'body' : 'hands';
    return key;
  }

  // ------------------------------------------------------------ Glättung
  function oneEuro(f, value, t, cfg) {
    if (f.x === null) {
      f.x = value;
      f.dx = 0;
      f.t = t;
      return value;
    }
    const dt = Math.max(0.001, (t - f.t) / 1000);
    f.t = t;
    const alpha = (cutoff) => 1 / (1 + 1 / (2 * Math.PI * cutoff * dt));
    f.dx += alpha(DERIVATIVE_CUTOFF) * ((value - f.x) / dt - f.dx);
    f.x += alpha(cfg.minCutoff + cfg.beta * Math.abs(f.dx)) * (value - f.x);
    return f.x;
  }

  function smoothPoints(filters, points, t, cfg) {
    return points.map((p, i) => {
      if (!filters[i]) filters[i] = { x: { x: null, dx: 0, t: 0 }, y: { x: null, dx: 0, t: 0 } };
      const out = { x: oneEuro(filters[i].x, p.x, t, cfg), y: oneEuro(filters[i].y, p.y, t, cfg) };
      if (p.visibility !== undefined) out.visibility = p.visibility;
      return out;
    });
  }

  // Jede erkannte Hand der Spur zuordnen, deren Handgelenk im letzten Bild
  // am nächsten lag. So behält jede Hand ihren eigenen Filter und ihre
  // Farbe, auch wenn MediaPipe die Reihenfolge der Hände vertauscht.
  function applyHands(rawHands, t) {
    const matched = new Array(rawHands.length).fill(null);
    const used = new Set();
    rawHands.forEach((h, i) => {
      const w = h.points && h.points[0];
      if (!w) return;
      let best = null, bestD = HAND_MATCH_DIST;
      for (const tr of handTracks) {
        if (used.has(tr)) continue;
        const d = Math.hypot(tr.raw.x - w.x, tr.raw.y - w.y);
        if (d < bestD) { bestD = d; best = tr; }
      }
      if (best) { used.add(best); matched[i] = best; }
    });
    const takenSlots = new Set([...used].map((tr) => tr.slot));
    const next = [];
    const out = [];
    rawHands.forEach((h, i) => {
      if (!h.points || !h.points.length) return;
      let tr = matched[i];
      if (!tr) {
        let slot = 0;
        while (takenSlots.has(slot)) slot++;
        takenSlots.add(slot);
        tr = { slot, filters: [], raw: null };
      }
      tr.raw = { x: h.points[0].x, y: h.points[0].y };
      next.push(tr);
      out.push({ slot: tr.slot, points: smoothPoints(tr.filters, h.points, t, HAND_FILTER) });
    });
    handTracks = next;
    handsState = out;
  }

  function applyBody(points, t) {
    if (!points || !points.length) {
      bodyFilters = [];
      bodyState = [];
      return;
    }
    bodyState = smoothPoints(bodyFilters, points, t, BODY_FILTER);
  }

  function resetSmoothing(key) {
    if (key === 'hands') {
      handTracks = [];
      handsState = null;
    } else {
      bodyFilters = [];
      bodyState = null;
    }
  }

  // ------------------------------------------------------------ Zeichnen
  function clearCanvas() {
    if (els.ctx) els.ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
  }

  function render() {
    if (!panel) return;
    if (!stream) {
      clearCanvas();
      return;
    }
    const hands = prefs.hands ? handsState : null;
    const body = prefs.body ? bodyState : null;
    draw(hands, body);
    updateInfo(hands, body);
  }

  function draw(hands, body) {
    const ctx = els.ctx;
    const w = els.canvas.width, h = els.canvas.height;
    ctx.clearRect(0, 0, w, h);
    const unit = Math.max(1.5, w / 400);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (body && body.length) {
      const seen = (i) => body[i] && (body[i].visibility === undefined || body[i].visibility >= MIN_VISIBILITY);
      ctx.strokeStyle = BODY_COLOR;
      ctx.lineWidth = unit * 2.2;
      ctx.beginPath();
      for (const [a, b] of BODY_CONNECTIONS) {
        if (!seen(a) || !seen(b)) continue;
        ctx.moveTo(body[a].x * w, body[a].y * h);
        ctx.lineTo(body[b].x * w, body[b].y * h);
      }
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      for (const i of BODY_POINTS) {
        if (!seen(i)) continue;
        ctx.beginPath();
        ctx.arc(body[i].x * w, body[i].y * h, unit * 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    for (const hand of hands || []) {
      const pts = hand.points;
      const color = HAND_COLORS[hand.slot % HAND_COLORS.length];
      ctx.strokeStyle = color;
      ctx.lineWidth = unit * 1.6;
      ctx.beginPath();
      for (const [a, b] of HAND_CONNECTIONS) {
        if (!pts[a] || !pts[b]) continue;
        ctx.moveTo(pts[a].x * w, pts[a].y * h);
        ctx.lineTo(pts[b].x * w, pts[b].y * h);
      }
      ctx.stroke();
      ctx.fillStyle = color;
      for (const p of pts) {
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, unit * 1.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  // Skelett-Aktualisierungen pro Sekunde. Pro Modell getrennt gezählt und
  // das schnellere angezeigt — so stimmt die Zahl auch in der Sekunde, in
  // der ein Modell ein-/ausgeschaltet wird oder fertig lädt (im Worker laufen
  // beide pro Bild, im Haupt-Thread abwechselnd).
  function countUpdates(keys) {
    if (!keys.length) return;
    for (const k of keys) fpsCounts[k]++;
    const now = performance.now();
    const elapsed = now - fpsSince;
    if (elapsed >= 1000) {
      // Die erste Messsekunde enthält das Aufwärmen der Modelle (~300 ms je
      // Modell, im Worker mit GPU-Shadern auch über 1 s) und würde eine viel
      // zu niedrige Rate anzeigen — verwerfen. Ebenso ein Fenster, in dem die
      // Erkennung zwischendurch stand (> 2 s statt ~1 s).
      if (fpsWarm && elapsed <= 2000) fps = Math.round((Math.max(fpsCounts.hands, fpsCounts.body) * 1000) / elapsed);
      fpsWarm = true;
      fpsCounts.hands = 0;
      fpsCounts.body = 0;
      fpsSince = now;
    }
  }

  function updateInfo(hands, body) {
    const parts = [];
    if (prefs.hands) {
      parts.push(tasks.hands.ready ? `Hände: ${hands ? hands.length : 0}` : (tasks.hands.failed ? 'Hände: –' : 'Hände: lädt…'));
    }
    if (prefs.body) {
      parts.push(tasks.body.ready ? `Körper: ${body && body.length ? 'erkannt' : '–'}` : (tasks.body.failed ? 'Körper: –' : 'Körper: lädt…'));
    }
    if (fps && enabledReadyKeys().length) parts.push(`${fps} Updates/s`);
    const text = parts.join(' · ');
    if (els.info.textContent !== text) els.info.textContent = text;
  }

  const taskState = (t) => (t.ready ? 'bereit' : (t.failed ? `fehlgeschlagen: ${t.error}` : (t.promise ? 'lädt' : 'aus')));

  window.JarvisCamera = {
    mount,
    start,
    stop,
    isActive: () => active,
    // Zur Fehlersuche in der Browser-Konsole: JarvisCamera.stats()
    stats: () => ({
      active,
      engine: engine === 'worker' ? 'Hintergrund-Thread' : 'Haupt-Thread',
      avgDetectCostMs: Math.round(avgDetectCost * 10) / 10,
      updatesPerSecond: fps,
      hands: taskState(tasks.hands),
      body: taskState(tasks.body),
    }),
  };
})();
