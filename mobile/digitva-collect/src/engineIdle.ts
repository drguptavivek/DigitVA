import { useFocusEffect } from "expo-router";
import { useCallback } from "react";

import { offlineEngine } from "./offlineEngine";
import { offlineSmartvaEngine } from "./smartva/nativeEngine";

/** Owner 2026-11-13 (digitva-xhz7): the engine processes stop this long after the last coding screen loses focus. */
export const ENGINE_IDLE_MS = 10 * 60 * 1000;
/** A release refused because a call was still pending is tried again after this. */
export const ENGINE_RELEASE_RETRY_MS = 60 * 1000;

export interface EngineIdle {
  /** A coding screen gained focus: cancels any countdown. Returns the blur, which starts it when no screen is left. */
  focus(): () => void;
}

/**
 * Counts focused coding screens; when the last one blurs, waits `idleMs`, then calls `release` (true when every engine
 * stopped, false when one still had a call pending: tried again after `retryMs`). A refocus cancels the wait. App
 * background changes nothing: the countdown keeps running, and native refuses a release mid-call.
 */
export function createEngineIdle(
  release: () => Promise<boolean>,
  idleMs = ENGINE_IDLE_MS,
  retryMs = ENGINE_RELEASE_RETRY_MS,
): EngineIdle {
  let focused = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function arm(ms: number) {
    timer = setTimeout(() => {
      timer = undefined;
      void release().catch(() => false).then((released) => {
        if (!released && focused === 0 && !timer) arm(retryMs);
      });
    }, ms);
  }

  return {
    focus() {
      focused += 1;
      if (timer) clearTimeout(timer);
      timer = undefined;
      let blurred = false;
      return () => {
        if (blurred) return;
        blurred = true;
        focused -= 1;
        if (focused === 0 && !timer) arm(idleMs);
      };
    },
  };
}

/** Stops both engines; an engine wrapper or native module without release (older builds, iOS) counts as stopped. */
export async function releaseEngines(): Promise<boolean> {
  const [icd, smartva] = await Promise.all([offlineEngine().release?.() ?? true, offlineSmartvaEngine().release?.() ?? true]);
  return icd && smartva;
}

export const engineIdle = createEngineIdle(releaseEngines);

/** Registers the calling screen as a coding screen while it has focus. `active` false registers nothing. */
export function useEngineScreen(active = true): void {
  useFocusEffect(useCallback(() => (active ? engineIdle.focus() : undefined), [active]));
}
