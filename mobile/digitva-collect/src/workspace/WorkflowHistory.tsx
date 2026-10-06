import { Text, View } from "react-native";

import { Button, styles } from "../ui";

import type { WorkflowEvents } from "./contracts";

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
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Workflow history</Text>
      {loading && !events ? <Text style={styles.muted}>Loading workflow history…</Text> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {error ? <Button label="Retry workflow history" onPress={onRetry} disabled={loading} /> : null}
      {events?.events.length === 0 ? <Text style={styles.muted}>No workflow events.</Text> : null}
      {events?.events.map((event) => (
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
