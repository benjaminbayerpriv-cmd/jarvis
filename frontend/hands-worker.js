// Runs hand landmark tracking off the main thread, for the same reason
// detect-worker.js exists: MediaPipe's own docs confirm both the old
// solutions API (Hands.send()) and the current Tasks API's detect() /
// detectForVideo() run *synchronously and block the main thread* — every
// hand-tracking pass freezes the whole page (orb, audio meter, the video
// draw loop) for however long it takes, exactly the bug detect-worker.js
// fixes for object detection. See:
// https://developers.google.com/mediapipe/solutions/vision/hand_landmarker/web_js
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
const { HandLandmarker, FilesetResolver } = self.$mediapipe;

const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const WASM_ROOT = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.17/wasm";

let handLandmarker = null;
let readyPromise = null;

async function createLandmarker(delegate) {
  const vision = await FilesetResolver.forVisionTasks(WASM_ROOT);
  return HandLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: MODEL_URL, delegate },
    runningMode: "VIDEO",
    numHands: 1,
    minHandDetectionConfidence: 0.6,
    minTrackingConfidence: 0.5,
  });
}

function ensureReady() {
  if (!readyPromise) {
    readyPromise = (async () => {
      try {
        handLandmarker = await createLandmarker("GPU");
      } catch (_) {
        // Not every machine/browser can give a Worker a GPU context for
        // this — CPU delegate still keeps the *isolation* benefit (nothing
        // here ever touches the main thread), just slower per frame.
        handLandmarker = await createLandmarker("CPU");
      }
      self.postMessage({ type: "ready" });
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
    const result = handLandmarker.detectForVideo(bitmap, timestamp);
    bitmap.close();
    const landmarks = (result.landmarks && result.landmarks[0]) || null;
    self.postMessage({ type: "result", id, landmarks });
  } catch (err) {
    bitmap.close();
    self.postMessage({ type: "error", id, error: String((err && err.stack) || err) });
  }
};
