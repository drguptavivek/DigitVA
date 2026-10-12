import { useEffect, useRef, useState } from "react";
import { View } from "react-native";
import type { WebView as WebViewType, WebViewMessageEvent } from "react-native-webview";

import { loadDevice } from "../../auth";
import { pickerPageUrl } from "./pickerBridge";
import type { PickerFrameProps } from "./IcdPickerFrame";

/**
 * Native build: the shared picker page from the enrolled DigitVA server in a
 * WebView. The page is static and public; WHO calls go over the message
 * channel to the app, which holds the bearer token. Navigation away from the
 * enrolled origin is refused.
 */
export function IcdPickerFrame({ init, revision, onMessage }: PickerFrameProps) {
  // Loaded on first use: the native module is absent in unit tests that only import the editor.
  const { WebView } = require("react-native-webview") as typeof import("react-native-webview");
  const web = useRef<WebViewType | null>(null);
  const [origin, setOrigin] = useState<string | null>(null);
  const latest = useRef({ init, revision, onMessage });
  latest.current = { init, revision, onMessage };

  useEffect(() => {
    let live = true;
    void loadDevice().then((device) => { if (live && device) setOrigin(new URL(device.server).origin); });
    return () => { live = false; };
  }, []);

  const post = (message: object) => web.current?.injectJavaScript(`window.__digitvaEmbedReceive(${JSON.stringify(message)});true;`);
  useEffect(() => { post({ t: "revision", value: revision }); }, [revision]);

  if (!origin) return <View style={{ flex: 1 }} />;
  const onWebMessage = (event: WebViewMessageEvent) => {
    let data: unknown;
    try { data = JSON.parse(event.nativeEvent.data); } catch { return; }
    if (data && (data as { t?: unknown }).t === "ready") post({ t: "init", ...latest.current.init, revision: latest.current.revision });
    else latest.current.onMessage(data, post);
  };
  return (
    <WebView
      ref={web}
      style={{ flex: 1, backgroundColor: "transparent" }}
      source={{ uri: `${origin}${pickerPageUrl(init.theme)}` }}
      originWhitelist={[origin]}
      onShouldStartLoadWithRequest={(request) => request.url.startsWith(`${origin}/`)}
      onMessage={onWebMessage}
      javaScriptEnabled
      domStorageEnabled={false}
      allowFileAccess={false}
      setSupportMultipleWindows={false}
      incognito
    />
  );
}
