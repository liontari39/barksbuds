// Unit tests for public/pixelpal.js (the shared, DOM-free pixel-art pipeline). Run: node tests/test_pixelpal.js
// (also run from Python by tests/test_pixel.py so `python -m unittest discover -s tests` covers it).
"use strict";
const assert = require("assert");
const PP = require("../public/pixelpal.js");

// a synthetic "dog": brown ellipse with darker ears, two dark eyes and a small red tag, on a noisy green lawn
function scene(W = 240, H = 180, tagY = 135) {
  const data = new Uint8ClampedArray(W * H * 4), mask = new Uint8Array(W * H);
  let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4, inDog = ((x - 120) / 80) ** 2 + ((y - 100) / 55) ** 2 <= 1;
    let c = [60 + rnd() * 30, 150 + rnd() * 40, 50 + rnd() * 20];
    if (inDog) {
      c = [150 + rnd() * 20, 105 + rnd() * 15, 70 + rnd() * 10];
      if (y < 75 && Math.abs(x - 120) > 40) c = [90, 60, 40];
      if (((x - 95) ** 2 + (y - 90) ** 2) < 30 || ((x - 145) ** 2 + (y - 90) ** 2) < 30) c = [20, 15, 12];
      if (((x - 120) ** 2 + (y - tagY) ** 2) < 26) c = [210, 30, 35];
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
    const m = p.toon ? 2 : 4; assert.ok(s.grid.w <= p.size - m && s.grid.h <= p.size - m, name);
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

// ---------------------------------------------------------------- Game Sprite preset
const FACE = { eyes: [[95 / 240, 90 / 180], [145 / 240, 90 / 180]], nose: [120 / 240, 112 / 180] };
// the default "game" preset is the photo-detailed 48 px cel look; these tests cover it
const G = (extra) => PP.render(scene(), Object.assign({}, PP.PRESETS.game, { backdrop: "none" }, extra || {}));
const rgbOf = (lab) => PP.toRgb(lab[0], lab[1], lab[2]);
const near = (a, b, tol = 2) => Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol && Math.abs(a[2] - b[2]) <= tol;
function findColor(s, rgb, x0 = 0, y0 = 0, x1 = s.width, y1 = s.height) {
  for (let y = Math.max(0, y0); y < Math.min(s.height, y1); y++) for (let x = Math.max(0, x0); x < Math.min(s.width, x1); x++) {
    const p = px(s, x, y); if (p[3] === 255 && near(p, rgb)) return [x, y];
  }
  return null;
}
// where a source point lands on the sprite (scene's dog bbox is x 40..200, y 45..155)
const toSprite = (s, sx, sy) => [s.grid.x + (sx - 40) / 161 * s.grid.w, s.grid.y + (sy - 45) / 111 * s.grid.h];

test("Game Sprite is the default preset: 48 px (32/48/64) cel look with friendly eyes", () => {
  assert.strictEqual(Object.keys(PP.PRESETS)[0], "game");
  const p = PP.PRESETS.game;
  assert.strictEqual(p.size, 48); assert.deepStrictEqual(p.sizes, [32, 48, 64]);
  assert.ok(p.cel && !p.toon); assert.strictEqual(p.eyes, "friendly"); assert.strictEqual(p.outline, "ink");
  assert.strictEqual(G({ face: null }).width, 48);
});

test("friendly eyes: dark pupil + white shine, no colored iris ring on a light coat", () => {
  const f = G({ face: FACE, chibi: 0 }), ringed = G({ face: FACE, chibi: 0, eyes: "" });
  assert.notDeepStrictEqual(Array.from(f.data), Array.from(ringed.data), "friendly differs from the ringed eye");
  for (const [sx, sy] of [[95, 90], [145, 90]]) {
    const [gx, gy] = toSprite(f, sx, sy);
    const sh = findColor(f, [255, 255, 255], Math.floor(gx - 4), Math.floor(gy - 4), Math.ceil(gx + 4), Math.ceil(gy + 4));
    assert.ok(sh, "shine near the eye");
    // the 3x3 around the shine is only white or dark (no saturated iris pixels)
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const q = px(f, sh[0] + dx, sh[1] + dy); if (q[3] !== 255) continue;
      const white = q[0] === 255 && q[1] === 255 && q[2] === 255, sat = Math.max(q[0], q[1], q[2]) - Math.min(q[0], q[1], q[2]);
      assert.ok(white || (q[0] + q[1] + q[2] < 200 && sat < 40), "eye pixel " + q.slice(0, 3));
    }
  }
});

test("cel look: flat colors, ink outline, N x N", () => {
  const s = G({ face: null });
  assert.strictEqual(s.width, 48); assert.strictEqual(s.height, 48);
  assert.ok(s.palette.length <= 16, "few colors: " + s.palette.length);
  // every opaque pixel touching the transparent outside is the one ink color
  const ink = new Set();
  for (let y = 0; y < s.height; y++) for (let x = 0; x < s.width; x++) {
    const p = px(s, x, y); if (p[3] !== 255) continue;
    const out = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => { const q = px(s, x + dx, y + dy); return x + dx < 0 || y + dy < 0 || x + dx >= s.width || y + dy >= s.height || q[3] === 0; });
    if (out) ink.add(p.slice(0, 3).join(","));
  }
  assert.strictEqual(ink.size, 1, "one outline color: " + [...ink].join(" "));
  const c = [...ink][0].split(",").map(Number);
  assert.ok(Math.max(...c) < 90, "outline is very dark: " + c);
});

test("cel look eye stamps: white highlights at the tapped eyes, none without taps", () => {
  const plain = G({ face: null }), white = [255, 255, 255];
  assert.strictEqual(findColor(plain, white), null, "no pure white without face stickers");
  const s = G({ face: FACE, chibi: 0 });
  for (const [sx, sy] of [[95, 90], [145, 90]]) {
    const [gx, gy] = toSprite(s, sx, sy);
    assert.ok(findColor(s, white, Math.floor(gx - 4), Math.floor(gy - 4), Math.ceil(gx + 4), Math.ceil(gy + 4)), `eye shine near ${gx.toFixed(1)},${gy.toFixed(1)}`);
  }
  // a dark pupil sits next to each shine
  const shine = findColor(s, white);
  let darkest = 999;
  for (let dy = -1; dy <= 2; dy++) for (let dx = -1; dx <= 2; dx++) { const q = px(s, shine[0] + dx, shine[1] + dy); darkest = Math.min(darkest, q[0] + q[1] + q[2]); }
  assert.ok(darkest < 200, "dark pupil beside the shine: " + darkest);
});

test("cel look nose, blush and tongue stamps use their colors only when asked", () => {
  const shineRgb = rgbOf(PP.STAMP_COLORS.h), blushRgb = rgbOf(PP.STAMP_COLORS.blush), tongueRgb = rgbOf(PP.STAMP_COLORS.t);
  const s = G({ face: FACE, chibi: 0, blush: true, mouth: "tongue" });
  const [nx, ny] = toSprite(s, 120, 112);
  assert.ok(findColor(s, shineRgb, Math.floor(nx - 4), Math.floor(ny - 4), Math.ceil(nx + 4), Math.ceil(ny + 4)), "nose shine near the nose tap");
  assert.ok(findColor(s, blushRgb), "blush");
  const t = findColor(s, tongueRgb); assert.ok(t && t[1] > ny, "tongue below the nose");
  const off = G({ face: FACE, chibi: 0, blush: false, mouth: "none" });
  assert.strictEqual(findColor(off, blushRgb), null); assert.strictEqual(findColor(off, tongueRgb), null);
  assert.ok(findColor(off, shineRgb), "nose stays without mouth/blush");
  const noFace = G({ face: FACE, chibi: 0, faceStamps: false });
  assert.strictEqual(findColor(noFace, [255, 255, 255]), null, "stickers can be turned off");
});

test("big head (chibi) enlarges the head and moves the face points apart", () => {
  const src = scene(), face = { eyes: [[95, 90], [145, 90]], nose: [120, 112] };
  const w = PP.bigHead(src, face, 1);
  const d0 = face.eyes[1][0] - face.eyes[0][0], d1 = w.face.eyes[1][0] - w.face.eyes[0][0];
  assert.ok(d1 > d0 * 1.12, `eyes spread ${d0} -> ${d1.toFixed(1)}`);
  const area = (m) => m.reduce((a, v) => a + (v > 127 ? 1 : 0), 0);
  assert.ok(area(w.src.mask) >= area(src.mask), "the silhouette does not shrink");
  assert.strictEqual(PP.bigHead(src, face, 0).face.eyes[0][0].toFixed(3), "95.000", "amount 0 is a no-op");
  // the eye stamps grow with the head
  const a = G({ face: FACE, chibi: 0 }), b = G({ face: FACE, chibi: 1.5 });
  const count = (s) => { let n = 0; for (let i = 0; i < s.data.length; i += 4) if (s.data[i] === 255 && s.data[i + 1] === 255 && s.data[i + 2] === 255) n++; return n; };
  assert.ok(count(b) >= count(a), "eye shines at least as big with a big head");
});

test("guessFace finds the two eyes of the synthetic dog (or declines)", () => {
  const g = PP.guessFace(scene());
  assert.ok(g, "found a face");
  const [l, r] = g.eyes;
  assert.ok(Math.abs(l[0] * 240 - 95) < 8 && Math.abs(l[1] * 180 - 90) < 8, "left eye " + l.map((v) => v.toFixed(3)));
  assert.ok(Math.abs(r[0] * 240 - 145) < 8 && Math.abs(r[1] * 180 - 90) < 8, "right eye " + r.map((v) => v.toFixed(3)));
  // a featureless blob has no face
  const flat = scene(); for (let i = 0; i < flat.data.length; i += 4) if (flat.mask[i / 4]) { flat.data[i] = 150; flat.data[i + 1] = 110; flat.data[i + 2] = 75; }
  assert.strictEqual(PP.guessFace(flat), null);
});

test("mergeIslands folds specks into their surroundings but keeps vivid accents", () => {
  const w = 6, h = 6, pal = [[0.6, 0.02, 0.03], [0.4, 0.02, 0.03], [0.55, 0.2, 0.1]];
  const ix = new Int16Array(w * h).fill(0); ix[2 * w + 2] = 1; ix[3 * w + 4] = 2;
  PP.mergeIslands(ix, w, h, pal, 3);
  assert.strictEqual(ix[2 * w + 2], 0, "grey speck merged"); assert.strictEqual(ix[3 * w + 4], 2, "vivid accent kept");
});

test("celShade lights the top-left rim and shades the bottom-right", () => {
  const w = 8, h = 8, pal = [[0.6, 0.01, 0.02]], ix = new Int16Array(w * h).fill(-1);
  for (let y = 1; y < 7; y++) for (let x = 1; x < 7; x++) ix[y * w + x] = 0;
  PP.celShade(ix, w, h, pal, 1, false);
  assert.strictEqual(pal.length, 3, "one highlight + one shadow tone");
  assert.ok(pal[ix[1 * w + 3]][0] > 0.6, "top rim lighter"); assert.ok(pal[ix[6 * w + 3]][0] < 0.6, "bottom rim darker");
  assert.strictEqual(ix[3 * w + 3], 0, "interior keeps the base color");
});

test("cel look is deterministic and turns a black coat into readable charcoal", () => {
  const a = G({ face: FACE }), b = G({ face: FACE });
  assert.deepStrictEqual(Array.from(a.data), Array.from(b.data));
  const blk = scene(); for (let i = 0; i < blk.data.length; i += 4) if (blk.mask[i / 4]) { const v = 18 + (i % 13); blk.data[i] = v; blk.data[i + 1] = v; blk.data[i + 2] = v + 2; }
  const s = PP.render(blk, Object.assign({}, PP.PRESETS.game, { backdrop: "none" }));
  const [cx, cy] = [s.grid.x + (s.grid.w >> 1), s.grid.y + (s.grid.h >> 1)], c = px(s, cx, cy);
  assert.ok(c[0] >= 30 && c[0] <= 90, "charcoal body, not pitch black: " + c);
});

// ---------------------------------------------------------------- Chunky (toon) preset: 32 px, cute, few colors
const T = (extra, src) => PP.render(src || scene(), Object.assign({}, PP.PRESETS.chunky, { backdrop: "none" }, extra || {}));
const colorsOf = (s) => { const c = new Set(); for (let i = 0; i < s.data.length; i += 4) if (s.data[i + 3] === 255) c.add(s.data[i] + "," + s.data[i + 1] + "," + s.data[i + 2]); return c; };
const countRgb = (s, rgb, tol = 2) => { let n = 0; for (let i = 0; i < s.data.length; i += 4) if (s.data[i + 3] === 255 && near([s.data[i], s.data[i + 1], s.data[i + 2]], rgb, tol)) n++; return n; };
const WHITE = rgbOf(PP.TOON_COLORS.white);
function blackDog() {
  const blk = scene();
  for (let i = 0; i < blk.data.length; i += 4) if (blk.mask[i / 4]) {
    const x = (i / 4) % 240, y = Math.floor(i / 4 / 240);
    if (((x - 120) ** 2 + (y - 135) ** 2) < 26) continue;   // keep the red tag
    const v = 18 + (i % 13); blk.data[i] = v; blk.data[i + 1] = v; blk.data[i + 2] = v + 2;
  }
  return blk;
}

test("Chunky is the second preset: 32 px (24/32/40) toon, one ink outline", () => {
  assert.strictEqual(Object.keys(PP.PRESETS)[1], "chunky");
  const p = PP.PRESETS.chunky;
  assert.strictEqual(p.size, 32); assert.deepStrictEqual(p.sizes, [24, 32, 40]); assert.ok(p.toon);
  for (const size of p.sizes) {
    const s = T({ face: FACE, size });
    assert.strictEqual(s.width, size); assert.strictEqual(s.height, size);
    const ink = new Set();
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      const q = px(s, x, y); if (q[3] !== 255) continue;
      const out = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => x + dx < 0 || y + dy < 0 || x + dx >= size || y + dy >= size || px(s, x + dx, y + dy)[3] === 0);
      if (out) ink.add(q.slice(0, 3).join(","));
    }
    assert.strictEqual(ink.size, 1, size + ": one outline color " + [...ink].join(" "));
    assert.ok(Math.max(...[...ink][0].split(",").map(Number)) < 90, "dark outline");
  }
});

test("Chunky keeps the palette small (8-12 colors incl. outline) for light and dark coats", () => {
  for (const size of [24, 32, 40]) for (const src of [scene(), blackDog()]) {
    const n = colorsOf(T({ face: FACE, size, mouth: "tongue", blush: true }, src)).size;
    assert.ok(n >= 5 && n <= 13, `${size}px: ${n} colors`);
  }
});

test("Chunky eyes: small dark dots with one white shine each, no colored iris or ring", () => {
  assert.strictEqual(countRgb(T({ face: null }), WHITE), 0, "no shine without face points");
  const s = T({ face: FACE, chibi: 0 });
  assert.strictEqual(countRgb(s, WHITE), 2, "exactly one 1-px shine per eye");
  for (let y = 0; y < s.height; y++) for (let x = 0; x < s.width; x++) {
    if (!near(px(s, x, y), WHITE)) continue;
    // the eye is the shine plus dark ink pixels: at most 2x2, and nothing colorful touching it
    let dark = 0;
    for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [-1, 0], [0, -1]]) { const q = px(s, x + dx, y + dy); if (q[3] === 255 && q[0] + q[1] + q[2] < 200) dark++; }
    assert.ok(dark >= 1 && dark <= 3, "dark eye pixels next to the shine: " + dark);
  }
  const happy = T({ face: FACE, chibi: 0, eyes: "happy" });
  assert.strictEqual(countRgb(happy, WHITE), 0, "closed happy eyes have no shine");
});

test("Chunky face: light muzzle, rounded nose, blush/tongue only when asked, stickers can be off", () => {
  const s = T({ face: FACE, chibi: 0, blush: true, mouth: "tongue" });
  const tongue = rgbOf(PP.TOON_COLORS.tongue), blush = rgbOf(PP.TOON_COLORS.blush);
  assert.ok(countRgb(s, tongue) >= 1, "tongue"); assert.ok(countRgb(s, blush) >= 1 && countRgb(s, blush) <= 4, "small blush");
  // muzzle: lighter than the coat around the nose
  const [nx, ny] = toSprite(s, 120, 118); let light = 0;
  for (let y = Math.floor(ny - 2); y <= ny + 3; y++) for (let x = Math.floor(nx - 4); x <= nx + 4; x++) { const q = px(s, x, y); if (q[3] === 255 && q[0] > 215 && q[1] > 190) light++; }
  assert.ok(light >= 4, "cream muzzle around the nose: " + light);
  const off = T({ face: FACE, chibi: 0, blush: false, mouth: "none" });
  assert.strictEqual(countRgb(off, tongue), 0); assert.strictEqual(countRgb(off, blush), 0);
  assert.strictEqual(countRgb(T({ face: FACE, faceStamps: false }), WHITE), 0, "stickers off");
});

test("Chunky turns a small red tag into a clear little red heart", () => {
  // the tag hangs on the collar, well below the nose (a pink spot right under the nose would be a tongue)
  const s = T({ face: FACE, chibi: 0 }, scene(240, 180, 146)), heart = rgbOf(PP.TOON_COLORS.heart), hi = rgbOf(PP.TOON_COLORS.heartHi);
  const n = countRgb(s, heart) + countRgb(s, hi);
  assert.ok(n >= 5 && n <= 7, "a 3x3 heart: " + n);
  const [tx, ty] = toSprite(s, 120, 146), at = findColor(s, heart, Math.floor(tx - 3), Math.floor(ty - 3), Math.ceil(tx + 4), Math.ceil(ty + 4));
  assert.ok(at, "heart sits where the tag was");
  const small = T({ face: FACE, chibi: 0, size: 24 }, scene(240, 180, 146));
  assert.ok(countRgb(small, heart) + countRgb(small, hi) >= 2, "a 2px heart at 24 px");
});

test("Chunky black coat: cool charcoal with a soft blue-grey highlight, deterministic", () => {
  const a = T({ face: FACE }, blackDog()), b = T({ face: FACE }, blackDog());
  assert.deepStrictEqual(Array.from(a.data), Array.from(b.data));
  const cols = [...colorsOf(a)].map((c) => c.split(",").map(Number));
  assert.ok(cols.some(([r, g, bb]) => r >= 35 && r <= 70 && bb >= r), "charcoal base");
  assert.ok(cols.some(([r, g, bb]) => r >= 60 && bb > r + 8), "blue-grey highlight");
  assert.ok(cols.some(([r, g, bb]) => r > 110 && Math.abs(r - bb) < 30), "grey muzzle");
});

test("regularize makes big flat regions: majority passes, then small islands merge", () => {
  const w = 10, h = 10, lbl = new Int16Array(w * h).fill(0);
  lbl[2 * w + 2] = 1; lbl[2 * w + 3] = 1;                      // a 2-cell speck
  for (let y = 5; y < 10; y++) for (let x = 5; x < 10; x++) lbl[y * w + x] = 2;   // a 25-cell patch
  lbl[7 * w + 7] = 0;                                          // a hole in the patch
  lbl[0] = -1;                                                 // background stays background
  PP.regularize(lbl, w, h, 1, 4);
  assert.strictEqual(lbl[2 * w + 2], 0, "speck merged"); assert.strictEqual(lbl[7 * w + 7], 2, "hole filled");
  assert.strictEqual(lbl[6 * w + 6], 2, "big patch kept"); assert.strictEqual(lbl[0], -1);
});

test("roundAlpha rounds square corners but keeps a 2px leg", () => {
  const w = 12, h = 12, a = new Uint8Array(w * h);
  for (let y = 1; y < 7; y++) for (let x = 1; x < 11; x++) a[y * w + x] = 1;     // body
  for (let y = 7; y < 11; y++) for (let x = 2; x < 4; x++) a[y * w + x] = 1;     // leg
  PP.roundAlpha(a, w, h);
  assert.strictEqual(a[1 * w + 10], 0, "corner rounded"); assert.strictEqual(a[4 * w + 5], 1, "body kept");
  assert.strictEqual(a[9 * w + 2] + a[9 * w + 3], 2, "leg kept");
  const b = new Uint8Array(w * h);                                             // hair-thin 1-px bits go: chunky silhouettes only
  for (let y = 1; y < 6; y++) for (let x = 1; x < 11; x++) b[y * w + x] = 1;
  for (let y = 6; y < 11; y++) b[y * w + 5] = 1;
  PP.roundAlpha(b, w, h);
  assert.strictEqual(b[9 * w + 5] + b[10 * w + 5], 0, "thin stick removed"); assert.strictEqual(b[3 * w + 5], 1, "body kept");
});

test("stubby shortens the body below the head and leaves the face where it was", () => {
  const src = scene(), face = { eyes: [[70, 70], [100, 70]], nose: [85, 85] };
  const w = PP.stubby(src, face, 1);
  const bottom = (m) => { for (let y = src.height - 1; y >= 0; y--) for (let x = 0; x < src.width; x++) if (m[y * src.width + x] > 127) return y; return -1; };
  const right = (m) => { for (let x = src.width - 1; x >= 0; x--) for (let y = 0; y < src.height; y++) if (m[y * src.width + x] > 127) return x; return -1; };
  assert.ok(bottom(w.src.mask) < bottom(src.mask) - 3, "shorter legs");
  assert.ok(right(w.src.mask) < right(src.mask) - 3, "shorter body");
  assert.deepStrictEqual(w.face.eyes.map((e) => e.map((v) => Math.round(v))), [[70, 70], [100, 70]], "face stays put");
  assert.strictEqual(PP.stubby(src, face, 0).src.mask.reduce((s2, v) => s2 + v, 0), src.mask.reduce((s2, v) => s2 + v, 0), "amount 0 is a no-op");
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
