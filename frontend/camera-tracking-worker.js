// JARVIS — Hintergrund-Thread (Module-Worker) für das Kamera-Tracking.
//
// Nimmt vom Haupt-Thread (camera-tracking.js) einzelne Kamerabilder als
// ImageBitmap entgegen, lässt Hand- und Körpermodell darauf laufen und schickt
// nur die Landmark-Koordinaten zurück. So blockiert die Erkennung (~20–25 ms
// pro Bild für beide Modelle) nie die Oberfläche, und beide Modelle können
// bei jedem Kamerabild laufen statt sich abzuwechseln.
//
// Wichtig: MediaPipe muss hier mit useModule=true geladen werden
// (FilesetResolver.forVisionTasks(…, true)). Die normale WASM-Variante wird
// per importScripts() geladen, und das gibt es in Module-Workern nicht; die
// "_module_"-Variante ist ein ES-Modul und wird stattdessen per import()
// geladen.

let mod = null;
let fileset = null;
const instances = { hands: null, body: null };

// Nachrichten strikt nacheinander abarbeiten — ein "detect" darf nie
// zwischen die awaits eines noch laufenden "load" rutschen.
let queue = Promise.resolve();
self.onmessage = (event) => {
  const msg = event.data || {};
  queue = queue.then(() => handle(msg)).catch((err) => {
    // handle() fängt seine Fehler selbst ab; das hier ist nur das Netz
    // darunter, damit die Kette nie dauerhaft abreißt.
    self.postMessage({ type: 'fatal', error: errorText(err) });
  });
};

async function handle(msg) {
  if (msg.type === 'load') return load(msg);
  if (msg.type === 'detect') return detect(msg);
  if (msg.type === 'unload') return unload(msg.key);
}

async function load({ id, key, base, config, forceCpu }) {
  try {
    if (!mod) mod = await import(`${base}/vision_bundle.mjs`);
    if (!fileset) fileset = await mod.FilesetResolver.forVisionTasks(`${base}/wasm`, true);
    unload(key);
    const Cls = mod[config.className];
    if (!Cls) throw new Error(`${config.className} fehlt in MediaPipe`);
    const delegates = forceCpu ? ['CPU'] : ['GPU', 'CPU'];
    let lastErr = null;
    for (const delegate of delegates) {
      try {
        await provideModuleFactory();
        instances[key] = await Cls.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: config.modelUrl, delegate },
          runningMode: 'VIDEO',
          ...config.options,
        });
        self.postMessage({ type: 'loaded', id, key, ok: true, delegate });
        return;
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error('unbekannter Fehler');
  } catch (err) {
    self.postMessage({ type: 'loaded', id, key, ok: false, error: errorText(err) });
  }
}

// MediaPipe löscht nach jedem erzeugten Modell self.ModuleFactory wieder
// (`self.ModuleFactory = self.Module = void 0`) und verlässt sich darauf,
// dass das erneute Laden des WASM-Loaders es neu setzt. Mit importScripts()
// stimmt das; ein ES-Modul führt der Browser aber nur beim ersten import()
// aus — ab dem zweiten Modell hieße es sonst "ModuleFactory not set".
// Deshalb vor jedem Erzeugen selbst aus dem (gecachten) Modul nachsetzen.
async function provideModuleFactory() {
  const loader = await import(fileset.wasmLoaderPath);
  const factory = loader.default || globalThis.ModuleFactory;
  if (typeof factory !== 'function') throw new Error('MediaPipe-WASM-Loader liefert keine ModuleFactory');
  self.ModuleFactory = factory;
}

function unload(key) {
  const inst = instances[key];
  instances[key] = null;
  if (inst) {
    try { inst.close(); } catch (e) {}
  }
}

function detect({ id, bitmap, ts, keys }) {
  const out = { type: 'result', id, ts, hands: null, body: null, errors: {} };
  const started = performance.now();
  try {
    for (const key of keys || []) {
      const inst = instances[key];
      if (!inst) continue;
      try {
        const r = inst.detectForVideo(bitmap, ts);
        if (key === 'hands') {
          out.hands = (r.landmarks || []).map((pts, i) => ({
            points: pts.map((p) => ({ x: p.x, y: p.y })),
            handedness: r.handedness && r.handedness[i] && r.handedness[i][0] ? r.handedness[i][0].categoryName : '',
          }));
        } else {
          const pts = r.landmarks && r.landmarks[0];
          out.body = pts ? pts.map((p) => ({ x: p.x, y: p.y, visibility: p.visibility })) : [];
        }
      } catch (err) {
        // Dieses Modell ist kaputt (z. B. WebGL-Kontext verloren): freigeben
        // und dem Haupt-Thread melden, der entscheidet über Neuladen.
        unload(key);
        out.errors[key] = errorText(err);
      }
    }
  } finally {
    try { bitmap && bitmap.close(); } catch (e) {}
  }
  out.cost = performance.now() - started;
  self.postMessage(out);
}

function errorText(err) {
  return String((err && err.message) || err || 'unbekannter Fehler');
}
