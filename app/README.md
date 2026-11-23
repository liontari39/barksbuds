# BarksBuds native app (Capacitor)

This folder is a Capacitor wrapper around the live BarksBuds site. The WebView
loads `https://barksbuds.app` (or `$BARKSBUDS_SERVER_URL`) so sign-in cookies
stay first-party and the existing `SameSite=Lax` session works.

The website itself is unchanged for browser visitors. Native camera, location
and push are feature-detected in `/native.js` only when Capacitor is present.

## Local setup

```bash
cd app
npm install
python3 scripts/make_icons.py
npx cap sync
```

Android Studio can open `android/` (`npm run open:android`). The iOS project
is in `ios/` and builds on a Mac (or CI); it cannot be compiled on Linux.

To point the WebView at a local server:

```bash
BARKSBUDS_SERVER_URL=http://10.0.2.2:8080 npx cap sync
```

Do not commit a machine-local URL.

## Deep links (magic-link sign-in)

Until Associated Domains (iOS) and App Links (Android) are live, a sign-in
email may open in the system browser instead of the app. After Mike adds
`IOS_TEAM_ID` and `ANDROID_CERT_SHA256` on the host, the site serves:

- `https://barksbuds.app/.well-known/apple-app-site-association`
- `https://barksbuds.app/.well-known/assetlinks.json`

The app also registers the `barksbuds://` custom scheme as a fallback.

## Push

Web Push (VAPID) already exists. Native push stores device tokens at
`POST /me/push/device` and sends via APNs/FCM only when those env vars are
set. Until then, tokens can be stored and nothing is sent. See
`docs/app-store/mike-checklist.md`.

## Secrets

Never commit `google-services.json`, `GoogleService-Info.plist`, `.p8` keys,
keystores, or service-account JSON. They are gitignored.

## Building a debug APK

Needs a JDK, the Android SDK, and accepted Android SDK licenses (Mike or CI
must accept those; this project does not accept agreements for you). Then:

```bash
cd android
./gradlew assembleDebug
```

The APK lands at `android/app/build/outputs/apk/debug/app-debug.apk`.
