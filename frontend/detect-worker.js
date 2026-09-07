// Runs YOLOv8n object detection off the main thread.
//
// A single CPU/WASM inference pass can take anywhere from ~100ms to well
// over a second depending on the machine — there's no GPU backend here,
// just onnxruntime-web's single-threaded wasm execution provider. Running
// that directly on the main thread (as an earlier version of this file
// did) blocks *everything* for that whole duration: the orb animation,
// the audio meter, even the video draw loop, because JavaScript is
// single-threaded and an awaited WASM call doesn't yield control back to
// the browser's own rendering/event loop until it's done. Moving the
// entire cv+onnx pipeline into a Worker is what actually keeps the rest
// of the app responsive while a detection pass runs.
importScripts(
  "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.min.js",
  "https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js"
);

const YOLO_INPUT_SHAPE = [1, 3, 640, 640];
const YOLO_TOPK = 100;
const YOLO_IOU_THRESHOLD = 0.45;
const YOLO_SCORE_THRESHOLD = 0.25;
const YOLO_MODEL_URL =
  "https://cdn.jsdelivr.net/gh/Hyuto/yolov8-onnxruntime-web@master/public/model/yolov8n.onnx";
const YOLO_NMS_URL =
  "https://cdn.jsdelivr.net/gh/Hyuto/yolov8-onnxruntime-web@master/public/model/nms-yolov8.onnx";

let yoloSession = null;
let detectCanvas = null; // OffscreenCanvas — no DOM in a Worker

function waitForOpenCv() {
  return new Promise((resolve) => {
    if (typeof cv !== "undefined" && cv.Mat) {
      resolve();
      return;
    }
    cv["onRuntimeInitialized"] = () => resolve();
  });
}

async function ensureYoloReady() {
  if (yoloSession) return;
  ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/";
  await waitForOpenCv();
  const [net, nms] = await Promise.all([
    ort.InferenceSession.create(YOLO_MODEL_URL),
    ort.InferenceSession.create(YOLO_NMS_URL),
  ]);
  // Warmup so the first *real* frame isn't the one paying for WASM
  // kernel-selection/JIT cost.
  const warm = new ort.Tensor(
    "float32",
    new Float32Array(YOLO_INPUT_SHAPE.reduce((a, b) => a * b)),
    YOLO_INPUT_SHAPE
  );
  await net.run({ images: warm });
  yoloSession = { net, nms };
  self.postMessage({ type: "ready" });
}
ensureYoloReady();

async function detectFrame(bitmap) {
  const vw = bitmap.width, vh = bitmap.height;
  if (!detectCanvas) detectCanvas = new OffscreenCanvas(vw, vh);
  if (detectCanvas.width !== vw || detectCanvas.height !== vh) {
    detectCanvas.width = vw;
    detectCanvas.height = vh;
  }
  const ctx = detectCanvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0, vw, vh);
  bitmap.close();

  const [modelWidth, modelHeight] = YOLO_INPUT_SHAPE.slice(2);
  // Not cv.imread(detectCanvas) — its wrapper does `instanceof
  // HTMLImageElement` before it ever gets to the OffscreenCanvas branch,
  // and that class doesn't exist in a Worker at all, so the check itself
  // throws a ReferenceError. matFromImageData is what imread calls
  // internally anyway once it identifies its input as a canvas.
  const imgData = ctx.getImageData(0, 0, vw, vh);
  const mat = cv.matFromImageData(imgData);
  const matC3 = new cv.Mat(mat.rows, mat.cols, cv.CV_8UC3);
  cv.cvtColor(mat, matC3, cv.COLOR_RGBA2BGR);

  // Letterbox pad to a square before resizing to the model's fixed square
  // input, so the frame's real aspect ratio isn't squashed.
  const maxSize = Math.max(matC3.rows, matC3.cols);
  const xPad = maxSize - matC3.cols, xRatio = maxSize / matC3.cols;
  const yPad = maxSize - matC3.rows, yRatio = maxSize / matC3.rows;
  const matPad = new cv.Mat();
  cv.copyMakeBorder(matC3, matPad, 0, yPad, 0, xPad, cv.BORDER_CONSTANT);

  const blob = cv.blobFromImage(
    matPad,
    1 / 255.0,
    new cv.Size(modelWidth, modelHeight),
    new cv.Scalar(0, 0, 0),
    true, // swapRB
    false // crop
  );

  mat.delete();
  matC3.delete();
  matPad.delete();

  const detections = [];
  try {
    const tensor = new ort.Tensor("float32", blob.data32F, YOLO_INPUT_SHAPE);
    const config = new ort.Tensor(
      "float32",
      new Float32Array([YOLO_TOPK, YOLO_IOU_THRESHOLD, YOLO_SCORE_THRESHOLD])
    );
    const { output0 } = await yoloSession.net.run({ images: tensor });
    const { selected } = await yoloSession.nms.run({ detection: output0, config });

    for (let i = 0; i < selected.dims[1]; i++) {
      const row = selected.data.slice(i * selected.dims[2], (i + 1) * selected.dims[2]);
      const box = row.slice(0, 4);
      const scores = row.slice(4);
      const score = Math.max(...scores);
      const labelId = scores.indexOf(score);
      const [x, y, bw, bh] = [
        (box[0] - 0.5 * box[2]) * xRatio, // upscale left
        (box[1] - 0.5 * box[3]) * yRatio, // upscale top
        box[2] * xRatio,                  // upscale width
        box[3] * yRatio,                  // upscale height
      ];
      detections.push({ bbox: [x, y, bw, bh], labelId, score });
    }
  } finally {
    blob.delete();
  }
  return detections;
}

self.onmessage = async (e) => {
  const { type, id, bitmap } = e.data;
  if (type !== "detect") return;
  try {
    await ensureYoloReady();
    const detections = await detectFrame(bitmap);
    self.postMessage({ type: "result", id, detections });
  } catch (err) {
    self.postMessage({ type: "error", id, error: String(err && err.stack || err) });
  }
};
