/**
 * The phone workspace's page scroller, so a panel can bring one of its parts into view (after Step 1 is
 * saved, the SmartVA card under the Step 1 causes). Null outside the native layout (web, tests).
 */
import { createContext, useContext, type RefObject } from "react";
import type { ScrollView, View } from "react-native";

export const WorkspaceScrollContext = createContext<RefObject<ScrollView | null> | null>(null);

/** Scroll the page so `target` sits a little below the top; no-op without a scroller. */
export function useScrollIntoView() {
  const scroller = useContext(WorkspaceScrollContext);
  return (target: View | null) => {
    const view = scroller?.current as (ScrollView & { getInnerViewRef?: () => unknown }) | null | undefined;
    const inner = view?.getInnerViewRef?.() ?? view?.getInnerViewNode();
    if (!target || !inner) return;
    target.measureLayout(inner as never, (_x, y) => scroller?.current?.scrollTo({ y: Math.max(0, y - 8), animated: true }), () => {});
  };
}
