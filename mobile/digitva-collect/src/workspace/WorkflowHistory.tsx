import { Text, View } from "react-native";

import { styles } from "../ui";
import type { WorkflowEvents } from "./contracts";

/** Shows the newest 50 server-provided events for one authorized case view. */
export function WorkflowHistory({ events }: { events: WorkflowEvents | null }) {
  if (!events) return null;
  const recent = events.events.slice(-50);
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Workflow history</Text>
      {events.events.length > recent.length ? <Text style={styles.muted}>Showing the {recent.length} most recent of {events.events.length} events.</Text> : null}
      {recent.map((event) => (
        <View key={event.event_id}>
          <Text style={styles.text}>{event.previous_state ?? "Start"} → {event.current_state}</Text>
          <Text style={styles.muted}>{event.event_created_at}{event.actor_role ? ` · ${event.actor_role}` : ""}</Text>
          {event.transition_reason ? <Text style={styles.text}>{event.transition_reason}</Text> : null}
        </View>
      ))}
    </View>
  );
}
