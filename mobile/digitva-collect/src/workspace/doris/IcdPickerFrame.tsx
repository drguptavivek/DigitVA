import { createElement, useEffect, useRef } from "react";

import { pickerPageUrl, type PickerInit } from "./pickerBridge";

export interface PickerFrameProps {
  init: PickerInit;
  /** Certificate revision; the page drops replies that predate a change. */
  revision: number;
  onMessage: (message: unknown, reply: (message: object) => void) => void;
}

/**
 * Browser build: the shared picker page in a same-origin iframe, so its
 * Bootstrap styles cannot touch the app. Messages are accepted only from that
 * frame and our own origin; the page gets no credentials.
 */
export function IcdPickerFrame({ init, revision, onMessage }: PickerFrameProps) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  // Fixed at mount: changing the URL would reload the page and lose the user's place.
  const src = useRef(pickerPageUrl(init.theme));
  const latest = useRef({ init, revision, onMessage });
  latest.current = { init, revision, onMessage };

  const post = (message: object) => frame.current?.contentWindow?.postMessage(message, window.location.origin);

  useEffect(() => {
    const listener = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow || event.origin !== window.location.origin) return;
      const data = event.data as { t?: unknown } | null;
      if (data && data.t === "ready") post({ t: "init", ...latest.current.init, revision: latest.current.revision });
      else latest.current.onMessage(data, post);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, []);

  useEffect(() => { post({ t: "revision", value: revision }); }, [revision]);

  return createElement("iframe", {
    ref: frame,
    src: src.current,
    title: "ICD-11 condition picker",
    style: { position: "absolute", inset: 0, width: "100%", height: "100%", border: 0, background: "transparent" },
  });
}
