// Unit tests for public/pixelpal.js (the shared, DOM-free pixel-art pipeline). Run: node tests/test_pixelpal.js
// (also run from Python by tests/test_pixel.py so `python -m unittest discover -s tests` covers it).
"use strict";
const assert = require("assert");
const PP = require("../public/pixelpal.js");

// a synthetic "dog": brown ellipse with darker ears, two dark eyes and a small red tag, on a noisy green lawn
function scene(W = 240, H = 180) {
  const data = new Uint8ClampedArray(W * H * 4), mask = new Uint8Array(W * H);
  let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4, inDog = ((x - 120) / 80) ** 2 + ((y - 100) / 55) ** 2 <= 1;
    let c = [60 + rnd() * 30, 150 + rnd() * 40, 50 + rnd() * 20];
    if (inDog) {
      c = [150 + rnd() * 20, 105 + rnd() * 15, 70 + rnd() * 10];
      if (y < 75 && Math.abs(x - 120) > 40) c = [90, 60, 40];
      if (((x - 95) ** 2 + (y - 90) ** 2) < 30 || ((x - 145) ** 2 + (y - 90) ** 2) < 30) c = [20, 15, 12];
      if (((x - 120) ** 2 + (y - 135) ** 2) < 26) c = [210, 30, 35];
      mask[y * W + x] = 255;
    }
    data[i] = c[0]; data[i + 1] = c[1]; data[i + 2] = c[2]; data[i + 3] = 255;
  }
  return { width: W, height: H, data, mask };
}
const px = (s, x, y) => Array.from(s.data.slice((y * s.width + x) * 4, (y * s.width + x) * 4 + 4));
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("every preset returns an N x N RGBA sprite within its color budget", () => {
  for (const [name, p] of Object.entries(PP.PRESETS)) {
    const s = PP.render(scene(), p);
    assert.strictEqual(s.width, p.size, name); assert.strictEqual(s.height, p.size, name);
    assert.strictEqual(s.data.length, p.size * p.size * 4, name);
    assert.ok(s.palette.length >= 2 && s.palette.length <= p.colors + 2, `${name}: ${s.palette.length} colors`);
    assert.ok(s.grid.w <= p.size - 4 && s.grid.h <= p.size - 4, name);
  }
});

test("sizes are clamped to 16..128 and the subject fills the grid", () => {
  assert.strictEqual(PP.render(scene(), { size: 4 }).width, 16);
  assert.strictEqual(PP.render(scene(), { size: 999 }).width, 128);
  const s = PP.render(scene(), { size: 48 });
  assert.ok(s.grid.w >= 40, "wide subject uses the full width: " + s.grid.w);
});

test("transparent background: alpha is only 0, 255, or the soft shadow", () => {
  const s = PP.render(scene(), { size: 48, backdrop: "none", shadow: true });
  const alphas = new Set(); for (let i = 3; i < s.data.length; i += 4) alphas.add(s.data[i]);
  for (const a of alphas) assert.ok(a === 0 || a === 255 || a === 72, "alpha " + a);
  assert.deepStrictEqual(px(s, 0, 0), [0, 0, 0, 0]);
  const noShadow = PP.render(scene(), { size: 48, shadow: false });
  for (let i = 3; i < noShadow.data.length; i += 4) assert.ok(noShadow.data[i] === 0 || noShadow.data[i] === 255);
});

test("backdrops fill the square with the brand color", () => {
  const s = PP.render(scene(), { size: 32, backdrop: "cream" });
  assert.deepStrictEqual(px(s, 0, 0), PP.BACKDROPS.cream.concat(255));
  for (let i = 3; i < s.data.length; i += 4) assert.strictEqual(s.data[i], 255);
});

test("the lawn never bleeds into the sprite", () => {
  const s = PP.render(scene(), { size: 48, outline: "none", shadow: false });
  for (let i = 0; i < s.data.length; i += 4) {
    if (!s.data[i + 3]) continue;
    const [r, g, b] = [s.data[i], s.data[i + 1], s.data[i + 2]];
    assert.ok(!(g > r + 40 && g > b + 40), `green pixel ${r},${g},${b}`);
  }
});

test("dark outline wraps the silhouette", () => {
  const s = PP.render(scene(), { size: 48, outline: "dark", shadow: false });
  const N = s.width, op = (x, y) => x >= 0 && y >= 0 && x < N && y < N && s.data[(y * N + x) * 4 + 3] === 255;
  let edge = 0, dark = 0;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    if (!op(x, y)) continue;
    if (!op(x - 1, y) || !op(x + 1, y) || !op(x, y - 1) || !op(x, y + 1)) {
      edge++; const [r, g, b] = px(s, x, y); if (r + g + b < 200) dark++;
    }
  }
  assert.ok(edge > 50 && dark / edge > 0.95, `${dark}/${edge} edge pixels dark`);
});

test("small vivid details (the red tag) survive as an accent color", () => {
  const s = PP.render(scene(), { size: 48, colors: 8 });
  let red = 0;
  for (let i = 0; i < s.data.length; i += 4) if (s.data[i + 3] && s.data[i] > 150 && s.data[i + 1] < 90 && s.data[i + 2] < 90) red++;
  assert.ok(red >= 1, "red tag kept");
  let eyes = 0;
  for (let i = 0; i < s.data.length; i += 4) if (s.data[i + 3] && s.data[i] + s.data[i + 1] + s.data[i + 2] < 120) eyes++;
  assert.ok(eyes >= 2, "dark eyes kept");
});

test("deterministic: the same input gives the same sprite", () => {
  const a = PP.render(scene(), PP.PRESETS.retro), b = PP.render(scene(), PP.PRESETS.retro);
  assert.deepStrictEqual(Buffer.from(a.data), Buffer.from(b.data));
});

test("dither and colors change the result; empty masks don't throw", () => {
  const a = PP.render(scene(), { size: 32, dither: 0 }), b = PP.render(scene(), { size: 32, dither: 0.6 });
  assert.notDeepStrictEqual(Buffer.from(a.data), Buffer.from(b.data));
  const sc = scene(); sc.mask.fill(0);
  const e = PP.render(sc, { size: 32, shadow: false });
  assert.strictEqual(e.width, 32);
  for (let i = 3; i < e.data.length; i += 4) assert.strictEqual(e.data[i], 0);
});

test("upscale is exact nearest-neighbor", () => {
  const s = PP.render(scene(), { size: 32 }), u = PP.upscale(s, 4);
  assert.strictEqual(u.width, 128);
  for (const [x, y] of [[0, 0], [10, 20], [17, 31], [31, 5]])
    for (const [dx, dy] of [[0, 0], [3, 3], [1, 2]]) assert.deepStrictEqual(px(u, x * 4 + dx, y * 4 + dy), px(s, x, y));
});

test("OKLab round trip and k-means sanity", () => {
  for (const c of [[0, 0, 0], [255, 255, 255], [200, 32, 30], [251, 179, 33], [42, 38, 34]]) {
    const back = PP.toRgb(...PP.toLab(...c));
    back.forEach((v, i) => assert.ok(Math.abs(v - c[i]) <= 1, `${c} -> ${back}`));
  }
  const pts = [], w = [];
  for (let i = 0; i < 50; i++) { pts.push([0.2, 0, 0]); pts.push([0.8, 0.1, 0]); w.push(1, 1); }
  const k = PP.kmeans(pts, w, 2, 10).sort((a, b) => a[0] - b[0]);
  assert.ok(Math.abs(k[0][0] - 0.2) < 1e-9 && Math.abs(k[1][0] - 0.8) < 1e-9);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n     " + e.message); }
}
console.log(`${tests.length - failed}/${tests.length} pixelpal tests passed`);
process.exit(failed ? 1 : 0);
