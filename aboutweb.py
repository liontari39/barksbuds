"""/about: who we are, the story of Jack (the dog in our logo), and how we treat members' info.

Jack facts are only what Mike has confirmed: Jack was Mike's Cairn terrier, he is the dog in the BarksBuds logo,
and he passed away in 2024 at 17. Do not add anecdotes here without Mike's OK.
The trust list only states things the code actually does (see accounts.py, webapp.py, privacy.py).
"""
import html

import accounts as A

e = html.escape

TRUST = [
    ("i-shield", "We never sell or share your info.", "We use it only to run BarksBuds and send the emails you choose."),
    ("i-lock", "Your email stays private.", "It's never shown on your profile, your dogs' pages or anywhere else on the site."),
    ("i-mail", "No passwords to leak.", f"You sign in with a one-time email link that expires after {A.LINK_TTL // 60} minutes."),
    ("i-camera", "Photo location is removed.", "Every photo is re-encoded on upload, which strips the hidden location data (EXIF) phones add."),
    ("i-users", "You choose who sees your dogs.", "Privacy settings control what shows, who can find you and who can message you."),
    ("i-check", "Leave any time.", "You can delete your account and your dogs' profiles yourself, from your account page."),
]


class AboutRoutes:
    def about_get(self, path, q):
        if path not in ("/about", "/about/"):
            return False
        trust = "".join(f'<li><svg class="ico" aria-hidden="true"><use href="#{i}"/></svg><div><strong>{e(t)}</strong> {e(d)}</div></li>'
                        for i, t, d in TRUST)
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">our story</span><h1>About BarksBuds</h1>
<p class="lead">A free community for dog people in NYC, Long Island and Westchester: a dog run map, meetups, packs and a profile for your pup. A group of friends that love their dogs.</p></div></section>
<section class="section"><div class="wrap narrow">
<div class="panel about-jack"><picture>
<source type="image/webp" srcset="/img/jack-about-480.webp?v=1 480w, /img/jack-about-960.webp?v=1 960w" sizes="(max-width: 640px) 260px, 280px">
<img src="/img/jack-about.jpg?v=1" width="960" height="1200" alt="Jack, Mike's Cairn terrier" loading="lazy" decoding="async">
</picture>
<div><span class="eyebrow">in loving memory</span><h2>Meet Jack</h2>
<p>The scruffy terrier in our logo is Jack, Mike's Cairn terrier. Jack lived to 17 and passed away in 2024.</p>
<p>We kept him in the logo, so a little of Jack comes along to every dog run, meetup and pack on BarksBuds.</p></div></div>
<h2 id="trust">Your info is safe with us</h2>
<ul class="trust">{trust}</ul>
<p class="small muted">The details are in our <a href="/privacy">privacy policy</a> and <a href="/terms">terms</a>. Questions? Write to <a href="mailto:hello@barksbuds.app">hello@barksbuds.app</a>.</p>
<div class="formfoot"><a class="btn" href="/signin">Join BarksBuds</a><a class="btn btn-ghost" href="/runs">Find a dog run</a></div>
</div></section>"""
        self.page("About BarksBuds", body, index=True, canonical="/about", active="about",
                  desc="BarksBuds is a free community for dog people in NYC, Long Island and Westchester. Meet Jack, the terrier in our logo, and see how we protect your info.",
                  og={"title": "About BarksBuds", "image": self._base() + "/img/og-image.jpg?v=jack3", "w": 1200, "h": 630})
        return True
