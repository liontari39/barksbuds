# Building an Android debug APK

A debug APK was not built in this pass. Doing so needs a JDK, the Android
SDK, and accepted Android SDK licenses. Those licenses are agreements this
work does not accept on Mike's behalf. After Mike (or CI) accepts them,
this is the local command:

```bash
# JDK 17+, ANDROID_HOME pointed at the command-line tools + platform 35
# and build-tools. Accept SDK licenses with sdkmanager --licenses yourself.
cd /workspace/barksbuds/app
npm install
python3 scripts/make_icons.py
npx cap sync android
cd android
./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

Codemagic can do the same in the cloud; see `/codemagic.yaml`. Do not commit
the APK, a keystore, or `local.properties`.

Smoke-test once you have an APK:

1. Install on a device or emulator (`adb install -r app-debug.apk`).
2. Confirm the WebView loads https://barksbuds.app (or your
   `BARKSBUDS_SERVER_URL`).
3. Sign in with a magic link (deep links work fully only after App Links
   are live).
4. Tap "Nearest first" and confirm the in-app location reason appears, then
   the system permission.
5. Open a dog's photos and confirm Take a photo / Choose from library.
6. Confirm the website in a normal browser is unchanged (no Capacitor UI).
