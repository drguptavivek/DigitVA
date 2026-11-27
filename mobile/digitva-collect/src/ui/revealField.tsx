import { createContext, useCallback, useRef } from "react";
import type { LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent, ScrollView, View } from "react-native";

import { spacing } from "../theme";

/** Scrolls *field* to the top of the enclosing scroll area, then calls *done* once the new position can be measured. */
export type RevealField = (field: View, done: () => void) => void;

export const RevealFieldContext = createContext<RevealField | undefined>(undefined);

/** Web: the field is a DOM node; the browser scrolls it to the top of its nearest scrollable ancestor. */
export const revealOnWeb: RevealField = (field, done) => {
  (field as unknown as { scrollIntoView?: (o: { block: "start" }) => void }).scrollIntoView?.({ block: "start" });
  requestAnimationFrame(done);
};

const SCROLL_FALLBACK_MS = 150;

/**
 * For the component that owns a ScrollView: pass *onScroll* (with scrollEventThrottle 16), *onLayout* and
 * *onContentSizeChange*; *reveal* scrolls a field to the top of the view (target clamped to the scrollable range) and
 * calls *done* the frame after the ScrollView reports the move (Android lays out later than one frame), or after a
 * short timer when no scroll event comes. Without layout (tests, some hosts) *done* runs at once. *reset* forgets the
 * offset and sizes: call it when the ScrollView is remounted (a Modal reopening starts at the top).
 */
export function useRevealField(scrollRef: { current: ScrollView | null }) {
  const offset = useRef(0);
  const viewH = useRef<number | undefined>(undefined);
  const contentH = useRef<number | undefined>(undefined);
  const pending = useRef<(() => void) | null>(null);
  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    offset.current = event.nativeEvent.contentOffset.y;
    pending.current?.();
  }, []);
  const onLayout = useCallback((event: LayoutChangeEvent) => { viewH.current = event.nativeEvent.layout.height; }, []);
  const onContentSizeChange = useCallback((_w: number, h: number) => { contentH.current = h; }, []);
  const reset = useCallback(() => {
    offset.current = 0;
    viewH.current = undefined;
    contentH.current = undefined;
  }, []);
  const reveal = useCallback<RevealField>((field, done) => {
    const scroll = scrollRef.current as unknown as { measureInWindow?: View["measureInWindow"]; scrollTo?: ScrollView["scrollTo"] } | null;
    if (!field?.measureInWindow || !scroll?.measureInWindow || !scroll.scrollTo) return done();
    field.measureInWindow((_x, fieldY) => {
      scroll.measureInWindow!((_sx, scrollY) => {
        let y = Math.max(0, offset.current + (fieldY - scrollY) - spacing.sm);
        if (viewH.current !== undefined && contentH.current !== undefined) y = Math.min(y, Math.max(0, contentH.current - viewH.current));
        let finished = false;
        let timer: ReturnType<typeof setTimeout>;
        const finish = () => {
          if (finished) return;
          finished = true;
          clearTimeout(timer);
          pending.current = null;
          done();
        };
        pending.current = () => { pending.current = null; requestAnimationFrame(finish); };
        timer = setTimeout(finish, SCROLL_FALLBACK_MS);
        scroll.scrollTo!({ y, animated: false });
      });
    });
  }, [scrollRef]);
  return { reveal, onScroll, onLayout, onContentSizeChange, reset };
}
