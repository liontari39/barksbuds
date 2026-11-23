/* Configurable server URL so the WebView is first-party on barksbuds.app
 * (SameSite=Lax cookies and CSRF Origin checks work). Override for local
 * dev with BARKSBUDS_SERVER_URL; never commit a machine-local URL. */
const serverUrl = (process.env.BARKSBUDS_SERVER_URL || "https://barksbuds.app").replace(/\/$/, "");

module.exports = {
  appId: "app.barksbuds",
  appName: "BarksBuds",
  webDir: "www",
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith("http://"),
    androidScheme: "https",
    allowNavigation: ["barksbuds.app", "*.barksbuds.app"],
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      backgroundColor: "#FFF8EA",
      showSpinner: false,
      launchFadeOutDuration: 200,
    },
    StatusBar: {
      style: "LIGHT",
      backgroundColor: "#FFF8EA",
    },
    PushNotifications: {
      presentationOptions: ["badge", "sound", "alert"],
    },
    Camera: {
      presentationStyle: "fullScreen",
    },
  },
  android: {
    appendUserAgent: "BarksBudsApp/1.0",
    allowMixedContent: false,
  },
  ios: {
    appendUserAgent: "BarksBudsApp/1.0",
    contentInset: "automatic",
    scheme: "BarksBuds",
    preferredContentMode: "mobile",
  },
};
