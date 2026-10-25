# BarksBuds launch checklist

Mike picks the day. Nothing here runs automatically.

## Hard deadline: database upgrade before **Nov 23, 2026**
The free Render Postgres instance expires on Nov 23, 2026. Before then (aim for **Nov 16** at the latest),
upgrade it to a paid plan in Render (Dashboard → barksbuds database → Upgrade), or every account, dog,
meetup and pack goes with it. This costs money, so it's Mike's call. It does **not** depend on the launch date.

## The week before
- [ ] Look at https://barksbuds.app on your phone: the homepage, /meetups, /packs, /runs, /tips, /privacy, /terms.
- [ ] Sign in with a magic link and make sure the email arrives (check spam once).
- [ ] Read the announcement drafts in `barksbuds-assets/launch/announcement.md` and edit them in your own voice.
- [ ] Optional: look at the tip suggestions waiting at `/admin/tips?key=…`.

## Launch day (about 10 minutes)
1. **Rehearse (changes nothing):**
   `python3 launch.py`
   It shows how many Sample badges are live and what it would do.
2. **Remove the samples:**
   `python3 launch.py --yes`
   This deletes the sample pack(s) and sample meetup(s) through `/admin/packs` and `/admin/meetups`, then checks
   /packs and /meetups. The admin key comes from `.admin_key` (or `$ADMIN_KEY`) and is never printed.
3. **Turn on member emails (Render dashboard → service `srv-dbed49jncjis73dsb390` → Environment):**
   - **Add** `RUN_SUGGEST_EMAIL = mike.karachalios@gmail.com` *first*. Today the "new dog run" and "tip suggestion"
     notices go to the allowlist address, so without this they would stop.
   - **Remove** `MEETUP_EMAIL_ALLOWLIST`. That's the only one to delete. While it's set, meetup and pack emails
     go only to Mike.
   - Save. Render redeploys by itself. If it doesn't show "Live" within about 5 minutes, use Manual Deploy → Deploy latest commit.
4. **Smoke test (5 minutes):**
   - /meetups and /packs: no "Sample" badges.
   - Create a real meetup at your usual run. RSVP from a second account, and check that the organizer email arrives.
   - /tips, one article, /privacy and /terms all load. /sitemap.xml and /robots.txt load.
5. **Announce:** post and send the drafts (after you edit them). Contact for replies: hello@barksbuds.app.

## If something goes wrong
- Emails going to the wrong people: put `MEETUP_EMAIL_ALLOWLIST=mike.karachalios@gmail.com` back in Render.
- If you ever want the samples back: `python3 seed.py --url https://barksbuds.app`. It's safe to re-run, and nothing seeds automatically on deploy.
- Site down: Render dashboard → Logs. The previous deploy can be rolled back from the Deploys tab.

## Notes
- Auto-deploy from GitHub is currently broken. After a `git push`, trigger a deploy by hand in Render (or through the API).
- No paid services are needed apart from the database upgrade above.
