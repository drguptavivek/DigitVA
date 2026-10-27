import { createElement, useEffect, useLayoutEffect, useRef, useState } from "react";

import { fontSize, ui } from "../../theme";
import { pickerPageUrl, type PickerInit } from "./pickerBridge";

export interface PickerFrameProps {
  init: PickerInit;
  /** Certificate revision; the page drops replies that predate a change. */
  revision: number;
  onMessage: (message: unknown, reply: (message: object) => void) => void;
  /** Offered next to Retry when the page never answers. */
  onClose?: () => void;
}

/** How long the page may take to say "ready" before the overlay offers Retry. */
export const PICKER_READY_TIMEOUT_MS = 15000;

/**
 * Browser build: the shared picker page in a same-origin iframe, so its
 * Bootstrap styles cannot touch the app. Messages are accepted only from that
 * frame and our own origin; the page gets no credentials.
 */
export function IcdPickerFrame({ init, revision, onMessage, onClose }: PickerFrameProps) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  // Fixed at mount: changing the URL would reload the page and lose the user's place.
  const src = useRef(pickerPageUrl(init.theme));
  const latest = useRef({ init, revision, onMessage });
  latest.current = { init, revision, onMessage };
  // Bumped by Retry: a new key reloads the iframe and restarts the ready timer.
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const heard = useRef(false);

  const post = (message: object) => frame.current?.contentWindow?.postMessage(message, window.location.origin);

  // Layout effect: the listener exists before the iframe can load. A passive effect could
  // run after the page's one-shot "ready" and the init reply would never be sent.
  useLayoutEffect(() => {
    const listener = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow || event.origin !== window.location.origin) return;
      const data = event.data as { t?: unknown } | null;
      if (data && data.t === "ready") {
        heard.current = true;
        setFailed(false);
        post({ t: "init", ...latest.current.init, revision: latest.current.revision });
      } else latest.current.onMessage(data, post);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, []);

  useEffect(() => {
    heard.current = false;
    const timer = setTimeout(() => { if (!heard.current) setFailed(true); }, PICKER_READY_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [attempt]);

  useEffect(() => { post({ t: "revision", value: revision }); }, [revision]);

  // The page re-sends "ready" itself until it gets init; this ping covers a page that
  // loaded before our listener or whose ready was dropped. It answers "ready" if not yet initialised.
  const iframe = createElement("iframe", {
    key: attempt,
    ref: frame,
    src: src.current,
    title: "ICD-11 condition picker",
    onLoad: () => { if (!heard.current) post({ t: "ping" }); },
    style: { position: "absolute", inset: 0, width: "100%", height: "100%", border: 0, background: "transparent" },
  });
  // Stable wrapper: swapping the tree shape would remount (reload) the iframe. A late "ready" clears the notice.
  const notice = failed
    ? createElement("div", { key: "notice", role: "alert", style: { position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, color: ui.light.primaryForeground, fontSize: fontSize.input, fontFamily: "sans-serif", pointerEvents: "none" } },
      createElement("span", null, "Search didn't load."),
      createElement("button", { type: "button", style: { pointerEvents: "auto" }, onClick: () => { setFailed(false); setAttempt((n) => n + 1); } }, "Retry"),
      onClose ? createElement("button", { type: "button", style: { pointerEvents: "auto" }, onClick: onClose }, "Close") : null)
    : null;
  return createElement("div", { style: { position: "absolute", inset: 0 } }, iframe, notice);
}
