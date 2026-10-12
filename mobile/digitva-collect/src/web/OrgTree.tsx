import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import { t } from "../i18n";
import type { BelowUnit, OrgPerson, OrgProject, UnitPeople } from "../organization/api";
import { radius, spacing, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";

/** A Below unit opened in place: its people and child units, or why they did not load. */
export type OpenedUnit = { loading: boolean; error: string; detail?: UnitPeople };

/** Half the connector gutter: children sit this far right of the parent's edge, then one more step for the line. */
const GUTTER = spacing.sm;
/** The horizontal stub meets the vertical line at the middle of a node's first row. */
const STUB_TOP = 22;

const layout = StyleSheet.create({
  node: { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, gap: spacing.xxs },
  header: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.xs },
  badge: { borderRadius: radius.md, paddingHorizontal: spacing.xs, paddingVertical: 2, overflow: "hidden" },
  badgeText: { fontSize: 12, fontWeight: "600" },
  children: { marginLeft: GUTTER, paddingLeft: GUTTER, borderLeftWidth: 1, gap: spacing.xs, marginTop: spacing.xs },
  stub: { position: "absolute", left: -GUTTER, top: STUB_TOP, width: GUTTER, borderTopWidth: 1 },
  wrap: { flexShrink: 1 },
});

/** Name and cadre only: the API never sends contact details, and nothing else is shown. */
function PeopleList({ people }: { people: OrgPerson[] }) {
  const styles = useUiStyles();
  if (!people.length) return <Text style={styles.muted}>{t("orgNoPeople")}</Text>;
  return (
    <>
      {people.map((person, index) => (
        <Text key={`${index}-${person.name}`} style={styles.text}>
          {t("orgPersonLine", { name: person.name, cadre: person.cadre })}
        </Text>
      ))}
    </>
  );
}

/** Indented, ruled group of child nodes; each child gets a short horizontal stub off the vertical line. */
function Children({ children }: { children: ReactNode[] }) {
  const { ui } = useTheme();
  const items = children.filter(Boolean);
  if (!items.length) return null;
  return (
    <View role="group" style={[layout.children, { borderLeftColor: ui.border }]}>
      {items.map((child, index) => (
        <View key={index} style={layout.wrap}>
          <View style={[layout.stub, { borderTopColor: ui.border }]} />
          {child}
        </View>
      ))}
    </View>
  );
}

type NodeProps = {
  title: string;
  mine?: boolean;
  cadres?: string[];
  count?: number;
  /** Present on lazily opened nodes. */
  toggle?: { unit: string; expanded: boolean; loading?: boolean; error?: string; onPress: () => void };
  /** Shown inside the node card (people); `children` hang below it on the connector. */
  body?: ReactNode;
  children?: ReactNode[];
};

function Node({ title, mine, cadres, count, toggle, body, children = [] }: NodeProps) {
  const styles = useUiStyles();
  const { ui } = useTheme();
  const kids = children.filter(Boolean);
  return (
    <View role="treeitem" aria-expanded={toggle ? toggle.expanded : kids.length ? true : undefined} aria-selected={mine || undefined}>
      <View
        style={[layout.node, { borderColor: mine ? ui.primary : ui.border, backgroundColor: mine ? ui.accent : ui.card }]}
      >
        <View style={layout.header}>
          <Text style={[styles.text, layout.wrap]}>{title}</Text>
          {mine ? (
            <View style={[layout.badge, { backgroundColor: ui.primary }]} accessibilityLabel={t("orgYouAreHere")}>
              <Text style={[layout.badgeText, { color: ui.primaryForeground }]}>{t("orgYou")}</Text>
            </View>
          ) : null}
        </View>
        {cadres?.length ? <Text style={styles.muted}>{t("orgCadres", { cadres: cadres.join(", ") })}</Text> : null}
        {count !== undefined ? <Text style={styles.muted}>{t("orgPeopleCount", { count })}</Text> : null}
        {toggle ? (
          <Button
            kind="secondary"
            label={toggle.expanded ? t("orgClose") : t("orgOpen")}
            accessibilityLabel={toggle.expanded ? t("orgCloseUnit", { unit: toggle.unit }) : t("orgOpenUnit", { unit: toggle.unit })}
            expanded={toggle.expanded}
            loading={toggle.loading}
            onPress={toggle.onPress}
          />
        ) : null}
        {toggle?.error ? <Text style={styles.error} accessibilityRole="alert">{toggle.error}</Text> : null}
        {body}
      </View>
      <Children>{kids}</Children>
    </View>
  );
}

type Toggle = (orgUnitId: string) => void;

function BelowNode({ unit, opened, onToggle }: { unit: BelowUnit; opened: Record<string, OpenedUnit>; onToggle: Toggle }) {
  const state = opened[unit.org_unit_id];
  // A unit whose load failed is not open: its button offers a retry.
  const expanded = Boolean(state && !state.error);
  return (
    <Node
      title={t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name })}
      count={unit.people_count}
      toggle={{ unit: unit.unit_name, expanded, loading: state?.loading, error: state?.error, onPress: () => onToggle(unit.org_unit_id) }}
      body={state?.detail ? <PeopleList people={state.detail.people} /> : null}
    >
      {(state?.detail?.children ?? []).map((child) => (
        <BelowNode key={child.org_unit_id} unit={child} opened={opened} onToggle={onToggle} />
      ))}
    </Node>
  );
}

/**
 * One project as a tree: ancestors root-first, the user's level (their own units highlighted), then the units below,
 * which open lazily. Below units hang under the user's first own unit (or the first unit of their level).
 */
export function OrgTree({
  project,
  opened,
  onToggle,
}: {
  project: OrgProject;
  opened: Record<string, OpenedUnit>;
  onToggle: Toggle;
}) {
  const mine = new Map(project.my_units.map((unit) => [unit.org_unit_id, unit]));
  const hostId = (project.my_level.find((unit) => mine.has(unit.org_unit_id)) ?? project.my_level[0])?.org_unit_id;
  const below = project.below.map((unit) => <BelowNode key={unit.org_unit_id} unit={unit} opened={opened} onToggle={onToggle} />);

  const levelNodes = project.my_level.map((unit) => {
    const own = mine.get(unit.org_unit_id);
    return (
      <Node
        key={unit.org_unit_id}
        title={own ? t("orgUnitLine", { unit: unit.unit_name, level: own.level_name }) : unit.unit_name}
        mine={Boolean(own)}
        cadres={own?.cadres}
        body={<PeopleList people={unit.people} />}
      >
        {unit.org_unit_id === hostId ? below : []}
      </Node>
    );
  });
  const tail = hostId ? levelNodes : [...levelNodes, ...below];

  // Fold the root-first ancestors into one nested chain around the level nodes.
  const root = project.above.reduceRight<ReactNode[]>(
    (inner, unit) => [
      <Node
        key={unit.org_unit_id}
        title={t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name })}
        body={<PeopleList people={unit.people} />}
      >
        {inner}
      </Node>,
    ],
    tail,
  );
  return <View role="tree" style={{ gap: spacing.xs }}>{root}</View>;
}

/** Drops a closed unit and every unit opened beneath it, so reopening it shows its children collapsed. */
export function dropUnitAndBelow(current: Record<string, OpenedUnit>, orgUnitId: string): Record<string, OpenedUnit> {
  const next = { ...current };
  const pending = [orgUnitId];
  while (pending.length) {
    const id = pending.pop()!;
    const detail = next[id]?.detail;
    delete next[id];
    for (const child of detail?.children ?? []) pending.push(child.org_unit_id);
  }
  return next;
}
