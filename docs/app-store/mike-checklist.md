# What Mike must do himself

Bots cannot create developer accounts, accept agreements, spend money, or
upload builds. Everything below has to be done in Mike's name (or a business
he controls). Costs are listed so there are no surprises.

## 1. Apple Developer Program — $99 / year

1. Enroll at https://developer.apple.com/programs/enroll/ as an individual, or
   as an organization.
2. If you enroll as an organization, Apple requires a D-U-N-S number. Request
   one free from Dun & Bradstreet before you start; it can take a few days
   (sometimes a couple of weeks).
3. Apple can take a week or two to approve an organization enrollment.
4. After you're in, create an app record with bundle ID `app.barksbuds`.
5. Create an APNs key (Keys → Apple Push Notifications service). Download the
   `.p8` file once, and note the Key ID and your Team ID. Keep the file off
   the repo and off chat logs.
6. Enable the Associated Domains capability for `applinks:barksbuds.app` and
   `webcredentials:barksbuds.app`.

## 2. Google Play Console — $25 one time

1. Register at https://play.google.com/console/signup. Google may ask for
   identity verification.
2. Create the app "BarksBuds" with package name `app.barksbuds`.
3. Create an upload keystore (or let Codemagic generate one) and back it up
   somewhere safe. If this key is lost, you cannot update the app.
4. Complete the Data safety form using `docs/app-store/data-safety.md`, plus
   the content rating questionnaire, target audience (adults), and store
   listing.

## 3. Firebase project (free) for FCM

1. Create a Firebase project (the Spark/free plan is enough).
2. Add an Android app with package `app.barksbuds` and an iOS app with bundle
   ID `app.barksbuds`.
3. Download `google-services.json` and `GoogleService-Info.plist`. Put them
   into Codemagic (or a local machine) at build time. Do not commit them.
4. Create a service account with the Firebase Cloud Messaging Admin role and
   a JSON key for the server. That file is a secret.

## 4. Hosting env vars (Render)

After the files and keys exist, add these on the live host. Leave them unset
until then — native notifications stay off and the well-known files stay 404.

- `IOS_TEAM_ID` — so `/ .well-known/apple-app-site-association` can be served
- `ANDROID_CERT_SHA256` — SHA-256 fingerprint of the Play signing / upload
  cert, so `/.well-known/assetlinks.json` can be served (colon-optional hex)
- `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC=app.barksbuds`
- `APNS_KEY_PATH` or `APNS_KEY_P8` (the .p8 body)
- `APNS_PRODUCTION=1` for App Store / TestFlight builds (`0` for sandbox)
- `FCM_SERVICE_ACCOUNT_FILE` (path) or `FCM_PROJECT_ID`, `FCM_CLIENT_EMAIL`,
  `FCM_PRIVATE_KEY`
- Optional: `httpx` with HTTP/2 on the server if you want APNs sending
  (FCM HTTP v1 works with the existing Python standard library)

Do not paste private keys into chat, email, or git.

## 5. Codemagic (free plan is enough to start)

1. Sign up at https://codemagic.io (Mike's account, not a bot's).
2. Connect the BarksBuds git repo when you're ready to ship a build.
3. Add signing secrets: iOS certificate/profile or Codemagic-managed signing,
   Android keystore, plus the Firebase files above.
4. A starter workflow already lives at `/codemagic.yaml` in this repo. It is
   not connected to any account.

A Mac is not required if Codemagic builds iOS. Android debug builds can also
be done locally after a JDK and Android SDK are installed and their licenses
are accepted (see `android-build.md`).

## 6. Store listing and review

1. Review `/privacy` (already updated for the app) and `/terms`.
2. Paste the copy from `listing-copy.md`.
3. Take or export the screenshots listed in `screenshots.md`.
4. Fill Apple's privacy nutrition labels and Google's Data safety form from
   `data-safety.md`.
5. Submit for review. Apple often takes 1–3 days and sometimes asks for a
   walkthrough of sign-in (use a demo account, Lily only) and of the native
   features (location on tap, camera for dog photos, notifications opt-in).

## 7. Things that are already done in the repo

- Capacitor project (`app/`, app ID `app.barksbuds`)
- Icons and splash sourced from the Jack logo
- Native push, geolocation and camera, feature-detected so the website is
  unchanged
- Privacy policy page at `/privacy`
- This checklist, listing copy, screenshot list, and Data safety answers
