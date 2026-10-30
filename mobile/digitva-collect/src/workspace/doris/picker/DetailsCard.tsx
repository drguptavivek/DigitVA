import { View } from "react-native";

import { Alert, Body, Button, Label, Muted, gap } from "../ui";
import { parseDorisDetails, type DorisDetails } from "../guidance";
import type { PickerItem } from "./expression";
import { LoadView, Panel } from "./Panel";
import { useLoad, type Post } from "./transport";

function Section({ title, children }: { title: string; children: string | string[] }) {
  return (
    <View style={{ gap: gap.xs }}>
      <Label>{title}</Label>
      {(Array.isArray(children) ? children : [children]).map((line, index) => <Body key={`${index}:${line}`}>{Array.isArray(children) ? `• ${line}` : line}</Body>)}
    </View>
  );
}

function DetailsBody({ details }: { details: DorisDetails }) {
  const empty = !details.coding_note && !details.definition && !details.fully_specified_name && !details.inclusions.length && !details.exclusions.length;
  return (
    <View style={{ gap: gap.sm }}>
      {details.coding_note ? <Alert variant="warning"><Body>☰ Coding note: {details.coding_note}</Body></Alert> : null}
      {details.definition ? <Section title="Definition">{details.definition}</Section> : null}
      {details.fully_specified_name ? <Section title="Fully specified name">{details.fully_specified_name}</Section> : null}
      {details.inclusions.length ? <Section title="Includes">{details.inclusions}</Section> : null}
      {details.exclusions.length ? <Section title="Exclusions">{details.exclusions.map((term) => term.title + (term.code ? ` (${term.code})` : ""))}</Section> : null}
      {empty ? <Muted>No additional WHO details were returned.</Muted> : null}
      {details.truncated ? <Muted>More WHO details exist than are shown here.</Muted> : null}
    </View>
  );
}

/**
 * WHO definition, coding note, inclusions and exclusions of a code (the `details` guidance route), and the way to its
 * hierarchy: the hierarchy is a path to a code, so it opens from the code's own card, not from every result row.
 */
export function DetailsCard({ item, post, onHierarchy, onClose }: { item: PickerItem; post: Post; onHierarchy: () => void; onClose: () => void }) {
  const state = useLoad(async () => parseDorisDetails(await post("details", { code: item.code })), [item.code]);
  return (
    <Panel testID="picker-details" title={`${item.code} — ${item.title}`} onClose={onClose}>
      <LoadView state={state} loading="Loading WHO code details…">{(details) => <DetailsBody details={details} />}</LoadView>
      <View style={{ flexDirection: "row" }}>
        <Button label="Hierarchy" variant="outline" size="sm" accessibilityLabel={`Hierarchy of ${item.code}`} onPress={onHierarchy} />
      </View>
    </Panel>
  );
}
