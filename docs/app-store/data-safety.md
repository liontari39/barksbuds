# Privacy nutrition / Data safety answers

These answers match what the code actually does today. If a feature changes,
update `/privacy` and this file together. Location is not stored. Email is
never shown publicly.

## Data the app collects

| Data | Collected? | Stored on our servers? | Why | Optional? | Shared with other companies to use for their own purposes? |
| --- | --- | --- | --- | --- | --- |
| Email address | Yes, on sign-in | Yes | Account, magic-link sign-in, emails the owner chose | Required to have an account | No (Brevo only sends our email) |
| Name (display / first name) | Yes, if the owner adds it | Yes | Profile, shown to other members | Optional | No |
| Photos | Yes, if the owner uploads them | Yes (re-encoded; EXIF/GPS stripped) | Dog profile and community photos | Optional | No |
| Approximate / precise location | Only on device, after a tap | No, we do not save it | Sort dog runs near the owner, or drop a pin when suggesting a run | Optional, user-started | No |
| Device token for notifications | Yes, if the owner turns notifications on | Yes | Meetup reminders and check-in notes | Optional, off by default | Apple or Google deliver the notification; they get the token |
| Meetup, pack, check-in, and vote activity | Yes, as the owner uses those features | Yes | Running the community | Optional (don't use the feature) | No |
| Technical logs (IP, pages) | Yes, via the host | Short-term, by the host | Security and reliability | Automatic | Host (Render, Cloudflare) as processors |

We do not collect: payment info, precise stored location, contacts, health
data, browsing history outside BarksBuds, advertising IDs, or data for
third-party advertising.

## Google Play Data safety form (suggested ticks)

- App collects user data: Yes
- Data is encrypted in transit: Yes (HTTPS)
- Users can request deletion: Yes (Delete my account on `/me`, or email
  hello@barksbuds.app)
- Data used for tracking / advertising / sale: No
- Location: approximate location may be used on-device only; do not mark
  "stored" or "shared". If the form requires a location type, choose
  approximate, ephemeral, and not shared.
- Photos: user-generated content, optional, not shared for third-party use
- Personal info: email, name
- App activity: app interactions (meetups, check-ins)
- Identifiers: if they have a row for a push token, it is optional and used
  for app functionality

## Apple privacy nutrition labels (suggested)

- Email Address — Account signup, App functionality; linked to identity; not
  used for tracking
- Name — App functionality; linked; not tracking
- Photos — App functionality; linked; not tracking
- Product Interaction (RSVPs, check-ins, votes) — App functionality; linked;
  not tracking
- User ID — App functionality; linked; not tracking
- Do not list Location as collected data (we do not store it). If Apple
  still wants a location row because the permission exists, mark it as not
  linked and used only for App functionality, not collected on our servers.
- Do not list Tracking, Advertising, or Purchase History

## Permissions copy (already in the app project once patched)

- Location when in use: "BarksBuds uses your location only when you tap to
  sort dog runs near you, or to drop a pin when suggesting a run. We don't
  save it."
- Camera: "BarksBuds uses the camera only when you take a photo of your dog."
- Photo library: "BarksBuds accesses your photos only when you choose a
  picture of your dog to upload."
- Notifications: off until the owner turns them on from the account page.
