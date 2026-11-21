"""Shared "Be the first in your town" empty state for /dogs, /packs, /meetups and /photos.

A warm headline, one clear call to action, and (for Long Island or unfiltered views) a few sourced, curated
dog runs plus local tips from localpicks.py, so an empty page still has something useful on it. All content is static
editorial content with source links; nothing here pretends to be a member.
"""
import html

import localpicks as L

e = html.escape

KINDS = {
    "dogs": ("i-paw", "Be the first in your town",
             "No dogs here yet. Add your pup, pick their favorite runs and your dog run friends will find you."),
    "packs": ("i-users", "Be the first in your town",
              "No packs here yet. Start one for your run and invite the regulars, so your dog sees familiar friends every week."),
    "meetups": ("i-cal", "Be the first in your town",
                "No meetups here yet. Pick a dog run, choose a time and invite the neighborhood."),
    "photos": ("i-camera", "Be the first to share a photo",
               "No photos yet. Share your dog at the run, on a walk or napping on the couch."),
}


def _run_href(r, runs):
    """Our run page when the run exists in the dataset, else None."""
    for x in runs or []:
        if x.get("id") == r["id"]:
            try:
                import runpageweb
                return runpageweb.run_path(x)
            except Exception:
                return "/runs/" + r["id"]
    return None


def picks_html(areas=None, runs=None, limit=6, heading="Dog runs to try on Long Island"):
    ps = L.picks(areas, limit)
    if not ps:
        return ""
    cards = []
    for r in ps:
        href = _run_href(r, runs)
        name = f'<a href="{e(href)}">{e(r["name"])}</a>' if href else e(r["name"])
        hours = (f'<p class="lp-hours"><svg class="ico" aria-hidden="true"><use href="#i-clock"/></svg>{e(r["hours"])}</p>'
                 if r["hours"] else '<p class="lp-hours muted">Hours: see source</p>')
        note = f'<p class="lp-note">{e(r["note"])}</p>' if r["note"] else ""
        cards.append(f'<li class="lp-card"><h4>{name}</h4><p class="lp-where"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>'
                     f'{e(r["where"])}</p>{note}{hours}<p class="lp-src">Source: {L.source_link(r["src"])}</p></li>')
    tips = "".join(f'<li>{e(t["text"])} <span class="lp-src">({L.source_link(t["src"])})</span></li>' for t in L.TIPS)
    guides = " &middot; ".join(f'<a href="/tips/{s}">{e(t)}</a>' for s, t in L.GUIDES)
    return (f'<section class="lp" aria-labelledby="lp-h"><div class="lp-head"><h3 id="lp-h">{e(heading)}</h3>'
            f'<a class="small" href="/runs">See all on the run map</a></div>'
            f'<ul class="lp-grid">{"".join(cards)}</ul>'
            f'<div class="lp-tips"><h3>Good to know on Long Island</h3><ul>{tips}</ul>'
            f'<p class="small">Our guides: {guides}</p></div>'
            f'<p class="small muted lp-fine">Details from official county, town and village pages, checked {L.VERIFIED_LABEL}. '
            f'Rules and hours can change, so check the source before you go.</p></section>')


def first_in_town_html(kind, cta_href, cta_label, *, areas=None, runs=None, where="", second=None):
    """The full empty state. `where` names the filtered place ("Suffolk County"), if any."""
    icon, title, sub = KINDS[kind]
    if where and kind != "photos":
        title = f"Be the first in {where}"
    btn2 = (f'<a class="btn btn-ghost" href="{e(second[0])}">{e(second[1])}</a>' if second else
            '<a class="btn btn-ghost" href="/runs">Find a dog run</a>')
    return (f'<div class="empty bfirst"><svg class="ico" aria-hidden="true"><use href="#{icon}"/></svg>'
            f'<span class="eyebrow">brand new here</span><h2>{e(title)}</h2><p class="muted">{e(sub)}</p>'
            f'<div class="bf-cta"><a class="btn" href="{e(cta_href)}">{e(cta_label)}</a>{btn2}</div>'
            f'<p class="small muted bf-share">Know someone with a dog nearby? Share BarksBuds with them. It\'s free.</p></div>'
            + picks_html(areas, runs))


def few_html(kind, cta_href, cta_label, where=""):
    """A compact invite band when a list has only a handful of entries."""
    icon, _, _ = KINDS[kind]
    place = f" in {where}" if where else " in your town"
    return (f'<div class="bfew"><svg class="ico" aria-hidden="true"><use href="#{icon}"/></svg>'
            f'<p><strong>Be the first{e(place)}.</strong> BarksBuds is brand new, so every pup who joins makes it better for the neighborhood.</p>'
            f'<a class="btn btn-sm" href="{e(cta_href)}">{e(cta_label)}</a></div>')
