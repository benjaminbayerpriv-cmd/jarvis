// Runs body/hand landmark tracking off the main thread. MediaPipe's own
// docs confirm both the old solutions API (Hands.send()) and the current
// Tasks API's detect()/detectForVideo() run *synchronously and block the
// main thread* — every tracking pass would otherwise freeze the whole page
// (orb, audio meter, the video draw loop) for however long it takes. See:
// https://developers.google.com/mediapipe/solutions/vision/hand_landmarker/web_js
//
// Runs PoseLandmarker (the "lite" model, body only) and HandLandmarker
// (numHands: 2) as two separate models rather than one combined
// HolisticLandmarker — measured ~30% faster per frame, since Holistic also
// runs a face-detection sub-model on every frame that this code never
// draws anyway. Real-time full-body-plus-both-hands tracking in a browser
// (WASM/WebGL) is still nowhere near what a native mobile ML framework
// (CoreML/Metal, NNAPI) can do — expect roughly 15-20fps for this, not 60.
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
const { PoseLandmarker, HandLandmarker, FilesetResolver } = self.$mediapipe;

const POSE_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const WASM_ROOT = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.17/wasm";

// A real photo (a person with both hands raised) used only to warm the
// models up before the caller ever gets a "ready" message — see warmUp()
// below for why this matters. MediaPipe's own public hand_landmarker demo
// asset, fetched the same way the .task model files above are.
const WARMUP_IMAGE_URL = "https://storage.googleapis.com/mediapipe-tasks/hand_landmarker/woman_hands.jpg";

let poseLandmarker = null;
let handLandmarker = null;
let readyPromise = null;
let activeDelegate = null; // "GPU" or "CPU" — whichever actually initialized

async function createLandmarkers(delegate) {
  const vision = await FilesetResolver.forVisionTasks(WASM_ROOT);
  return Promise.all([
    PoseLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: POSE_MODEL_URL, delegate },
      runningMode: "VIDEO",
      minPoseDetectionConfidence: 0.5,
    }),
    HandLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: HAND_MODEL_URL, delegate },
      runningMode: "VIDEO",
      numHands: 2,
      minHandDetectionConfidence: 0.6,
      minTrackingConfidence: 0.5,
    }),
  ]);
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
    for (let i = 0; i < 3; i++) {
      const bitmap = await createImageBitmap(blob);
      poseLandmarker.detectForVideo(bitmap, i + 1);
      handLandmarker.detectForVideo(bitmap, i + 1);
      bitmap.close();
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
      // GPU vs. CPU delegate is a 10-20x difference for these models —
      // logged clearly since a silent fallback here is exactly what makes
      // tracking feel broken/laggy for no visible reason.
      try {
        [poseLandmarker, handLandmarker] = await createLandmarkers("GPU");
        activeDelegate = "GPU";
      } catch (err) {
        console.warn("[tracking-worker] GPU delegate failed, falling back to CPU (10-20x slower):", err);
        [poseLandmarker, handLandmarker] = await createLandmarkers("CPU");
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
    const poseResult = poseLandmarker.detectForVideo(bitmap, timestamp);
    const handResult = handLandmarker.detectForVideo(bitmap, timestamp);
    const ms = performance.now() - t0;
    bitmap.close();

    let leftHand = null;
    let rightHand = null;
    if (handResult.landmarks) {
      for (let i = 0; i < handResult.landmarks.length; i++) {
        const label = handResult.handedness?.[i]?.[0]?.categoryName;
        if (label === "Left") leftHand = handResult.landmarks[i];
        else if (label === "Right") rightHand = handResult.landmarks[i];
      }
    }

    self.postMessage({
      type: "result",
      id,
      ms,
      pose: (poseResult.landmarks && poseResult.landmarks[0]) || null,
      leftHand,
      rightHand,
    });
  } catch (err) {
    bitmap.close();
    self.postMessage({ type: "error", id, error: String((err && err.stack) || err) });
  }
};
