import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

import type { PickerFrameProps } from "../IcdPickerFrame";
import type { PickerReply } from "../pickerBridge";

/** A failed bridge call: the bridge's `{code, message, status}` reply as an Error. */
export class PickerError extends Error {
  constructor(message: string, readonly code: string, readonly status: number) {
    super(message);
  }
}

export type Post = (path: string, body: object) => Promise<unknown>;

/**
 * Promise-wrapped `{t:"req"}` messages to the picker bridge, the same channel the web page uses. The bridge drops
 * replies that went stale (certificate revision moved, modal closed), so a call may never settle: callers guard with
 * their own token or by unmounting.
 */
export function usePost(onMessage: PickerFrameProps["onMessage"]): Post {
  const latest = useRef(onMessage);
  latest.current = onMessage;
  const next = useRef(1);
  return useCallback((path, body) => new Promise((resolve, reject) => {
    latest.current({ t: "req", id: next.current++, path, body }, (message) => {
      const reply = message as PickerReply;
      if (reply.ok) resolve(reply.data);
      else reject(new PickerError(reply.error.message, reply.error.code, reply.error.status));
    });
  }), []);
}

/** Text the picker wrote for the coder itself; unlike any other error it is safe to show as it is. */
export class Notice extends Error {}

const GENERIC = "The request could not be completed.";
// DORIS error codes (app/routes/api/doris_clinical.py) with fixed wording of our own: the reply's text is never shown.
const KNOWN_CODES = new Map([
  ["CODE_NOT_FOUND", "Select a valid ICD-11 code."],
  ["INVALID_INPUT", "The request was not accepted. Check the text and try again."],
  ["INVALID_SELECTION", "The selected code does not match its WHO URI."],
  ["NOT_AVAILABLE", "This case is not available here."],
  ["WHO_API_UNAVAILABLE", "The WHO ICD-11 service is unavailable. Try again shortly."],
]);

/**
 * What the coder reads for a failure: a `Notice`, a known DORIS code's fixed line, or a generic line. Transport
 * texts ("HTTP 502"), parser texts ("Invalid DORIS response: axes[0].id") and offline engine texts never reach the screen.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof Notice) return error.message;
  return (error instanceof PickerError && KNOWN_CODES.get(error.code)) || GENERIC;
}

export type Loaded<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ok"; data: T };

/** Runs `load` on mount and when `deps` change; a result that arrives after that is ignored. */
export function useLoad<T>(load: () => Promise<T>, deps: DependencyList): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    load().then(
      (data) => { if (live) setState({ status: "ok", data }); },
      (error) => { if (live) setState({ status: "error", message: errorMessage(error) }); },
    );
    return () => { live = false; };
  }, deps);
  return state;
}
