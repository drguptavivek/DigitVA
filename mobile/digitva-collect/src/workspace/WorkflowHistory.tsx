import { Platform, StyleSheet, Text, View } from "react-native";

import { Button, useUiStyles } from "../ui";
import { formatWhen } from "../ui/interviewRows";
import { useTheme } from "../theme";
import { SkeletonCards, StateView } from "../ui/StateView";

import type { WorkflowEvents } from "./contracts";
import { humanizeKey } from "./humanizeKey";

/** Shows one bounded, newest-first page of events for an authorized case view. */
export function WorkflowHistory({
  events,
  cursor,
  loading,
  error,
  onOlder,
  onLatest,
  onRetry,
}: {
  events: WorkflowEvents | null;
  cursor: string | null;
  loading: boolean;
  error: string;
  onOlder: () => void;
  onLatest: () => void;
  onRetry: () => void;
}) {
  const styles = useUiStyles();
  const { ui } = useTheme();
  const phone = Platform.OS !== "web";
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Workflow history</Text>
      {loading && !events ? <SkeletonCards count={2} /> : null}
      {error ? <StateView kind="error" title={error} actionLabel="Retry workflow history" onAction={loading ? undefined : onRetry} /> : null}
      {events?.events.length === 0 ? <StateView title="No workflow events." /> : null}
      {events?.events.map((event) => phone ? (
        // Phone (round-6 C4): a two-line row, humanised states and timestamp, the reason in muted below.
        <View key={event.event_id} style={{ minHeight: 56, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: ui.border }}>
          <Text style={styles.text}>{event.previous_state ? humanizeKey(event.previous_state) : "Start"} → {humanizeKey(event.current_state)}</Text>
          <Text style={styles.muted}>{formatWhen(event.event_created_at)}{event.actor_role ? ` · ${humanizeKey(event.actor_role)}` : ""}</Text>
          {event.transition_reason ? <Text style={styles.muted}>{humanizeKey(event.transition_reason)}</Text> : null}
        </View>
      ) : (
        <View key={event.event_id}>
          <Text style={styles.text}>{event.previous_state ?? "Start"} → {event.current_state}</Text>
          <Text style={styles.muted}>{event.event_created_at}{event.actor_role ? ` · ${event.actor_role}` : ""}</Text>
          {event.transition_reason ? <Text style={styles.text}>{event.transition_reason}</Text> : null}
        </View>
      ))}
      {cursor !== null ? <Button label="Latest events" kind="secondary" onPress={onLatest} disabled={loading} /> : null}
      {events?.next_cursor ? <Button label="Load older events" kind="secondary" onPress={onOlder} disabled={loading} /> : null}
      {loading && events ? <Text style={styles.muted}>Loading workflow history…</Text> : null}
    </View>
  );
}
