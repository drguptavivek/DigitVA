import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type ViewProps } from "react-native";

import { t } from "../i18n";
import type { BelowUnit, OrgPerson, OrgProject, UnitPeople, UnitRole } from "../organization/api";
import { radius, spacing, useTheme } from "../theme";
import { useUiStyles } from "../ui";
import { Chevron, FoldButton } from "./Chevron";
import { roleLabelKey } from "./roleHome";

/** Role values as plain labels, joined: "Coder, Reviewer". */
export function roleNames(roles: string[]): string {
  return roles.map((role) => t(roleLabelKey(role))).join(", ");
}

/** A unit grant's roles with their cadre: "Coder (Medical Officer), Reviewer". */
function unitRoleNames(roles: UnitRole[]): string {
  return roles.map(({ role, cadre }) => (cadre ? t("orgRoleCadre", { role: t(roleLabelKey(role)), cadre }) : t(roleLabelKey(role)))).join(", ");
}

/** A role reaching a node from above: from a unit grant (`unit`) or a project grant (`unit` null). */
type Via = { roles: string; unit: string | null };
const viaText = ({ roles, unit }: Via) => (unit ? t("orgViaUnit", { roles, unit }) : t("orgViaProject", { roles }));

/** A Below unit opened in place: its people and child units, or why they did not load. */
export type OpenedUnit = { loading: boolean; error: string; detail?: UnitPeople };

/** Half the connector gutter: children sit this far right of the parent's edge, then one more step for the line. */
const GUTTER = spacing.xs;
/** The horizontal stub meets the vertical line at the middle of a node's first row. */
const STUB_TOP = 22;

/** Level name -> chart family index, by first appearance; Node reads it so one unit type keeps one colour. */
const LevelTints = createContext<Map<string, number>>(new Map());

/** Indexes each distinct level name in order of first appearance (blank names get none). */
export function levelTints(names: string[]): Map<string, number> {
  const index = new Map<string, number>();
  for (const name of names) if (name && !index.has(name)) index.set(name, index.size);
  return index;
}
/** Connector thickness: thick and high-contrast so the nesting reads at a glance. */
const LINE = 2;

const layout = StyleSheet.create({
  node: { borderWidth: 1, borderRadius: radius.md, paddingVertical: 6, paddingHorizontal: spacing.xs, gap: 2 },
  header: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.xs, minHeight: 32 },
  badge: { borderRadius: radius.md, paddingHorizontal: spacing.xs, paddingVertical: 2, overflow: "hidden" },
  badgeText: { fontSize: 12, fontWeight: "600" },
  children: { marginLeft: GUTTER, paddingLeft: GUTTER + LINE, gap: spacing.xxs, marginTop: spacing.xxs },
  // One vertical segment per child: it runs to the next sibling, and on the last child stops at its own stub (an elbow), so no line trails below.
  rail: { position: "absolute", left: -GUTTER - LINE, top: -spacing.xxs, borderLeftWidth: LINE },
  stub: { position: "absolute", left: -GUTTER - LINE, top: STUB_TOP, width: GUTTER + LINE, borderTopWidth: LINE },
  // 32px tall plus 6px hitSlop above and below = a 44px touch target without growing the card.
  branch: { alignSelf: "flex-start", minHeight: 32, flexDirection: "row", alignItems: "center", gap: spacing.xxs, paddingHorizontal: spacing.xs },
  branchText: { fontSize: 14 },
  top: { flexDirection: "row", alignItems: "flex-start", gap: spacing.xs },
  toggle: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 32 },
  // 44x44 target; the negative margin keeps the 32px row (node padding is 6) from growing.
  chevron: { width: 44, height: 44, marginVertical: -6, alignItems: "center", justifyContent: "center", borderRadius: radius.md },
  count: { minWidth: 24, alignItems: "center", borderWidth: 1, borderRadius: 9999, paddingHorizontal: spacing.xs, paddingVertical: 2 },
  countText: { fontSize: 12 },
  // "fixed" is web-only: the flyout covers the viewport, not the card it is rendered inside.
  layer: { position: "fixed" as unknown as "absolute", left: 0, right: 0, top: 0, bottom: 0, zIndex: 50, flexDirection: "row", justifyContent: "flex-end" },
  scrim: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  flyout: { width: "88%", maxWidth: 360, height: "100%", padding: spacing.md, borderLeftWidth: 1, gap: spacing.sm, zIndex: 11 },
  flyoutHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  close: { minHeight: 44, minWidth: 44, alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.sm },
  wrap: { flexShrink: 1 },
  unitName: { fontSize: 16, fontWeight: "600" },
  person: { fontSize: 14, lineHeight: 18 },
  roles: { fontSize: 12, lineHeight: 16 },
});

/** Name with the member's roles beneath, in a smaller type than the unit name: the API never sends contact details, and cadres are not shown. */
function PeopleList({ people }: { people: OrgPerson[] }) {
  const styles = useUiStyles();
  if (!people.length) return <Text style={styles.muted}>{t("orgNoPeople")}</Text>;
  return (
    <>
      {people.map((person, index) => (
        <View key={`${index}-${person.name}`}>
          <Text style={[styles.muted, layout.person]}>{person.name}</Text>
          {person.roles?.length ? <Text style={[styles.muted, layout.roles]}>{person.roles.join(" · ")}</Text> : null}
        </View>
      ))}
    </>
  );
}

/** What the single flyout shows: static units carry their people, below units read them from `opened` once loaded. */
type FlyoutTarget = { id: string; title: string; people?: OrgPerson[] };
type ShowPeople = () => void;

const dialogProps = { role: "dialog", "aria-modal": true } as unknown as ViewProps;

/** Right-hand overlay listing a unit's member names. One instance serves the whole tree. */
function PeopleFlyout({ target, opened, onClose }: { target: FlyoutTarget; opened: Record<string, OpenedUnit>; onClose: () => void }) {
  const styles = useUiStyles();
  const { ui } = useTheme();
  const state = target.people ? undefined : opened[target.id];
  const people = target.people ?? state?.detail?.people;

  // Escape closes, Tab stays on the only control; focus enters on open and returns to the badge on close.
  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return undefined;
    document.getElementById("org-people-close")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        event.preventDefault();
        document.getElementById("org-people-close")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.getElementById(`org-people-${target.id}`)?.focus();
    };
  }, [onClose, target.id]);

  return (
    <View style={layout.layer} accessibilityViewIsModal>
      <Pressable accessibilityRole="button" accessibilityLabel={t("orgClose")} onPress={onClose} style={layout.scrim} />
      <View {...dialogProps} accessibilityLabel={target.title} style={[layout.flyout, { backgroundColor: ui.card, borderLeftColor: ui.border }]}>
        <View style={layout.flyoutHeader}>
          <Text style={[styles.text, layout.unitName, layout.wrap]}>{target.title}</Text>
          <Pressable nativeID="org-people-close" accessibilityRole="button" accessibilityLabel={t("orgClose")} onPress={onClose} style={[layout.close, { borderColor: ui.border }]}>
            <Text style={styles.text}>{t("orgClose")}</Text>
          </Pressable>
        </View>
        {people ? (
          <PeopleList people={people} />
        ) : state?.error ? (
          <Text style={styles.error} accessibilityRole="alert">{state.error}</Text>
        ) : (
          <View style={layout.header}>
            <ActivityIndicator />
            <Text style={styles.muted}>{t("loading")}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

/** Indented, ruled group of child nodes; each child gets a short horizontal stub off the vertical line. */
function Children({ children }: { children: ReactNode[] }) {
  const { ui } = useTheme();
  const items = children.filter(Boolean);
  if (!items.length) return null;
  return (
    <View role="group" style={layout.children}>
      {items.map((child, index) => (
        <View key={index} style={layout.wrap}>
          <View
            style={[
              layout.rail,
              { borderLeftColor: ui.mutedForeground },
              index === items.length - 1 ? { height: STUB_TOP + spacing.xxs } : { bottom: -spacing.xxs },
            ]}
          />
          <View style={[layout.stub, { borderTopColor: ui.mutedForeground }]} />
          {child}
        </View>
      ))}
    </View>
  );
}

type NodeProps = {
  /** Unit id: the people badge is findable by it, so focus can return there when the flyout closes. */
  id: string;
  title: string;
  unitName: string;
  mine?: boolean;
  /** The user's own roles here (unit grants), already labelled. */
  myRoles?: string;
  /** Roles reaching this node from a unit above or the project; none and no own roles mutes the node. */
  via?: Via[];
  count: number;
  onShowPeople: ShowPeople;
  /** Present on lazily opened nodes. */
  toggle?: { arrow?: boolean; unit: string; expanded: boolean; loading?: boolean; error?: string; onPress: () => void };
  /** Unit type: cards of one level share a tint. */
  level?: string;
  children?: ReactNode[];
};

function Node({ id, title, unitName, mine, myRoles, via = [], level, count, onShowPeople, toggle, children = [] }: NodeProps) {
  const styles = useUiStyles();
  const { ui } = useTheme();
  const tints = useContext(LevelTints);
  const slot = level !== undefined ? tints.get(level) : undefined;
  const family = slot === undefined ? undefined : ui.chart[slot % ui.chart.length];
  // The branch (units nested under this card) folds on its own arrow; people live in the flyout.
  const [branchOpen, setBranchOpen] = useState(true);
  const kids = children.filter(Boolean);
  // The arrow only exists where there are sub-units to open; the badge alone loads a leaf unit's names.
  const foldable = Boolean(toggle) && toggle?.arrow !== false;
  const expanded = toggle?.expanded;
  const label = toggle ? (toggle.expanded ? t("orgCloseUnit", { unit: toggle.unit }) : t("orgOpenUnit", { unit: toggle.unit })) : title;
  // No role here, own or inherited: the node is context only, so it reads muted.
  const roleless = !mine && !via.length;
  const headerContent = (
    <>
      <View style={[layout.header, layout.wrap, { flex: 1 }]}>
        <Text style={[styles.text, layout.unitName, layout.wrap, roleless ? { color: ui.mutedForeground } : family && { color: family.foreground }]}>{title}</Text>
        {mine ? (
          <View style={[layout.badge, layout.wrap, { backgroundColor: ui.primary }]} accessibilityLabel={t("orgYouAreHere")}>
            <Text style={[layout.badgeText, { color: ui.primaryForeground }]}>{myRoles ? t("orgYouRoles", { roles: myRoles }) : t("orgYou")}</Text>
          </View>
        ) : null}
      </View>
      {toggle?.loading ? <ActivityIndicator /> : null}
    </>
  );
  return (
    <View role="treeitem" aria-expanded={foldable ? expanded : undefined} aria-selected={mine || undefined}>
      <View
        style={[
          layout.node,
          { borderColor: mine ? ui.primary : ui.border, backgroundColor: family?.tint ?? ui.secondary },
          family && { borderLeftWidth: 3, borderLeftColor: mine ? ui.primary : family.bar },
        ]}
      >
        <View style={layout.top}>
          {foldable ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={label}
              accessibilityState={{ expanded, busy: toggle?.loading }}
              onPress={toggle?.onPress}
              style={[layout.toggle, layout.wrap, { flex: 1 }]}
            >
              {headerContent}
            </Pressable>
          ) : (
            <View style={[layout.header, layout.wrap, { flex: 1 }]}>{headerContent}</View>
          )}
          <Pressable
            nativeID={`org-people-${id}`}
            accessibilityRole="button"
            accessibilityLabel={`${t("orgShowMembers", { unit: unitName })} · ${t("orgPeopleCount", { count })}`}
            hitSlop={12}
            onPress={onShowPeople}
            style={[layout.count, { borderColor: ui.border }]}
          >
            <Text style={[layout.countText, { color: ui.mutedForeground }]}>{count}</Text>
          </Pressable>
          {foldable ? (
            <FoldButton label={label} expanded={Boolean(expanded)} onPress={toggle?.onPress} style={layout.chevron}>
              <Chevron expanded={Boolean(expanded)} />
            </FoldButton>
          ) : null}
        </View>
        {via.map((entry, index) => (
          <Text key={index} style={[layout.roles, { color: ui.mutedForeground }]}>{viaText(entry)}</Text>
        ))}
        {kids.length ? (
          <FoldButton
            label={branchOpen ? t("orgFoldBranch", { unit: title }) : t("orgUnfoldBranch", { unit: title })}
            expanded={branchOpen}
            hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
            onPress={() => setBranchOpen((open) => !open)}
            style={layout.branch}
          >
            <Chevron expanded={branchOpen} />
            <Text style={[layout.branchText, { color: ui.foreground }]} aria-hidden>{t("orgBranchUnits", { count: kids.length })}</Text>
          </FoldButton>
        ) : null}
        {toggle?.error ? <Text style={styles.error} accessibilityRole="alert">{toggle.error}</Text> : null}
      </View>
      {branchOpen ? <Children>{kids}</Children> : null}
    </View>
  );
}

type Toggle = (orgUnitId: string) => void;

function BelowNode({ unit, via, opened, onToggle, onShow }: { unit: BelowUnit; via: Via[]; opened: Record<string, OpenedUnit>; onToggle: Toggle; onShow: (target: FlyoutTarget) => void }) {
  const state = opened[unit.org_unit_id];
  // A unit whose load failed is not open: its button offers a retry.
  const expanded = Boolean(state && !state.error);
  const title = t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name });
  return (
    <Node
      id={unit.org_unit_id}
      title={title}
      unitName={unit.unit_name}
      level={unit.level_name}
      via={via}
      count={unit.people_count}
      // Load the names on first look (or retry a failure); never toggle an already open or loading unit shut.
      onShowPeople={() => {
        if (!state || state.error) onToggle(unit.org_unit_id);
        onShow({ id: unit.org_unit_id, title });
      }}
      toggle={{ arrow: unit.has_children, unit: unit.unit_name, expanded, loading: state?.loading, error: state?.error, onPress: () => onToggle(unit.org_unit_id) }}
    >
      {(state?.detail?.children ?? []).map((child) => (
        <BelowNode key={child.org_unit_id} unit={child} via={via} opened={opened} onToggle={onToggle} onShow={onShow} />
      ))}
    </Node>
  );
}

/**
 * One project as a tree, nested by real parentage: ancestors root-first, the user's own units highlighted, then the
 * units below, which open lazily. A node hangs under the node whose id is its `parent_org_unit_id`; a node whose
 * parent is not in the reply is a root. An older server sends no parent ids: the flat layout is used then, with the
 * below units under the user's first own unit.
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
  const [flyout, setFlyout] = useState<FlyoutTarget | null>(null);
  const close = useCallback(() => setFlyout(null), []);
  const tints = levelTints(levelNames(project, opened));
  const tree = (
    <LevelTints.Provider value={tints}>
      <OrgNodes project={project} opened={opened} onToggle={onToggle} onShow={setFlyout} />
    </LevelTints.Provider>
  );
  return (
    <>
      {tree}
      {flyout ? <PeopleFlyout target={flyout} opened={opened} onClose={close} /> : null}
    </>
  );
}

/** Level names root-down: above, my level, below, then lazily opened children (first appearance fixes the colour). */
function levelNames(project: OrgProject, opened: Record<string, OpenedUnit>): string[] {
  const names = [...project.above.map((u) => u.level_name), ...project.my_units.map((u) => u.level_name)];
  const pending = [...project.below];
  while (pending.length) {
    const unit = pending.shift()!;
    names.push(unit.level_name);
    pending.push(...(opened[unit.org_unit_id]?.detail?.children ?? []));
  }
  return names;
}

type NodesProps = { project: OrgProject; opened: Record<string, OpenedUnit>; onToggle: Toggle; onShow: (target: FlyoutTarget) => void };

function OrgNodes({ project, opened, onToggle, onShow }: NodesProps) {
  const mine = new Map(project.my_units.map((unit) => [unit.org_unit_id, unit]));
  const ownTitle = (unit: { org_unit_id: string; unit_name: string }) => {
    const own = mine.get(unit.org_unit_id);
    return own ? t("orgUnitLine", { unit: unit.unit_name, level: own.level_name }) : unit.unit_name;
  };
  // A non-own unit at my level shares the user's level; own units carry their own.
  const levelOf = (id: string) => mine.get(id)?.level_name ?? project.my_units[0]?.level_name;
  const ownRoles = (id: string) => mine.get(id)?.roles ?? [];
  const entries = [
    ...project.above.map((unit) => ({ unit, render: (kids: ReactNode[], via: Via[]) => (
      <Node key={unit.org_unit_id} id={unit.org_unit_id} title={t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name })} unitName={unit.unit_name} level={unit.level_name} via={via} count={unit.people.length} onShowPeople={() => onShow({ id: unit.org_unit_id, title: t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name }), people: unit.people })}>
        {kids}
      </Node>
    ) })),
    ...project.my_level.map((unit) => ({ unit, render: (kids: ReactNode[], via: Via[]) => (
      <Node key={unit.org_unit_id} id={unit.org_unit_id} title={ownTitle(unit)} unitName={unit.unit_name} level={levelOf(unit.org_unit_id)} mine={mine.has(unit.org_unit_id)} myRoles={unitRoleNames(ownRoles(unit.org_unit_id))} via={via} count={unit.people.length} onShowPeople={() => onShow({ id: unit.org_unit_id, title: ownTitle(unit), people: unit.people })}>
        {kids}
      </Node>
    ) })),
    // A below unit's parent is an own unit (or none), so it never has in-reply children: BelowNode opens its own lazily.
    ...project.below.map((unit) => ({ unit, render: (_kids: ReactNode[], via: Via[]) => <BelowNode key={unit.org_unit_id} unit={unit} via={via} opened={opened} onToggle={onToggle} onShow={onShow} /> })),
  ];
  const hasParents = entries.every(({ unit }) => unit.parent_org_unit_id !== undefined);
  if (!hasParents) return <FlatTree project={project} opened={opened} onToggle={onToggle} onShow={onShow} />;

  const byId = new Map(entries.map((entry) => [entry.unit.org_unit_id, entry]));
  const kidsOf = new Map<string, typeof entries>();
  const roots: typeof entries = [];
  for (const entry of entries) {
    const parentId = entry.unit.parent_org_unit_id;
    if (parentId && parentId !== entry.unit.org_unit_id && byId.has(parentId)) {
      kidsOf.set(parentId, [...(kidsOf.get(parentId) ?? []), entry]);
    } else {
      roots.push(entry);
    }
  }
  // A unit grant covers its subtree: each node passes its own roles down as "via <unit>", on top of what reached it.
  const build = (entry: (typeof entries)[number], via: Via[]): ReactNode => {
    const own = ownRoles(entry.unit.org_unit_id);
    const below = own.length ? [...via, { roles: roleNames(own.map((r) => r.role)), unit: entry.unit.unit_name }] : via;
    return entry.render((kidsOf.get(entry.unit.org_unit_id) ?? []).map((kid) => build(kid, below)), via);
  };
  const projectRoles = project.my_positions?.project_roles ?? [];
  const rootVia: Via[] = projectRoles.length ? [{ roles: roleNames(projectRoles), unit: null }] : [];
  return <View role="tree" style={{ gap: spacing.xs }}>{roots.map((root) => build(root, rootVia))}</View>;
}

/** Older-server layout, without parent ids: below units hang under the user's first own unit (or first level unit). */
function FlatTree({ project, opened, onToggle, onShow }: NodesProps) {
  const mine = new Map(project.my_units.map((unit) => [unit.org_unit_id, unit]));
  const hostId = (project.my_level.find((unit) => mine.has(unit.org_unit_id)) ?? project.my_level[0])?.org_unit_id;
  const below = project.below.map((unit) => <BelowNode key={unit.org_unit_id} unit={unit} via={[]} opened={opened} onToggle={onToggle} onShow={onShow} />);

  const levelNodes = project.my_level.map((unit) => {
    const own = mine.get(unit.org_unit_id);
    const title = own ? t("orgUnitLine", { unit: unit.unit_name, level: own.level_name }) : unit.unit_name;
    return (
      <Node
        key={unit.org_unit_id}
        id={unit.org_unit_id}
        title={title}
        unitName={unit.unit_name}
        mine={Boolean(own)}
        level={own?.level_name ?? project.my_units[0]?.level_name}
        count={unit.people.length}
        onShowPeople={() => onShow({ id: unit.org_unit_id, title, people: unit.people })}
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
        id={unit.org_unit_id}
        title={t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name })}
        unitName={unit.unit_name}
        level={unit.level_name}
        count={unit.people.length}
        onShowPeople={() => onShow({ id: unit.org_unit_id, title: t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name }), people: unit.people })}
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
