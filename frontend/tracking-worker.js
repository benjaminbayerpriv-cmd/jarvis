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

let landmarker = null;
let readyPromise = null;

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

function ensureReady() {
  if (!readyPromise) {
    readyPromise = (async () => {
      try {
        landmarker = await createLandmarker("GPU");
      } catch (_) {
        // Not every machine/browser can give a Worker a GPU context for
        // this — CPU delegate still keeps the *isolation* benefit (nothing
        // here ever touches the main thread), just slower per frame.
        landmarker = await createLandmarker("CPU");
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
    const result = landmarker.detectForVideo(bitmap, timestamp);
    bitmap.close();
    self.postMessage({
      type: "result",
      id,
      pose: (result.poseLandmarks && result.poseLandmarks[0]) || null,
      leftHand: (result.leftHandLandmarks && result.leftHandLandmarks[0]) || null,
      rightHand: (result.rightHandLandmarks && result.rightHandLandmarks[0]) || null,
    });
  } catch (err) {
    bitmap.close();
    self.postMessage({ type: "error", id, error: String((err && err.stack) || err) });
  }
};
