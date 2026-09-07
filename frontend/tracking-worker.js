// Runs body/hand landmark tracking off the main thread. MediaPipe's own
// docs confirm both the old solutions API (Hands.send()) and the current
// Tasks API's detect()/detectForVideo() run *synchronously and block the
// main thread* — every tracking pass would otherwise freeze the whole page
// (orb, audio meter, the video draw loop) for however long it takes. See:
// https://developers.google.com/mediapipe/solutions/vision/hand_landmarker/web_js
//
// Uses HolisticLandmarker rather than the plain HandLandmarker: it tracks
// pose (33-point body skeleton), left hand, and right hand all from one
// model, in one pass — a single-hand model can't tell "no hand" apart from
// "wrong hand" the way a two-handed one that separately labels left/right
// can, and the pose landmarks are what give shoulders/arms/legs, not just
// the hands. Face landmarks come back too but the caller has no reason to
// draw them (as-is; a face overlay was never wanted here).
//
// This has to be a *classic* worker, not a module one, even though
// @mediapipe/tasks-vision is published ESM-only: the library's own runtime
// calls importScripts() internally (to load its WASM glue code), and
// importScripts() throws inside a module worker ("Module scripts don't
// support importScripts()"). So instead of `import ... from ".../tasks-
// vision"`, this loads a vendored, pre-patched copy of the same package —
// frontend/mediapipe-tasks-vision.js is jsdelivr's `+esm` bundle for
// @mediapipe/tasks-vision@0.10.17 with its trailing `export{...}`
// statement (invalid in a classic script) replaced by a plain
// `self.$mediapipe = {...}` assignment using the same (minified) names.
// See https://ankdev.me/blog/how-to-run-mediapipe-task-vision-in-a-web-worker
// for the reference writeup of this exact workaround.
importScripts("/static/mediapipe-tasks-vision.js");
const { HolisticLandmarker, FilesetResolver } = self.$mediapipe;

const MODEL_URL = "https://storage.googleapis.com/mediapipe-assets/holistic_landmarker.task";
const WASM_ROOT = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.17/wasm";

// A real photo (a person with both hands raised) used only to warm the
// model up before the caller ever gets a "ready" message — see the
// comment on warmUp() below for why this matters. This is MediaPipe's own
// public hand_landmarker demo asset, already fetched from Google's CDN the
// same way the .task model files above are.
const WARMUP_IMAGE_URL = "https://storage.googleapis.com/mediapipe-tasks/hand_landmarker/woman_hands.jpg";

let landmarker = null;
let readyPromise = null;
let activeDelegate = null; // "GPU" or "CPU" — whichever actually initialized

async function createLandmarker(delegate) {
  const vision = await FilesetResolver.forVisionTasks(WASM_ROOT);
  return HolisticLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: MODEL_URL, delegate },
    runningMode: "VIDEO",
    minFaceDetectionConfidence: 0.5,
    minPoseDetectionConfidence: 0.5,
    minHandLandmarksConfidence: 0.5,
  });
}

// MediaPipe/TFLite's GPU delegate compiles its shaders lazily, per code
// path, the first time that path actually runs — not once at model-load
// time. "Pose detected", "hand detected", "hand tracked from last frame"
// are each a different path. A blank/synthetic warmup image never
// triggers most of these (there's nothing in it to detect), so the *real*
// first-ever frame with an actual hand/body in it is the one that pays
// the compile cost — measured live at over a second for that single
// frame, vs. ~70-100ms once warm. Running a few passes over a real photo
// with a visible hand and body *before* signaling ready moves that one-
// time cost out of the user's first few seconds of actually using the
// camera.
async function warmUp() {
  try {
    const blob = await fetch(WARMUP_IMAGE_URL).then((r) => r.blob());
    const bitmap = await createImageBitmap(blob);
    for (let i = 0; i < 3; i++) {
      const warmupBitmap = i === 0 ? bitmap : await createImageBitmap(blob);
      landmarker.detectForVideo(warmupBitmap, i + 1);
      warmupBitmap.close();
    }
  } catch (err) {
    // Not fatal — worst case the first real frame just pays the cost this
    // was meant to avoid.
    console.warn("[tracking-worker] warmup pass failed (non-fatal):", err);
  }
}

function ensureReady() {
  if (!readyPromise) {
    readyPromise = (async () => {
      // GPU vs. CPU delegate is a 10-20x difference for this model (measured:
      // ~50ms/frame on GPU vs. 250-1300ms/frame on CPU) — logged clearly
      // since a silent fallback here is exactly what makes tracking feel
      // broken/laggy for no visible reason.
      try {
        landmarker = await createLandmarker("GPU");
        activeDelegate = "GPU";
      } catch (err) {
        console.warn("[tracking-worker] GPU delegate failed, falling back to CPU (10-20x slower):", err);
        landmarker = await createLandmarker("CPU");
        activeDelegate = "CPU";
      }
      await warmUp();
      console.log(`[tracking-worker] ready, using ${activeDelegate} delegate`);
      self.postMessage({ type: "ready", delegate: activeDelegate });
    })();
  }
  return readyPromise;
}
ensureReady();

self.onmessage = async (e) => {
  const { type, id, bitmap, timestamp } = e.data;
  if (type !== "detect") return;
  try {
    await ensureReady();
    const t0 = performance.now();
    const result = landmarker.detectForVideo(bitmap, timestamp);
    const ms = performance.now() - t0;
    bitmap.close();
    self.postMessage({
      type: "result",
      id,
      ms,
      pose: (result.poseLandmarks && result.poseLandmarks[0]) || null,
      leftHand: (result.leftHandLandmarks && result.leftHandLandmarks[0]) || null,
      rightHand: (result.rightHandLandmarks && result.rightHandLandmarks[0]) || null,
    });
  } catch (err) {
    bitmap.close();
    self.postMessage({ type: "error", id, error: String((err && err.stack) || err) });
  }
};
