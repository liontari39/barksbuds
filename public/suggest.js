// "Suggest a run" form: tap-to-drop / drag pin on a Leaflet map, live "already on the map?" and coverage hints.
(function () {
  "use strict";
  var C = window.SG || {}, f = document.getElementById("sgform");
  if (!f) return;
  var la = f.querySelector("#lat"), ln = f.querySelector("#lng"), ll = document.getElementById("sgll");
  var nearEl = document.getElementById("sgnear"), covEl = document.getElementById("sgcov");
  var county = f.querySelector("#county"), stateRow = document.getElementById("staterow");
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  if (county && stateRow) county.addEventListener("change", function () { stateRow.hidden = county.value !== "other"; });
  if (!window.L) { document.getElementById("sgmap").innerHTML = '<p style="padding:16px">The map didn\'t load. Add an address instead.</p>'; return; }
  var start = C.start, map = L.map("sgmap", { scrollWheelZoom: false, zoomSnap: 0.5 }).setView(start || [40.8, -73.55], start ? 17 : 9);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, crossOrigin: true,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
  map.on("focus", function () { map.scrollWheelZoom.enable(); });
  var icon = L.divIcon({ className: "pinx", iconSize: [30, 40], iconAnchor: [15, 40],
    html: '<svg viewBox="0 0 30 40" aria-hidden="true"><path d="M15 1C7.3 1 1 7.1 1 14.7 1 25 15 39 15 39s14-14 14-24.3C29 7.1 22.7 1 15 1z" fill="#FBB321" stroke="#141414" stroke-width="2"/><circle cx="15" cy="14.5" r="5.5" fill="#C8201E"/></svg>' });
  var mk = null, runs = null;
  function m(a, b) {
    var R = 6371000, t = Math.PI / 180, dLa = (b.lat - a.lat) * t, dLo = (b.lng - a.lng) * t;
    var h = Math.sin(dLa / 2) * Math.sin(dLa / 2) + Math.cos(a.lat * t) * Math.cos(b.lat * t) * Math.sin(dLo / 2) * Math.sin(dLo / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function check(p) {
    var b = C.box || [0, 0, 0, 0], out = !(p.lat >= b[0] && p.lat <= b[1] && p.lng >= b[2] && p.lng <= b[3]);
    covEl.hidden = !out;
    var go = function () {
      var near = (runs || []).filter(function (r) { return r.id !== C.self && typeof r.lat === "number"; })
        .map(function (r) { return { r: r, d: m(p, r) }; }).filter(function (x) { return x.d <= (C.dup || 150); })
        .sort(function (a, b) { return a.d - b.d; }).slice(0, 4);
      nearEl.hidden = !near.length;
      if (near.length) nearEl.innerHTML = "<b>Already on the map nearby:</b><ul>" + near.map(function (x) {
        return "<li>" + esc(x.r.name) + " · about " + Math.round(x.d) + " m away</li>"; }).join("") + "</ul>" +
        (C.self ? "" : "If it's one of these, use <b>Suggest an edit</b> on its card instead.");
    };
    if (runs) go(); else fetch("/api/runs").then(function (r) { return r.json(); }).then(function (d) { runs = d.runs || []; go(); }).catch(function () {});
  }
  function set(lat, lng, pan) {
    la.value = lat.toFixed(6); ln.value = lng.toFixed(6);
    ll.textContent = "Pin: " + lat.toFixed(5) + ", " + lng.toFixed(5);
    if (!mk) {
      mk = L.marker([lat, lng], { icon: icon, draggable: true, keyboard: true, title: "Dog run pin", alt: "Dog run pin" }).addTo(map);
      mk.on("dragend", function () { var p = mk.getLatLng(); set(p.lat, p.lng); });
    } else mk.setLatLng([lat, lng]);
    if (pan) map.setView([lat, lng], Math.max(map.getZoom(), 17));
    check({ lat: lat, lng: lng });
  }
  map.on("click", function (ev) { set(ev.latlng.lat, ev.latlng.lng); });
  if (start) set(start[0], start[1]);
  document.getElementById("sgclear").addEventListener("click", function () {
    if (mk) { mk.remove(); mk = null; }
    la.value = ln.value = ""; ll.textContent = ""; nearEl.hidden = covEl.hidden = true;
  });
  var me = document.getElementById("sgme");
  me.addEventListener("click", function () {
    if (!("geolocation" in navigator)) { ll.textContent = "Your browser can't share location."; return; }
    me.disabled = true;
    navigator.geolocation.getCurrentPosition(function (p) { me.disabled = false; set(p.coords.latitude, p.coords.longitude, true); },
      function () { me.disabled = false; ll.textContent = "Couldn't get your location. Tap the map instead."; },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  });
})();
