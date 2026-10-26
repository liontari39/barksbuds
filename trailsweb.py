"""Dog-friendly hiking trails (/trails) with a Leaflet map, region filters and official sources.

Routes:
  GET  /trails           list + map (indexable, in the sitemap)
  GET  /api/trails       the same data as JSON
  GET  /trails/suggest   -> /tips/suggest?topic=trail (members suggest a trail through the tip-suggestion queue)
Data lives in trailsdata.py; every entry links the official page(s) it was checked against.
"""
import html, json

import trailsdata as T

e = html.escape
GREEN = "#1F7A4D"

CSS = """<style>
.trchips{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0;padding:0;list-style:none}
.trchips button,.trchips a{display:inline-flex;align-items:center;gap:6px;min-height:42px;background:#fff;border:2px solid var(--black);border-radius:999px;padding:6px 14px;font:800 .93rem/1 Nunito,system-ui,sans-serif;color:var(--black);cursor:pointer;text-decoration:none}
.trchips button[aria-pressed="true"]{background:#1F7A4D;border-color:#1F7A4D;color:#fff}
.trchips .n{font-weight:700;opacity:.75}
.trmapwrap{position:relative;border:2px solid var(--black);border-radius:var(--r);overflow:hidden;box-shadow:6px 6px 0 #1F7A4D;background:#e7eadf}
#tmap{height:460px}
@media (max-width:640px){#tmap{height:340px}}
.trlegend{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin:12px 0 0;font-size:.9rem;color:var(--muted)}
.trlegend .dot{display:inline-block;width:14px;height:14px;border-radius:50%;background:#1F7A4D;border:2px solid #fff;box-shadow:0 0 0 1px #1F7A4D;vertical-align:-2px;margin-right:6px}
.trnote{display:flex;gap:12px;align-items:flex-start;background:#EAF5EE;border:2px solid #1F7A4D;border-radius:16px;padding:14px 16px;margin:22px 0 0;font-size:.95rem}
.trnote .ico{color:#1F7A4D;margin-top:3px}
.trsec{margin:40px 0 0}.trsec h2{font-size:1.6rem;margin:0 0 14px}
.trgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px}
@media (max-width:420px){.trgrid{grid-template-columns:1fr}}
.trcard{background:#fff;border:2px solid var(--black);border-radius:var(--r);padding:20px;box-shadow:5px 5px 0 #1F7A4D;display:flex;flex-direction:column;gap:8px;scroll-margin-top:90px}
.trcard.hl{outline:3px solid #1F7A4D;outline-offset:3px}
.trcard h3{font-size:1.3rem;margin:0}
.trpark{margin:0;font-weight:800;color:var(--muted);font-size:.92rem}
.trcard dl{margin:4px 0 0;display:grid;grid-template-columns:1fr;gap:6px}
.trcard dt{font-weight:800;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:#1F7A4D;margin:0}
.trcard dd{margin:0 0 4px;font-size:.95rem;line-height:1.5}
.trcard ul{margin:0;padding-left:18px}
.trsrc a{word-break:break-word}
.trfoot{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-top:auto;padding-top:6px;font-size:.88rem;color:var(--muted)}
.trshow{font:800 .9rem/1 Nunito,system-ui,sans-serif;color:#1F7A4D;background:none;border:2px solid #1F7A4D;border-radius:999px;padding:9px 14px;min-height:40px;cursor:pointer}
.trshow:hover{background:#EAF5EE}
.trask{display:flex;flex-wrap:wrap;gap:16px;align-items:center;justify-content:space-between;background:var(--black);color:#E9E1D3;border-radius:24px;padding:24px;margin:44px 0 0}
.trask h2{color:#fff;margin:0;font-size:1.5rem}.trask p{margin:4px 0 0;color:#D9D0C2}
.trpin{display:block;width:30px;height:40px}
.trpin svg{width:100%;height:100%;filter:drop-shadow(0 3px 3px rgba(0,0,0,.35))}
.leaflet-popup-content{font:600 .92rem/1.4 Nunito,sans-serif;margin:10px 12px}
.leaflet-popup-content b{font-family:"Baloo 2";font-size:1.02rem;color:var(--black)}
</style>"""

PIN_SVG = ('<svg viewBox="0 0 30 40" aria-hidden="true"><path d="M15 39s13-12.6 13-23.5A13 13 0 0 0 2 15.5C2 26.4 15 39 15 39z" fill="#1F7A4D" stroke="#fff" stroke-width="2"/>'
           '<path d="M15 7l-6 9h3.5L8 22h14l-4.5-6H21z" fill="#fff"/><rect x="14" y="22" width="2" height="3.5" fill="#fff"/></svg>')

JS = """<link rel="stylesheet" href="/vendor/leaflet/leaflet.css"><script src="/vendor/leaflet/leaflet.js"></script><script>(function(){
var data=JSON.parse(document.getElementById('trail-data').textContent);var el=document.getElementById('tmap');
var chips=[].slice.call(document.querySelectorAll('button[data-region]'));var map=null,markers={},active='all';
if(el&&window.L){el.hidden=false;document.getElementById('tmap-fallback').hidden=true;
map=L.map(el,{scrollWheelZoom:false});map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,crossOrigin:true,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
var icon=L.divIcon({className:'trpin',html:PIN,iconSize:[30,40],iconAnchor:[15,39],popupAnchor:[0,-34]});
data.forEach(function(t){var m=L.marker([t.lat,t.lng],{icon:icon,title:t.name,alt:t.name+' trail pin'});
var d=document.createElement('div');var b=document.createElement('b');b.textContent=t.name;d.appendChild(b);d.appendChild(document.createElement('br'));
d.appendChild(document.createTextNode(t.park+' \\u00b7 '+t.region_label));d.appendChild(document.createElement('br'));var a=document.createElement('a');a.href='#'+t.slug;a.textContent='Dog rules & parking';
a.addEventListener('click',function(){hl(t.slug)});d.appendChild(a);m.bindPopup(d,{autoPanPadding:[24,24]});m.addTo(map);markers[t.slug]={m:m,r:t.region}});
[].forEach.call(document.querySelectorAll('.trshow'),function(b){b.hidden=false});fit();}
function fit(){if(!map)return;var b=[];data.forEach(function(t){if(active==='all'||t.region===active)b.push([t.lat,t.lng])});if(b.length)map.fitBounds(b,{padding:[30,30],maxZoom:13})}
function hl(s){var c=document.getElementById(s);if(!c)return;[].forEach.call(document.querySelectorAll('.trcard.hl'),function(x){x.classList.remove('hl')});c.classList.add('hl')}
chips.forEach(function(c){c.addEventListener('click',function(){active=c.getAttribute('data-region');chips.forEach(function(x){x.setAttribute('aria-pressed',x===c?'true':'false')});
[].forEach.call(document.querySelectorAll('.trsec'),function(s){s.hidden=!(active==='all'||s.getAttribute('data-sec')===active)});
Object.keys(markers).forEach(function(k){var o=markers[k];if(active==='all'||o.r===active){o.m.addTo(map)}else{map.removeLayer(o.m)}});fit();
document.getElementById('trcount').textContent=document.querySelectorAll('.trsec:not([hidden]) .trcard').length})});
[].forEach.call(document.querySelectorAll('.trshow'),function(btn){btn.addEventListener('click',function(){var s=btn.getAttribute('data-slug'),o=markers[s];if(!o||!map)return;
if(!map.hasLayer(o.m))o.m.addTo(map);el.scrollIntoView({behavior:'smooth',block:'center'});map.setView(o.m.getLatLng(),14,{animate:false});o.m.openPopup();hl(s)})});
})();</script>"""


def trail_json(t):
    return {"slug": t["slug"], "name": t["name"], "park": t["park"], "region": t["region"], "region_label": T.REGION_LABEL[t["region"]],
            "area": t["area"], "lat": t["lat"], "lng": t["lng"], "dogs": t["dogs"], "where": t["where"], "distance": t["distance"],
            "difficulty": t["difficulty"], "access": t["access"], "parking": t["parking"], "restrictions": t["restrictions"],
            "sources": [{"label": l, "url": u} for l, u in t["sources"]], "checked": T.CHECKED}


def trail_card(t):
    rows = [("Dogs", e(t["dogs"]))]
    if t["where"]:
        rows.append(("Where dogs may go", e(t["where"])))
    if t["distance"]:
        rows.append(("Distance", e(t["distance"])))
    if t["difficulty"]:
        rows.append(("Difficulty", e(t["difficulty"])))
    if t["access"]:
        rows.append(("Getting there", e(t["access"])))
    rows.append(("Parking", e(t["parking"]) if t["parking"] else "Not listed on the official page; check before you go."))
    if t["restrictions"]:
        rows.append(("Seasonal &amp; other limits", "<ul>" + "".join(f"<li>{e(r)}</li>" for r in t["restrictions"]) + "</ul>"))
    src = "<ul class=\"trsrc\">" + "".join(f'<li><a href="{e(u)}" rel="noopener" target="_blank">{e(l)}</a></li>' for l, u in t["sources"]) + "</ul>"
    rows.append(("Official source", src))
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return (f'<article class="trcard" id="{t["slug"]}" data-region="{t["region"]}"><h3>{e(t["name"])}</h3>'
            f'<p class="trpark">{e(t["park"])} &middot; {e(t["area"])} &middot; {e(T.REGION_LABEL[t["region"]])}</p><dl>{dl}</dl>'
            f'<div class="trfoot"><span>Pin: <a href="https://www.openstreetmap.org/?mlat={t["lat"]}&amp;mlon={t["lng"]}#map=15/{t["lat"]}/{t["lng"]}" rel="noopener" target="_blank">'
            f'{t["lat"]:.5f}, {t["lng"]:.5f}</a></span><button type="button" class="trshow" hidden data-slug="{t["slug"]}">Show on map</button></div></article>')


class TrailRoutes:
    def trails_get(self, path, q):
        if path in ("/trails", "/trails/"):
            self._app_reset(); self.trails_page(q); return True
        if path == "/api/trails":
            self._json(200, {"updated": T.CHECKED, "count": len(T.TRAILS), "data": [trail_json(t) for t in T.TRAILS]}); return True
        if path in ("/trails/suggest", "/trails/suggest/"):
            self._app_reset(); self.redirect("/tips/suggest?topic=trail"); return True
        return False

    def trails_page(self, q):
        flash = "Thanks! We'll check your trail against the official park rules before adding it." if q.get("m", [""])[0] == "sent" else ""
        n = len(T.TRAILS)
        counts = {k: sum(1 for t in T.TRAILS if t["region"] == k) for k, _ in T.REGIONS}
        chips = (f'<li><button type="button" data-region="all" aria-pressed="true">All <span class="n">{n}</span></button></li>'
                 + "".join(f'<li><button type="button" data-region="{k}" aria-pressed="false">{e(v)} <span class="n">{counts[k]}</span></button></li>' for k, v in T.REGIONS))
        secs = "".join(f'<section class="trsec" id="region-{k}" data-sec="{k}" aria-labelledby="h-{k}"><h2 id="h-{k}">{e(v)}</h2>'
                       f'<div class="trgrid">{"".join(trail_card(t) for t in T.TRAILS if t["region"] == k)}</div></section>' for k, v in T.REGIONS)
        data = json.dumps([{k: trail_json(t)[k] for k in ("slug", "name", "park", "region", "region_label", "lat", "lng")} for t in T.TRAILS]).replace("<", "\\u003c")
        body = f"""{CSS}<section class="phead"><div class="wrap"><span class="eyebrow">dog-friendly trails</span>
<h1>Hiking trails where dogs are welcome</h1>
<p class="lead">{n} trails in New York City, Long Island and Westchester where leashed dogs are allowed, each checked against the official park or agency page.
Every card lists the dog rules, parking, seasonal limits and a link to the source.</p>
<ul class="trchips" aria-label="Filter by region">{chips}</ul></div></section>
<section class="section" style="padding-top:28px"><div class="wrap">
<div class="trmapwrap"><div id="tmap" role="region" aria-label="Map of dog-friendly trails" hidden></div>
<p id="tmap-fallback" style="margin:0;padding:24px">The map needs JavaScript. Every trail is listed below with its coordinates.</p></div>
<p class="trlegend"><span><span class="dot" aria-hidden="true"></span>Green pins are trails.</span><span>Showing <b id="trcount">{n}</b> trails.</span><a href="/runs">Looking for a fenced dog run instead?</a></p>
<div class="trnote" role="note"><svg class="ico" aria-hidden="true"><use href="#i-alert"/></svg><div><strong>Rules change, and posted signs always win.</strong>
We checked every trail on {e(T.CHECKED)} against official pages, but parks update rules, fees and closures. Tap the official source before you go.
Keep your dog leashed (6 ft or shorter almost everywhere here), pack out every bag, and read our <a href="/tips/trail-etiquette-with-dogs">trail etiquette tips</a>.</div></div>
{secs}
<div class="trask"><div><h2>Know a great dog-friendly trail?</h2><p>Tell us where it is and where the dog rules are posted. We verify every suggestion with the park before adding it.</p></div>
<a class="btn btn-gold" href="/trails/suggest">Suggest a trail</a></div>
<p class="small muted" style="margin-top:22px">Not on the list on purpose: Nassau County parks and preserves (dogs only in county dog runs), Forest Park's trails, Westchester County nature preserves and sanctuaries, and the Jamaica Bay Wildlife Refuge, where official rules don't allow dogs on the trails. Pins are approximate; use the official map for trailheads.</p>
</div></section><script type="application/json" id="trail-data">{data}</script>"""
        base = self._base()
        ld = {"@context": "https://schema.org", "@type": "ItemList", "name": "Dog-friendly hiking trails in NYC, Long Island and Westchester", "url": base + "/trails",
              "numberOfItems": n, "itemListElement": [
                  {"@type": "ListItem", "position": i + 1, "item": {"@type": "Place", "name": f'{t["name"]}, {t["park"]}', "url": f'{base}/trails#{t["slug"]}',
                                                                      "geo": {"@type": "GeoCoordinates", "latitude": t["lat"], "longitude": t["lng"]}}}
                  for i, t in enumerate(T.TRAILS)]}
        body += '<script type="application/ld+json">' + json.dumps(ld).replace("<", "\\u003c") + "</script>"
        desc = f"{n} dog-friendly hiking trails in NYC, Long Island and Westchester with leash rules, parking, seasonal limits and official sources."
        og = {"title": "Dog-friendly hiking trails | BarksBuds", "desc": desc, "image": base + "/img/og-image.jpg?v=jack3", "w": 1200, "h": 630,
              "alt": "BarksBuds: a group of friends that love their dogs"}
        return self.page("Dog-friendly hiking trails", body, index=True, active="trails", canonical="/trails", desc=desc, og=og,
                         scripts=JS.replace("PIN", json.dumps(PIN_SVG).replace("</", "<\\/")), flash=flash)
