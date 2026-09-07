// Runs hand tracking off the main thread using classical (non-ML) OpenCV.js
// — skin-color segmentation + contours, not a neural network. Two earlier
// versions of this file used MediaPipe's deep-learning landmark models
// (first Holistic, then a lighter Pose+Hand split); both worked but never
// got past ~15-25fps in a browser, since WASM/WebGL ML inference is nowhere
// near a native mobile ML framework (CoreML/Metal, NNAPI). Classical CV
// trades the precise 21-point finger skeleton for much less precision (a
// bounding box around "this looks like a skin-colored blob roughly here")
// in exchange for genuinely fast, simple pixel processing with no neural
// net at all.
//
// This still has to run in a Worker: even without ML, a synchronous
// multi-step OpenCV pipeline on every frame would otherwise block the main
// thread (orb, audio meter, video draw loop) for its own duration.
//
// No body/pose tracking here (a prior version had that via MediaPipe) —
// classical background-subtraction-based body silhouette tracking needs
// *motion* to tell foreground from background, so it fades away whenever
// someone just sits still in front of the camera, which is the normal case
// for a voice assistant. Not worth shipping something that flickers away
// on its own. Hands are tracked instead via skin color, which works
// regardless of motion.
importScripts("https://docs.opencv.org/4.9.0/opencv.js");

const CASCADE_URL =
  "https://cdn.jsdelivr.net/gh/opencv/opencv@4.9.0/data/haarcascades/haarcascade_frontalface_default.xml";

let faceCascade = null;
let readyPromise = null;

function waitForOpenCv() {
  return new Promise((resolve) => {
    if (typeof cv !== "undefined" && cv.Mat) {
      resolve();
      return;
    }
    cv["onRuntimeInitialized"] = () => resolve();
  });
}

function ensureReady() {
  if (!readyPromise) {
    readyPromise = (async () => {
      await waitForOpenCv();
      const xml = await fetch(CASCADE_URL).then((r) => r.text());
      cv.FS_createDataFile("/", "face.xml", xml, true, false, false);
      faceCascade = new cv.CascadeClassifier();
      faceCascade.load("/face.xml");
      self.postMessage({ type: "ready" });
    })();
  }
  return readyPromise;
}
ensureReady();

// All the classical-CV ops below (Haar cascade, color conversion,
// morphology) scale with pixel count, and the public opencv.js WASM build
// has zero SIMD (per cv.getBuildInformation(): "CPU/HW features: Baseline:"
// empty — no accelerated kernels at all). At the camera's native 1280x720
// that measured 400-900ms/frame; downscaling the frame before processing
// is what actually gets this fast, since detection only needs to know
// *roughly* where a hand is, not per-pixel precision. Measured ~45-65ms/
// frame at this size, versus ~130-150ms at 320px wide and 400-900ms at
// full camera resolution.
const PROC_WIDTH = 160;

function detectFrame(bitmap) {
  const vw = bitmap.width, vh = bitmap.height;
  const scale = PROC_WIDTH / vw;
  const pw = PROC_WIDTH, ph = Math.round(vh * scale);
  const canvas = new OffscreenCanvas(pw, ph);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0, pw, ph);
  bitmap.close();
  const imgData = ctx.getImageData(0, 0, pw, ph);

  const mat = cv.matFromImageData(imgData);
  const gray = new cv.Mat();
  cv.cvtColor(mat, gray, cv.COLOR_RGBA2GRAY);

  const faces = new cv.RectVector();
  const minFaceSize = new cv.Size(Math.round(pw * 0.15), Math.round(ph * 0.15));
  faceCascade.detectMultiScale(gray, faces, 1.1, 4, 0, minFaceSize);

  const matC3 = new cv.Mat();
  cv.cvtColor(mat, matC3, cv.COLOR_RGBA2RGB);
  const ycrcb = new cv.Mat();
  cv.cvtColor(matC3, ycrcb, cv.COLOR_RGB2YCrCb);

  // YCrCb skin range (Cr/Cb stay stable across lighting changes, unlike
  // HSV's hue at low saturation) — the standard Chai & Ngan range. Much
  // less prone to picking up cream/beige fabric than a naive HSV threshold.
  const low = new cv.Mat(ycrcb.rows, ycrcb.cols, ycrcb.type(), new cv.Scalar(0, 133, 77, 0));
  const high = new cv.Mat(ycrcb.rows, ycrcb.cols, ycrcb.type(), new cv.Scalar(255, 173, 127, 255));
  const skinMask = new cv.Mat();
  cv.inRange(ycrcb, low, high, skinMask);

  // Exclude detected face regions from the skin mask so a face isn't
  // mistaken for a third "hand". Skin-color segmentation genuinely can't
  // tell hand-shaped skin from face-shaped skin — if a hand overlaps or
  // touches the face in frame, they'll still merge into one blob; this
  // only helps when they're apart, which is the normal case for gesturing
  // at a camera.
  for (let i = 0; i < faces.size(); i++) {
    const f = faces.get(i);
    const pad = Math.round(f.width * 0.15);
    const x0 = Math.max(0, f.x - pad), y0 = Math.max(0, f.y - pad);
    const x1 = Math.min(pw, f.x + f.width + pad), y1 = Math.min(ph, f.y + f.height + pad);
    cv.rectangle(skinMask, new cv.Point(x0, y0), new cv.Point(x1, y1), new cv.Scalar(0), -1);
  }

  const kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(7, 7));
  cv.morphologyEx(skinMask, skinMask, cv.MORPH_OPEN, kernel);
  cv.morphologyEx(skinMask, skinMask, cv.MORPH_CLOSE, kernel);

  const contours = new cv.MatVector();
  const hierarchy = new cv.Mat();
  cv.findContours(skinMask, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);

  const minArea = pw * ph * 0.01; // ignore tiny noise blobs
  const candidates = [];
  for (let i = 0; i < contours.size(); i++) {
    const c = contours.get(i);
    const area = cv.contourArea(c);
    if (area >= minArea) candidates.push({ area, rect: cv.boundingRect(c) });
    c.delete();
  }
  candidates.sort((a, b) => b.area - a.area);
  const hands = candidates.slice(0, 2).map((c) => ({
    x: c.rect.x / pw,
    y: c.rect.y / ph,
    w: c.rect.width / pw,
    h: c.rect.height / ph,
  }));

  mat.delete();
  gray.delete();
  matC3.delete();
  ycrcb.delete();
  low.delete();
  high.delete();
  skinMask.delete();
  kernel.delete();
  contours.delete();
  hierarchy.delete();
  faces.delete();

  return { hands };
}

self.onmessage = async (e) => {
  const { type, id, bitmap } = e.data;
  if (type !== "detect") return;
  try {
    await ensureReady();
    const t0 = performance.now();
    const result = detectFrame(bitmap);
    const ms = performance.now() - t0;
    self.postMessage({ type: "result", id, ms, ...result });
  } catch (err) {
    self.postMessage({ type: "error", id, error: String((err && err.stack) || err) });
  }
};
