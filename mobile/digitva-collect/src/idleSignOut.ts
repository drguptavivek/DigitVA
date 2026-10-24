import { useEffect, useRef, useState } from "react";

/**
 * Web idle sign-out (docs/policy/expo-client.md "Idle sign-out"). The server enforces the same 30 minutes
 * on its own clock, counting only non-background requests; this timer warns first and keeps the server
 * stamp fresh while the user is working without sending requests (typing in a form).
 */
export const IDLE_WARN_MS = 28 * 60_000;
export const IDLE_SIGN_OUT_MS = 30 * 60_000;
/** While the user is active, at most one keep-alive request per interval (server stamp grain is 30 s). */
export const IDLE_PING_MS = 30_000;
const CHECK_MS = 10_000;
const INPUT_EVENTS = ["pointerdown", "keydown", "scroll", "touchstart"] as const;

export interface IdleMonitor {
  /** A real user input. Ignored while the warning is showing: only "Stay signed in" counts then. */
  input(): void;
  /** The user chose "Stay signed in". */
  stay(): void;
  /** Compare the clock with the last input; call on a timer and when the tab becomes visible. */
  check(): void;
}

export function createIdleMonitor(opts: {
  now?: () => number;
  onWarn(shown: boolean): void;
  onSignOut(): void;
  ping(): void;
}): IdleMonitor {
  const now = opts.now ?? Date.now;
  let lastInput = now();
  let lastPing = lastInput;
  let warned = false;
  let signedOut = false;

  const ping = () => { lastPing = now(); opts.ping(); };
  return {
    input() {
      if (warned || signedOut) return;
      lastInput = now();
      if (lastInput - lastPing >= IDLE_PING_MS) ping();
    },
    stay() {
      if (signedOut) return;
      lastInput = now();
      warned = false;
      opts.onWarn(false);
      ping();
    },
    check() {
      if (signedOut) return;
      const idle = now() - lastInput;
      if (idle >= IDLE_SIGN_OUT_MS) {
        signedOut = true;
        opts.onWarn(false);
        opts.onSignOut();
      } else if (idle >= IDLE_WARN_MS && !warned) {
        warned = true;
        opts.onWarn(true);
      }
    },
  };
}

/** Wire the monitor to the page while *enabled*; returns whether the warning shows and the "Stay" action. */
export function useIdleSignOut(enabled: boolean, ping: () => void, signOut: () => void) {
  const [warning, setWarning] = useState(false);
  const monitor = useRef<IdleMonitor | undefined>(undefined);
  const latest = useRef({ ping, signOut });
  latest.current = { ping, signOut };

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || typeof document === "undefined") return undefined;
    const idle = createIdleMonitor({
      onWarn: setWarning,
      onSignOut: () => latest.current.signOut(),
      ping: () => latest.current.ping(),
    });
    monitor.current = idle;
    const onInput = () => idle.input();
    const onVisible = () => { if (document.visibilityState === "visible") idle.check(); };
    for (const type of INPUT_EVENTS) window.addEventListener(type, onInput, { capture: true, passive: true });
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(() => idle.check(), CHECK_MS);
    return () => {
      for (const type of INPUT_EVENTS) window.removeEventListener(type, onInput, { capture: true });
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
      monitor.current = undefined;
      setWarning(false);
    };
  }, [enabled]);

  return { warning, stay: () => monitor.current?.stay() };
}
