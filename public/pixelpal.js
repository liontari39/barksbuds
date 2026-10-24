/* BarksBuds pixel pal: turns a photo + a dog mask into a small, crisp pixel-art sprite.
   Pure functions (no DOM), so the same file runs in the browser and in Node tests.
   Pipeline: tight crop -> masked supersampling -> Kuwahara edge-preserving smoothing -> sprite grid
   -> tone + saturation boost (OKLab) -> k-means palette -> optional ordered dither -> stray pixel cleanup
   -> rim shading -> 1px selective outline -> optional pixel drop shadow / brand backdrop. */
(function (root) {
  "use strict";

  var PRESETS = {
    // "Game sprite": flat cel-shaded color, one ink outline, hand-drawn eyes/nose stamps (like a 16-bit game character)
    game: { size: 48, sizes: [32, 48, 64], colors: 6, outline: "ink", dither: 0, shadow: true, shade: false, cel: true, saturation: 1.15, contrast: 1.0, smooth: 3, smoothPasses: 2, cluster: 3, sharpen: 0, features: 0, accents: true, chibi: 1, blush: true, mouth: "smile", eyes: "friendly" },
    // the earlier, more photo-detailed cel look (kept for anyone who liked it)
    chunky: { size: 32, sizes: [24, 32, 40], colors: 10, outline: "ink", dither: 0, shadow: true, toon: true, clean: 2, saturation: 1.15, chibi: 1, blush: true, mouth: "tongue", eyes: "dots" },
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
    if (opts.toon) return renderToon(src, opts);
    var face = normFace(opts.face, src.width, src.height);
    if (opts.chibi > 0 && face) { var wr = bigHead(src, face, opts.chibi); src = wr.src; face = wr.face; }
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
    for (var kp = 0; R > 0 && kp < Math.max(1, opts.smoothPasses | 0); kp++) {
      var outLab = new Array(SN);
      for (y = 0; y < SH; y++) for (x = 0; x < SW; x++) {
        var idx = y * SW + x; if (!lab[idx]) { outLab[idx] = null; continue; }
        if (opts.cel && lab[idx][1] * lab[idx][1] + lab[idx][2] * lab[idx][2] > 0.0081) { outLab[idx] = lab[idx]; continue; }   // keep vivid accents crisp
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
      if (opts.cel && gl[g]) {   // a cell that is one-third vivid (a red tag) takes the vivid color outright
        var vL = 0, vA = 0, vB = 0, vn = 0;
        for (j = 0; j < F; j++) for (i = 0; i < F; i++) { var vc = lab[(y * F + j) * SW + x * F + i]; if (vc && vc[1] * vc[1] + vc[2] * vc[2] > 0.0081) { vL += vc[0]; vA += vc[1]; vB += vc[2]; vn++; } }
        if (vn >= 3) gl[g] = [vL / vn, vA / vn, vB / vn];
      }
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
    if (opts.cel) smoothSilhouette(ga, gw, gh, gl);

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
    var darkCoat = false;
    if (Ls.length && opts.cel) darkCoat = celTone(gl, ga, Ls, opts);
    else if (Ls.length) {
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
    var K = Math.max(2, Math.min(32, (opts.colors | 0) - (darkCoat ? 1 : 0)));
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
    for (var mp = 0; mp < (opts.cluster == null ? 1 : opts.cluster); mp++) modeFilter(ix, gw, gh, pal, opts.cel ? 0.035 : 0.006);

    // 10. rim shading: lighter top edge, darker bottom edge (or cel shading: flat regions, top-left light)
    if (opts.cel) {
      mergeIslands(ix, gw, gh, pal, N >= 56 ? 4 : N >= 40 ? 3 : 2);
      celShade(ix, gw, gh, pal, N >= 56 ? 2 : 1, darkCoat);
    } else if (opts.shade) shadeRims(ix, gw, gh, pal);

    // 10b. face stamps: crisp hand-drawn eyes, nose, mouth, blush
    var ink = inkColor(pal, ix, darkCoat);
    if (face && opts.faceStamps !== false) stampFace(ix, gw, gh, pal, face, { x0: x0, y0: y0, bw: bw, bh: bh }, opts, ink, src, N, darkCoat);

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
        var pc = pal[nb], oc = opts.outline === "ink" ? toRgb(ink[0], ink[1], ink[2]) : soft ? toRgb(pc[0] * 0.55, pc[1] * 0.85, pc[2] * 0.85) : toRgb(Math.min(0.2, pc[0] * 0.32), pc[1] * 0.45, pc[2] * 0.45);
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
  function modeFilter(ix, w, h, pal, tol) {
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
      if (best >= 0 && self <= 2 && bc >= 4 && dist(pal[v], pal[best]) < (tol || 0.006)) out[i] = best;
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

  // ================================================================ game-sprite steps
  // face points arrive normalized (0..1) to the source image; keep them in source pixels
  function normFace(f, W, H) {
    if (!f) return null;
    var eyes = (f.eyes || []).filter(Boolean).slice(0, 2).map(function (e) { return [e[0] * W, e[1] * H]; });
    var nose = f.nose ? [f.nose[0] * W, f.nose[1] * H] : null;
    if (!eyes.length && !nose) return null;
    return { eyes: eyes, nose: nose };
  }

  // the head: centered a little above the face points, sized from their spread (or the eye-nose distance in profile)
  function headCircle(face, src) {
    var pts = face.eyes.slice(); if (face.nose) pts.push(face.nose);
    var cx = 0, cy = 0; pts.forEach(function (p) { cx += p[0]; cy += p[1]; }); cx /= pts.length; cy /= pts.length;
    var spread = 0;
    for (var i = 0; i < pts.length; i++) for (var j = i + 1; j < pts.length; j++) spread = Math.max(spread, Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]));
    if (!spread) return null;
    var two = face.eyes.length === 2;
    var r = spread * (two ? 1.5 : 2.3);
    if (src) { var bb = mainBox(src.mask, src.width, src.height); r = Math.max(r, 0.25 * Math.min(bb[2] - bb[0] + 1, bb[3] - bb[1] + 1)); }
    return { x: cx, y: cy - spread * (two ? 0.15 : 0.1), r: r };
  }

  // "chibi": a smooth bulge that enlarges the head region by up to ~30% (inverse-mapped, bilinear)
  function bulgeK(r, R, s) { var u = r / R; if (u >= 1) return 1; var q = 1 - u * u; return 1 - (1 - 1 / s) * q * q; }
  function bigHead(src, face, amount, gain) {
    var hc = headCircle(face, src); if (!hc) return { src: src, face: face };
    var W = src.width, H = src.height, s = 1 + (gain || 0.3) * Math.max(0, Math.min(1.5, amount)), R = hc.r * 1.8;   // reach past the head so its outline grows
    var data = new Uint8ClampedArray(src.data), mask = new Uint8Array(src.mask);
    var x0 = Math.max(0, Math.floor(hc.x - R)), x1 = Math.min(W - 1, Math.ceil(hc.x + R)), y0 = Math.max(0, Math.floor(hc.y - R)), y1 = Math.min(H - 1, Math.ceil(hc.y + R));
    for (var y = y0; y <= y1; y++) for (var x = x0; x <= x1; x++) {
      var dx = x - hc.x, dy = y - hc.y, r = Math.sqrt(dx * dx + dy * dy); if (r >= R) continue;
      var k = bulgeK(r, R, s), sx = Math.max(0, Math.min(W - 1.001, hc.x + dx * k)), sy = Math.max(0, Math.min(H - 1.001, hc.y + dy * k));
      var ix = sx | 0, iy = sy | 0, fx = sx - ix, fy = sy - iy, o = y * W + x;
      var a = iy * W + ix, b = a + 1, c = a + W, d = c + 1;
      var w00 = (1 - fx) * (1 - fy), w10 = fx * (1 - fy), w01 = (1 - fx) * fy, w11 = fx * fy;
      for (var ch = 0; ch < 4; ch++) data[4 * o + ch] = src.data[4 * a + ch] * w00 + src.data[4 * b + ch] * w10 + src.data[4 * c + ch] * w01 + src.data[4 * d + ch] * w11;
      mask[o] = src.mask[a] * w00 + src.mask[b] * w10 + src.mask[c] * w01 + src.mask[d] * w11;
    }
    function fwd(p) {   // where a source point lands after the bulge (bisection on the monotonic radial map)
      var dx = p[0] - hc.x, dy = p[1] - hc.y, r = Math.sqrt(dx * dx + dy * dy); if (r >= R || !r) return p.slice();
      var lo = 0, hi = R; for (var it = 0; it < 30; it++) { var mid = (lo + hi) / 2; if (mid * bulgeK(mid, R, s) < r) lo = mid; else hi = mid; }
      var rd = (lo + hi) / 2; return [hc.x + dx * rd / r, hc.y + dy * rd / r];
    }
    return { src: { width: W, height: H, data: data, mask: mask }, face: { eyes: face.eyes.map(fwd), nose: face.nose && fwd(face.nose) } };
  }

  // round off the silhouette: fill 1-px notches (closing) and shave 1-px bumps, without cutting thin legs or ears
  function smoothSilhouette(a, w, h, lab) {
    function at(x, y) { return x >= 0 && y >= 0 && x < w && y < h ? a[y * w + x] : 0; }
    for (var pass = 0; pass < 1; pass++) {
      var chg = [];
      for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
        var i = y * w + x, n8 = 0;
        for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) if (dx || dy) n8 += at(x + dx, y + dy);
        var hz = at(x - 1, y) && at(x + 1, y), vt = at(x, y - 1) && at(x, y + 1);
        if (!a[i] && n8 >= 5 && (hz || vt) && lab[i]) chg.push([i, 1]);          // notch / pinhole
        else if (a[i] && n8 <= 2 && !hz && !vt) chg.push([i, 0]);               // lone bump
      }
      for (var c = 0; c < chg.length; c++) a[chg[c][0]] = chg[c][1];
    }
    for (var i2 = 0; i2 < w * h; i2++) if (a[i2] && !lab[i2]) {   // newly filled cells borrow a neighbour's color
      var x2 = i2 % w, y2 = (i2 - x2) / w;
      for (var k = 0; k < 8 && !lab[i2]; k++) { var nx = x2 + [1, -1, 0, 0, 1, -1, 1, -1][k], ny = y2 + [0, 0, 1, -1, 1, 1, -1, -1][k]; if (nx >= 0 && ny >= 0 && nx < w && ny < h && lab[ny * w + nx]) lab[i2] = lab[ny * w + nx]; }
      if (!lab[i2]) a[i2] = 0;
    }
  }

  // cel tone: friendly, slightly brighter and more saturated; a black coat becomes a readable charcoal ramp
  function celTone(gl, ga, Ls, opts) {
    Ls.sort(function (a, b) { return a - b; });
    var lo = Ls[Math.floor(Ls.length * 0.05)], hi = Ls[Math.floor(Ls.length * 0.95)], med = Ls[Math.floor(Ls.length / 2)];
    var dark = med < 0.4, sat = opts.saturation || 1.15, span = Math.max(0.05, hi - lo);
    for (var g = 0; g < gl.length; g++) if (ga[g]) {
      var c = gl[g], L, A, B;
      if (dark) {
        var t = Math.max(-0.2, Math.min(1.25, (c[0] - lo) / span));
        L = 0.24 + 0.27 * Math.pow(Math.max(0, t), 0.85) + Math.min(0, t) * 0.2;   // ~#302c32 base .. #6e6667 highlights
        var chroma = Math.sqrt(c[1] * c[1] + c[2] * c[2]);
        if (chroma > 0.06) { A = c[1] * sat; B = c[2] * sat; }                     // keep real color (tag, tongue)
        else { A = c[1] * 0.5 + 0.004; B = c[2] * 0.5 - 0.01; }                    // cool, faintly purple charcoal
      } else {
        // light coats are lifted toward a friendly pastel base (~#dcc1a7 for a tan dog), patches stay readable
        L = Math.max(0.25, Math.min(0.97, Math.max(med, 0.78) + (c[0] - med) * 0.95 * (opts.contrast || 1)));
        A = c[1] * sat * 1.15; B = c[2] * sat * 1.15 + 0.008;
      }
      gl[g] = [L, A, B];
    }
    return dark;
  }

  // merge small single-color islands into their surroundings (keeps vivid accents like a red tag)
  function mergeIslands(ix, w, h, pal, minSize) {
    var lbl = new Int32Array(w * h).fill(-1), stack = [], comp = [];
    for (var i = 0; i < w * h; i++) {
      if (ix[i] < 0 || lbl[i] >= 0) continue;
      var v = ix[i], cells = [], id = comp.length; lbl[i] = id; stack.push(i);
      while (stack.length) {
        var p = stack.pop(); cells.push(p); var x = p % w, y = (p - x) / w;
        var nb = [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, y > 0 ? p - w : -1, y < h - 1 ? p + w : -1];
        for (var k = 0; k < 4; k++) { var q = nb[k]; if (q >= 0 && lbl[q] < 0 && ix[q] === v) { lbl[q] = id; stack.push(q); } }
      }
      comp.push(cells);
    }
    for (var c = 0; c < comp.length; c++) {
      var cl = comp[c]; if (cl.length >= minSize) continue;
      var col = pal[ix[cl[0]]]; if (Math.sqrt(col[1] * col[1] + col[2] * col[2]) > 0.08) continue;
      var cnt = {}, best = -1, bc = 0;
      cl.forEach(function (p) {
        var x = p % w, y = (p - x) / w, nb = [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, y > 0 ? p - w : -1, y < h - 1 ? p + w : -1];
        nb.forEach(function (q) { if (q >= 0 && ix[q] >= 0 && lbl[q] !== c) { cnt[ix[q]] = (cnt[ix[q]] || 0) + 1; if (cnt[ix[q]] > bc) { bc = cnt[ix[q]]; best = ix[q]; } } });
      });
      if (best >= 0) cl.forEach(function (p) { ix[p] = best; });
    }
  }

  // cel shading, lit from the top-left: each big color region gets one highlight and one shadow tone along its rims
  function celShade(ix, w, h, pal, rim, dark) {
    var cnt = {}, tot = 0, i, x, y;
    for (i = 0; i < w * h; i++) if (ix[i] >= 0) { cnt[ix[i]] = (cnt[ix[i]] || 0) + 1; tot++; }
    var hl = {}, sh = {};
    Object.keys(cnt).forEach(function (k) {
      if (cnt[k] < tot * 0.06) return;
      var c = pal[k];
      if (Math.sqrt(c[1] * c[1] + c[2] * c[2]) > 0.09) return;      // leave accents alone
      var up = dark ? 0.1 : 0.075, dn = dark ? 0.07 : 0.09;
      hl[k] = pal.push([Math.min(0.97, c[0] + up), c[1] * 1.05 + (dark ? -0.002 : 0.002), c[2] * 1.05 + (dark ? -0.012 : 0.01)]) - 1;
      sh[k] = pal.push([Math.max(0.1, c[0] - dn), c[1] * 1.1 + 0.004, c[2] * 1.1 - 0.012]) - 1;
    });
    function off(xx, yy) { return xx < 0 || yy < 0 || xx >= w || yy >= h || ix[yy * w + xx] < 0; }
    var out = ix.slice();
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      i = y * w + x; var v = ix[i]; if (v < 0 || hl[v] == null) continue;
      var lit = false, shade = false;
      for (var d = 1; d <= rim; d++) {
        if (off(x, y - d) || off(x - d, y) || (d === 1 && off(x - 1, y - 1))) lit = true;
        if (off(x, y + d) || off(x + d, y) || (d === 1 && off(x + 1, y + 1))) shade = true;
      }
      // a region boundary against a darker color also casts a little shadow beneath it
      if (!shade && y > 0 && ix[i - w] >= 0 && ix[i - w] !== v && hl[ix[i - w]] == null && pal[ix[i - w]][0] < pal[v][0] - 0.12) shade = true;
      if (lit && !shade) out[i] = hl[v]; else if (shade && !lit) out[i] = sh[v];
    }
    for (i = 0; i < ix.length; i++) ix[i] = out[i];
  }

  // one ink color for outline and pupils: a very dark, slightly warm (or, for black coats, near-black) tone of the coat
  function inkColor(pal, ix, dark) {
    var cnt = {}, best = -1, bc = 0;
    for (var i = 0; i < ix.length; i++) if (ix[i] >= 0) { cnt[ix[i]] = (cnt[ix[i]] || 0) + 1; if (cnt[ix[i]] > bc) { bc = cnt[ix[i]]; best = ix[i]; } }
    var c = best >= 0 ? pal[best] : [0.5, 0, 0];
    return dark ? [0.12, c[1] * 0.4 + 0.004, c[2] * 0.4 - 0.006] : [0.2, c[1] * 0.6 + 0.012, c[2] * 0.6 + 0.016];
  }

  // hand-drawn stamps.  e pupil, a iris, w white, n nose, h nose shine, m mouth line, t tongue, T tongue shade
  var EYES = {
    xl: ["..kkk..", ".kaaak.", "kawweak", "kaweeak", "kaeeeak", ".kaaak.", "..kkk.."],
    s: ["ew", "ee"],
    m: [".ae.", "aewe", "aeee", ".ee."],
    l: [".aaa.", "aewwa", "aeewa", "aeeea", ".aaa."]
  };
  var NOSES = {
    xl: [".nhhnn.", "nnnnnnn", "nnnnnnn", ".nnnnn."],
    s: ["nhn", ".n."],
    m: ["nhnn", "nnnn", ".nn."],
    l: [".nhhn.", "nnnnnn", "nnnnnn", ".nnnn."]
  };
  var MOUTHS = { xl: ["...m...", "m..m..m", ".mm.mm."], s: ["m"], m: [".m.", "m.m"], l: ["..m..", "m.m.m", ".m.m."] };   // a little "w" dog mouth
  var TONGUES = { xl: [".tt.", "ttTt", "tTTt", ".tt."], s: ["t"], m: ["tt", "tT"], l: [".tt.", "ttTt", ".tt."] };
  var STAMP_COLORS = { w: [1, 0, 0], h: [0.62, 0.02, 0.005], t: [0.72, 0.17, 0.03], T: [0.6, 0.15, 0.03], blush: [0.79, 0.09, 0.02] };

  // iris color: the most colorful third of the pixels around the tapped eye (the pupil and lashes are dark and grey)
  function sampleIris(src, x, y, r) {
    var px = [];
    for (var yy = Math.round(y - r); yy <= Math.round(y + r); yy++) for (var xx = Math.round(x - r); xx <= Math.round(x + r); xx++) {
      if (xx < 0 || yy < 0 || xx >= src.width || yy >= src.height || (xx - x) * (xx - x) + (yy - y) * (yy - y) > r * r) continue;
      var o = 4 * (yy * src.width + xx); px.push(toLab(src.data[o], src.data[o + 1], src.data[o + 2]));
    }
    if (!px.length) return null;
    px.sort(function (a, b) { return Math.hypot(b[1], b[2]) - Math.hypot(a[1], a[2]); });
    var n = Math.max(1, Math.round(px.length / 3)), L = 0, A = 0, B = 0;
    for (var i = 0; i < n; i++) { L += px[i][0]; A += px[i][1]; B += px[i][2]; }
    return [L / n, A / n, B / n];
  }

  function stampFace(ix, gw, gh, pal, face, box, opts, ink, src, N, dark) {
    function toGrid(p) { return [(p[0] - box.x0) * gw / box.bw, (p[1] - box.y0) * gh / box.bh]; }
    var eyes = face.eyes.map(toGrid), nose = face.nose && toGrid(face.nose);
    // stamp size from the face's size on the grid
    var unit = eyes.length === 2 ? Math.hypot(eyes[0][0] - eyes[1][0], eyes[0][1] - eyes[1][1]) / 1.0
      : (eyes.length && nose) ? Math.hypot(eyes[0][0] - nose[0], eyes[0][1] - nose[1]) * 1.25 : N / 6;
    var sz = unit >= 13 ? "xl" : unit >= 7.5 ? "l" : unit >= 5 ? "m" : "s";
    // "friendly" eyes: no colored iris or ring on light coats (big amber rings read as scary); dark eyes with a
    // white shine, one size smaller. Dark coats keep their eyes as before.
    var friendly = opts.eyes === "friendly" && !dark;
    var esz = friendly ? { xl: "l", l: "m", m: "m", s: "s" }[sz] : sz;
    var cache = {};
    function idx(key, lab) { if (cache[key] != null) return cache[key]; cache[key] = pal.push(lab) - 1; return cache[key]; }
    var spread = Math.max(1.5, Math.max(box.bw, box.bh) * 0.012);
    function put(pattern, cx, cy, colorOf, onlyOpaque) {
      var ph = pattern.length, pw = pattern[0].length, ox = Math.round(cx - pw / 2), oy = Math.round(cy - ph / 2);
      for (var r = 0; r < ph; r++) for (var c = 0; c < pw; c++) {
        var ch = pattern[r][c]; if (ch === ".") continue;
        var x = ox + c, y = oy + r; if (x < 0 || y < 0 || x >= gw || y >= gh) continue;
        var g = y * gw + x; if (onlyOpaque && ix[g] < 0) continue;
        var ci = colorOf(ch, g); if (ci != null) ix[g] = ci;
      }
    }
    // blush first, so eyes and nose sit on top of it
    if (opts.blush && eyes.length) {
      var bl = idx("blush", STAMP_COLORS.blush), mid = eyes.length === 2 ? (eyes[0][0] + eyes[1][0]) / 2 : (nose ? nose[0] : eyes[0][0]);
      var cheek = sz === "s" ? ["b"] : sz === "xl" ? ["bbb"] : ["bb"], dy = { xl: 4.5, l: 3.5, m: 2.5, s: 1.5 }[sz], dx = { xl: 2.5, l: 1.5, m: 1, s: 1 }[sz];
      eyes.forEach(function (e) { var side = e[0] < mid ? -1 : 1; if (eyes.length === 1 && nose) side = e[0] < nose[0] ? -1 : 1; put(cheek, e[0] + side * dx, e[1] + dy, function () { return bl; }, true); });
    }
    // both eyes share one iris color: the more colorful of the two samples (one eye is often in shadow)
    var raw = null;
    face.eyes.forEach(function (fe) { var c = sampleIris(src, fe[0], fe[1], spread * 2.5); if (c && (!raw || Math.hypot(c[1], c[2]) > Math.hypot(raw[1], raw[2]))) raw = c; });
    var chroma = raw ? Math.hypot(raw[1], raw[2]) : 0, boost = chroma ? Math.min(2.6, 0.13 / chroma) : 1;
    var iris = !friendly && !dark && raw && chroma > 0.025 && raw[0] > 0.18 ? [Math.max(0.62, Math.min(0.74, raw[0] + 0.12)), raw[1] * boost, raw[2] * boost] : null;
    eyes.forEach(function (e) {
      var pupil = idx("pupil", [Math.min(0.17, ink[0]), ink[1] * 0.7, ink[2] * 0.7]), white = idx("white", STAMP_COLORS.w);
      var irisI = iris ? idx("iris", iris) : idx("iris-dark", dark ? [0.2, 0.01, 0.012] : friendly ? [0.26, 0.012, 0.02] : [Math.max(0.36, ink[0] + 0.2), 0.025, 0.045]);
      var ringI = friendly ? pupil : idx("ring", [Math.min(0.2, ink[0]), ink[1], ink[2]]);
      put(EYES[esz], e[0], e[1], function (ch) { return ch === "e" ? pupil : ch === "w" ? white : ch === "k" ? ringI : irisI; });
    });
    if (nose && dark) {   // dark coats: a soft grey muzzle around the nose so it reads (like a greying poodle face)
      var muz = idx("muzzle", [0.6, 0.006, 0.002]), muz2 = idx("muzzle2", [0.74, 0.004, 0.002]);
      var mw = { xl: 9, l: 7, m: 6, s: 4 }[sz], mh = { xl: 6, l: 5, m: 4, s: 3 }[sz], mp = [];
      for (var r = 0; r < mh; r++) { var row = ""; for (var c = 0; c < mw; c++) { var ex = (c + 0.5 - mw / 2) / (mw / 2), ey = (r + 0.5 - mh / 2) / (mh / 2); row += ex * ex + ey * ey <= 1.05 ? (ey < -0.3 && ex < 0 ? "u" : "g") : "."; } mp.push(row); }
      put(mp, nose[0], nose[1] + 0.5, function (ch) { return ch === "u" ? muz2 : muz; }, true);
    }
    if (nose) {
      var nI = idx("nose", dark ? [0.14, 0.01, -0.004] : [Math.min(0.26, ink[0] + 0.06), ink[1] * 0.6 + 0.01, ink[2] * 0.4]), hI = idx("noseshine", STAMP_COLORS.h);
      var np = NOSES[sz], nh = np.length;
      put(np, nose[0], nose[1], function (ch) { return ch === "h" ? hI : nI; });
      var below = nose[1] + nh / 2 + (sz === "s" ? 0.5 : 1);
      if (opts.mouth === "smile" || opts.mouth === "tongue") {
        var mI = idx("mouth", [Math.min(0.2, ink[0]), ink[1], ink[2]]), mp = MOUTHS[sz];
        put(mp, nose[0], below + mp.length / 2 - 0.5, function () { return mI; }, true);
        if (opts.mouth === "tongue") {
          var tI = idx("tongue", STAMP_COLORS.t), TI = idx("tongue2", STAMP_COLORS.T), tp = TONGUES[sz];
          put(tp, nose[0], below + mp.length + tp.length / 2 - 0.5, function (ch) { return ch === "T" ? TI : tI; });
        }
      }
    }
  }

  // best-effort face guess: two dark, round-ish spots side by side in the upper part of the dog, and a dark blob below them.
  // Returns normalized {eyes, nose, confidence} or null; the maker shows it as a suggestion the member can fix with taps.
  function guessFace(src) {
    var W = src.width, H = src.height, box = mainBox(src.mask, W, H), bw = box[2] - box[0] + 1, bh = box[3] - box[1] + 1;
    var st = Math.max(1, Math.round(Math.max(bw, bh) / 90)), gw = Math.ceil(bw / st), gh = Math.ceil(bh / st), L = new Float64Array(gw * gh), m = new Uint8Array(gw * gh), x, y;
    for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
      var sx = box[0] + x * st, sy = box[1] + y * st, o = sy * W + sx;
      if (sx >= W || sy >= H) continue;
      m[y * gw + x] = src.mask[o] > 160 ? 1 : 0;
      L[y * gw + x] = toLab(src.data[4 * o], src.data[4 * o + 1], src.data[4 * o + 2])[0];
    }
    var r = Math.max(2, Math.round(Math.min(gw, gh) / 14)), cands = [];
    for (y = r; y < Math.min(gh - r, Math.round(gh * 0.6)); y++) for (x = r; x < gw - r; x++) {
      if (!m[y * gw + x]) continue;
      var inner = 0, ni = 0, ring = 0, nr = 0, ok = true;
      for (var dy = -2 * r; dy <= 2 * r && ok; dy++) for (var dx = -2 * r; dx <= 2 * r; dx++) {
        var xx = x + dx, yy = y + dy, d2 = dx * dx + dy * dy; if (xx < 0 || yy < 0 || xx >= gw || yy >= gh) continue;
        if (d2 <= (r * 0.6) * (r * 0.6)) { if (!m[yy * gw + xx]) { ok = false; break; } inner += L[yy * gw + xx]; ni++; }
        else if (d2 <= 4 * r * r && d2 >= r * r && m[yy * gw + xx]) { ring += L[yy * gw + xx]; nr++; }
      }
      if (!ok || !ni || nr < 6) continue;
      var contrast = ring / nr - inner / ni;
      if (contrast > 0.08) cands.push([contrast, x, y]);
    }
    cands.sort(function (a, b) { return b[0] - a[0]; });
    var picks = [];   // non-maximum suppression
    for (var i = 0; i < cands.length && picks.length < 8; i++) if (picks.every(function (p) { return Math.hypot(p[1] - cands[i][1], p[2] - cands[i][2]) > r * 1.5; })) picks.push(cands[i]);
    var best = null;
    for (i = 0; i < picks.length; i++) for (var j = i + 1; j < picks.length; j++) {
      var a = picks[i], b = picks[j], dxe = Math.abs(a[1] - b[1]), dye = Math.abs(a[2] - b[2]);
      if (dxe < gw * 0.08 || dxe > gw * 0.45 || dye > dxe * 0.5) continue;
      var score = a[0] + b[0] - dye / gw;
      if (!best || score > best.score) best = { score: score, e: [a, b] };
    }
    if (!best || best.score < 0.28) return null;   // not confident: let the member tap
    var e1 = best.e[0], e2 = best.e[1], mx = (e1[1] + e2[1]) / 2, my = (e1[2] + e2[2]) / 2, de = Math.abs(e1[1] - e2[1]), nose = null, nb = 0;
    for (i = 0; i < picks.length; i++) {
      var p = picks[i]; if (p === e1 || p === e2) continue;
      if (p[2] > my + de * 0.3 && p[2] < my + de * 1.4 && Math.abs(p[1] - mx) < de * 0.6 && p[0] > nb) { nb = p[0]; nose = p; }
    }
    function nrm(p) { return [(box[0] + p[1] * st) / W, (box[1] + p[2] * st) / H]; }
    return { eyes: [nrm(e1), nrm(e2)].sort(function (a, b) { return a[0] - b[0]; }), nose: nose ? nrm(nose) : null, confidence: Math.min(1, best.score / 0.4) };
  }

  // ================================================================ "toon": chunky, cute, hand-made game sprite
  // The photo only supplies the silhouette and a few flat coat colors; everything else is regularized and drawn
  // from hand-designed stamps (small dark eyes with one shine, a rounded nose, a light muzzle, a red heart tag).
  var TOON = {
    eyes: { xl: ["we", "ee"], l: ["we", "ee"], m: ["w", "e"], s: ["e"] },
    happy: { xl: [".e.", "e.e"], l: [".e.", "e.e"], m: ["ee"], s: ["e"] },
    noses: { xl: ["nhnnn", "nnnnn", ".nnn."], l: ["nhnn", "nnnn", ".nn."], m: ["nhn", ".n."], s: ["nn"] },
    mouths: { xl: ["..m..", "m...m", ".mmm."], l: ["m....m", ".mmmm."], m: ["m...m", ".mmm."], s: [] },
    tongues: { xl: ["tt", "tt"], l: ["tt", "tt"], m: ["t"], s: ["t"] },
    spots: [["pp", "pp"], ["ppp", ".pp"], ["pp.", "ppp"]],
    heart: ["r.r", "rrr", ".r."],
    heartS: ["rr"]
  };
  var TOON_COLORS = { white: [0.99, 0, 0.003], blush: [0.8, 0.065, 0.02], tongue: [0.72, 0.15, 0.035], ear: [0.8, 0.07, 0.012], heart: [0.6, 0.2, 0.09], heartHi: [0.75, 0.15, 0.06] };

  // shorter, stubbier body: squeeze everything below the head (vertically) and beside it (horizontally)
  function stubby(src, face, amount) {
    var hc = headCircle(face, src); if (!hc) return { src: src, face: face };
    var a = Math.max(0, Math.min(2, amount)), ky = 1 - 0.3 * a, kx = 1 - 0.18 * a;
    var W = src.width, H = src.height, yb = hc.y + hc.r * 0.85, xl = hc.x - hc.r, xr = hc.x + hc.r;
    var data = new Uint8ClampedArray(W * H * 4), mask = new Uint8Array(W * H);
    var mapX = new Float64Array(W);
    for (var x = 0; x < W; x++) mapX[x] = x > xr ? xr + (x - xr) / kx : x < xl ? xl - (xl - x) / kx : x;
    for (var y = 0; y < H; y++) {
      var sy = y > yb ? yb + (y - yb) / ky : y; if (sy > H - 1.001 || sy < 0) continue;
      var iy = sy | 0, fy = sy - iy;
      for (x = 0; x < W; x++) {
        var sx = mapX[x]; if (sx < 0 || sx > W - 1.001) continue;
        var ix = sx | 0, fx = sx - ix, o = y * W + x, p = iy * W + ix;
        var w00 = (1 - fx) * (1 - fy), w10 = fx * (1 - fy), w01 = (1 - fx) * fy, w11 = fx * fy;
        for (var ch = 0; ch < 4; ch++) data[4 * o + ch] = src.data[4 * p + ch] * w00 + src.data[4 * p + 4 + ch] * w10 + src.data[4 * (p + W) + ch] * w01 + src.data[4 * (p + W) + 4 + ch] * w11;
        mask[o] = src.mask[p] * w00 + src.mask[p + 1] * w10 + src.mask[p + W] * w01 + src.mask[p + W + 1] * w11;
      }
    }
    function fwd(q) { var X = q[0], Y = q[1]; return [X > xr ? xr + (X - xr) * kx : X < xl ? xl - (xl - X) * kx : X, Y > yb ? yb + (Y - yb) * ky : Y]; }
    return { src: { width: W, height: H, data: data, mask: mask }, face: { eyes: face.eyes.map(fwd), nose: face.nose && fwd(face.nose) } };
  }

  // flood-fill components of equal labels (4-connected)
  function components(lbl, w, h, skip) {
    var id = new Int32Array(w * h).fill(-1), comps = [], stack = [];
    for (var i = 0; i < w * h; i++) {
      if (lbl[i] === skip || id[i] >= 0) continue;
      var v = lbl[i], cells = [], c = comps.length; id[i] = c; stack.push(i);
      while (stack.length) {
        var p = stack.pop(); cells.push(p); var x = p % w, y = (p - x) / w;
        if (x > 0 && id[p - 1] < 0 && lbl[p - 1] === v) { id[p - 1] = c; stack.push(p - 1); }
        if (x < w - 1 && id[p + 1] < 0 && lbl[p + 1] === v) { id[p + 1] = c; stack.push(p + 1); }
        if (y > 0 && id[p - w] < 0 && lbl[p - w] === v) { id[p - w] = c; stack.push(p - w); }
        if (y < h - 1 && id[p + w] < 0 && lbl[p + w] === v) { id[p + w] = c; stack.push(p + w); }
      }
      comps.push({ v: v, cells: cells });
    }
    return { id: id, comps: comps };
  }

  // big, clean, flat regions: a few majority passes, then every island smaller than minSize joins its neighbour
  function regularize(lbl, w, h, passes, minSize) {
    var x, y, i;
    for (var ps = 0; ps < passes; ps++) {
      var out = lbl.slice();
      for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        i = y * w + x; if (lbl[i] < 0) continue;
        var cnt = {}, self = 0;
        for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
          var xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
          var u = lbl[yy * w + xx]; if (u < 0) continue; cnt[u] = (cnt[u] || 0) + 1;
        }
        self = cnt[lbl[i]];
        for (var k in cnt) if (cnt[k] > self && cnt[k] >= 5) { out[i] = +k; self = cnt[k]; }
      }
      for (i = 0; i < lbl.length; i++) lbl[i] = out[i];
    }
    for (var round = 0; round < 3; round++) {
      var cc = components(lbl, w, h, -1), changed = false;
      cc.comps.forEach(function (c, ci) {
        if (c.cells.length >= minSize) return;
        var cnt = {}, best = -1, bc = 0;
        c.cells.forEach(function (p) {
          var px = p % w, py = (p - px) / w, nb = [px > 0 ? p - 1 : -1, px < w - 1 ? p + 1 : -1, py > 0 ? p - w : -1, py < h - 1 ? p + w : -1];
          nb.forEach(function (q) { if (q >= 0 && lbl[q] >= 0 && cc.id[q] !== ci) { cnt[lbl[q]] = (cnt[lbl[q]] || 0) + 1; if (cnt[lbl[q]] > bc) { bc = cnt[lbl[q]]; best = lbl[q]; } } });
        });
        if (best >= 0) { c.cells.forEach(function (p) { lbl[p] = best; }); changed = true; }
      });
      if (!changed) break;
    }
  }

  // rounded silhouette: 3x3 majority on the alpha (rounds corners, fills notches) without erasing 2px legs
  function roundAlpha(a, w, h) {
    var out = a.slice();
    function at(xx, yy) { return xx >= 0 && yy >= 0 && xx < w && yy < h && a[yy * w + xx]; }
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var n = 0;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) { var xx = x + dx, yy = y + dy; if (xx >= 0 && yy >= 0 && xx < w && yy < h && a[yy * w + xx]) n++; }
      var i = y * w + x;
      if (!a[i] && n >= 6) out[i] = 1;
      else if (a[i] && n <= 3) out[i] = 0;
      else if (a[i] && n <= 4 && !at(x - 1, y) && !at(x + 1, y) && !at(x, y + 1)) out[i] = 0;   // a 1-px spike hanging down
      else if (a[i] && n === 4) {   // a square convex corner of a part at least 3 px thick both ways gets cut
        for (var c = 0; c < 4; c++) {
          var sx = c & 1 ? 1 : -1, sy = c & 2 ? 1 : -1;   // the direction the body extends in
          if (at(x - sx, y) || at(x, y - sy)) continue;
          if (at(x + sx, y) && at(x + 2 * sx, y) && at(x, y + sy) && at(x, y + 2 * sy) && at(x + sx, y + sy) && at(x + 2 * sx, y + 2 * sy)) { out[i] = 0; break; }
        }
      }
    }
    for (var k = 0; k < a.length; k++) a[k] = out[k];
    // cutting corners can leave a new 1-px nub hanging below a foot: trim one pixel (from a snapshot, so thin legs only lose their tip)
    var cut = [];
    for (y = 1; y < h; y++) for (x = 0; x < w; x++)
      if (a[y * w + x] && !at(x - 1, y) && !at(x + 1, y) && !at(x, y + 1) && !at(x - 1, y + 1) && !at(x + 1, y + 1) && (at(x - 1, y - 1) || at(x, y - 1) || at(x + 1, y - 1))) cut.push(y * w + x);
    cut.forEach(function (q) { a[q] = 0; });
  }

  function renderToon(src, opts) {
    var W0 = src.width, H0 = src.height;
    var face = normFace(opts.face, W0, H0), amount = opts.chibi || 0;
    if (amount > 0 && face) {
      // a small head on a full-body photo gets a stronger boost than a close-up portrait
      var hc0 = headCircle(face, src), bb0 = mainBox(src.mask, W0, H0), q = hc0 ? hc0.r / Math.max(bb0[2] - bb0[0] + 1, bb0[3] - bb0[1] + 1) : 0.4;
      var wr = bigHead(src, face, amount, 0.5 + Math.max(0, Math.min(0.3, (0.36 - q) * 2.2))); src = wr.src; face = wr.face;
      wr = stubby(src, face, amount * (1 + Math.max(0, Math.min(0.5, (0.36 - q) * 3)))); src = wr.src; face = wr.face;
    }
    var N = Math.max(16, Math.min(64, opts.size | 0)), W = src.width, H = src.height, px = src.data, mask = src.mask, x, y, i, g;
    var box = mainBox(mask, W, H), x0 = box[0], y0 = box[1], bw = box[2] - x0 + 1, bh = box[3] - y0 + 1;
    var bottom = opts.shadow ? 2 : 1, innerW = N - 2, innerH = N - 1 - bottom;
    var scale = Math.max(bw / innerW, bh / innerH);
    var gw = Math.max(1, Math.min(innerW, Math.round(bw / scale))), gh = Math.max(1, Math.min(innerH, Math.round(bh / scale))), G = gw * gh;

    // 1. per-cell coverage and mean color (linear RGB, solid mask only), plus how much of the cell is a vivid red/pink accent
    var sr = new Float64Array(G), sg = new Float64Array(G), sb = new Float64Array(G), sw = new Float64Array(G), cov = new Float64Array(G), cnt = new Float64Array(G);
    var vr = new Float64Array(G), vg = new Float64Array(G), vb = new Float64Array(G), vn = new Float64Array(G);
    var st = Math.max(1, Math.floor(scale / 6));
    for (y = 0; y < bh; y += st) {
      var gy = Math.min(gh - 1, Math.floor(y * gh / bh));
      for (x = 0; x < bw; x += st) {
        var gx = Math.min(gw - 1, Math.floor(x * gw / bw)), c = gy * gw + gx, p = (y + y0) * W + x + x0, m = mask[p];
        cnt[c]++; cov[c] += m / 255; if (m < 200) continue;
        var R = LUT[px[4 * p]], Gc = LUT[px[4 * p + 1]], B = LUT[px[4 * p + 2]];
        sr[c] += R; sg[c] += Gc; sb[c] += B; sw[c]++;
        if (R > 0.08 && R > Gc * 3 && R > B * 2.2) { var vl = toLab(px[4 * p], px[4 * p + 1], px[4 * p + 2]); if (vl[1] > 0.07 && Math.hypot(vl[1], vl[2]) > 0.085) { vr[c] += R; vg[c] += Gc; vb[c] += B; vn[c]++; } }
      }
    }
    function linLab(r, gg, b) { return toLab(l2s(r), l2s(gg), l2s(b)); }
    var ga = new Uint8Array(G), lab = new Array(G), vivid = new Uint8Array(G);
    for (g = 0; g < G; g++) {
      cov[g] = cnt[g] ? cov[g] / cnt[g] : 0;
      ga[g] = cov[g] >= 0.45 ? 1 : 0;
      lab[g] = sw[g] ? linLab(sr[g] / sw[g], sg[g] / sw[g], sb[g] / sw[g]) : null;
      if (sw[g] && vn[g] >= Math.max(1, sw[g] * 0.12)) vivid[g] = 1;
    }
    // 2. silhouette: drop specks, round corners, fill notches
    cleanAlpha(ga, gw, gh, lab.map(function (l) { return l || [0.5, 0, 0]; }));
    roundAlpha(ga, gw, gh);
    for (g = 0; g < G; g++) if (ga[g] && !lab[g]) {   // borrowed color for cells with no solid samples
      var gx2 = g % gw, gy2 = (g - gx2) / gw;
      for (var rr = 1; rr < 4 && !lab[g]; rr++) for (var dy = -rr; dy <= rr && !lab[g]; dy++) for (var dx = -rr; dx <= rr; dx++) {
        var qx = gx2 + dx, qy = gy2 + dy; if (qx >= 0 && qy >= 0 && qx < gw && qy < gh && lab[qy * gw + qx]) { lab[g] = lab[qy * gw + qx]; break; }
      }
      if (!lab[g]) lab[g] = [0.5, 0, 0];
    }

    // 3. coat regions: k-means on the coat (not the accent), merged by lightness; a dark coat is one region
    var coat = [], cw = [];
    for (g = 0; g < G; g++) if (ga[g] && !vivid[g]) { coat.push(lab[g]); cw.push(1); }
    if (!coat.length) for (g = 0; g < G; g++) if (ga[g]) { coat.push(lab[g]); cw.push(1); }
    var Ls = coat.map(function (c) { return c[0]; }).sort(function (a, b) { return a - b; });
    var med = Ls.length ? Ls[Math.floor(Ls.length / 2)] : 0.5, dark = med < 0.4;
    var maxRegions = opts.regions || (opts.colors >= 12 ? 3 : opts.colors >= 8 ? 2 : 1);
    var cents = dark || maxRegions < 2 ? [coat.length ? meanLab(coat) : [0.5, 0, 0]] : kmeans(coat, cw, Math.min(3, maxRegions + 1), 20);
    cents.sort(function (a, b) { return a[0] - b[0]; });
    var lbl = new Int16Array(G).fill(-1);
    for (g = 0; g < G; g++) if (ga[g]) lbl[g] = nearest(cents, lab[g]);
    // merge clusters that are too alike, and cap the number of regions (merge the smallest into its nearest)
    var sizes = cents.map(function () { return 0; }); for (g = 0; g < G; g++) if (lbl[g] >= 0) sizes[lbl[g]]++;
    var alive = cents.map(function (_, k) { return k; });
    function remap(from, to) { for (var q = 0; q < G; q++) if (lbl[q] === from) lbl[q] = to; sizes[to] += sizes[from]; sizes[from] = 0; alive = alive.filter(function (k) { return k !== from; }); }
    for (var guard = 0; guard < 4 && alive.length > 1; guard++) {
      var bestPair = null, bd = Infinity;
      for (var a1 = 0; a1 < alive.length; a1++) for (var a2 = a1 + 1; a2 < alive.length; a2++) { var d = dist(cents[alive[a1]], cents[alive[a2]]); if (d < bd) { bd = d; bestPair = [alive[a1], alive[a2]]; } }
      if (bd > 0.07 * 0.07 * 1.96 && alive.length <= maxRegions) break;
      var small = sizes[bestPair[0]] < sizes[bestPair[1]] ? bestPair[0] : bestPair[1];
      remap(small, small === bestPair[0] ? bestPair[1] : bestPair[0]);
    }
    var minIsl = Math.max(3, Math.round(G * 0.012 * (opts.clean == null ? 2 : opts.clean)));
    regularize(lbl, gw, gh, opts.clean == null ? 2 : Math.min(3, opts.clean), minIsl);
    sizes = cents.map(function () { return 0; }); for (g = 0; g < G; g++) if (lbl[g] >= 0) sizes[lbl[g]]++;
    var baseK = 0; for (var k2 = 0; k2 < sizes.length; k2++) if (sizes[k2] > sizes[baseK]) baseK = k2;

    // 4. friendly flat colors: light coats become a warm pastel, patches stay soft; black coats a cool charcoal
    var pal = [], cache = {};
    function idx(key, c) { if (cache[key] == null) cache[key] = pal.push(c) - 1; return cache[key]; }
    var sat = opts.saturation || 1.15, regionCol = {}, cb = cents[baseK];
    var baseL = dark ? 0.31 : Math.max(0.78, Math.min(0.86, cb[0] + 0.12));
    Object.keys(sizes).forEach(function (k) {
      if (!sizes[k]) return; var c = cents[k], L, A, B;
      if (dark) { L = baseL; A = c[1] * 0.3 - 0.002; B = c[2] * 0.3 - 0.013; }
      else {
        var dL = c[0] - cb[0];
        L = +k === baseK ? baseL : baseL + (dL < 0 ? -1 : 1) * Math.max(0.12, Math.min(0.2, Math.abs(dL) * 0.8));
        A = c[1] * sat; B = c[2] * sat + (+k === baseK ? 0.004 : 0);
        var chr = Math.hypot(A, B); if (chr < 0.03) { A += 0.008; B += 0.02; }   // never a dead grey: nudge warm
      }
      regionCol[k] = [L, A, B];
    });
    var ink = dark ? [0.15, -0.004, -0.02] : [0.27, regionCol[baseK][1] * 0.5 + 0.02, regionCol[baseK][2] * 0.4 + 0.025];
    var inkI = idx("ink", ink);
    var shades = {};
    Object.keys(regionCol).forEach(function (k) {
      var c = regionCol[k], big = sizes[k] >= G * 0.05 || +k === baseK;
      shades[k] = { base: idx("r" + k, c),
        hl: big ? idx("h" + k, dark ? [c[0] + 0.13, c[1] - 0.006, c[2] - 0.035] : [Math.min(0.96, c[0] + 0.07), c[1] * 0.9, c[2] * 0.9 + 0.004]) : null,
        sh: big ? idx("s" + k, dark ? [c[0] - 0.075, c[1], c[2] - 0.01] : [c[0] - 0.1, c[1] * 1.05 + 0.006, c[2] * 1.05 - 0.004]) : null };
    });

    // 5. face geometry on the grid: level eyes, spread a little wider and lower; nose centred under them (front-ish)
    var fg = null;
    if (face) {
      var toG = function (q) { return [(q[0] - x0) * gw / bw, (q[1] - y0) * gh / bh]; };
      var eyes = face.eyes.map(toG), nose = face.nose && toG(face.nose), unit;
      if (eyes.length === 2) {
        eyes.sort(function (a, b) { return a[0] - b[0]; });
        var mx = (eyes[0][0] + eyes[1][0]) / 2, my = (eyes[0][1] + eyes[1][1]) / 2, de = Math.max(1, Math.hypot(eyes[1][0] - eyes[0][0], eyes[1][1] - eyes[0][1]));
        var half = Math.max(1.5, de * (de >= 10 ? 0.52 : 0.56)), ey = my + de * 0.1;
        eyes = [[mx - half, ey], [mx + half, ey]]; unit = de;
        if (nose && opts.front !== false) nose = [mx, Math.max(ey + Math.max(1.6, de * 0.32), Math.min(nose[1], ey + de * 0.5))];
      } else if (eyes.length === 1 && nose) { unit = Math.hypot(eyes[0][0] - nose[0], eyes[0][1] - nose[1]) * 1.25; eyes[0][1] += unit * 0.08; }
      else unit = N / 6;
      eyes = eyes.map(function (e) {   // keep each eye at least 2 cells inside the silhouette
        var ex2 = e[0], ey2 = Math.round(e[1] - 0.5), cxm = eyes.length === 2 ? (eyes[0][0] + eyes[1][0]) / 2 : (nose ? nose[0] : e[0]), dir = e[0] < cxm ? -1 : 1;
        function solid(xx) { xx = Math.round(xx - 0.5); return xx >= 0 && xx < gw && ey2 >= 0 && ey2 < gh && ga[ey2 * gw + xx]; }
        for (var t = 0; t < 3 && !(solid(ex2 + dir * 2) && solid(ex2 + dir)); t++) ex2 -= dir;
        return [ex2, e[1]];
      });
      fg = { eyes: eyes, nose: nose, unit: unit, sz: unit >= 10 ? "xl" : unit >= 6.5 ? "l" : unit >= 3.5 ? "m" : "s" };
    }

    // 6. paint: regions, then light muzzle (around the nose), pink inner ears, curls, cel shading
    if (fg && !dark && fg.eyes.length === 2) {   // no dark "mask" across the eyes: the face zone is base coat
      var fe0 = fg.eyes[0], fe1 = fg.eyes[1], fcx = (fe0[0] + fe1[0]) / 2, fdd = fe1[0] - fe0[0], cleared = false;
      for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
        g = y * gw + x; if (lbl[g] < 0 || lbl[g] === baseK || regionCol[lbl[g]][0] > baseL) continue;
        var fx = (x + 0.5 - fcx) / (fdd * 0.85), fy = (y + 0.5 - (fe0[1] + fdd * 0.15)) / (fdd * 0.5);
        if (fx * fx + fy * fy <= 1) { lbl[g] = baseK; cleared = true; }
      }
      if (cleared) regularize(lbl, gw, gh, 0, minIsl);
    }
    var ix = new Int16Array(G).fill(-1), role = new Int8Array(G);   // role 0 coat, 1 muzzle, 2 ear
    for (g = 0; g < G; g++) if (ga[g]) ix[g] = shades[lbl[g]].base;
    var muzzleK = null;
    if (fg && fg.nose && opts.faceStamps !== false) {
      var mzc = dark ? [0.56, -0.006, -0.022] : [Math.min(0.95, baseL + 0.13), regionCol[baseK][1] * 0.45, regionCol[baseK][2] * 0.5 + 0.006];
      var muzI = idx("muzzle", mzc), muzS = idx("muzzle-s", dark ? [0.44, -0.008, -0.03] : [mzc[0] - 0.07, mzc[1] * 1.2 + 0.004, mzc[2] * 1.1 + 0.004]);
      muzzleK = { base: muzI, sh: muzS };
      var u = fg.unit, rx = Math.max(2.2, u * (dark ? 0.66 : 0.52)), ry = Math.max(1.6, u * (dark ? 0.42 : 0.36)), ncx = fg.nose[0], ncy = fg.nose[1] + ry * (dark ? 0.6 : 0.35);
      for (y = Math.floor(ncy - ry - 1); y <= Math.ceil(ncy + ry + 1); y++) for (x = Math.floor(ncx - rx - 1); x <= Math.ceil(ncx + rx + 1); x++) {
        if (x < 0 || y < 0 || x >= gw || y >= gh) continue; g = y * gw + x; if (!ga[g]) continue;
        var ex = (x + 0.5 - ncx) / rx, eyy = (y + 0.5 - ncy) / ry;
        if (ex * ex + eyy * eyy <= 1) { ix[g] = muzI; role[g] = 1; }
      }
      // a light coat's darkest patch never sits on the face: soften dark masks around the eyes to the coat's patch tone
    }
    if (fg && !dark && fg.eyes.length === 2 && opts.faceStamps !== false) {
      var e0 = fg.eyes[0], e1 = fg.eyes[1], cxh = (e0[0] + e1[0]) / 2, dd = e1[0] - e0[0], earI = idx("ear", TOON_COLORS.ear);
      var isEar = new Uint8Array(G);
      for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
        g = y * gw + x; if (!ga[g] || y > e0[1] - dd * 0.55) continue;
        var ddx = (x + 0.5 - cxh) / (dd * 1.0), ddy = (y + 0.5 - (e0[1] + dd * 0.15)) / (dd * 0.85);
        if (ddx * ddx + ddy * ddy > 1) isEar[g] = 1;
      }
      var ecc = components(Array.prototype.map.call(isEar, function (v) { return v ? 1 : 0; }), gw, gh, 0);
      ecc.comps.forEach(function (c) {
        if (c.cells.length < 4) return;
        c.cells.forEach(function (q) {
          var qx = q % gw, qy = (q - qx) / gw, inner = true;
          for (var oy = -1; oy <= 1 && inner; oy++) for (var ox = -1; ox <= 1; ox++) { var tx = qx + ox, ty = qy + oy; if (tx < 0 || ty < 0 || tx >= gw || ty >= gh || !ga[ty * gw + tx]) { inner = false; break; } }
          if (inner && qy + 1 < gh && ga[q + gw]) { ix[q] = earI; role[q] = 2; }
        });
      });
    }
    function off(xx, yy) { return xx < 0 || yy < 0 || xx >= gw || yy >= gh || !ga[yy * gw + xx]; }
    var out2 = ix.slice();
    for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) {
      g = y * gw + x; if (!ga[g] || role[g] === 2) continue;
      var sh = role[g] === 1 ? muzzleK : shades[lbl[g]];
      var lit = off(x, y - 1) || off(x - 1, y), shade = off(x, y + 1) || off(x + 1, y) || (!off(x, y + 1) && off(x + 1, y + 1) && off(x, y + 2));
      if (role[g] === 1) { if (shade && sh.sh != null) out2[g] = sh.sh; continue; }
      if (shade && !lit && sh.sh != null) out2[g] = sh.sh; else if (lit && !shade && sh.hl != null) out2[g] = sh.hl;
    }
    ix = out2;
    if (dark && opts.curls !== false) {   // curly coat hint: a sparse, regular sprinkle of highlight pixels away from the edges
      var hlI = shades[baseK].hl;
      for (y = 2; y < gh - 2; y++) for (x = 2; x < gw - 2; x++) {
        g = y * gw + x; if (!ga[g] || role[g] || ix[g] !== shades[lbl[g]].base) continue;
        var ok = true; for (var cy2 = -2; cy2 <= 2 && ok; cy2++) for (var cx2 = -2; cx2 <= 2; cx2++) if (off(x + cx2, y + cy2)) { ok = false; break; }
        if (!ok) continue;
        var row = Math.floor(y / 3);
        if (y % 4 === 1 && (x + row * 3) % 6 === 0) { ix[g] = hlI; if (x + 1 < gw && ga[g + gw + 1] && !role[g + gw + 1]) ix[g + gw + 1] = hlI; }
      }
    }

    // merle / spotted coats: a few simple, chunky patches where the photo is darkest (never on the face)
    if (!dark && opts.spots !== false) {
      var darker = 0, coatN = 0;
      for (g = 0; g < G; g++) if (ga[g] && !vivid[g]) { coatN++; if (lab[g][0] < cb[0] - 0.05) darker++; }
      if (coatN && darker > coatN * 0.08 && darker < coatN * 0.5) {
        var pk = null; Object.keys(regionCol).forEach(function (k) { if (regionCol[k][0] < baseL - 0.05 && (pk == null || sizes[k] > sizes[pk])) pk = k; });
        var pc = pk != null ? regionCol[pk] : [baseL - 0.15, regionCol[baseK][1] * 0.7, regionCol[baseK][2] * 0.6];
        var spotI = pk != null ? shades[pk].base : idx("spot", pc), cand = [];
        var avoid = function (xx, yy) {
          if (!fg || fg.eyes.length < 1) return false;
          var ee = fg.eyes, fx2 = ee.length === 2 ? (ee[0][0] + ee[1][0]) / 2 : ee[0][0], fy2 = ee[0][1] + fg.unit * 0.2;
          var rx2 = fg.unit * (ee.length === 2 ? 1.0 : 0.9), ry2 = fg.unit * 0.65, ax = (xx + 0.5 - fx2) / rx2, ay = (yy + 0.5 - fy2) / ry2;
          return ax * ax + ay * ay <= 1;
        };
        for (y = 1; y < gh - 1; y++) for (x = 1; x < gw - 1; x++) {
          g = y * gw + x; if (!ga[g] || role[g] || lbl[g] !== baseK) continue;
          var inside = true; for (var sy2 = -2; sy2 <= 2 && inside; sy2++) for (var sx2 = -2; sx2 <= 2; sx2++) if (off(x + sx2, y + sy2)) { inside = false; break; }
          if (!inside || avoid(x, y)) continue;
          var dsum = 0; for (var by = -1; by <= 1; by++) for (var bx = -1; bx <= 1; bx++) dsum += cb[0] - lab[(y + by) * gw + x + bx][0];
          if (dsum / 9 > 0.04) cand.push([dsum / 9, x, y]);
        }
        cand.sort(function (a, b) { return b[0] - a[0] || a[2] - b[2] || a[1] - b[1]; });
        var picked = [], maxSpots = Math.max(2, Math.round(G / 90));
        cand.forEach(function (cnd) {
          if (picked.length >= maxSpots || picked.some(function (q) { return Math.max(Math.abs(q[1] - cnd[1]), Math.abs(q[2] - cnd[2])) < 5; })) return;
          picked.push(cnd);
          var sp = TOON.spots[picked.length % TOON.spots.length];
          for (var r2 = 0; r2 < sp.length; r2++) for (var c2 = 0; c2 < sp[r2].length; c2++) {
            if (sp[r2][c2] !== "p") continue; var tx = cnd[1] + c2 - 1, ty = cnd[2] + r2;
            if (tx < 0 || ty < 0 || tx >= gw || ty >= gh) continue; var tg = ty * gw + tx;
            if (ga[tg] && !role[tg] && lbl[tg] === baseK && ix[tg] === shades[baseK].base && !avoid(tx, ty)) ix[tg] = spotI;
          }
        });
      }
    }

    // 7. accent: a small red/pink spot (a collar tag) becomes a clear little red heart
    var vc = components(Array.prototype.map.call(vivid, function (v, q) { return v && ga[q] ? 1 : 0; }), gw, gh, 0);
    vc.comps.forEach(function (c) {
      if (c.cells.length > G * 0.05) return;
      var hx = 0, hy = 0; c.cells.forEach(function (q) { hx += q % gw; hy += Math.floor(q / gw); }); hx = hx / c.cells.length + 0.5; hy = hy / c.cells.length + 0.5;
      if (fg && fg.nose && Math.hypot(hx - fg.nose[0], hy - fg.nose[1]) < fg.unit * 0.55) return;   // that is a tongue, not a tag
      var rI = idx("heart", TOON_COLORS.heart), rh = idx("heart-hi", TOON_COLORS.heartHi);
      var pat = N >= 28 ? TOON.heart : TOON.heartS, bestFit = -1, bx = hx, by = hy;
      for (var sdy = -1; sdy <= 1; sdy++) for (var sdx = -2; sdx <= 2; sdx++) {   // nudge it fully inside the dog
        var fit = 0, hox = Math.round(hx + sdx - pat[0].length / 2), hoy = Math.round(hy + sdy - pat.length / 2);
        for (var hr = 0; hr < pat.length; hr++) for (var hc2 = 0; hc2 < pat[0].length; hc2++) {
          var tx2 = hox + hc2, ty2 = hoy + hr; if (pat[hr][hc2] === "." ) continue;
          if (tx2 >= 0 && ty2 >= 0 && tx2 < gw && ty2 < gh && ga[ty2 * gw + tx2] && (tx2 + 1 >= gw || ga[ty2 * gw + tx2 + 1] || hc2 < pat[0].length - 1) && (tx2 < 1 || ga[ty2 * gw + tx2 - 1])) fit++;
        }
        fit -= (Math.abs(sdx) + Math.abs(sdy)) * 0.1;
        if (fit > bestFit) { bestFit = fit; bx = hx + sdx; by = hy + sdy; }
      }
      hx = bx; hy = by;
      stamp(ix, gw, gh, pat, hx, hy, function (ch, r, cc) { return r === 0 && cc === 0 ? rh : rI; }, false, ga);
    });

    // 8. face stamps
    if (fg && opts.faceStamps !== false) {
      var sz = fg.sz, eyeI = inkI, whI = idx("white", TOON_COLORS.white);
      if (opts.blush && fg.eyes.length) {
        var blI = idx("blush", dark ? [0.62, 0.07, 0.015] : TOON_COLORS.blush), mid = fg.nose ? fg.nose[0] : fg.eyes[0][0];
        fg.eyes.forEach(function (e) {
          var side = fg.eyes.length === 2 ? (e[0] < mid ? -1 : 1) : (e[0] < mid ? -1 : 1);
          var big = sz === "l" || sz === "xl"; stamp(ix, gw, gh, big ? ["bb"] : ["b"], e[0] + side * (big ? 1.2 : 0.8), e[1] + (sz === "xl" ? 2.6 : big ? 2.2 : 1.6), function () { return blI; }, true, ga);
        });
      }
      var epat = opts.eyes === "happy" ? TOON.happy[sz] : TOON.eyes[sz];
      fg.eyes.forEach(function (e, n) {
        var pat = epat;
                stamp(ix, gw, gh, pat, e[0], e[1], function (ch) { return ch === "w" ? whI : eyeI; }, false, ga);
      });
      if (fg.nose) {
        var noseI = inkI, nhI = muzzleK ? muzzleK.base : idx("noseshine", dark ? [0.56, -0.006, -0.022] : [0.86, 0.01, 0.02]);
        var np = TOON.noses[sz];
        stamp(ix, gw, gh, np, fg.nose[0], fg.nose[1], function (ch) { return ch === "h" ? nhI : noseI; }, false, ga);
        var below = Math.round(fg.nose[1] - np.length / 2) + np.length;
        // small faces: a tongue alone reads better than smile lines; bigger faces get a smile, tongue hanging from it
        var small = sz === "s" || sz === "m", mp = (opts.mouth === "smile" || (opts.mouth === "tongue" && !small)) ? TOON.mouths[sz] : [];
        if (mp.length) stamp(ix, gw, gh, mp, fg.nose[0], below + mp.length / 2, function () { return noseI; }, true, ga);
        if (opts.mouth === "tongue") {
          var tp = TOON.tongues[sz], tI = idx("tongue", TOON_COLORS.tongue);
          stamp(ix, gw, gh, tp, fg.nose[0], below + (mp.length ? mp.length - 1 : 0) + tp.length / 2, function () { return tI; }, false, ga);
        }
      }
    }

    // 9. compose: ink outline, soft drop shadow, backdrop
    var ox = Math.floor((N - gw) / 2), oy = N - bottom - gh;
    var outImg = new Uint8ClampedArray(N * N * 4), cell = new Int16Array(N * N).fill(-1);
    for (y = 0; y < gh; y++) for (x = 0; x < gw; x++) { g = y * gw + x; if (ix[g] >= 0) cell[(y + oy) * N + x + ox] = ix[g]; }
    var rgbPal = pal.map(function (c) { return toRgb(c[0], c[1], c[2]); });
    for (i = 0; i < N * N; i++) if (cell[i] >= 0) { var rc = rgbPal[cell[i]]; outImg[4 * i] = rc[0]; outImg[4 * i + 1] = rc[1]; outImg[4 * i + 2] = rc[2]; outImg[4 * i + 3] = 255; }
    if (opts.shadow) {
      var scx = ox + gw / 2 - 0.5, scy = oy + gh - 0.5, srx = Math.max(2, gw * 0.4), sry = 1.1;
      for (y = Math.floor(scy - sry); y <= Math.ceil(scy + sry); y++) for (x = Math.floor(scx - srx); x <= Math.ceil(scx + srx); x++) {
        if (x < 0 || y < 0 || x >= N || y >= N) continue;
        var e2 = Math.pow((x - scx) / srx, 2) + Math.pow((y - scy) / sry, 2), k3 = y * N + x;
        if (e2 <= 1 && cell[k3] < 0) { outImg[4 * k3] = SHADOW[0]; outImg[4 * k3 + 1] = SHADOW[1]; outImg[4 * k3 + 2] = SHADOW[2]; outImg[4 * k3 + 3] = 64; }
      }
    }
    if (opts.outline && opts.outline !== "none") {
      var oc = toRgb(ink[0], ink[1], ink[2]);
      for (y = 0; y < N; y++) for (x = 0; x < N; x++) {
        var k4 = y * N + x; if (cell[k4] >= 0) continue;
        var near = (x > 0 && cell[k4 - 1] >= 0) || (x < N - 1 && cell[k4 + 1] >= 0) || (y > 0 && cell[k4 - N] >= 0) || (y < N - 1 && cell[k4 + N] >= 0);
        if (near) { outImg[4 * k4] = oc[0]; outImg[4 * k4 + 1] = oc[1]; outImg[4 * k4 + 2] = oc[2]; outImg[4 * k4 + 3] = 255; }
      }
    }
    var bdp = typeof opts.backdrop === "string" ? BACKDROPS[opts.backdrop] : opts.backdrop;
    if (bdp) for (i = 0; i < N * N; i++) {
      var al = outImg[4 * i + 3] / 255;
      for (var chn = 0; chn < 3; chn++) outImg[4 * i + chn] = Math.round(outImg[4 * i + chn] * al + bdp[chn] * (1 - al));
      outImg[4 * i + 3] = 255;
    }
    return { width: N, height: N, data: outImg, palette: rgbPal, grid: { x: ox, y: oy, w: gw, h: gh }, face: fg, dark: dark };
  }

  function meanLab(pts) { var s = [0, 0, 0]; pts.forEach(function (p) { s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; }); return [s[0] / pts.length, s[1] / pts.length, s[2] / pts.length]; }

  // place a pattern centred on (cx, cy), clipped to the silhouette
  function stamp(ix, gw, gh, pattern, cx, cy, colorOf, onlyOpaque, ga) {
    var ph = pattern.length, pw = pattern[0].length, ox = Math.round(cx - pw / 2), oy = Math.round(cy - ph / 2);
    for (var r = 0; r < ph; r++) for (var c = 0; c < pw; c++) {
      var ch = pattern[r][c]; if (ch === ".") continue;
      var x = ox + c, y = oy + r; if (x < 0 || y < 0 || x >= gw || y >= gh) continue;
      var g = y * gw + x; if (!ga[g]) continue;   // stamps never grow the silhouette
      ix[g] = colorOf(ch, r, c);
    }
  }

  function upscale(spr, s) {
    var W = spr.width * s, H = spr.height * s, out = new Uint8ClampedArray(W * H * 4);
    for (var y = 0; y < H; y++) { var sy = (y / s) | 0; for (var x = 0; x < W; x++) { var si = (sy * spr.width + ((x / s) | 0)) * 4, di = (y * W + x) * 4; out[di] = spr.data[si]; out[di + 1] = spr.data[si + 1]; out[di + 2] = spr.data[si + 2]; out[di + 3] = spr.data[si + 3]; } }
    return { width: W, height: H, data: out };
  }

  var api = { render: render, upscale: upscale, PRESETS: PRESETS, BACKDROPS: BACKDROPS, toLab: toLab, toRgb: toRgb, kmeans: kmeans,
    guessFace: guessFace, bigHead: bigHead, stubby: stubby, regularize: regularize, roundAlpha: roundAlpha, TOON: TOON, TOON_COLORS: TOON_COLORS, STAMP_COLORS: STAMP_COLORS, headCircle: headCircle, mergeIslands: mergeIslands, celShade: celShade, smoothSilhouette: smoothSilhouette, EYES: EYES, NOSES: NOSES };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PixelPal = api;
})(typeof self !== "undefined" ? self : this);
