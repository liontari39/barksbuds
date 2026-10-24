(function () {
  "use strict";
  var OFF = /^off-leash area/i;
  var REGION = { Manhattan: "nyc", Brooklyn: "nyc", Bronx: "nyc", Queens: "nyc", "Staten Island": "nyc", Nassau: "li", Suffolk: "li", Westchester: "wc" };
  var COUNTY_SUFFIX = { Nassau: 1, Suffolk: 1, Westchester: 1 };
  var state = { q: "", region: "", county: "", f: { fenced: false, small: false, water: false, shade: false }, off: false, me: null, sel: null };
  var runs = [], map = null, markers = {}, meMarker = null, layer = null;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var SMALL = window.matchMedia("(max-width:900px)").matches;
  var listEl = $("#results"), countEl = $("#count"), resetEl = $("#reset");

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function norm(s) { return String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9 ]+/g, " "); }
  function hasLL(r) { return typeof r.lat === "number" && typeof r.lng === "number"; }
  function isOff(r) { return OFF.test(r.type || ""); }

  var LABEL = { yes: "Yes", no: "No", partial: "Partial", seasonal: "Seasonal", nearby: "Nearby, outside the run", minimal: "Minimal" };
  function val(v) {
    v = String(v || "").trim();
    if (!v) return '<span class="unk">Not yet confirmed</span>';
    return esc(LABEL[v.toLowerCase()] || (v.charAt(0).toUpperCase() + v.slice(1)));
  }
  function text(v) { v = String(v || "").trim(); return v ? esc(v.charAt(0).toUpperCase() + v.slice(1)) : '<span class="unk">Not yet confirmed</span>'; }

  var FILTERS = {
    fenced: function (r) { return r.fenced === "yes"; },
    small: function (r) { return r.small_dog_area === "yes"; },
    water: function (r) { return r.water === "yes" || r.water === "seasonal"; },
    shade: function (r) { return r.shade === "yes" || r.shade === "partial"; }
  };

  function km(a, b) {
    var R = 6371, toR = Math.PI / 180, dLa = (b.lat - a.lat) * toR, dLo = (b.lng - a.lng) * toR;
    var h = Math.sin(dLa / 2) * Math.sin(dLa / 2) + Math.cos(a.lat * toR) * Math.cos(b.lat * toR) * Math.sin(dLo / 2) * Math.sin(dLo / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function miles(r) { return state.me && hasLL(r) ? km(state.me, r) * 0.621371 : null; }

  function destination(r) {
    // Verified pins (exact run or an officially described spot) route best; otherwise a written address/park name beats an approximate pin.
    if (hasLL(r) && (r.pin_precision === "exact" || r.pin_precision === "described" || /^Centroid of NYC Open Data/.test(r.coord_source || ""))) return r.lat + "," + r.lng;
    if (r.address) return r.address;
    return [r.park || r.name, r.town_or_neighborhood, "NY"].filter(Boolean).join(", ");
  }
  function sources(r) {
    var out = [];
    [r.source_url].concat(String(r.source_url_2 || "").split("|")).forEach(function (u) {
      u = String(u || "").trim();
      if (/^https?:\/\//.test(u) && out.indexOf(u) < 0) out.push(u);
    });
    return out;
  }
  function host(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return "source"; } }

  function filtered() {
    var q = norm(state.q).trim(), terms = q ? q.split(/\s+/) : [];
    var out = runs.filter(function (r) {
      if (isOff(r) && !state.off) return false;
      if (state.region && REGION[r.county] !== state.region) return false;
      if (state.county && r.county !== state.county) return false;
      for (var k in state.f) if (state.f[k] && !FILTERS[k](r)) return false;
      if (terms.length) {
        var hay = r._hay;
        for (var i = 0; i < terms.length; i++) if (hay.indexOf(terms[i]) < 0) return false;
      }
      return true;
    });
    if (state.me) {
      out.sort(function (a, b) {
        var da = miles(a), db = miles(b);
        if (da == null && db == null) return a._i - b._i;
        if (da == null) return 1; if (db == null) return -1;
        return da - db;
      });
    }
    return out;
  }

  function tags(r) {
    var t = [];
    t.push(isOff(r) ? '<li class="o">Off-leash area, set hours</li>' : '<li class="t">' + esc(r.county) + "</li>");
    if (r.fenced === "yes") t.push('<li class="y">Fenced</li>');
    else if (r.fenced === "no") t.push('<li class="n">Not fenced</li>');
    if (r.small_dog_area === "yes") t.push('<li class="y">Small-dog area</li>');
    if (r.water === "yes" || r.water === "seasonal") t.push('<li class="y">Water' + (r.water === "seasonal" ? " (seasonal)" : "") + "</li>");
    if (r.shade === "yes" || r.shade === "partial") t.push('<li class="y">' + (r.shade === "partial" ? "Some shade" : "Shade") + "</li>");
    if (/resident|permit|members/i.test((r.residency_permit_rules || "") + " " + (r.type || "")) && !/^NYC dog license/i.test(r.residency_permit_rules || "")) t.push("<li>Residents / permit</li>");
    if (!hasLL(r)) t.push("<li>Not on map yet</li>");
    return t.join("");
  }

  function card(r) {
    var d = miles(r), dest = encodeURIComponent(destination(r)), srcs = sources(r);
    var where = [r.park && r.park !== r.name ? r.park : "", r.town_or_neighborhood, r.county + (COUNTY_SUFFIX[r.county] ? " County" : "")].filter(Boolean).map(esc).join(" · ");
    var amen = [["Fenced", r.fenced], ["Small-dog area", r.small_dog_area + (r.small_dog_weight_limit ? " (" + r.small_dog_weight_limit + ")" : "")], ["Water", r.water], ["Shade", r.shade], ["Surface", r.surface], ["Seating", r.seating]]
      .map(function (a) { return "<div><dt>" + a[0] + "</dt><dd>" + (a[0] === "Surface" || a[0] === "Seating" ? text(a[1]) : val(String(a[1]).trim())) + "</dd></div>"; }).join("");
    var facts = [["Hours", r.hours], ["Who can use it", r.residency_permit_rules], ["Fees", r.fees], ["Type", r.type], ["Run by", r.operator], ["Address", r.address], ["Good to know", r.notes]]
      .filter(function (f, i) { return i < 3 || String(f[1] || "").trim(); })
      .map(function (f) { return "<div><dt>" + f[0] + "</dt><dd>" + text(f[1]) + "</dd></div>"; }).join("");
    return '<li class="card' + (isOff(r) ? " off" : "") + '" id="run-' + esc(r.id) + '" data-id="' + esc(r.id) + '">' +
      '<div class="card-h"><span class="badge" aria-hidden="true"><svg class="ico"><use href="#' + (isOff(r) ? "i-paw" : "i-pin") + '"/></svg></span>' +
      '<div><h2><button type="button" class="nm" aria-controls="more-' + esc(r.id) + '">' + esc(r.name) + '</button></h2><p class="where">' + where + "</p></div>" +
      (d != null ? '<span class="dist">' + (d < 10 ? d.toFixed(1) : Math.round(d)) + " mi</span>" : "") + "</div>" +
      '<ul class="tags" aria-label="Highlights">' + tags(r) + "</ul>" +
      '<details class="more" id="more-' + esc(r.id) + '"><summary><svg class="ico chev" aria-hidden="true"><use href="#i-chev"/></svg>Details, hours &amp; directions</summary><div class="body">' +
      '<dl class="amen">' + amen + "</dl>" +
      '<dl class="facts">' + facts + "</dl>" +
      '<div class="actions">' +
      '<a class="btn" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&amp;destination=' + dest + '"><svg class="ico" aria-hidden="true"><use href="#i-nav"/></svg>Google Maps<span class="sr-only"> directions to ' + esc(r.name) + ' (opens in new tab)</span></a>' +
      '<a class="btn btn-ghost" target="_blank" rel="noopener" href="https://maps.apple.com/?daddr=' + dest + '">Apple Maps<span class="sr-only"> directions to ' + esc(r.name) + ' (opens in new tab)</span></a>' +
      "</div>" +
      (srcs.length ? '<p class="src">Source: ' + srcs.map(function (u) { return '<a href="' + esc(u) + '" target="_blank" rel="noopener nofollow">' + esc(host(u)) + "</a>"; }).join(", ") + (r.last_checked ? " · checked " + esc(r.last_checked) : "") + "</p>" : "") +
      (hasLL(r) ? (r.pin_precision === "approximate" ? '<p class="src">Map pin is approximate. We\'re confirming the exact spot in the park.</p>' : r.pin_precision === "park-wide" ? '<p class="src">Off-leash use covers most of the park, so the pin marks the park.</p>' : "") : '<p class="src">This run isn\'t pinned on the map yet. We\'re confirming its exact location.</p>') +
      '<p class="help"><svg class="ico" aria-hidden="true"><use href="#i-edit"/></svg><span>Know this run? <a href="/#join">Help us fill in details</a> by joining the waitlist.</span></p>' +
      "</div></details></li>";
  }

  function pinIcon(r, sel) {
    var c = isOff(r) ? "#C98A0C" : "#C8201E", w = SMALL ? 24 : 30, h = SMALL ? 32 : 40;
    return L.divIcon({
      className: "pinx" + (sel ? " sel" : ""), iconSize: [w, h], iconAnchor: [w / 2, h], popupAnchor: [0, -h + 4],
      html: '<svg viewBox="0 0 30 40" aria-hidden="true"><path d="M15 1C7.3 1 1 7.1 1 14.7 1 25 15 39 15 39s14-14 14-24.3C29 7.1 22.7 1 15 1z" fill="' + c + '" stroke="#141414" stroke-width="2"/><circle cx="15" cy="14.5" r="5.5" fill="#FFF8EA"/></svg>'
    });
  }

  function render() {
    var list = filtered();
    var nOff = list.filter(isOff).length, nRuns = list.length - nOff, onMap = list.filter(hasLL).length;
    countEl.innerHTML = list.length
      ? "<b>" + nRuns + "</b> dog run" + (nRuns === 1 ? "" : "s") + (state.off ? " + <b>" + nOff + "</b> off-leash area" + (nOff === 1 ? "" : "s") : "") + (onMap < list.length ? " · " + onMap + " on map" : "") + (state.me ? " · nearest first" : "")
      : "No matches";
    listEl.innerHTML = list.length ? list.map(card).join("") : '<li class="empty">No dog runs match those filters. <button class="linkbtn" type="button" data-reset>Clear filters</button></li>';
    var dirty = state.q || state.region || state.county || state.off || Object.keys(state.f).some(function (k) { return state.f[k]; });
    resetEl.hidden = !dirty;
    $("#lg-off").hidden = !state.off;
    if (map) {
      layer.clearLayers(); markers = {};
      var batch = [];
      list.forEach(function (r) {
        if (!hasLL(r)) return;
        var m = L.marker([r.lat, r.lng], { icon: pinIcon(r, r.id === state.sel), title: r.name, alt: r.name, riseOnHover: true, keyboard: true });
        m.bindPopup(function () {
          var el = document.createElement("div");
          el.innerHTML = "<b>" + esc(r.name) + "</b><br>" + esc(r.town_or_neighborhood) + " · " + esc(r.county) + '<br><button type="button">See details</button>';
          el.querySelector("button").addEventListener("click", function () { select(r.id, { scroll: true, open: true, fromMap: true }); });
          return el;
        });
        m.on("click", function () { select(r.id, { scroll: !window.matchMedia("(max-width:900px)").matches, fromMap: true }); });
        m.bbOff = isOff(r); batch.push(m); markers[r.id] = m;
      });
      if (layer.addLayers) layer.addLayers(batch); else batch.forEach(function (m) { m.addTo(layer); });
    }
  }

  function fit(list) {
    if (!map) return;
    var pts = list.filter(hasLL).map(function (r) { return [r.lat, r.lng]; });
    if (state.me) pts.push([state.me.lat, state.me.lng]);
    if (pts.length === 1) map.setView(pts[0], 14);
    else if (pts.length) map.fitBounds(pts, { padding: SMALL ? [14, 14] : [36, 36], maxZoom: 14 });
  }

  function select(id, o) {
    o = o || {};
    var prev = state.sel; state.sel = id;
    $$(".card.active").forEach(function (c) { c.classList.remove("active"); });
    var c = document.getElementById("run-" + id);
    if (c) {
      c.classList.add("active");
      if (o.open) c.querySelector("details").open = true;
      if (o.scroll) c.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    }
    var r = runs.filter(function (x) { return x.id === id; })[0];
    [prev, id].forEach(function (k) { var x = runs.filter(function (y) { return y.id === k; })[0]; if (x && markers[k]) markers[k].setIcon(pinIcon(x, k === id)); });
    if (map && r && hasLL(r) && !o.fromMap) {
      var mk = markers[id];
      map.setView([r.lat, r.lng], Math.max(map.getZoom(), 14));
      if (mk) { if (layer.zoomToShowLayer) layer.zoomToShowLayer(mk, function () { mk.openPopup(); }); else mk.openPopup(); }
      if (window.matchMedia("(max-width:900px)").matches) $(".mapwrap").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function update(refit) { render(); if (refit) fit(filtered()); }

  // events
  var t;
  $("#q").addEventListener("input", function (e) { clearTimeout(t); t = setTimeout(function () { state.q = e.target.value; update(true); }, 120); });
  var areaEl = $("#area");
  function setRegion(rg) {
    state.region = rg;
    $$(".seg [data-region]").forEach(function (x) { x.setAttribute("aria-pressed", String(x.getAttribute("data-region") === rg)); });
  }
  $$(".seg [data-region]").forEach(function (b) {
    b.addEventListener("click", function () {
      setRegion(b.getAttribute("data-region"));
      if (state.county && state.region && REGION[state.county] !== state.region) { state.county = ""; areaEl.value = ""; }
      if (!state.region) { state.county = ""; areaEl.value = ""; }
      update(true);
    });
  });
  areaEl.addEventListener("change", function () {
    state.county = areaEl.value;
    setRegion(state.county ? REGION[state.county] : state.region);
    update(true);
  });
  $$(".chip[data-f]").forEach(function (b) {
    b.addEventListener("click", function () {
      var k = b.getAttribute("data-f"); state.f[k] = !state.f[k];
      b.setAttribute("aria-pressed", String(state.f[k])); update(true);
    });
  });
  $("#offleash").addEventListener("click", function () {
    state.off = !state.off; this.setAttribute("aria-pressed", String(state.off)); update(false);
  });
  function reset() {
    state.q = ""; $("#q").value = ""; state.county = ""; areaEl.value = ""; state.region = ""; state.off = false;
    Object.keys(state.f).forEach(function (k) { state.f[k] = false; });
    $$("[aria-pressed]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-region") === "")); });
    update(true);
  }
  resetEl.addEventListener("click", reset);
  listEl.addEventListener("click", function (e) {
    if (e.target.closest("[data-reset]")) return reset();
    var nm = e.target.closest("button.nm");
    if (nm) { var li = nm.closest(".card"); var d = li.querySelector("details"); d.open = !d.open; select(li.getAttribute("data-id"), {}); }
  });
  listEl.addEventListener("toggle", function (e) {
    if (e.target.tagName === "DETAILS" && e.target.open) { var li = e.target.closest(".card"); if (li.getAttribute("data-id") !== state.sel) select(li.getAttribute("data-id"), { fromMap: true }); }
  }, true);

  var nearBtn = $("#near");
  nearBtn.addEventListener("click", function () {
    if (!("geolocation" in navigator)) { countEl.textContent = "Your browser can't share location. Try searching a town instead."; return; }
    nearBtn.disabled = true; var lbl = nearBtn.querySelector(".lbl"); var old = lbl.textContent; lbl.textContent = "Locating…";
    navigator.geolocation.getCurrentPosition(function (p) {
      nearBtn.disabled = false; lbl.textContent = "Nearest first";
      state.me = { lat: p.coords.latitude, lng: p.coords.longitude };
      if (map) {
        if (meMarker) meMarker.remove();
        meMarker = L.marker([state.me.lat, state.me.lng], { icon: L.divIcon({ className: "", html: '<div class="me-dot"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }), title: "You are here", alt: "You are here", zIndexOffset: 1000 }).addTo(map);
      }
      render();
      var near = filtered().filter(hasLL).slice(0, 4);
      fit(near.length ? near : filtered());
      listEl.focus({ preventScroll: true });
    }, function (err) {
      nearBtn.disabled = false; lbl.textContent = old;
      countEl.textContent = err && err.code === 1 ? "Location is off. Allow location access or search by town." : "Couldn't find your location. Try searching by town.";
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  });

  function setCtl() { document.documentElement.style.setProperty("--ctl", $(".controls").offsetHeight + "px"); }
  window.addEventListener("resize", setCtl); setCtl();

  function initMap() {
    if (!window.L) return;
    map = L.map("map", { scrollWheelZoom: false, zoomControl: true, zoomSnap: 0.25 }).setView([40.8, -73.55], 9);
    // Keep the Leaflet credit but drop the default flag icon from the attribution prefix.
    map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    // Standard OpenStreetMap tiles: free, no API key; attribution required by the OSM tile usage policy.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, crossOrigin: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    map.on("focus click", function () { map.scrollWheelZoom.enable(); });
    map.on("mouseout", function () { map.scrollWheelZoom.disable(); });
    layer = (L.markerClusterGroup ? L.markerClusterGroup({
      showCoverageOnHover: false, maxClusterRadius: SMALL ? 40 : 50, disableClusteringAtZoom: 14, spiderfyOnMaxZoom: true, chunkedLoading: true,
      iconCreateFunction: function (c) {
        var ms = c.getAllChildMarkers(), n = ms.length, allOff = ms.every(function (m) { return m.bbOff; });
        return L.divIcon({ html: "<div><span>" + n + "</span></div>", className: "marker-cluster" + (allOff ? " mc-off" : ""), iconSize: [40, 40] });
      }
    }) : L.layerGroup()).addTo(map);
  }

  fetch("/api/runs", { credentials: "same-origin" }).then(function (r) {
    if (!r.ok) throw new Error(r.status); return r.json();
  }).then(function (data) {
    runs = (data.runs || data).map(function (r, i) {
      r._i = i;
      r._hay = norm([r.name, r.park, r.town_or_neighborhood, r.county, r.address].join(" "));
      return r;
    });
    var u = new URLSearchParams(location.search);
    if (u.get("q")) { state.q = u.get("q"); $("#q").value = state.q; }
    var rg = (u.get("region") || "").toLowerCase(); rg = { nyc: "nyc", li: "li", "long-island": "li", wc: "wc", westchester: "wc" }[rg];
    if (rg) setRegion(rg);
    var c = (u.get("county") || "").toLowerCase();
    Object.keys(REGION).forEach(function (k) { if (k.toLowerCase() === c || (c === "the bronx" && k === "Bronx")) { state.county = k; areaEl.value = k; setRegion(REGION[k]); } });
    initMap(); setCtl();
    update(true);
    document.body.setAttribute("data-ready", "1");
  }).catch(function () {
    countEl.textContent = "Sorry, we couldn't load the dog runs. Please refresh to try again.";
  });
})();
