import { useCallback, useEffect, useRef } from "react";
import type { LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent, ScrollView } from "react-native";

import { browserSessionStore, canRestoreScroll, readScroll, saveScroll } from "./viewState";

const SAVE_INTERVAL_MS = 250;
const GIVE_UP_MS = 6000;
const SETTLE_MS = 1200;
const USER_INPUT_EVENTS = ["wheel", "touchstart", "keydown", "mousedown"] as const;

/**
 * Remember a scroller's offset per (mode, case, section) in sessionStorage and put it back after a reload.
 * Restore retries as content grows (the section loads asynchronously) and stops for good at the first
 * sign of user input or after a few seconds, so it never fights the reader. Web only: no-op without
 * sessionStorage.
 */
export function useScrollMemory(mode: string, vaSid: string, section: string) {
  const scroller = useRef<ScrollView>(null);
  const memo = useRef({ target: 0, pending: false, viewport: 0, content: 0, latest: 0, timer: undefined as ReturnType<typeof setTimeout> | undefined, settle: undefined as ReturnType<typeof setTimeout> | undefined });
  const where = useRef({ mode, vaSid, section });
  where.current = { mode, vaSid, section };

  const persist = useCallback(() => {
    const state = memo.current;
    if (state.timer) clearTimeout(state.timer);
    state.timer = undefined;
    if (!state.pending) saveScroll(browserSessionStore(), where.current.mode, where.current.vaSid, where.current.section, state.latest);
  }, []);

  const tryRestore = useCallback(() => {
    const state = memo.current;
    if (!state.pending || !canRestoreScroll(state.target, state.content, state.viewport)) return;
    // Keep re-applying while the page settles (late content and scroll anchoring move the offset);
    // saving stays paused until the offset has been stable for SETTLE_MS or the user acts.
    scroller.current?.scrollTo({ y: state.target, animated: false });
    if (state.settle) clearTimeout(state.settle);
    state.settle = setTimeout(() => { state.pending = false; }, SETTLE_MS);
  }, []);

  useEffect(() => {
    const state = memo.current;
    const store = browserSessionStore();
    if (!store || !section) return undefined;
    state.target = readScroll(store, mode, vaSid, section);
    state.latest = state.target;
    state.pending = state.target > 0;
    const stop = () => { state.pending = false; };
    const giveUp = setTimeout(stop, GIVE_UP_MS);
    if (state.pending) USER_INPUT_EVENTS.forEach((name) => document.addEventListener(name, stop, { passive: true }));
    window.addEventListener("pagehide", persist);
    tryRestore();
    return () => {
      clearTimeout(giveUp);
      if (state.timer) clearTimeout(state.timer);
      if (state.settle) clearTimeout(state.settle);
      state.timer = undefined;
      state.settle = undefined;
      USER_INPUT_EVENTS.forEach((name) => document.removeEventListener(name, stop));
      window.removeEventListener("pagehide", persist);
    };
  }, [mode, vaSid, section, persist, tryRestore]);

  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const state = memo.current;
    state.latest = event.nativeEvent.contentOffset.y;
    if (!state.pending && !state.timer) state.timer = setTimeout(persist, SAVE_INTERVAL_MS);
  }, [persist]);

  const onContentSizeChange = useCallback((_width: number, height: number) => {
    memo.current.content = height;
    tryRestore();
  }, [tryRestore]);

  const onLayout = useCallback((event: LayoutChangeEvent) => {
    memo.current.viewport = event.nativeEvent.layout.height;
    tryRestore();
  }, [tryRestore]);

  return { ref: scroller, onScroll, onContentSizeChange, onLayout, scrollEventThrottle: 100 };
}
