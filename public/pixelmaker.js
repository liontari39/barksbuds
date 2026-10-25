/* BarksBuds pixel pal maker (page: /me/dogs/<id>/pixel).
   1. pick a photo (gallery or a local file that never leaves the device)
   2. select the dog: tap-to-select with the MediaPipe interactive segmenter (vendored, Apache-2.0), plus
      keep/erase brushes and a crop box that also work on their own if the model can't load
   3. style it with pixelpal.js, preview live, then save the sprite PNG or download it. */
const root = document.getElementById("pxm");
const cfg = JSON.parse(root.dataset.cfg);
const PP = window.PixelPal;
const $ = (id) => document.getElementById(id);
const MAXW = cfg.ai ? 1024 : 640;       // working resolution: plenty for a 64 px sprite, quick on phones (AI Portrait: 96 px, so more)
const DETAIL = [                        // "Detail" slider: smoother/cleaner  ->  more texture
  { smooth: 3, cluster: 3, sharpen: 0.25, features: 0.65 },
  { smooth: 2, cluster: 2, sharpen: 0.35, features: 0.75 },
  { smooth: 2, cluster: 1, sharpen: 0.4, features: 0.75 },
  { smooth: 1, cluster: 1, sharpen: 0.5, features: 0.8 },
  { smooth: 0, cluster: 0, sharpen: 0.6, features: 0.85 }];
const CEL_DETAIL = [                    // Game Sprite (48 px cel): the middle step is exactly the preset
  { smooth: 3, cluster: 5 }, { smooth: 3, cluster: 4 }, {},
  { smooth: 2, cluster: 2, sharpen: 0.2, features: 0.3 }, { smooth: 1, cluster: 1, sharpen: 0.4, features: 0.6 }];
const TOON_DETAIL = [                   // Chunky: big flat shapes; "detail" only changes how small a color patch may be
  { clean: 4 }, { clean: 3 }, { clean: 2 }, { clean: 1 }, { clean: 0 }];
const PORTRAIT_DETAIL = [               // Portrait (AI test page, 96 px): the 4th step is exactly the preset
  { smooth: 3, cluster: 2, sharpen: 0.2, features: 0.6 }, { smooth: 2, cluster: 1, sharpen: 0.3, features: 0.7 },
  { smooth: 2, cluster: 0 }, {}, { smooth: 0, cluster: 0, sharpen: 0.6, features: 0.9 }];
// only Game Sprite and Chunky are offered in the UI (plus Portrait on the hidden AI test page); classic/retro/soft stay in pixelpal.js
const PRESET_UI = { game: { detail: 2, face: true, eyes: [["friendly", "Shiny"], ["ring", "Ringed"]] },
  chunky: { detail: 2, face: true, eyes: [["dots", "Dots"], ["happy", "Happy (^ ^)"]] },
  portrait: { detail: 3, face: false, eyes: [["friendly", "Shiny"], ["ring", "Ringed"]] } };
const SIZE_NAMES = ["Small", "Medium", "Large"];

let seg = null, segState = "idle", segWaiters = [];
let W = 0, H = 0, work = null, rgba = null, auto = null, edit = null, crop = null, undo = [];
let face = { eyes: [], nose: null };   // normalized eye/nose points for the cartoon face stickers
let tool = "tap", preset = "game", sprite = null, view = "after", cursor = null, cropA = null;
const src = $("pxsrc"), sctx = src.getContext("2d");
const status = (t) => { $("pxstatus").textContent = t; };
const saveOff = (v) => ["pxsavebtn", "pxsave2", "pxdl"].forEach((id) => { const b = $(id); if (b) b.disabled = v; });
// AI test page state: the untouched photo, the AI-painted version (same size), and the full-size original for the AI crop
let photoRgba = null, painted = null, origImg = null, aiBusy = false, worker = null;

// ---------------------------------------------------------------- smart select (lazy, optional)
async function loadSeg() {
  if (segState !== "idle") return;
  segState = "loading";
  try {
    const { FilesetResolver, InteractiveSegmenterLegacy } = await import("/vendor/mediapipe/vision_bundle.mjs");
    const fs = await FilesetResolver.forVisionTasks("/vendor/mediapipe");
    seg = await InteractiveSegmenterLegacy.createFromOptions(fs, {
      baseOptions: { modelAssetPath: "/vendor/mediapipe/magic_touch.tflite", delegate: "CPU" },
      outputCategoryMask: false, outputConfidenceMasks: true });
    segState = "ready";
  } catch (err) {
    console.warn("pixel pal: smart select unavailable", err);
    segState = "failed";
  }
  segWaiters.splice(0).forEach((f) => f());
}
const segReady = () => (segState === "ready" || segState === "failed") ? Promise.resolve() : new Promise((r) => segWaiters.push(r));

function segmentAt(nx, ny) {
  if (!seg) return false;
  const r = seg.segment(work, { keypoint: { x: Math.min(0.999, Math.max(0, nx)), y: Math.min(0.999, Math.max(0, ny)) } });
  const m = r.confidenceMasks && r.confidenceMasks[0];
  if (!m) { r.close && r.close(); return false; }
  const a = m.getAsFloat32Array(), mw = m.width, mh = m.height;
  let added = 0;
  for (let y = 0; y < H; y++) {
    const my = Math.min(mh - 1, (y * mh / H) | 0);
    for (let x = 0; x < W; x++) {
      const v = Math.round(a[my * mw + Math.min(mw - 1, (x * mw / W) | 0)] * 255), k = y * W + x;
      if (v > auto[k]) { if (v > 127 && auto[k] <= 127) added++; auto[k] = v; }
    }
  }
  r.close && r.close();
  return added;
}

// ---------------------------------------------------------------- step 1: pick a photo
async function useImage(source) {
  $("pxpickerr").textContent = "";
  let bmp;
  try {
    bmp = source instanceof Blob ? await createImageBitmap(source) : await new Promise((res, rej) => {
      const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = source; });
  } catch (err) {
    $("pxpickerr").textContent = "We couldn't open that photo. Try a JPEG or PNG.";
    return;
  }
  const iw = bmp.naturalWidth || bmp.width, ih = bmp.naturalHeight || bmp.height, s = Math.min(1, MAXW / Math.max(iw, ih));
  W = Math.max(1, Math.round(iw * s)); H = Math.max(1, Math.round(ih * s));
  work = document.createElement("canvas"); work.width = W; work.height = H;
  const wctx = work.getContext("2d", { willReadFrequently: true });
  wctx.imageSmoothingQuality = "high"; wctx.drawImage(bmp, 0, 0, W, H);
  rgba = wctx.getImageData(0, 0, W, H);
  photoRgba = rgba; painted = null; origImg = bmp; aiReset();
  auto = new Uint8Array(W * H); edit = new Uint8Array(W * H); crop = { x0: 0, y0: 0, x1: W, y1: H }; undo = []; cropA = null;
  face = { eyes: [], nose: null }; faceStatus();
  src.width = W; src.height = H;
  $("pxpick").hidden = true; $("pxed").hidden = false;
  $("pxundo").disabled = true; $("pxsaved").textContent = "";
  draw(); $("pxed").scrollIntoView({ behavior: "smooth", block: "start" });
  if (segState !== "ready") status(segState === "failed" ? "" : "Loading smart select (about 10 MB, only the first time)…");
  await segReady();
  if (segState === "ready") {
    setTool("tap");
    const n = segmentAt(0.5, 0.48);
    status(n ? `Selected the middle of the photo. Tap any part of ${cfg.name} that's missing, or use the Erase brush to remove extras.`
             : `Tap on ${cfg.name} to select.`);
    if (n) guessFaceNow();
  } else {
    $("pxtooltap").disabled = true;
    setTool("keep");
    status(`Smart select isn't available on this device. Paint over ${cfg.name} with the Keep brush, or crop tight and press "Keep everything in crop".`);
  }
  draw(); schedule();
}

document.querySelectorAll(".pxpick").forEach((b) => b.addEventListener("click", () => useImage(b.dataset.src)));
$("pxfile").addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) useImage(f); ev.target.value = ""; });

// ---------------------------------------------------------------- step 2: select the dog
const toolInputs = document.querySelectorAll('input[name="tool"]');
toolInputs.forEach((r) => { if (r.value === "tap") r.id = "pxtooltap"; r.addEventListener("change", () => setTool(r.value)); });
function setTool(t) {
  tool = t; toolInputs.forEach((r) => { r.checked = r.value === t; });
  $("pxbsize").closest(".pxbrush").classList.toggle("off", !(t === "keep" || t === "erase"));
  cropA = null; draw();
}

// ---------------------------------------------------------------- cartoon face: eye and nose points
function guessFaceNow() {
  if (face.eyes.length || face.nose) return;
  try {
    const g = PP.guessFace({ width: W, height: H, data: rgba.data, mask: finalMask() });
    if (g) { face = { eyes: g.eyes, nose: g.nose, guessed: true }; faceStatus(); draw(); }
  } catch (err) { console.warn("pixel pal: face guess failed", err); }
}
function faceStatus() {
  const e = face.eyes.length, n = face.nose ? 1 : 0, el = $("pxfacest"); if (!el) return;
  el.textContent = !e && !n ? `No eyes marked yet. Choose Eyes and tap the middle of each of ${cfg.name}'s eyes for cartoon eyes.`
    : (face.guessed ? "We guessed where the eyes and nose are (white and dark dots). If they're off, choose Eyes or Nose and tap the right spot. " : "")
      + `${e} of 2 eyes marked${n ? ", nose marked" : ", nose not marked"}.`;
}
function faceTap(p) {
  const q = [p.x / W, p.y / H];
  if (face.guessed) face = { eyes: tool === "eyes" ? [] : face.eyes, nose: tool === "nose" ? null : face.nose };
  if (tool === "nose") face.nose = q;
  else if (face.eyes.length < 2) face.eyes.push(q);
  else {                              // a third tap moves whichever eye is closer
    const d = face.eyes.map((e) => Math.hypot(e[0] - q[0], e[1] - q[1]));
    face.eyes[d[0] <= d[1] ? 0 : 1] = q;
  }
  if (tool === "eyes" && face.eyes.length === 2 && !face.nose) status(`Both eyes marked. Choose Nose and tap ${cfg.name}'s nose.`);
  faceStatus(); draw(); schedule();
}
$("pxfacereset").addEventListener("click", () => { face = { eyes: [], nose: null }; faceStatus(); draw(); schedule(); });

function finalMask() {
  const out = new Uint8Array(W * H);
  for (let y = crop.y0; y < crop.y1; y++) for (let x = crop.x0; x < crop.x1; x++) {
    const k = y * W + x, e = edit[k];
    out[k] = e === 1 ? 255 : e === 2 ? 0 : auto[k];
  }
  return out;
}

function draw() {
  if (!rgba) return;
  const m = finalMask(), img = sctx.createImageData(W, H), d = img.data, s = rgba.data;
  for (let k = 0, i = 0; k < W * H; k++, i += 4) {
    const a = m[k] / 255;
    // unselected parts are dimmed and tinted, so the selection pops; its edge gets a gold line
    const x = k % W, inside = m[k] > 127;
    if (inside && (x === 0 || x === W - 1 || k < W || k >= W * (H - 1) || m[k - 1] <= 127 || m[k + 1] <= 127 || m[k - W] <= 127 || m[k + W] <= 127)) {
      d[i] = 251; d[i + 1] = 179; d[i + 2] = 33; d[i + 3] = 255; continue;
    }
    d[i] = s[i] * (0.22 + 0.78 * a) + 34 * (1 - a); d[i + 1] = s[i + 1] * (0.22 + 0.78 * a) + 24 * (1 - a);
    d[i + 2] = s[i + 2] * (0.22 + 0.78 * a) + 52 * (1 - a); d[i + 3] = 255;
  }
  sctx.putImageData(img, 0, 0);
  const lw = Math.max(1.5, W / 300);
  sctx.lineWidth = lw;
  if (crop.x0 > 0 || crop.y0 > 0 || crop.x1 < W || crop.y1 < H) {
    sctx.setLineDash([lw * 4, lw * 3]); sctx.strokeStyle = "#FBB321";
    sctx.strokeRect(crop.x0 + lw / 2, crop.y0 + lw / 2, crop.x1 - crop.x0 - lw, crop.y1 - crop.y0 - lw); sctx.setLineDash([]);
  }
  const fr = Math.max(4, W / 70);
  face.eyes.forEach((e) => {             // eye markers: white dot with a dark ring; nose: dark dot with a white ring
    sctx.beginPath(); sctx.arc(e[0] * W, e[1] * H, fr, 0, Math.PI * 2); sctx.fillStyle = "#fff"; sctx.fill();
    sctx.lineWidth = lw * 1.5; sctx.strokeStyle = "#2a2622"; sctx.stroke();
  });
  if (face.nose) {
    sctx.beginPath(); sctx.arc(face.nose[0] * W, face.nose[1] * H, fr, 0, Math.PI * 2); sctx.fillStyle = "#2a2622"; sctx.fill();
    sctx.lineWidth = lw * 1.5; sctx.strokeStyle = "#fff"; sctx.stroke();
  }
  if (cropA && cursor) { sctx.strokeStyle = "#C8201E"; sctx.strokeRect(Math.min(cropA.x, cursor.x), Math.min(cropA.y, cursor.y), Math.abs(cursor.x - cropA.x), Math.abs(cursor.y - cropA.y)); }
  if (cursor && (document.activeElement === src || hover)) {
    const r = (tool === "keep" || tool === "erase") ? brushR() : W / 60;
    sctx.beginPath(); sctx.arc(cursor.x, cursor.y, r, 0, Math.PI * 2);
    sctx.strokeStyle = "#fff"; sctx.lineWidth = lw * 2; sctx.stroke();
    sctx.strokeStyle = tool === "erase" ? "#C8201E" : "#2a2622"; sctx.lineWidth = lw; sctx.stroke();
  }
}
let raf = 0; const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };

function pushUndo() {
  undo.push({ auto: auto.slice(), edit: edit.slice(), crop: Object.assign({}, crop) });
  if (undo.length > 15) undo.shift();
  $("pxundo").disabled = false;
}
$("pxundo").addEventListener("click", () => {
  const u = undo.pop(); if (!u) return;
  auto = u.auto; edit = u.edit; crop = u.crop; $("pxundo").disabled = !undo.length; draw(); schedule();
});
$("pxclear").addEventListener("click", () => { pushUndo(); auto.fill(0); edit.fill(0); draw(); schedule(); status("Selection cleared."); });
$("pxall").addEventListener("click", () => {
  pushUndo(); edit.fill(0);
  for (let y = crop.y0; y < crop.y1; y++) auto.fill(255, y * W + crop.x0, y * W + crop.x1);
  draw(); schedule(); status("Everything inside the crop is selected. Use the Erase brush to remove the background.");
});

const brushR = () => Math.max(2, +$("pxbsize").value * W / Math.max(120, src.clientWidth));
function dab(x, y, val) {
  const r = brushR(), r2 = r * r;
  for (let yy = Math.max(0, Math.floor(y - r)); yy <= Math.min(H - 1, Math.ceil(y + r)); yy++)
    for (let xx = Math.max(0, Math.floor(x - r)); xx <= Math.min(W - 1, Math.ceil(x + r)); xx++)
      if ((xx - x) * (xx - x) + (yy - y) * (yy - y) <= r2) edit[yy * W + xx] = val;
}
function stroke(a, b, val) {
  const n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / (brushR() * 0.4)));
  for (let i = 1; i <= n; i++) dab(a.x + (b.x - a.x) * i / n, a.y + (b.y - a.y) * i / n, val);
}
function tapAt(p) {
  if (segState !== "ready") return;
  pushUndo();
  const t0 = performance.now(), n = segmentAt(p.x / W, p.y / H);
  status(n ? `Added that part (${Math.round(performance.now() - t0)} ms). Keep tapping, or touch up with the brushes.`
           : "That spot was already selected. Use the Erase brush to remove extra bits.");
  draw(); schedule();
}
function setCrop(a, b) {
  const x0 = Math.max(0, Math.round(Math.min(a.x, b.x))), x1 = Math.min(W, Math.round(Math.max(a.x, b.x)));
  const y0 = Math.max(0, Math.round(Math.min(a.y, b.y))), y1 = Math.min(H, Math.round(Math.max(a.y, b.y)));
  if (x1 - x0 < W / 20 || y1 - y0 < H / 20) return false;
  pushUndo(); crop = { x0, y0, x1, y1 }; return true;
}

const pt = (ev) => { const r = src.getBoundingClientRect(); return { x: (ev.clientX - r.left) * W / r.width, y: (ev.clientY - r.top) * H / r.height }; };
let drag = null, hover = false;
src.addEventListener("pointerdown", (ev) => {
  if (!rgba) return; ev.preventDefault(); src.setPointerCapture(ev.pointerId);
  const p = pt(ev); drag = { start: p, last: p }; cursor = p;
  if (tool === "keep" || tool === "erase") { pushUndo(); dab(p.x, p.y, tool === "keep" ? 1 : 2); redraw(); }
  if (tool === "crop") cropA = p;
});
src.addEventListener("pointermove", (ev) => {
  if (!rgba) return; const p = pt(ev); cursor = p; hover = true;
  if (drag && (tool === "keep" || tool === "erase")) { stroke(drag.last, p, tool === "keep" ? 1 : 2); drag.last = p; }
  redraw();
});
src.addEventListener("pointerleave", () => { hover = false; redraw(); });
src.addEventListener("pointerup", (ev) => {
  if (!drag) return; const p = pt(ev), moved = Math.hypot(p.x - drag.start.x, p.y - drag.start.y);
  if (tool === "tap" && moved < W / 40) tapAt(p);
  else if ((tool === "eyes" || tool === "nose") && moved < W / 40) faceTap(p);
  else if (tool === "crop") { cropA = null; if (setCrop(drag.start, p)) status("Cropped. Everything outside the yellow box is ignored."); draw(); }
  else if (tool === "keep" || tool === "erase") schedule();
  drag = null;
});
src.addEventListener("focus", () => { if (!cursor && W) cursor = { x: W / 2, y: H / 2 }; redraw(); });
src.addEventListener("blur", redraw);
src.addEventListener("keydown", (ev) => {
  if (!rgba) return;
  const step = (ev.shiftKey ? 0.08 : 0.025) * Math.max(W, H), mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
  cursor = cursor || { x: W / 2, y: H / 2 };
  if (mv) {
    ev.preventDefault();
    const nx = Math.max(0, Math.min(W - 1, cursor.x + mv[0] * step)), ny = Math.max(0, Math.min(H - 1, cursor.y + mv[1] * step));
    if (ev.altKey && (tool === "keep" || tool === "erase")) { stroke(cursor, { x: nx, y: ny }, tool === "keep" ? 1 : 2); schedule(); }
    cursor = { x: nx, y: ny }; redraw();
  } else if (ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    if (tool === "tap") tapAt(cursor);
    else if (tool === "eyes" || tool === "nose") faceTap(cursor);
    else if (tool === "keep" || tool === "erase") { pushUndo(); dab(cursor.x, cursor.y, tool === "keep" ? 1 : 2); draw(); schedule(); }
    else if (tool === "crop") {
      if (!cropA) { cropA = Object.assign({}, cursor); status("First corner set. Move to the opposite corner and press Enter."); }
      else { if (setCrop(cropA, cursor)) status("Cropped."); cropA = null; schedule(); }
      draw();
    }
  }
});

// ---------------------------------------------------------------- step 3: style + preview
function opts() {
  const det = +$("pxdetail").value;
  const base = Object.assign({}, PP.PRESETS[preset], preset === "game" ? CEL_DETAIL[det] : preset === "chunky" ? TOON_DETAIL[det]
    : preset === "portrait" ? PORTRAIT_DETAIL[det] : DETAIL[det]);
  const hasFace = $("pxface").checked && (face.eyes.length || face.nose);
  return Object.assign(base, {
    face: hasFace ? { eyes: face.eyes, nose: face.nose } : null,
    chibi: hasFace ? +$("pxchibi").value : 0, blush: $("pxblush").checked, mouth: $("pxmouth").value, eyes: $("pxeyes").value,
    size: +$("pxsize").value, colors: +$("pxcolors").value, outline: $("pxoutline").value,
    shadow: $("pxshadow").checked, dither: $("pxdither").checked ? (preset === "retro" ? PP.PRESETS.retro.dither : 0.45) : 0,
    backdrop: (document.querySelector('input[name="backdrop"]:checked') || {}).value || "none" });
}
let timer = 0;
function schedule() { clearTimeout(timer); timer = setTimeout(renderNow, 90); }
function renderNow() {
  if (!rgba) return;
  const m = finalMask();
  let n = 0; for (let k = 0; k < m.length; k += 7) if (m[k] > 127) n++;
  const out = $("pxout"), o = out.getContext("2d");
  o.clearRect(0, 0, out.width, out.height);
  if (n * 7 < W * H * 0.004) { sprite = null; saveOff(true); drawBefore(m); return; }
  const t0 = performance.now();
  sprite = PP.render({ width: W, height: H, data: rgba.data, mask: m }, opts());
  const c = spriteCanvas(sprite, 1);
  o.imageSmoothingEnabled = false; o.drawImage(c, 0, 0, out.width, out.height);
  out.classList.toggle("solid", opts().backdrop !== "none");
  saveOff(false);
  root.dataset.renderMs = Math.round(performance.now() - t0);
  drawBefore(m);
}
function drawBefore(m) {
  const b = $("pxbefore"), bc = b.getContext("2d"); bc.clearRect(0, 0, b.width, b.height);
  let x0 = W, y0 = H, x1 = -1, y1 = -1;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (m[y * W + x] > 127) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (x1 < 0) return;
  const t = document.createElement("canvas"); t.width = W; t.height = H;
  const tc = t.getContext("2d"), id = new ImageData(new Uint8ClampedArray(rgba.data), W, H);
  for (let k = 0; k < W * H; k++) id.data[k * 4 + 3] = m[k];
  tc.putImageData(id, 0, 0);
  const s = Math.min(b.width * 0.9 / (x1 - x0 + 1), b.height * 0.9 / (y1 - y0 + 1)), dw = (x1 - x0 + 1) * s, dh = (y1 - y0 + 1) * s;
  bc.drawImage(t, x0, y0, x1 - x0 + 1, y1 - y0 + 1, (b.width - dw) / 2, (b.height - dh) / 2, dw, dh);
}
function spriteCanvas(spr, scale) {
  const big = scale > 1 ? PP.upscale(spr, scale) : spr, c = document.createElement("canvas");
  c.width = big.width; c.height = big.height;
  c.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(big.data), big.width, big.height), 0, 0);
  return c;
}

function applyPreset(name) {
  preset = name; const p = PP.PRESETS[name];
  const sizes = p.sizes || [32, 48, 64], sel = $("pxsize");
  sel.replaceChildren(...sizes.map((n, k) => { const o = document.createElement("option"); o.value = String(n); o.textContent = `${SIZE_NAMES[k] || n} (${n} px)`; return o; }));
  sel.value = String(p.size); $("pxcolors").value = p.colors; $("pxcolorsv").textContent = p.colors;
  $("pxoutline").value = p.outline; $("pxshadow").checked = !!p.shadow; $("pxdither").checked = p.dither > 0;
  $("pxdetail").value = PRESET_UI[name].detail;
  $("pxface").checked = !!PRESET_UI[name].face;
  const ey = $("pxeyes");
  ey.replaceChildren(...PRESET_UI[name].eyes.map(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; return o; }));
  $("pxblush").checked = !!p.blush; $("pxmouth").value = p.mouth || "none"; ey.value = p.eyes || PRESET_UI[name].eyes[0][0]; $("pxchibi").value = String(p.chibi || 0);
  document.querySelectorAll("[data-preset]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.preset === name ? "true" : "false"));
  schedule();
}
document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => applyPreset(b.dataset.preset)));
["pxsize", "pxdetail", "pxoutline", "pxshadow", "pxdither", "pxface", "pxblush", "pxmouth", "pxeyes", "pxchibi"].forEach((id) => $(id).addEventListener("input", schedule));
$("pxcolors").addEventListener("input", () => { $("pxcolorsv").textContent = $("pxcolors").value; schedule(); });
document.querySelectorAll('input[name="backdrop"]').forEach((r) => r.addEventListener("change", schedule));
document.querySelectorAll(".pxba button").forEach((b) => b.addEventListener("click", () => {
  view = b.dataset.v; $("pxout").hidden = view !== "after"; $("pxbefore").hidden = view !== "before";
  document.querySelectorAll(".pxba button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
}));

// ---------------------------------------------------------------- save / download / start over
const pngBlob = (c) => new Promise((res) => c.toBlob(res, "image/png"));
$("pxdl").addEventListener("click", async () => {
  if (!sprite) return;
  const blob = await pngBlob(spriteCanvas(sprite, Math.ceil(512 / sprite.width)));
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${cfg.slug}-pixel-pal.png`;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
});
async function save(btn) {
  if (!sprite) return;
  const msg = $("pxsaved");
  if (!$("pxsavebtn")) return;
  $("pxsavebtn").disabled = $("pxsave2").disabled = true; msg.textContent = "Saving…";
  const fd = new FormData();
  fd.append("csrf", cfg.csrf); fd.append("primary", btn.dataset.primary);
  fd.append("sprite", await pngBlob(spriteCanvas(sprite, 1)), "sprite.png");
  try {
    const r = await fetch(`/me/dogs/${cfg.dog}/pixel`, { method: "POST", body: fd, credentials: "same-origin" });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "Save failed");
    msg.textContent = btn.dataset.primary === "1" ? `Saved! The pixel pal is now ${cfg.name}'s profile picture. ` : `Saved to ${cfg.name}'s page. `;
    const a = document.createElement("a"); a.href = j.page; a.textContent = `See ${cfg.name}'s page`; msg.append(a);
  } catch (err) {
    msg.textContent = (err && err.message) || "We couldn't save that. Please try again.";
  }
  $("pxsavebtn").disabled = $("pxsave2").disabled = false;
}
if ($("pxsavebtn")) {
  $("pxsavebtn").addEventListener("click", () => save($("pxsavebtn")));
  $("pxsave2").addEventListener("click", () => save($("pxsave2")));
}

// ---------------------------------------------------------------- AI paint (hidden test page only: cfg.ai)
// The selected dog is cropped from the full-size photo, painted by a small AI model (AnimeGANv2 face paint v2, MIT)
// in a worker on this device, pasted back over the photo, and then pixelated by pixelpal.js as usual.
const AI_SIZE = 512, AI_EST_MS = 45000;      // painting estimate for the progress bar (phones: ~10 s to a few minutes)
function aiReset() {
  if (!cfg.ai) return;
  $("pxaion").checked = true; $("pxaion").disabled = true; $("pxaigo").disabled = aiBusy;
  $("pxaigo").textContent = "Paint with AI"; if (!aiBusy) { $("pxaibarw").hidden = true; $("pxaist").textContent = ""; }
}
function aiBox(m) {
  let x0 = W, y0 = H, x1 = -1, y1 = -1;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (m[y * W + x] > 127) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (x1 < 0) return null;
  const side = Math.max(x1 - x0 + 1, y1 - y0 + 1) * 1.1;   // square, a little room around the dog
  return { x: (x0 + x1 + 1) / 2 - side / 2, y: (y0 + y1 + 1) / 2 - side / 2, side };
}
function aiProgress(pct, text) { $("pxaibarw").hidden = false; $("pxaibar").value = Math.round(pct); if (text) $("pxaist").textContent = text; }
function aiPaint() {
  if (!cfg.ai || aiBusy || !photoRgba) return Promise.resolve(false);
  const box = aiBox(finalMask());
  if (!box) { $("pxaist").textContent = `Select ${cfg.name} first, then paint.`; return Promise.resolve(false); }
  aiBusy = true; $("pxaigo").disabled = true;
  const iw = origImg.naturalWidth || origImg.width, k = iw / W;            // working -> original pixels
  const c = document.createElement("canvas"); c.width = c.height = AI_SIZE;
  const cx = c.getContext("2d", { willReadFrequently: true }), z = AI_SIZE / (box.side * k);
  cx.fillStyle = "#808080"; cx.fillRect(0, 0, AI_SIZE, AI_SIZE); cx.imageSmoothingQuality = "high";
  cx.drawImage(origImg, -box.x * k * z, -box.y * k * z, iw * z, (origImg.naturalHeight || origImg.height) * z);
  const px = cx.getImageData(0, 0, AI_SIZE, AI_SIZE).data, N = AI_SIZE * AI_SIZE, inp = new Float32Array(3 * N);
  for (let i = 0; i < N; i++) { inp[i] = px[i * 4] / 127.5 - 1; inp[N + i] = px[i * 4 + 1] / 127.5 - 1; inp[2 * N + i] = px[i * 4 + 2] / 127.5 - 1; }
  if (!worker) worker = new Worker("/pixelai-worker.js?v=1", { type: "module" });
  const t0 = performance.now(); let paintT = 0, tick = 0;
  aiProgress(1, "Getting the AI painter ready… This may take a few minutes. Keep this page open.");
  return new Promise((resolve) => {
    const finish = (ok) => { clearInterval(tick); aiBusy = false; $("pxaigo").disabled = false; resolve(ok); };
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === "progress") {
        if (m.stage === "download") aiProgress(2 + m.pct * 0.38, `Downloading the AI painter (only the first time): ${m.detail}. This may take a few minutes.`);
        else if (m.stage === "runtime") aiProgress(m.pct ? 42 : 2, `${m.detail}…`);
        else if (m.stage === "paint") {
          paintT = performance.now(); clearInterval(tick);
          tick = setInterval(() => {
            const t = performance.now() - paintT, sec = Math.round(t / 1000);
            aiProgress(45 + 54 * (1 - Math.exp(-t / AI_EST_MS)), `Painting ${cfg.name}… ${sec}s so far. This may take a few minutes on a phone.`);
          }, 500);
          aiProgress(45, `Painting ${cfg.name}… This may take a few minutes on a phone.`);
        }
      } else if (m.type === "done") {
        const o = document.createElement("canvas"); o.width = o.height = AI_SIZE;
        const img = new ImageData(AI_SIZE, AI_SIZE), y = m.pixels, d = img.data;
        for (let i = 0; i < N; i++) {
          d[i * 4] = (y[i] + 1) * 127.5; d[i * 4 + 1] = (y[N + i] + 1) * 127.5; d[i * 4 + 2] = (y[2 * N + i] + 1) * 127.5; d[i * 4 + 3] = 255;
        }
        o.getContext("2d").putImageData(img, 0, 0);
        const t = document.createElement("canvas"); t.width = W; t.height = H;
        const tc = t.getContext("2d", { willReadFrequently: true });
        tc.putImageData(photoRgba, 0, 0); tc.imageSmoothingQuality = "high";
        tc.drawImage(o, box.x, box.y, box.side, box.side);
        painted = tc.getImageData(0, 0, W, H);
        rgba = $("pxaion").checked ? painted : photoRgba; $("pxaion").disabled = false;
        root.dataset.aiMs = m.ms; root.dataset.aiTotalMs = Math.round(performance.now() - t0); root.dataset.aiBackend = m.backend;
        aiProgress(100, `Done in ${Math.max(1, Math.round((performance.now() - t0) / 1000))}s. If you change the selection a lot, paint again.`);
        $("pxaigo").textContent = "Paint again";
        if (preset !== "portrait") applyPreset("portrait"); else schedule();
        draw(); finish(true);
      } else if (m.type === "error") {
        console.warn("pixel pal AI:", m.message);
        aiProgress(0, `The AI painter couldn't run on this device (${m.message}). The regular styles still work.`);
        finish(false);
      }
    };
    worker.onerror = (ev) => { aiProgress(0, "The AI painter couldn't start on this device. The regular styles still work."); console.warn(ev); finish(false); };
    worker.postMessage({ type: "run", pixels: inp }, [inp.buffer]);
  });
}
if (cfg.ai) {
  $("pxaigo").addEventListener("click", () => aiPaint());
  $("pxaion").addEventListener("change", () => { if (!painted) return; rgba = $("pxaion").checked ? painted : photoRgba; draw(); schedule(); });
}
$("pxreset").addEventListener("click", () => {
  rgba = null; sprite = null; auto = edit = null; undo = []; cursor = null; photoRgba = painted = origImg = null;
  $("pxed").hidden = true; $("pxpick").hidden = false; status(""); $("pxsaved").textContent = "";
  $("pxpick").scrollIntoView({ behavior: "smooth", block: "start" });
});
applyPreset("game");
loadSeg();
window.__pixelpal = { status: () => segState, useImage, tapAt: (x, y) => tapAt({ x: x * W, y: y * H }), setTool,
  eraseRect: (x0, y0, x1, y1) => { pushUndo(); for (let y = Math.round(y0 * H); y < Math.round(y1 * H); y++) edit.fill(2, y * W + Math.round(x0 * W), y * W + Math.round(x1 * W)); draw(); schedule(); },
  applyPreset, sprite: () => sprite, aiPaint, aiPainted: () => !!painted, rerender: renderNow, guessFace: guessFaceNow,
  setFace: (f) => { face = { eyes: (f && f.eyes) || [], nose: (f && f.nose) || null }; faceStatus(); draw(); schedule(); },
  face: () => JSON.parse(JSON.stringify(face)), faceTap: (x, y) => faceTap({ x: x * W, y: y * H }),
  state: () => ({ W, H, data: Array.from(rgba.data), mask: Array.from(finalMask()) }) };
