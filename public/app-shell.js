/* App chrome for Capacitor and installed PWAs. No-ops in a regular browser tab. */
(function () {
  function isApp() {
    return !!(window.Capacitor
      || (window.matchMedia && matchMedia("(display-mode: standalone)").matches)
      || window.navigator.standalone);
  }
  if (!isApp()) return;
  var root = document.documentElement;
  root.classList.add("bb-app");
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) {
    root.classList.add("bb-rm");
  }
  var reduce = root.classList.contains("bb-rm");
  var C = window.Capacitor || {};
  var Plugins = C.Plugins || {};
  var path = location.pathname || "/";

  function svg(d) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' + d + "</svg>";
  }
  var I = {
    back: svg('<path d="M15 6l-6 6 6 6"/>'),
    more: svg('<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>'),
    msg: svg('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12z"/>'),
    runs: svg('<path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.6"/>'),
    meet: svg('<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>'),
    check: svg('<circle cx="6" cy="10" r="2"/><circle cx="10" cy="5.5" r="2"/><circle cx="14" cy="5.5" r="2"/><circle cx="18" cy="10" r="2"/><path d="M12 11c-3 0-6 4.5-6 7a3 3 0 0 0 3 3c1.2 0 2-.6 3-.6s1.8.6 3 .6a3 3 0 0 0 3-3c0-2.5-3-7-6-7z"/>'),
    picks: svg('<path d="M12 20s-7.5-4.6-9-9.2C2 7.6 4.2 5 7 5c2 0 3.3 1.1 5 3 1.7-1.9 3-3 5-3 2.8 0 5 2.6 4 5.8-1.5 4.6-9 9.2-9 9.2z"/>'),
    me: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>')
  };

  function titleText() {
    var h = document.querySelector("main h1, .phead h1, .intro h1, h1");
    if (h && h.textContent.trim()) return h.textContent.trim();
    return (document.title || "BarksBuds").replace(/\s*[·|].*BarksBuds.*$/, "").replace(/\s*\|.*$/, "") || "BarksBuds";
  }
  function isTabRoot() {
    if (path === "/" || path === "/index.html") return "home";
    if (path === "/runs" || path === "/runs/" || path === "/runs.html") return "runs";
    if (path === "/meetups" || path === "/meetups/" || path === "/meetups/calendar" || path === "/meetups/calendar/") return "meetups";
    if (path === "/recommendations" || path === "/recommendations/" || path === "/picks" || path === "/picks/") return "picks";
    if (path === "/me" || path === "/me/") return "me";
    if (path === "/signin" || path === "/signin/") return "signin";
    return "";
  }
  function activeTab() {
    if (path === "/runs" || path.indexOf("/runs/") === 0) return "runs";
    if (path.indexOf("/meetups") === 0) return "meetups";
    if (path.indexOf("/recommendations") === 0 || path.indexOf("/picks") === 0) return "picks";
    if (path === "/me" || path.indexOf("/me/") === 0 || path.indexOf("/humans/") === 0) return "me";
    return "";
  }
  function parentOf(p) {
    if (p.indexOf("/runs/") === 0) return "/runs";
    if (p.indexOf("/meetups/") === 0) return "/meetups/calendar";
    if (p.indexOf("/recommendations") === 0) return "/picks";
    if (p.indexOf("/me/") === 0) return "/me";
    if (p.indexOf("/dogs/") === 0) return "/dogs";
    if (p.indexOf("/packs/") === 0) return "/packs";
    if (p.indexOf("/humans/") === 0) return "/me";
    return "/runs";
  }

  // ----- chrome
  var appbar = document.createElement("header");
  appbar.className = "bb-appbar";
  appbar.setAttribute("role", "banner");
  var tabRoot = isTabRoot();
  var left = tabRoot
    ? '<a class="bb-brand" href="/runs" aria-label="BarksBuds home"><img src="/img/icon-nav-40.png?v=jack4" width="28" height="28" alt=""></a>'
    : '<button type="button" class="bb-iconbtn" data-bb="back" aria-label="Back">' + I.back + "</button>";
  appbar.innerHTML = left + '<h1 class="bb-title"></h1>' +
    '<a class="bb-iconbtn" href="/messages" aria-label="Messages" data-bb="msg">' + I.msg + "</a>" +
    '<button type="button" class="bb-iconbtn" data-bb="more" aria-label="More">' + I.more + "</button>";
  var titleEl = appbar.querySelector(".bb-title");
  var tabTitles = { runs: "Dog runs", meetups: "Meetups", picks: "Local picks", me: "My dogs", home: "BarksBuds", signin: "Sign in" };
  if (titleEl) titleEl.textContent = (tabRoot && tabTitles[tabRoot]) || titleText();
  document.body.appendChild(appbar);
  var pageH = document.querySelector(".phead h1");
  if (pageH && titleEl) {
    var a = titleEl.textContent.trim().toLowerCase();
    var b = pageH.textContent.trim().toLowerCase();
    if (a && b && (a === b || b.indexOf(a) !== -1 || a.indexOf(b) !== -1)) {
      pageH.setAttribute("hidden", "");
      pageH.classList.add("bb-title-dup");
    }
  }

  var tabbar = document.createElement("nav");
  tabbar.className = "bb-tabbar";
  tabbar.setAttribute("aria-label", "App");
  var on = activeTab();
  function tab(id, href, icon, label, button) {
    var cur = on === id ? ' aria-current="page"' : "";
    if (button) {
      return '<button type="button" class="bb-tab' + (on === id ? " is-on" : "") + '" data-bb-tab="' + id + '" aria-label="' + label + '"' + cur + ">" + icon + "<span>" + label + "</span></button>";
    }
    return '<a class="bb-tab" href="' + href + '" data-bb-tab="' + id + '"' + cur + ">" + icon + "<span>" + label + "</span></a>";
  }
  tabbar.innerHTML = tab("runs", "/runs", I.runs, "Runs") +
    tab("meetups", "/meetups/calendar", I.meet, "Meetups") +
    tab("checkin", "#", I.check, "Check in", true) +
    tab("picks", "/picks", I.picks, "Picks") +
    tab("me", "/me", I.me, "Me");
  document.body.appendChild(tabbar);

  var skel = document.createElement("div");
  skel.className = "bb-skel";
  skel.setAttribute("aria-hidden", "true");
  skel.innerHTML = "<i></i><i></i><i></i><i></i><i></i>";
  document.body.appendChild(skel);
  var ptr = document.createElement("div");
  ptr.className = "bb-ptr";
  ptr.innerHTML = "<span>Release to refresh</span>";
  document.body.appendChild(ptr);

  // ----- sheets
  var scrim = document.createElement("div");
  scrim.className = "bb-scrim";
  scrim.setAttribute("hidden", "");
  var sheet = document.createElement("div");
  sheet.className = "bb-sheet";
  sheet.setAttribute("role", "dialog");
  sheet.setAttribute("aria-modal", "true");
  sheet.innerHTML = '<div class="bb-sheet-h"><span class="grab" aria-hidden="true"></span><h2></h2><button type="button" class="bb-iconbtn" data-bb="close" aria-label="Close">' +
    svg('<path d="M6 6l12 12M18 6L6 18"/>') + '</button></div><div class="bb-sheet-b"></div>';
  document.body.appendChild(scrim);
  document.body.appendChild(sheet);
  var sheetTitle = sheet.querySelector("h2");
  var sheetBody = sheet.querySelector(".bb-sheet-b");
  var sheetOpen = false;

  function closeSheet() {
    if (!sheetOpen) return false;
    sheetOpen = false;
    sheet.classList.remove("is-on");
    scrim.classList.remove("is-on");
    setTimeout(function () { if (!sheetOpen) scrim.setAttribute("hidden", ""); }, reduce ? 0 : 200);
    return true;
  }
  function openSheet(title, node) {
    sheetTitle.textContent = title;
    sheetBody.innerHTML = "";
    if (typeof node === "string") sheetBody.innerHTML = node;
    else if (node) sheetBody.appendChild(node);
    scrim.removeAttribute("hidden");
    requestAnimationFrame(function () {
      sheetOpen = true;
      scrim.classList.add("is-on");
      sheet.classList.add("is-on");
    });
  }
  scrim.addEventListener("click", closeSheet);
  sheet.querySelector("[data-bb=close]").addEventListener("click", closeSheet);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeSheet();
  });

  function haptic(style) {
    try {
      if (Plugins.Haptics && Plugins.Haptics.impact) Plugins.Haptics.impact({ style: style || "Light" });
    } catch (e) {}
  }

  // ----- status bar + splash
  function applyStatus() {
    var dark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
    try {
      if (Plugins.StatusBar) {
        if (Plugins.StatusBar.setStyle) Plugins.StatusBar.setStyle({ style: dark ? "LIGHT" : "DARK" });
        if (Plugins.StatusBar.setBackgroundColor) Plugins.StatusBar.setBackgroundColor({ color: dark ? "#1A1714" : "#FFF8EA" });
        if (Plugins.StatusBar.setOverlaysWebView) Plugins.StatusBar.setOverlaysWebView({ overlay: true });
      }
    } catch (e) {}
  }
  applyStatus();
  if (window.matchMedia) {
    try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyStatus); } catch (e) {}
  }
  function hideSplash() {
    try { if (Plugins.SplashScreen && Plugins.SplashScreen.hide) Plugins.SplashScreen.hide({ fadeOutDuration: reduce ? 0 : 220 }); } catch (e) {}
  }
  if (document.readyState === "complete") hideSplash();
  else window.addEventListener("load", hideSplash);

  // ----- more menu, back, check-in
  var MORE = [
    ["/trails", "Trails"], ["/packs", "Packs"], ["/puppy-pods", "Puppy Pods"], ["/dogs", "Dogs"], ["/photos", "Photos"],
    ["/pixel-pals", "Pixel Pals"], ["/tips", "Tips"], ["/community", "Community"],
    ["/messages", "Messages"], ["/about", "About"]
  ];
  function openMore() {
    var signed = !!document.querySelector('a[href="/me"], form[action="/signout"]');
    var html = '<div class="bb-more">';
    MORE.forEach(function (x) { html += '<a href="' + x[0] + '">' + x[1] + "</a>"; });
    if (window.BB_CARD) html += '<a href="' + window.BB_CARD + '">Your card</a>';
    if (signed) html += '<a href="/me/run-alerts">Run alerts</a>';
    html += signed
      ? '<a href="/me">My dogs</a>'
      : '<a href="/signin">Sign in</a><a href="/signin">Join BarksBuds</a>';
    html += "</div>";
    openSheet("More", html);
  }

  function goBack() {
    if (closeSheet()) return;
    if (window.history.length > 1 && !tabRoot) history.back();
    else location.href = parentOf(path);
  }

  function runIdFromPath() {
    var m = path.match(/^\/runs\/([^/]+)/);
    if (!m) return "";
    var slug = decodeURIComponent(m[1]);
    var id = slug.split("-")[0];
    // ids look like q-001 — first two hyphen parts
    var m2 = slug.match(/^([a-z]+-\d+)/i);
    return m2 ? m2[1] : id;
  }

  function csrf() {
    if (window.BB_CSRF) return window.BB_CSRF;
    var el = document.querySelector('input[name="csrf"]');
    return el ? el.value : "";
  }

  function existingCheckinForm() {
    return document.querySelector("form.checkin, .mine-in");
  }

  function openCheckinSheet(preselectedRun) {
    var existing = existingCheckinForm();
    if (existing && !preselectedRun) {
      var box = document.createElement("div");
      var clone = existing.cloneNode(true);
      clone.id = "bb-checkin-form";
      clone.hidden = false;
      clone.removeAttribute("hidden");
      clone.style.display = "";
      box.appendChild(clone);
      openSheet("Check in", box);
      return;
    }
    if (!csrf()) {
      location.href = "/signin?next=" + encodeURIComponent(path || "/runs");
      return;
    }
    var dogs = window.BB_DOGS || [];
    function dogForm(rid, rname) {
      if (!dogs.length) {
        return '<p>Add your dog to check in.</p><p><a class="btn btn-sm" href="/me/dogs/new">Add a dog</a></p>';
      }
      var ticks = dogs.map(function (d) {
        return '<label class="tick"><input type="checkbox" name="dogs" value="' + d.id + '" checked><span>' +
          String(d.name).replace(/</g, "&lt;") + "</span></label>";
      }).join("");
      return '<form class="checkin" method="post" action="/runs/' + rid + '/checkin">' +
        '<input type="hidden" name="csrf" value="' + csrf() + '">' +
        (rname ? "<p><b>" + String(rname).replace(/</g, "&lt;") + "</b></p>" : "") +
        '<fieldset class="checks-grid" style="margin-bottom:10px"><legend>Who\'s with you?</legend>' + ticks + "</fieldset>" +
        '<label class="switch small" style="margin-bottom:12px"><input type="checkbox" name="anon" value="1"><span>Don\'t show or count us on the map or the run page</span></label>' +
        '<button class="btn" type="submit">We\'re here</button>' +
        '<p class="small muted" style="margin:8px 0 0">Check-ins end on their own after 2 hours.</p></form>';
    }
    if (preselectedRun) {
      openSheet("Check in", dogForm(preselectedRun.id, preselectedRun.name));
      return;
    }
    var rid = runIdFromPath();
    if (rid && existing) {
      openCheckinSheet();
      return;
    }
    openSheet("Check in", "<p>Finding dog runs…</p>");
    var loc = window.bbLocate || (navigator.geolocation && navigator.geolocation.getCurrentPosition.bind(navigator.geolocation));
    function showRuns(me) {
      fetch("/api/runs", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (data) {
        var runs = (data && data.runs) || [];
        if (me && me.lat) {
          runs.forEach(function (r) {
            if (r.lat != null && r.lng != null) {
              var dlat = r.lat - me.lat, dlng = r.lng - me.lng;
              r._d = dlat * dlat + dlng * dlng;
            } else r._d = 9e9;
          });
          runs.sort(function (a, b) { return a._d - b._d; });
        }
        var top = runs.slice(0, 16);
        var ul = document.createElement("ul");
        ul.className = "bb-check-list";
        top.forEach(function (r) {
          var li = document.createElement("li");
          var b = document.createElement("button");
          b.type = "button";
          b.innerHTML = String(r.name).replace(/</g, "&lt;") +
            (r.town_or_neighborhood ? '<div class="muted">' + String(r.town_or_neighborhood).replace(/</g, "&lt;") + "</div>" : "");
          b.addEventListener("click", function () {
            haptic("Light");
            openSheet("Check in", dogForm(r.id, r.name));
          });
          li.appendChild(b);
          ul.appendChild(li);
        });
        var wrap = document.createElement("div");
        wrap.appendChild(document.createTextNode(""));
        var p = document.createElement("p");
        p.className = "small muted";
        p.textContent = me && me.lat ? "Nearest runs, or pick one from the map." : "Pick a run to check in.";
        wrap.appendChild(p);
        wrap.appendChild(ul);
        openSheet("Check in", wrap);
      }).catch(function () {
        openSheet("Check in", '<p>Couldn\'t load dog runs.</p><p><a class="btn btn-sm" href="/runs">Open the map</a></p>');
      });
    }
    if (loc) {
      loc(function (p) { showRuns({ lat: p.coords.latitude, lng: p.coords.longitude }); },
        function () { showRuns(null); },
        { enableHighAccuracy: false, timeout: 4000, maximumAge: 300000 });
    } else showRuns(null);
  }

  document.addEventListener("click", function (ev) {
    var back = ev.target.closest && ev.target.closest("[data-bb=back]");
    if (back) { ev.preventDefault(); goBack(); return; }
    var more = ev.target.closest && ev.target.closest("[data-bb=more]");
    if (more) { ev.preventDefault(); openMore(); return; }
    var chk = ev.target.closest && ev.target.closest("[data-bb-tab=checkin]");
    if (chk) { ev.preventDefault(); haptic("Light"); openCheckinSheet(); return; }
  });

  // move on-page check-in into a sheet trigger on run pages
  var pageForm = existingCheckinForm();
  if (pageForm && path.indexOf("/runs/") === 0) {
    var launch = document.createElement("p");
    launch.className = "bb-checkin-launch";
    launch.style.margin = "14px 0 0";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm";
    btn.setAttribute("data-bb-tab", "checkin");
    btn.textContent = pageForm.classList.contains("mine-in") ? "You're here" : "We're here";
    launch.appendChild(btn);
    pageForm.parentNode.insertBefore(launch, pageForm);
    pageForm.hidden = true;
  }

  // filters sheet on the run finder
  var filters = document.getElementById("filters");
  if (filters) {
    var row = filters.previousElementSibling || filters.parentNode;
    var fb = document.createElement("button");
    fb.type = "button";
    fb.className = "btn btn-ghost btn-sm bb-filter-btn";
    fb.textContent = "Filters";
    fb.addEventListener("click", function () {
      var box = document.createElement("div");
      box.appendChild(filters);
      filters.style.display = "block";
      openSheet("Filters", box);
    });
    if (row && row.classList && row.classList.contains("searchrow")) row.appendChild(fb);
    else filters.parentNode.insertBefore(fb, filters);
  }
  var filterNavs = document.querySelectorAll('nav[aria-label^="Filter"]');
  if (filterNavs.length && (path.indexOf("/picks") === 0 || path.indexOf("/recommendations") === 0 || path.indexOf("/meetups") === 0)) {
    var pbtn = document.createElement("button");
    pbtn.type = "button";
    pbtn.className = "btn btn-ghost btn-sm bb-filter-btn";
    pbtn.textContent = "Filters";
    pbtn.addEventListener("click", function () {
      var box = document.createElement("div");
      filterNavs.forEach(function (n) { box.appendChild(n); });
      openSheet("Filters", box);
    });
    filterNavs[0].parentNode.insertBefore(pbtn, filterNavs[0]);
  }

  // ----- haptics on check-in / RSVP / vote
  document.addEventListener("submit", function (ev) {
    var act = (ev.target.getAttribute("action") || "");
    if (/checkin|checkout|\/rsvp|\/vote|\/unvote/.test(act)) haptic("Medium");
  });

  // ----- prefetch + skeleton + view transitions
  if (!document.querySelector('meta[name="view-transition"]')) {
    var vt = document.createElement("meta");
    vt.setAttribute("name", "view-transition");
    vt.setAttribute("content", "same-origin");
    document.head.appendChild(vt);
  }
  var prefetched = {};
  function prefetch(href) {
    try {
      var u = new URL(href, location.href);
      if (u.origin !== location.origin) return;
      if (u.pathname === path && u.search === location.search) return;
      if (/^\/(auth|signout|admin)/.test(u.pathname)) return;
      var key = u.pathname + u.search;
      if (prefetched[key]) return;
      prefetched[key] = true;
      var l = document.createElement("link");
      l.rel = "prefetch";
      l.href = u.href;
      document.head.appendChild(l);
    } catch (e) {}
  }
  document.addEventListener("pointerdown", function (ev) {
    var a = ev.target.closest && ev.target.closest("a[href]");
    if (a) prefetch(a.getAttribute("href"));
  }, { passive: true });

  function showSkel() {
    if (reduce) return;
    skel.classList.add("is-on");
  }
  window.addEventListener("pageshow", function () { skel.classList.remove("is-on"); });
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("a[href]");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || a.target === "_blank") return;
    var href = a.getAttribute("href") || "";
    if (href.charAt(0) === "#" || href.indexOf("mailto:") === 0 || href.indexOf("javascript:") === 0) return;
    try {
      var u = new URL(href, location.href);
      if (u.origin !== location.origin) return;
      if (/^\/(auth|signout|admin)/.test(u.pathname)) return;
      if (u.pathname === path && u.search === location.search && u.hash) return;
      showSkel();
    } catch (e) {}
  });

  // ----- pull to refresh (lists only; skip the map)
  var lists = /^\/(runs|meetups|picks|recommendations|me|dogs|photos|community|packs)(\/|$)/.test(path) || path === "/runs";
  if (lists && !reduce) {
    var startY = 0, pulling = false, ready = false;
    function ignore(t) {
      return t.closest && (t.closest("#map, .mapwrap, .bb-sheet, input, textarea, select, .leaflet-container"));
    }
    document.addEventListener("touchstart", function (ev) {
      if (sheetOpen || window.scrollY > 2) { pulling = false; return; }
      if (ev.touches.length !== 1 || ignore(ev.target)) { pulling = false; return; }
      startY = ev.touches[0].clientY;
      pulling = true;
      ready = false;
    }, { passive: true });
    document.addEventListener("touchmove", function (ev) {
      if (!pulling) return;
      var dy = ev.touches[0].clientY - startY;
      if (dy < 0 || window.scrollY > 2) { ptr.style.height = "0px"; return; }
      var h = Math.min(72, dy * 0.45);
      ptr.style.height = h + "px";
      ready = h > 48;
      ptr.querySelector("span").textContent = ready ? "Release to refresh" : "Pull to refresh";
    }, { passive: true });
    document.addEventListener("touchend", function () {
      if (pulling && ready) { haptic("Light"); location.reload(); }
      pulling = false; ready = false;
      ptr.style.height = "0px";
    });
  }

  // ----- Android hardware back
  if (Plugins.App && Plugins.App.addListener) {
    Plugins.App.addListener("backButton", function (ev) {
      if (closeSheet()) return;
      if (!isTabRoot() && ev && ev.canGoBack) history.back();
      else if (Plugins.App.exitApp) Plugins.App.exitApp();
    });
  }

  // Arrival check-in prompt: only while the app or home-screen version is open and visible.
  // Never asks for location permission on its own; never tracks in the background.
  (function arrivePrompt() {
    var htmlEl = document.documentElement;
    if (!htmlEl.classList.contains("bb-app")) return;
    if (!navigator.geolocation) return;
    var NEAR_M = 150, COOL_MS = 2 * 60 * 60 * 1000;
    function km(a, b) {
      var r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLng = (b.lng - a.lng) * r;
      var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
      return 6371 * 2 * Math.asin(Math.sqrt(h));
    }
    function dismissed(id) {
      try { return Date.now() - Number(localStorage.getItem("bb-arrive-dismiss:" + id) || 0) < COOL_MS; } catch (e) { return false; }
    }
    function dismiss(id) {
      try { localStorage.setItem("bb-arrive-dismiss:" + id, String(Date.now())); } catch (e) {}
    }
    var runsCache = null;
    function loadRuns(cb) {
      if (runsCache) return cb(runsCache);
      fetch("/api/runs", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
        runsCache = (d && d.runs) || [];
        cb(runsCache);
      }).catch(function () {});
    }
    function consider(pos) {
      if (document.visibilityState !== "visible") return;
      loadRuns(function (runs) {
        var me = { lat: pos.coords.latitude, lng: pos.coords.longitude }, best = null, bestM = NEAR_M;
        runs.forEach(function (r) {
          if (r.lat == null || r.lng == null) return;
          var m = km(me, { lat: r.lat, lng: r.lng }) * 1000;
          if (m < bestM) { bestM = m; best = r; }
        });
        if (!best || dismissed(best.id)) return;
        if (path.indexOf("/runs/" + best.id) === 0 && document.querySelector("form[action$='/checkout']")) return;
        if (document.querySelector(".bb-sheet")) return;
        dismiss(best.id);
        var name = String(best.name || "the dog run").replace(/</g, "&lt;");
        openSheet("Check in?", "<p>Looks like you're at <b>" + name + "</b>. Want to check in?</p>" +
          "<p class=\"small muted\">We only checked because this app is open. We don't track you in the background.</p>" +
          "<p><button type=\"button\" class=\"btn\" data-arrive-go>Check in</button></p>");
        var btn = document.querySelector("[data-arrive-go]");
        if (btn) btn.addEventListener("click", function () {
          location.href = "/runs/" + encodeURIComponent(best.id) + "?m=gate#here";
        });
      });
    }
    function maybe() {
      if (document.visibilityState !== "visible") return;
      function loc() {
        navigator.geolocation.getCurrentPosition(consider, function () {}, { enableHighAccuracy: false, timeout: 4000, maximumAge: 120000 });
      }
      if (navigator.permissions && navigator.permissions.query) {
        navigator.permissions.query({ name: "geolocation" }).then(function (p) {
          if (p.state === "granted") loc();
        }).catch(function () {});
      }
    }
    maybe();
    setInterval(maybe, 120000);
    document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") maybe(); });
  })();

})();
