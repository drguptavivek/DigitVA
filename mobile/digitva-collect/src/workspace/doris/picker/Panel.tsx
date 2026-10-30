import { useRef, type ReactNode } from "react";
import { View } from "react-native";

import { Alert, Button, Card, Muted, SectionTitle, gap } from "../ui";
import type { Loaded } from "./transport";

/** A picker card: heading, a close button, then its content. */
export function Panel({ title, closeLabel = "Close", onClose, testID, children }: { title: string; closeLabel?: string; onClose: () => void; testID: string; children: ReactNode }) {
  return (
    <Card testID={testID} style={{ gap: gap.sm, padding: gap.md }}>
      <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: gap.sm }}>
        <SectionTitle>{title}</SectionTitle>
        <Button label={closeLabel} variant="outline" size="sm" accessibilityLabel={`${closeLabel} ${title}`} onPress={onClose} />
      </View>
      {children}
    </Card>
  );
}

/** Loading text, the error as an alert, or the loaded content. */
export function LoadView<T>({ state, loading, children }: { state: Loaded<T>; loading: string; children: (data: T) => ReactNode }) {
  if (state.status === "loading") return <Muted>{loading}</Muted>;
  if (state.status === "error") return <Alert variant="destructive">{state.message}</Alert>;
  return <>{children(state.data)}</>;
}

/**
 * Wraps a card that sits in the results scroller. `scrollTo` (given only when the coder opened the card) is called
 * once, with the card's y in the scroller, as soon as it is laid out; a card the picker opened itself passes none and
 * leaves the list where it is. `onBack` adds "Back to results", which returns to the row that opened the card.
 */
export function Reveal({ scrollTo, onBack, children }: { scrollTo: ((y: number) => void) | null; onBack: (() => void) | null; children: ReactNode }) {
  const done = useRef(false);
  return (
    <View
      onLayout={(event) => {
        if (!scrollTo || done.current) return;
        done.current = true;
        scrollTo(event.nativeEvent.layout.y);
      }}
      style={{ gap: gap.xs, marginTop: gap.xs }}
    >
      {onBack ? <Button label="← Back to results" variant="ghost" size="sm" accessibilityLabel="Back to results" onPress={onBack} style={{ alignSelf: "flex-start" }} /> : null}
      {children}
    </View>
  );
}
