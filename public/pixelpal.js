/* BarksBuds pixel pal: turns a photo + a dog mask into a small, crisp pixel-art sprite.
   Pure functions (no DOM), so the same file runs in the browser and in Node tests.
   Pipeline: tight crop -> masked supersampling -> Kuwahara edge-preserving smoothing -> sprite grid
   -> tone + saturation boost (OKLab) -> k-means palette -> optional ordered dither -> stray pixel cleanup
   -> rim shading -> 1px selective outline -> optional pixel drop shadow / brand backdrop. */
(function (root) {
  "use strict";

  var PRESETS = {
    classic: { size: 48, colors: 10, outline: "dark", dither: 0, shadow: true, shade: true, saturation: 1.18, contrast: 1.05, smooth: 2, cluster: 2, sharpen: 0.35, features: 0.75 },
    retro: { size: 32, colors: 8, outline: "dark", dither: 0.5, shadow: true, shade: true, saturation: 1.3, contrast: 1.12, smooth: 1, cluster: 1, sharpen: 0.3, features: 0.8 },
    soft: { size: 64, colors: 16, outline: "soft", dither: 0, shadow: true, shade: false, saturation: 1.08, contrast: 1.0, smooth: 2, cluster: 1, sharpen: 0.25, features: 0.6 }
  };
  var BACKDROPS = { none: null, cream: [255, 248, 234], sunny: [255, 231, 168], sky: [205, 232, 247], mint: [214, 240, 222], rose: [251, 221, 214] };
  var SHADOW = [42, 32, 26];

  // ---------------------------------------------------------------- color
  function s2l(c) { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function l2s(c) { c = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055; return Math.max(0, Math.min(255, Math.round(c * 255))); }
  var LUT = new Float64Array(256); for (var i = 0; i < 256; i++) LUT[i] = s2l(i);
  function toLab(r, g, b) {
    r = LUT[r]; g = LUT[g]; b = LUT[b];
    var l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    var m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    var s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s];
  }
  function toRgb(L, a, b) {
    var l = L + 0.3963377774 * a + 0.2158037573 * b, m = L - 0.1055613458 * a - 0.0638541728 * b, s = L - 0.0894841775 * a - 1.2914855480 * b;
    l = l * l * l; m = m * m * m; s = s * s * s;
    return [l2s(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            l2s(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            l2s(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)];
  }
  function dist(p, q) { var dl = (p[0] - q[0]) * 1.4, da = p[1] - q[1], db = p[2] - q[2]; return dl * dl + da * da + db * db; }

  function rng(seed) { var x = seed >>> 0 || 1; return function () { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; }; }

  // ---------------------------------------------------------------- k-means in OKLab (weighted, deterministic)
  function kmeans(pts, wts, k, iters) {
    var n = pts.length, rand = rng(12345), cents = [], i, j;
    if (!n) return [];
    var tw = 0; for (i = 0; i < n; i++) tw += wts[i];
    var r = rand() * tw, acc = 0;
    for (i = 0; i < n; i++) { acc += wts[i]; if (acc >= r) break; }
    cents.push(pts[Math.min(i, n - 1)].slice());
    var d2 = new Float64Array(n);
    for (i = 0; i < n; i++) d2[i] = dist(pts[i], cents[0]);
    while (cents.length < k) {   // k-means++ seeding
      var sum = 0; for (i = 0; i < n; i++) sum += d2[i] * wts[i];
      if (sum <= 1e-12) break;
      r = rand() * sum; acc = 0;
      for (i = 0; i < n; i++) { acc += d2[i] * wts[i]; if (acc >= r) break; }
      var c = pts[Math.min(i, n - 1)].slice(); cents.push(c);
      for (i = 0; i < n; i++) { var d = dist(pts[i], c); if (d < d2[i]) d2[i] = d; }
    }
    k = cents.length;
    var asg = new Int32Array(n);
    for (var it = 0; it < iters; it++) {
      var sums = [], moved = 0;
      for (j = 0; j < k; j++) sums.push([0, 0, 0, 0]);
      for (i = 0; i < n; i++) {
        var best = 0, bd = Infinity;
        for (j = 0; j < k; j++) { var dd = dist(pts[i], cents[j]); if (dd < bd) { bd = dd; best = j; } }
        if (asg[i] !== best) moved++;
        asg[i] = best; var s = sums[best], w = wts[i];
        s[0] += pts[i][0] * w; s[1] += pts[i][1] * w; s[2] += pts[i][2] * w; s[3] += w;
      }
      for (j = 0; j < k; j++) if (sums[j][3] > 0) cents[j] = [sums[j][0] / sums[j][3], sums[j][1] / sums[j][3], sums[j][2] / sums[j][3]];
      if (it > 0 && !moved) break;
    }
    return cents;
  }

  function nearest(pal, c) { var best = 0, bd = Infinity; for (var j = 0; j < pal.length; j++) { var d = dist(pal[j], c); if (d < bd) { bd = d; best = j; } } return best; }

  // ---------------------------------------------------------------- main
  function render(src, opts) {
    opts = Object.assign({}, PRESETS.classic, opts || {});
    var N = Math.max(16, Math.min(128, opts.size | 0)), W = src.width, H = src.height, px = src.data, mask = src.mask;
    var F = 3, i, j, x, y;

    // 1. tight crop to the dog
    var box = mainBox(mask, W, H), x0 = box[0], y0 = box[1], x1 = box[2], y1 = box[3];
    var bw = x1 - x0 + 1, bh = y1 - y0 + 1;

    // 2. layout on the N x N canvas
    var bottom = opts.shadow ? 3 : 2, innerW = N - 4, innerH = N - 2 - bottom;
    var scale = Math.max(bw / innerW, bh / innerH);
    var gw = Math.max(1, Math.min(innerW, Math.round(bw / scale))), gh = Math.max(1, Math.min(innerH, Math.round(bh / scale)));

    // 3. masked supersampling onto a (gw*F) x (gh*F) grid; background never bleeds into edge colors
    var SW = gw * F, SH = gh * F, SN = SW * SH;
    var sr = new Float64Array(SN), sg = new Float64Array(SN), sb = new Float64Array(SN), sm = new Float64Array(SN), sa = new Float64Array(SN), sc = new Float64Array(SN);
    // colors come from an eroded mask: segmentation edges often carry a rim of background
    var er = Math.max(1, Math.round(Math.max(bw, bh) / (Math.max(gw, gh) * F) * 0.9));
    var cm = erode(mask, W, H, x0, y0, bw, bh, er);
    var colMap = new Int32Array(bw); for (x = 0; x < bw; x++) colMap[x] = Math.min(SW - 1, Math.floor(x * SW / bw));
    for (y = 0; y < bh; y++) {
      var row = Math.min(SH - 1, Math.floor(y * SH / bh)) * SW, base = (y + y0) * W + x0;
      for (x = 0; x < bw; x++) {
        var p = base + x, m = mask[p] / 255, o = row + colMap[x], me = cm[y * bw + x] / 255;
        var cwt = me > 0.6 ? Math.min(1, (me - 0.6) / 0.3) : 0; cwt *= cwt;
        sr[o] += px[4 * p] * cwt; sg[o] += px[4 * p + 1] * cwt; sb[o] += px[4 * p + 2] * cwt; sm[o] += cwt; sa[o] += m; sc[o] += 1;
      }
    }
    var cov = new Float64Array(SN), lab = new Array(SN);
    for (i = 0; i < SN; i++) {
      cov[i] = sc[i] ? sa[i] / sc[i] : 0;
      lab[i] = sm[i] > 1e-9 ? toLab(Math.round(sr[i] / sm[i]), Math.round(sg[i] / sm[i]), Math.round(sb[i] / sm[i])) : null;
    }

    // fill colorless edge cells from their colored neighbours
    for (var pass = 0; pass < 6; pass++) {
      var fills = [];
      for (y = 0; y < SH; y++) for (x = 0; x < SW; x++) {
        var fi = y * SW + x; if (lab[fi] || cov[fi] <= 0) continue;
        var fL = 0, fA = 0, fB = 0, fn = 0;
        for (var fy = -1; fy <= 1; fy++) for (var fx = -1; fx <= 1; fx++) {
          var gx = x + fx, gy = y + fy; if (gx < 0 || gy < 0 || gx >= SW || gy >= SH) continue;
          var fc = lab[gy * SW + gx]; if (fc) { fL += fc[0]; fA += fc[1]; fB += fc[2]; fn++; }
        }
        if (fn) fills.push([fi, [fL / fn, fA / fn, fB / fn]]);
      }
      if (!fills.length) break;
      for (var fz = 0; fz < fills.length; fz++) lab[fills[fz][0]] = fills[fz][1];
    }

    // 4. Kuwahara filter (edge-preserving smoothing) on the supersampled grid
    var R = Math.max(0, opts.smooth | 0);
    if (R > 0) {
      var outLab = new Array(SN);
      for (y = 0; y < SH; y++) for (x = 0; x < SW; x++) {
        var idx = y * SW + x; if (!lab[idx]) { outLab[idx] = null; continue; }
        var bestVar = Infinity, bestMean = lab[idx];
        for (var qd = 0; qd < 4; qd++) {
          var dx0 = qd & 1 ? 0 : -R, dy0 = qd & 2 ? 0 : -R, n = 0, mL = 0, mA = 0, mB = 0, vL = 0;
          for (var yy = y + dy0; yy <= y + dy0 + R; yy++) {
            if (yy < 0 || yy >= SH) continue;
            for (var xx = x + dx0; xx <= x + dx0 + R; xx++) {
              if (xx < 0 || xx >= SW) continue;
              var c = lab[yy * SW + xx]; if (!c) continue;
              n++; mL += c[0]; mA += c[1]; mB += c[2]; vL += c[0] * c[0];
            }
          }
          if (n < 2) continue;
          mL /= n; var v = vL / n - mL * mL;
          if (v < bestVar) { bestVar = v; bestMean = [mL, mA / n, mB / n]; }
        }
        outLab[idx] = bestMean;
      }
      lab = outLab;
    }

    // 5. down to the sprite grid
    var G = gw * gh, darkest = new Array(G), gl = new Array(G), ga = new Uint8Array(G), cw = new Float64Array(G);
    for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
      var aL = 0, aA = 0, aB = 0, wsum = 0, csum = 0, dk = null;
      for (j = 0; j < F; j++) for (i = 0; i < F; i++) {
        var si = (y * F + j) * SW + x * F + i, cc = lab[si], cv = cov[si]; csum += cv;
        if (!cc || cv <= 0) continue;
        if (cv > 0.5 && (!dk || cc[0] < dk[0])) dk = cc;
        var wgt = cv * ((i === 1 && j === 1) ? 1.6 : 1);
        aL += cc[0] * wgt; aA += cc[1] * wgt; aB += cc[2] * wgt; wsum += wgt;
      }
      var g = y * gw + x; cw[g] = csum / (F * F);
      gl[g] = wsum > 0 ? [aL / wsum, aA / wsum, aB / wsum] : null; darkest[g] = dk;
      ga[g] = (gl[g] && cw[g] >= (opts.alphaThreshold || 0.5)) ? 1 : 0;
    }

    // 5b. feature emphasis: small dark details (eyes, nose, mouth line) get averaged away at sprite size,
    // so a cell holding a much darker spot than its surroundings takes most of that spot's color
    var fe = opts.features == null ? 0.75 : opts.features;
    if (fe > 0) {
      var feat = [];
      for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
        g = y * gw + x; if (!ga[g] || !darkest[g]) continue;
        var nsum = 0, nn = 0;
        for (var ny = -2; ny <= 2; ny++) for (var nx = -2; nx <= 2; nx++) {
          var ax = x + nx, ay = y + ny; if (ax < 0 || ay < 0 || ax >= gw || ay >= gh) continue;
          var ag = ay * gw + ax; if (ga[ag] && gl[ag]) { nsum += gl[ag][0]; nn++; }
        }
        var nm = nsum / nn, dkc = darkest[g], drop = nm - dkc[0];
        if (drop > 0.16 && gl[g][0] < nm) { var tw2 = fe * Math.min(1, (drop - 0.16) / 0.12); feat.push([g, [gl[g][0] + (dkc[0] - gl[g][0]) * tw2, gl[g][1] + (dkc[1] - gl[g][1]) * tw2, gl[g][2] + (dkc[2] - gl[g][2]) * tw2]]); }
      }
      for (var fz2 = 0; fz2 < feat.length; fz2++) gl[feat[fz2][0]] = feat[fz2][1];
    }

    // 6. silhouette cleanup: stray specks, notches, pinholes, tiny islands
    cleanAlpha(ga, gw, gh, gl);

    // 6b. local contrast (unsharp mask on lightness) so small features like eyes and noses read at sprite size
    var sharp = opts.sharpen == null ? 0.35 : opts.sharpen;
    if (sharp > 0) {
      var nl = new Float64Array(G);
      for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
        g = y * gw + x; if (!ga[g]) continue;
        var tot = 0, cnt = 0;
        for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
          var xx3 = x + dx, yy3 = y + dy; if (xx3 < 0 || yy3 < 0 || xx3 >= gw || yy3 >= gh) continue;
          var gg = yy3 * gw + xx3; if (!ga[gg]) continue; var wv = (dx || dy) ? 1 : 2; tot += gl[gg][0] * wv; cnt += wv;
        }
        nl[g] = gl[g][0] + sharp * (gl[g][0] - tot / cnt);
      }
      for (g = 0; g < G; g++) if (ga[g]) gl[g] = [nl[g], gl[g][1], gl[g][2]];
    }

    // 7. tone: median-anchored contrast stretch, dark-coat lift, saturation boost
    var Ls = []; for (g = 0; g < G; g++) if (ga[g]) Ls.push(gl[g][0]);
    if (Ls.length) {
      Ls.sort(function (a, b) { return a - b; });
      var lo = Ls[Math.floor(Ls.length * 0.03)], hi = Ls[Math.floor(Ls.length * 0.97)], med = Ls[Math.floor(Ls.length / 2)];
      // map the coat's own range [lo, hi] onto a slightly wider one; a gamma pulls the median toward the middle
      // so a black dog's curls and a cream dog's markings both separate, without crushing either end
      var outLo = Math.max(0.035, lo * 0.7), outHi = Math.min(0.97, hi + 0.08 + (hi < 0.5 ? 0.08 : 0));
      var tm = Math.max(0.05, Math.min(0.95, (med - lo) / Math.max(0.04, hi - lo)));
      var gam = Math.pow(Math.max(0.55, Math.min(1.8, Math.log(0.5) / Math.log(tm))), 0.55);
      var kc = opts.contrast || 1;
      for (g = 0; g < G; g++) if (ga[g]) {
        var c3 = gl[g], tt = (c3[0] - lo) / Math.max(0.04, hi - lo);
        tt = tt < 0 ? -0.15 * Math.tanh(-tt / 0.15) : tt > 1 ? 1 + 0.1 * Math.tanh((tt - 1) / 0.1) : tt;
        var tg = tt <= 0 ? tt : Math.pow(tt, gam);
        tg = 0.5 + (tg - 0.5) * kc;                       // contrast around the middle of the ramp
        var L = Math.max(0.025, Math.min(0.98, outLo + (outHi - outLo) * tg));
        // hue-shifted ramps, like hand-made pixel art: cool shadows, a touch of warmth in highlights
        var hs = (opts.hueShift == null ? 1 : opts.hueShift) * Math.max(-1, Math.min(1, (tg - 0.5) / 0.4));
        gl[g] = [L, c3[1] * opts.saturation + (hs < 0 ? -hs * 0.01 : 0), c3[2] * opts.saturation + (hs < 0 ? hs * 0.026 : hs * 0.006)];
      }
    }

    // 8. palette (k-means) and mapping with optional 4x4 ordered dither
    var pts = [], wts = []; for (g = 0; g < G; g++) if (ga[g]) { pts.push(gl[g]); wts.push(1); }
    var K = Math.max(2, Math.min(32, opts.colors | 0));
    var pal = kmeans(pts, wts, K, 16);
    // accent colors: a small, vivid detail (a red collar tag, a pink tongue) loses the k-means vote to the coat,
    // so strongly colored pixels that no palette entry represents get up to two extra entries of their own
    if (opts.accents !== false && pal.length) {
      var cand = [], cw = [];
      for (i = 0; i < pts.length; i++) {
        var pc = pts[i], chroma = Math.sqrt(pc[1] * pc[1] + pc[2] * pc[2]);
        if (chroma > 0.07 && dist(pal[nearest(pal, pc)], pc) > 0.008) { cand.push(pc); cw.push(1); }
      }
      var vivid = cand.some(function (q) { return Math.sqrt(q[1] * q[1] + q[2] * q[2]) > 0.08; });
      if ((cand.length >= 2 || vivid) && cand.length <= pts.length * 0.08) {
        var acc2 = kmeans(cand, cw, cand.length >= 8 ? 2 : 1, 8);
        for (i = 0; i < acc2.length; i++) if (dist(pal[nearest(pal, acc2[i])], acc2[i]) > 0.006) pal.push(acc2[i]);
      }
    }
    pal.sort(function (a, b) { return a[0] - b[0]; });
    var BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], amp = (opts.dither || 0) * 0.11;
    var ix = new Int16Array(G).fill(-1);
    for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
      g = y * gw + x; if (!ga[g]) continue;
      var t = (BAYER[(y & 3) * 4 + (x & 3)] + 0.5) / 16 - 0.5, cc2 = gl[g];
      ix[g] = nearest(pal, amp ? [cc2[0] + t * amp, cc2[1], cc2[2]] : cc2);
    }

    // 9. lone-pixel cleanup (keeps high-contrast details like eye shines)
    cleanColors(ix, gw, gh, pal);
    for (var mp = 0; mp < (opts.cluster == null ? 1 : opts.cluster); mp++) modeFilter(ix, gw, gh, pal);

    // 10. rim shading: lighter top edge, darker bottom edge
    if (opts.shade) shadeRims(ix, gw, gh, pal);

    // 11. compose onto N x N with outline, shadow and backdrop
    var ox = Math.floor((N - gw) / 2), oy = N - bottom - gh;
    var out = new Uint8ClampedArray(N * N * 4), cell = new Int16Array(N * N).fill(-1);
    for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) { g = y * gw + x; if (ix[g] >= 0) cell[(y + oy) * N + x + ox] = ix[g]; }
    var rgbPal = pal.map(function (c) { return toRgb(c[0], c[1], c[2]); });
    for (i = 0; i < N * N; i++) if (cell[i] >= 0) { var rc = rgbPal[cell[i]]; out[4 * i] = rc[0]; out[4 * i + 1] = rc[1]; out[4 * i + 2] = rc[2]; out[4 * i + 3] = 255; }
    if (opts.shadow) {
      var cx = ox + gw / 2 - 0.5, cy = oy + gh - 0.5, rx = Math.max(2, gw * 0.4), ry = 1.2;
      for (y = Math.floor(cy - ry); y <= Math.ceil(cy + ry); y++) for (x = Math.floor(cx - rx); x <= Math.ceil(cx + rx); x++) {
        if (x < 0 || y < 0 || x >= N || y >= N) continue;
        var e = Math.pow((x - cx) / rx, 2) + Math.pow((y - cy) / ry, 2), k2 = y * N + x;
        if (e <= 1 && cell[k2] < 0) { out[4 * k2] = SHADOW[0]; out[4 * k2 + 1] = SHADOW[1]; out[4 * k2 + 2] = SHADOW[2]; out[4 * k2 + 3] = 72; }
      }
    }
    if (opts.outline && opts.outline !== "none") {
      var soft = opts.outline === "soft";
      for (y = 0; y < N; y++) for (x = 0; x < N; x++) {
        var k3 = y * N + x; if (cell[k3] >= 0) continue;
        var nb = -1, nbs = [[0, -1], [-1, 0], [1, 0], [0, 1]];
        for (var q = 0; q < 4; q++) { var xx2 = x + nbs[q][0], yy2 = y + nbs[q][1]; if (xx2 >= 0 && yy2 >= 0 && xx2 < N && yy2 < N && cell[yy2 * N + xx2] >= 0) { nb = cell[yy2 * N + xx2]; break; } }
        if (nb < 0) continue;
        var pc = pal[nb], oc = soft ? toRgb(pc[0] * 0.55, pc[1] * 0.85, pc[2] * 0.85) : toRgb(Math.min(0.2, pc[0] * 0.32), pc[1] * 0.45, pc[2] * 0.45);
        out[4 * k3] = oc[0]; out[4 * k3 + 1] = oc[1]; out[4 * k3 + 2] = oc[2]; out[4 * k3 + 3] = 255;
      }
    }
    var bd = typeof opts.backdrop === "string" ? BACKDROPS[opts.backdrop] : opts.backdrop;
    if (bd) for (i = 0; i < N * N; i++) {
      var al = out[4 * i + 3] / 255;
      for (var ch = 0; ch < 3; ch++) out[4 * i + ch] = Math.round(out[4 * i + ch] * al + bd[ch] * (1 - al));
      out[4 * i + 3] = 255;
    }
    return { width: N, height: N, data: out, palette: rgbPal, grid: { x: ox, y: oy, w: gw, h: gh } };
  }

  // bounding box of the dog: the biggest blob of the mask (plus any big pieces), ignoring faint specks
  function mainBox(mask, W, H) {
    var st = Math.max(1, Math.floor(Math.max(W, H) / 160)), cw = Math.ceil(W / st), ch = Math.ceil(H / st), c = new Uint8Array(cw * ch), x, y, i;
    for (y = 0; y < ch; y++) for (x = 0; x < cw; x++) {
      var on = 0, n = 0;
      for (var yy = y * st; yy < Math.min(H, (y + 1) * st); yy++) for (var xx = x * st; xx < Math.min(W, (x + 1) * st); xx++) { n++; if (mask[yy * W + xx] >= 128) on++; }
      c[y * cw + x] = on * 2 >= n ? 1 : 0;
    }
    var lbl = new Int32Array(cw * ch), boxes = [], stack = [];
    for (i = 0; i < cw * ch; i++) if (c[i] && !lbl[i]) {
      var b = [cw, ch, -1, -1, 0], id = boxes.length + 1; lbl[i] = id; stack.push(i);
      while (stack.length) {
        var p = stack.pop(), px = p % cw, py = (p - px) / cw; b[4]++;
        if (px < b[0]) b[0] = px; if (py < b[1]) b[1] = py; if (px > b[2]) b[2] = px; if (py > b[3]) b[3] = py;
        var nb = [p - 1, p + 1, p - cw, p + cw], ok = [px > 0, px < cw - 1, py > 0, py < ch - 1];
        for (var k = 0; k < 4; k++) if (ok[k] && c[nb[k]] && !lbl[nb[k]]) { lbl[nb[k]] = id; stack.push(nb[k]); }
      }
      boxes.push(b);
    }
    if (!boxes.length) return [0, 0, W - 1, H - 1];
    var big = 0; boxes.forEach(function (b) { big = Math.max(big, b[4]); });
    var r = [W, H, -1, -1];
    boxes.forEach(function (b) {
      if (b[4] < big * 0.12) return;
      r[0] = Math.min(r[0], b[0] * st); r[1] = Math.min(r[1], b[1] * st);
      r[2] = Math.max(r[2], Math.min(W - 1, (b[2] + 1) * st - 1)); r[3] = Math.max(r[3], Math.min(H - 1, (b[3] + 1) * st - 1));
    });
    return r;
  }

  function erode(mask, W, H, x0, y0, bw, bh, r) {   // separable min filter over the crop box
    var tmp = new Uint8Array(bw * bh), out = new Uint8Array(bw * bh), x, y, k, v;
    for (y = 0; y < bh; y++) for (x = 0; x < bw; x++) {
      v = 255; for (k = -r; k <= r; k++) { var xx = x + x0 + k; var mv = xx < 0 || xx >= W ? 0 : mask[(y + y0) * W + xx]; if (mv < v) v = mv; }
      tmp[y * bw + x] = v;
    }
    for (y = 0; y < bh; y++) for (x = 0; x < bw; x++) {
      v = 255; for (k = -r; k <= r; k++) { var yy = y + k; var tv = yy < 0 || yy >= bh ? (y + y0 + k >= 0 && y + y0 + k < H ? mask[(y + y0 + k) * W + x + x0] : 0) : tmp[yy * bw + x]; if (tv < v) v = tv; }
      out[y * bw + x] = v;
    }
    return out;
  }

  function cleanAlpha(a, w, h, lab) {
    var x, y, i, n4, n8, pass;
    function at(xx, yy) { return xx >= 0 && yy >= 0 && xx < w && yy < h ? a[yy * w + xx] : 0; }
    for (pass = 0; pass < 2; pass++) {
      var chg = [];
      for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        i = y * w + x; n4 = at(x, y - 1) + at(x, y + 1) + at(x - 1, y) + at(x + 1, y);
        n8 = n4 + at(x - 1, y - 1) + at(x + 1, y - 1) + at(x - 1, y + 1) + at(x + 1, y + 1);
        if (a[i] && n4 <= 1 && n8 <= 2) chg.push([i, 0]);
        else if (!a[i] && n4 >= 3 && lab[i]) chg.push([i, 1]);
      }
      for (var c = 0; c < chg.length; c++) a[chg[c][0]] = chg[c][1];
    }
    // drop islands much smaller than the main body
    var lbl = new Int32Array(w * h), sizes = [0], cur = 0, stack = [];
    for (i = 0; i < w * h; i++) if (a[i] && !lbl[i]) {
      cur++; var sz = 0; stack.push(i); lbl[i] = cur;
      while (stack.length) {
        var p = stack.pop(); sz++; var px = p % w, py = (p - px) / w;
        var nb = [[px - 1, py], [px + 1, py], [px, py - 1], [px, py + 1]];
        for (var k = 0; k < 4; k++) { var qx = nb[k][0], qy = nb[k][1]; if (qx < 0 || qy < 0 || qx >= w || qy >= h) continue; var qi = qy * w + qx; if (a[qi] && !lbl[qi]) { lbl[qi] = cur; stack.push(qi); } }
      }
      sizes.push(sz);
    }
    var big = Math.max.apply(null, sizes);
    for (i = 0; i < w * h; i++) if (a[i] && sizes[lbl[i]] < Math.max(3, big * 0.04)) a[i] = 0;
  }

  function cleanColors(ix, w, h, pal) {
    var chg = [];
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var i = y * w + x, v = ix[i]; if (v < 0) continue;
      var nb = [], same = 0;
      if (y > 0) nb.push(ix[i - w]); if (y < h - 1) nb.push(ix[i + w]); if (x > 0) nb.push(ix[i - 1]); if (x < w - 1) nb.push(ix[i + 1]);
      for (var k = 0; k < nb.length; k++) if (nb[k] === v) same++;
      if (same) continue;
      var cnt = {}, best = -1, bc = 0;
      for (k = 0; k < nb.length; k++) if (nb[k] >= 0) { cnt[nb[k]] = (cnt[nb[k]] || 0) + 1; if (cnt[nb[k]] > bc) { bc = cnt[nb[k]]; best = nb[k]; } }
      if (best >= 0 && bc >= 2 && dist(pal[v], pal[best]) < 0.012) chg.push([i, best]);
    }
    for (var c = 0; c < chg.length; c++) ix[chg[c][0]] = chg[c][1];
  }

  // majority filter: merges speckle into clean clusters, but never across strong edges
  function modeFilter(ix, w, h, pal) {
    var out = ix.slice();
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var i = y * w + x, v = ix[i]; if (v < 0) continue;
      var cnt = {}, self = 0, best = -1, bc = 0;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
        var xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
        var u = ix[yy * w + xx]; if (u < 0) continue;
        if (u === v) { self++; continue; }
        cnt[u] = (cnt[u] || 0) + 1; if (cnt[u] > bc) { bc = cnt[u]; best = u; }
      }
      if (best >= 0 && self <= 2 && bc >= 4 && dist(pal[v], pal[best]) < 0.006) out[i] = best;
    }
    for (var k = 0; k < ix.length; k++) ix[k] = out[k];
  }

  function shadeRims(ix, w, h, pal) {
    function step(v, dL) {
      var c = pal[v], target = [Math.max(0, Math.min(1, c[0] + dL)), c[1], c[2]], best = v, bd = Infinity;
      for (var j = 0; j < pal.length; j++) { if (j === v || (dL > 0 ? pal[j][0] <= c[0] : pal[j][0] >= c[0])) continue; var d = dist(pal[j], target); if (d < bd) { bd = d; best = j; } }
      return bd < 0.02 ? best : v;
    }
    var chg = [];
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var i = y * w + x, v = ix[i]; if (v < 0) continue;
      var up = y === 0 || ix[i - w] < 0, dn = y === h - 1 || ix[i + w] < 0;
      if (up && !dn) chg.push([i, step(v, 0.09)]);
      else if (dn && !up) chg.push([i, step(v, -0.09)]);
    }
    for (var c = 0; c < chg.length; c++) ix[chg[c][0]] = chg[c][1];
  }

  function upscale(spr, s) {
    var W = spr.width * s, H = spr.height * s, out = new Uint8ClampedArray(W * H * 4);
    for (var y = 0; y < H; y++) { var sy = (y / s) | 0; for (var x = 0; x < W; x++) { var si = (sy * spr.width + ((x / s) | 0)) * 4, di = (y * W + x) * 4; out[di] = spr.data[si]; out[di + 1] = spr.data[si + 1]; out[di + 2] = spr.data[si + 2]; out[di + 3] = spr.data[si + 3]; } }
    return { width: W, height: H, data: out };
  }

  var api = { render: render, upscale: upscale, PRESETS: PRESETS, BACKDROPS: BACKDROPS, toLab: toLab, toRgb: toRgb, kmeans: kmeans };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PixelPal = api;
})(typeof self !== "undefined" ? self : this);
