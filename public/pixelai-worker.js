/* BarksBuds AI pixel portrait (TEST): runs the AnimeGANv2 "face paint v2" generator (MIT, Bryan Lee) on the
   visitor's own device with ONNX Runtime Web (WASM, MIT). Nothing is uploaded. Module worker so the page stays
   responsive. Messages in:  {type:"run", pixels: Float32Array(3*512*512) CHW in [-1,1]}
               out: {type:"progress", stage, pct, detail} | {type:"done", pixels, ms, backend} | {type:"error", message} */
const ORT_VER = "1.30.0";
const ORT_BASE = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VER}/dist/`;
const MODEL_URL = "/vendor/animegan/face_paint_512_v2.onnx";
const MODEL_BYTES = 8594990;
const CACHE = "barksbuds-ai-v1";
let session = null, ort = null;
const post = (m, t) => self.postMessage(m, t || []);

async function fetchModel() {
  let cache = null;
  try { cache = await caches.open(CACHE); const hit = await cache.match(MODEL_URL); if (hit) return new Uint8Array(await hit.arrayBuffer()); } catch (e) { cache = null; }
  const r = await fetch(MODEL_URL);
  if (!r.ok || !r.body) throw new Error(`Couldn't download the AI painter (HTTP ${r.status}).`);
  const total = +r.headers.get("Content-Length") || MODEL_BYTES, reader = r.body.getReader(), parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    parts.push(value); got += value.length;
    post({ type: "progress", stage: "download", pct: Math.min(100, got * 100 / total), detail: `${(got / 1048576).toFixed(1)} of ${(total / 1048576).toFixed(1)} MB` });
  }
  const buf = new Uint8Array(got); let o = 0; for (const p of parts) { buf.set(p, o); o += p.length; }
  if (cache) { try { await cache.put(MODEL_URL, new Response(buf.slice(), { headers: { "Content-Type": "application/octet-stream" } })); } catch (e) { /* storage full or private mode: fine */ } }
  return buf;
}

async function init() {
  if (session) return;
  post({ type: "progress", stage: "runtime", pct: 0, detail: "Loading the AI engine" });
  ort = await import(ORT_BASE + "ort.wasm.min.mjs");
  ort.env.wasm.wasmPaths = ORT_BASE;
  ort.env.wasm.numThreads = self.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 1) : 1;
  const model = await fetchModel();
  post({ type: "progress", stage: "runtime", pct: 100, detail: "Starting the AI painter" });
  session = await ort.InferenceSession.create(model, { executionProviders: ["wasm"], graphOptimizationLevel: "all" });
}

self.onmessage = async (ev) => {
  const m = ev.data || {};
  if (m.type !== "run") return;
  try {
    await init();
    post({ type: "progress", stage: "paint", pct: 0, detail: "Painting" });
    const t0 = performance.now();
    const input = new ort.Tensor("float32", m.pixels, [1, 3, 512, 512]);
    const out = await session.run({ [session.inputNames[0]]: input });
    const y = out[session.outputNames[0]].data;
    const pixels = new Float32Array(y);            // copy so the buffer can be transferred
    post({ type: "done", pixels, ms: Math.round(performance.now() - t0), backend: `wasm x${ort.env.wasm.numThreads}` }, [pixels.buffer]);
  } catch (err) {
    post({ type: "error", message: (err && err.message) || String(err) });
  }
};
