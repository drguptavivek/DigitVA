/**
 * The views of the interviewer's /worklist route: Home (dashboard), Interviews (searchable list), the site/unit
 * picker and the project chooser. Presentational: worklist.tsx owns the data, sync and refresh logic and passes
 * what each view shows plus the handlers it calls.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";

import { t } from "../i18n";
import { clock } from "../nativeShell/shellContext";
import { controlText, controls, radius, spacing, useTheme } from "../theme";
import { Button, Card, ListRow, Notice as UiNotice, SectionLabel, Separator, TextField, TextLink, useUiStyles, type NoticeTone } from "../ui";
import { Chevron } from "../web/Chevron";
import { CaseCard } from "../ui/CaseCard";
import { ChoiceSheet, type ChoiceList } from "../ui/ChoiceSheet";
import {
  filterInterviews,
  interviewCounts,
  parseInterviewFilter,
  type InterviewAction,
  type InterviewFilter,
  type InterviewItem,
} from "../ui/interviewRows";
import type { HomeSummary } from "../ui/homeSummary";
import { isInternalPlaceholderUnit } from "../ui/placeholderUnit";
import { pickerModel, recentTarget, type PickerTarget } from "../ui/sitePicker";
import { OfflineNotice, SkeletonCards, StateView } from "../ui/StateView";
import type { RecentTarget } from "../recentTarget";

/**
 * "GUJ026 · Gujarat Health System" (code and display name); tapping it opens the project chooser when the account has
 * more than one project. With no project yet (the reference data is still loading) it keeps its empty line, so the
 * title block never collapses and the cards under it never jump.
 */
export function ProjectLine({ project, name, onPress }: { project?: string; name?: string; onPress?: () => void }) {
  const { ui, typography } = useTheme();
  const text = [project, name].filter(Boolean).join(" · ");
  if (!text) return <View testID="project-line-empty" aria-hidden style={{ minHeight: typography.subhead.lineHeight }} />;
  const label = (
    <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xxs }}>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground, flexShrink: 1 }}>{text}</Text>
      {onPress ? <Chevron expanded size={18} color={ui.mutedForeground} /> : null}
    </View>
  );
  if (!onPress) return label;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${text}. ${t("changeProject")}`} onPress={onPress} style={{ minHeight: controls.minTouchTarget, justifyContent: "center" }}>
      {label}
    </Pressable>
  );
}

/** Project chooser: the same searchable sheet as the site picker. */
export function ProjectSheet({ visible, projects, selectedId, onPick, onClose }: {
  visible: boolean; projects: Array<{ project_id: string; project_name: string }>; selectedId?: string; onPick(projectId: string): void; onClose(): void;
}) {
  const build = useCallback((query: string): ChoiceList => ({
    sections: [{
      key: "projects",
      rows: projects
        .filter((project) => project.project_name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
        .map((project) => ({ key: project.project_id, label: project.project_name, selected: project.project_id === selectedId, onPick: () => onPick(project.project_id) })),
    }],
  }), [projects, selectedId, onPick]);
  return <ChoiceSheet visible={visible} title={t("chooseProject")} searchLabel={t("pickerSearch")} onClose={onClose} build={build} />;
}

/**
 * The site/unit picker: unit names only, grouped under a site header only across several sites.
 * Opt-in for Register a death: `selectedKey` ticks the chosen row, and `siteNote` names the one shared site once
 * under the list (the worklist interview picker passes neither).
 */
export function SitePickerSheet({ visible, targets, recent, selectedKey, siteNote = false, onPick, onClose }: {
  visible: boolean; targets: PickerTarget[]; recent?: RecentTarget; selectedKey?: string; siteNote?: boolean; onPick(target: PickerTarget): void; onClose(): void;
}) {
  const build = useCallback((query: string): ChoiceList => {
    const model = pickerModel(targets, query);
    const last = recentTarget(targets, recent);
    const row = (target: PickerTarget, label: string) => ({ key: target.key, label, selected: target.key === selectedKey, onPick: () => onPick(target) });
    const shared = siteNote && !model.headers ? targets.find((target) => target.unitName !== undefined && target.siteName)?.siteName : undefined;
    return {
      recent: last ? row(last, pickerModel([last]).groups[0]?.rows[0]?.label ?? last.label) : undefined,
      sections: model.groups.map((group) => ({ key: group.siteId, title: group.title, rows: group.rows.map((item) => row(item.target, item.label)) })),
      note: shared && !isInternalPlaceholderUnit(shared) ? shared : undefined,
    };
  }, [targets, recent, selectedKey, siteNote, onPick]);
  return <ChoiceSheet visible={visible} title={t("chooseSite")} searchLabel={t("pickerSearch")} onClose={onClose} build={build} />;
}

/** A sync outcome or paused-project note as a tinted notice; children may mix strings and expressions. */
export function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: NoticeTone }) {
  const { ui, typography } = useTheme();
  return (
    <UiNotice tone={tone}>
      <Text style={{ ...typography.subhead, color: ui.foreground }}>{children}</Text>
    </UiNotice>
  );
}

/** A count label as a row label: "need a visit" starts with a capital (no-op for Hindi). */
const asRowLabel = (label: string) => label.charAt(0).toLocaleUpperCase() + label.slice(1);

export interface HomeViewProps {
  loaded: boolean;
  offline: boolean;
  summary: HomeSummary;
  /** Ready to send from this phone (shared count, src/unsentWork.ts); undefined while not counted. */
  unsent: number | undefined;
  /** Attached files waiting beside those records (shown as a note, not added to the count). */
  unsentFiles?: number;
  canStart: boolean;
  busy: boolean;
  onResume(item: InterviewItem): void;
  onStart(): void;
  onSend(): void;
  onViewTodo(): void;
  /** Open Interviews on the Drafts chip (the Drafts count row). */
  onViewDrafts?(): void;
  children?: React.ReactNode;
}

/**
 * Home (design sheet 01): the counts in one grouped card (Unsent on the attention tint with an amber badge while
 * anything waits, numbers in a right-aligned tabular column, every row keeping the chevron slot so they align),
 * then the screen's one filled button: Send now while anything is unsent (or the count is not known yet), else the
 * next step (Resume draft, or Start an interview); with nothing unsent Send now is not shown at all. Then the next-step card and `children` (the "go somewhere" rows: Register a death and the
 * coding case lists, in one card), 16pt apart.
 */
export function HomeView(p: HomeViewProps) {
  const { ui, typography } = useTheme();
  if (!p.loaded) return <HomeSkeleton />;
  const latest = p.summary.inProgress[0];
  const count = p.summary.inProgress.length;
  const edited = latest ? new Date(latest.updatedAt) : undefined;
  const editedKnown = edited !== undefined && !Number.isNaN(edited.getTime());
  const waiting = Boolean(p.unsent || p.unsentFiles);
  // The primary is always the next useful action: Send now while work waits, else the next step is filled. An
  // uncounted queue keeps Send now: hiding it would claim there is nothing to send. Offline, Send now stays but is
  // disabled, and the next step (which works from the cached reference data) stays the filled button.
  const offerSend = waiting || p.unsent === undefined;
  const nextKind = offerSend && !p.offline ? "secondary" : "primary";
  // A count of zero is not a row (nothing to look at); an uncounted unsent queue still shows its dash.
  const countRows = [
    ...(p.unsent === undefined || waiting ? [{
      key: "unsent",
      node: (
        <ListRow
          label={t("homeUnsent")}
          secondary={p.unsentFiles ? t("homeUnsentFiles", { count: p.unsentFiles }) : undefined}
          value={String(p.unsent ?? "–")}
          numeric
          tone={waiting ? "attention" : undefined}
          badge={waiting}
        />
      ),
    }] : []),
    ...(p.summary.needVisit > 0 ? [{
      key: "visit",
      node: (
        <ListRow
          label={asRowLabel(t("homeNeedVisit"))}
          value={String(p.summary.needVisit)}
          numeric
          accessibilityLabel={`${p.summary.needVisit} ${t("homeNeedVisit")}. ${t("homeView")}`}
          onPress={p.onViewTodo}
        />
      ),
    }] : []),
    ...(count > 0 ? [{
      key: "drafts",
      node: (
        <ListRow
          label={t("homeDraftsInProgress")}
          value={String(count)}
          numeric
          accessibilityLabel={p.onViewDrafts ? `${count} ${t("homeDraftsInProgress")}. ${t("homeView")}` : undefined}
          onPress={p.onViewDrafts}
        />
      ),
    }] : []),
  ];
  return (
    <View style={{ gap: spacing.md }}>
      {p.offline ? <OfflineNotice /> : null}
      {countRows.length > 0 ? (
        <Card grouped chevronSlot testID="home-counts">
          {countRows.map((row, index) => (
            <View key={row.key}>
              {index ? <Separator /> : null}
              {row.node}
            </View>
          ))}
        </Card>
      ) : null}
      {offerSend ? <Button testID="home-send-now" label={t("homeSendNow")} onPress={p.onSend} disabled={p.busy || p.offline} loading={p.busy} /> : null}
      <View style={{ gap: spacing.xs }}>
        <SectionLabel>{t("homeNextStep")}</SectionLabel>
        <Card testID="home-next-step">
          {latest ? (
            <>
              <Text style={{ ...typography.body, color: ui.foreground }}>
                {editedKnown ? t("homeResumeLine", { name: latest.title, time: clock(edited.getTime()) }) : latest.title}
              </Text>
              {count > 1 ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("homeDraftsMany", { count })}</Text> : null}
              <Button testID="home-next-primary" kind={nextKind} label={t("homeResumeDraft")} onPress={() => p.onResume(latest)} />
              {p.canStart ? <Button kind="secondary" label={t("newInterview")} onPress={p.onStart} /> : null}
            </>
          ) : (
            <>
              <Text style={{ ...typography.body, color: ui.foreground }}>{t("homeStartHint")}</Text>
              <Button testID="home-next-primary" kind={nextKind} label={t("homeStartInterview")} disabled={!p.canStart} onPress={p.onStart} />
            </>
          )}
        </Card>
      </View>
      {p.children}
    </View>
  );
}

/**
 * Home while the store and its reference data load: the counts card, the NEXT STEP label and card, and the card of
 * "go somewhere" rows, in their loaded geometry as placeholder bars, so nothing moves when the content arrives.
 * Hidden from screen readers except one "Loading" label.
 */
function HomeSkeleton() {
  const { ui, typography, textScale } = useTheme();
  const bar = (width: `${number}%`, height = 14) => <View style={{ width, height, borderRadius: 4, backgroundColor: ui.border }} />;
  // A ListRow's height (48pt, growing with the text size), a bar in place of its label.
  const rows = (count: number) => Array.from({ length: count }, (_, index) => (
    <View key={index}>
      {index ? <Separator /> : null}
      <View style={{ minHeight: 48 * Math.max(1, textScale), justifyContent: "center", paddingHorizontal: spacing.md }}>{bar("45%")}</View>
    </View>
  ));
  return (
    <View testID="state-loading" accessible accessibilityLabel={t("loading")} accessibilityState={{ busy: true }} style={{ gap: spacing.md }}>
      <View aria-hidden><Card grouped>{rows(3)}</Card></View>
      <View aria-hidden style={{ gap: spacing.xs }}>
        <View style={{ minHeight: typography.caption.lineHeight, justifyContent: "center", paddingHorizontal: spacing.md, paddingTop: spacing.xs }}>{bar("25%", 12)}</View>
        <Card>
          <View style={{ minHeight: typography.body.lineHeight, justifyContent: "center" }}>{bar("80%", 16)}</View>
          <View style={{ height: controls.minHeight, borderRadius: radius.md, backgroundColor: ui.border }} />
        </Card>
      </View>
      <View aria-hidden><Card grouped>{rows(3)}</Card></View>
    </View>
  );
}

const CHIPS: Array<{ key: InterviewFilter; label: () => string }> = [
  { key: "todo", label: () => t("filterTodo") },
  { key: "drafts", label: () => t("filterDrafts") },
];
// Behind "More": rarely needed lists. "All" is the state with no chip picked, and the sheet's way back to it.
const MORE_FILTERS: Array<{ key: InterviewFilter; label: () => string }> = [
  { key: "sent", label: () => t("filterSent") },
  { key: "revisions", label: () => t("filterRevisions") },
  { key: "all", label: () => t("filterAll") },
];

function FilterChips({ value, counts, onChange }: { value: InterviewFilter; counts: Record<InterviewFilter, number>; onChange(filter: InterviewFilter): void }) {
  const { ui, typography, textScale } = useTheme();
  const [more, setMore] = useState(false);
  // "All" is the default, so it leaves the chip plain "More"; only Sent and Revisions highlight it.
  const activeMore = MORE_FILTERS.find((chip) => chip.key === value && chip.key !== "all");
  const moreOn = activeMore !== undefined;
  const moreText = activeMore ? t("filterMoreActive", { label: activeMore.label() }) : t("filterMore");
  const build = useCallback((): ChoiceList => ({
    sections: [{
      key: "more",
      rows: MORE_FILTERS.map((chip) => {
        const count = chip.key !== "all" && counts[chip.key] > 0 ? counts[chip.key] : undefined;
        return {
          key: chip.key,
          label: count === undefined ? chip.label() : t("filterCount", { label: chip.label(), count }),
          selected: chip.key === value,
          onPick: () => { setMore(false); onChange(chip.key); },
        };
      }),
    }],
  }), [counts, value, onChange]);
  return (
    <View accessibilityRole="tablist" style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
      {CHIPS.map((chip) => {
        const on = chip.key === value;
        const count = chip.key !== "all" && counts[chip.key] > 0 ? counts[chip.key] : undefined;
        const text = count === undefined ? chip.label() : t("filterCount", { label: chip.label(), count });
        return (
          <Pressable
            key={chip.key}
            accessibilityRole="tab"
            accessibilityLabel={text}
            accessibilityState={{ selected: on }}
            onPress={() => onChange(on ? "all" : chip.key)}
            // 36pt chips; the slop makes the 44pt target.
            hitSlop={{ top: 4, bottom: 4 }}
            style={{ minHeight: controls.compactHeight * Math.max(1, textScale), paddingHorizontal: spacing.sm, alignItems: "center", justifyContent: "center", borderRadius: radius.full, backgroundColor: on ? ui.primaryTint : ui.card }}
          >
            <Text numberOfLines={1} style={{ ...typography.subhead, ...controlText, lineHeight: 22 * textScale, fontWeight: on ? "600" : "400", color: on ? ui.primary : ui.foreground }}>{text}</Text>
          </Pressable>
        );
      })}
      <Pressable
        accessibilityRole="tab"
        accessibilityLabel={t("filterMore")}
        accessibilityState={{ selected: moreOn }}
        onPress={() => setMore(true)}
        hitSlop={{ top: 4, bottom: 4 }}
        style={{ minHeight: controls.compactHeight * Math.max(1, textScale), paddingHorizontal: spacing.sm, alignItems: "center", justifyContent: "center", borderRadius: radius.full, backgroundColor: moreOn ? ui.primaryTint : ui.card }}
      >
        <Text numberOfLines={1} style={{ ...typography.subhead, ...controlText, lineHeight: 22 * textScale, fontWeight: moreOn ? "600" : "400", color: moreOn ? ui.primary : ui.foreground }}>{moreText}</Text>
      </Pressable>
      <ChoiceSheet visible={more} title={t("filterMore")} searchLabel={t("pickerSearch")} searchable={false} onClose={() => setMore(false)} build={build} />
    </View>
  );
}


/** One Interviews row: the shared CaseCard with the ID under the title, a status badge and one action. */
export function InterviewCard({ item, onAction, onRetryDemo, onDelete }: { item: InterviewItem; onAction(action: InterviewAction): void; onRetryDemo(item: InterviewItem): void; onDelete?(item: InterviewItem): void }) {
  const { colors, typography } = useTheme();
  const styles = useUiStyles();
  const card = (
    <CaseCard
      idBelowTitle
      testID={`interview-${item.key}`}
      title={item.title}
      caseId={item.caseId}
      ageYears={item.ageYears}
      sex={item.sex}
      dateOfDeath={item.dateOfDeath}
      area={item.unit}
      badges={[item.badge]}
      actions={(
        <>
          {/* The main action is wide and one line; Delete draft follows it as a small secondary action. */}
          {item.action ? <Button label={item.action.label} onPress={() => onAction(item.action as InterviewAction)} style={{ flexGrow: 1, flexShrink: 0, minWidth: 140 }} /> : null}
          {/* Delete draft: red text, never an outline and never the loudest thing on the card. */}
          {item.deletable && onDelete ? <TextLink tone="destructive" label={t("deleteDraft")} onPress={() => onDelete(item)} /> : null}
        </>
      )}
    >
      {item.timeText ? <Text testID="time-line" style={{ ...typography.caption, color: colors.textMuted }}>{item.timeText}</Text> : null}
      {item.lines.map((line, index) => (
        <Text key={index} style={line.tone === "error" ? styles.error : { ...typography.caption, color: colors.textMuted }}>{line.text}</Text>
      ))}
      {item.retryDemo ? <Button kind="secondary" size="sm" label={item.retryLabel ?? t("demoDraftRetry")} onPress={() => onRetryDemo(item)} /> : null}
    </CaseCard>
  );
  // Any case-backed card (to do, sent, or a sent/revision row whose interview belongs to a death) opens the case
  // detail from anywhere on the card; its own button (Start, View details, Revise) stays the one accessible control.
  const a = item.action;
  const open: InterviewAction | undefined = a?.type === "case" ? a
    : a?.type === "revise" && a.source.death_id ? { type: "case", deathId: a.source.death_id, projectId: a.source.project_id, label: a.label } : undefined;
  if (!open) return card;
  return <Pressable accessible={false} accessibilityRole="button" style={{ minHeight: controls.minTouchTarget }} testID={`open-${item.key}`} onPress={() => onAction(open)}>{card}</Pressable>;
}

export interface InterviewsViewProps {
  loaded: boolean;
  offline: boolean;
  items: InterviewItem[];
  initialFilter?: string | string[];
  canRegister: boolean;
  refreshing: boolean;
  busy: boolean;
  canRefresh: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  loadFailed: boolean;
  /** What to say when the revisions list failed to load (no connection, or Retry + Ref); defaults from `offline`. */
  loadFailedText?: string;
  onAction(action: InterviewAction): void;
  onRetryDemo(item: InterviewItem): void;
  onDeleteDraft?(item: InterviewItem): void;
  onRegister(): void;
  /** Pull-to-refresh; Send lives in the Sync sheet, so the list has no Send or Refresh button. */
  onRefresh(): void;
  onLoadMore(): void;
  /** Above the search row and scrolling with the list (project line, the coding case lists). */
  header?: React.ReactNode;
  footer?: React.ReactNode;
}

/**
 * Interviews: `header` (project line, coding case lists), search and filter chips with counts, then the cards, all
 * in one virtualised list (the one scroller on the screen, so the header scrolls away with the cards). Search and
 * chips show even when the list is empty, so the empty state sits under them. Pulling the list down refreshes it (a
 * no-op while busy or offline, where the reason is shown at its foot).
 */
export function InterviewsView(p: InterviewsViewProps) {
  const { ui, typography } = useTheme();
  const wanted = parseInterviewFilter(p.initialFilter);
  const [filter, setFilter] = useState<InterviewFilter>(wanted);
  // A link that returns to an open Interviews with another filter (Help, the Sync sheet) applies it; a plain tab tap
  // keeps the address, so the chip the user picked stays.
  // ponytail: the same filter linked twice after a manual chip change is not re-applied (the address is unchanged).
  useEffect(() => setFilter(wanted), [wanted]);
  const [query, setQuery] = useState("");
  const counts = useMemo(() => interviewCounts(p.items), [p.items]);
  const shown = useMemo(() => filterInterviews(p.items, filter, query), [p.items, filter, query]);
  const empty = p.items.length === 0;
  const refreshDisabled = p.busy || !p.canRefresh || p.offline;
  type Entry = { key: string; item?: InterviewItem; part?: "empty" | "footer" };
  // Empty state and footer are list entries, so the one FlatList scrolls everything below the fixed search row.
  const data: Entry[] = [
    ...(p.loaded ? shown.map((item) => ({ key: item.key, item })) : []),
    ...(shown.length === 0 || !p.loaded ? [{ key: "__empty", part: "empty" as const }] : []),
    { key: "__footer", part: "footer" as const },
  ];
  // An element, not a component: a new component type each render would remount the search field and drop its focus.
  const listHeader = (
    <View testID="interviews-header" style={{ gap: spacing.xs, paddingBottom: spacing.xs }}>
      {p.header}
      {p.offline ? <OfflineNotice /> : null}
      <TextField
        accessibilityLabel={t("searchInterviewsLabel")}
        placeholder={t("searchInterviews")}
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
      />
      <FilterChips value={filter} counts={counts} onChange={setFilter} />
    </View>
  );
  return (
    <View style={{ flex: 1 }}>
      <FlatList keyboardDismissMode="on-drag"
        ListHeaderComponent={listHeader}
        testID="interviews-list"
        style={{ flex: 1 }}
        // Pull to refresh for screen readers (WCAG 2.5.1); the Sync sheet's Refresh button does the same with one tap.
        accessibilityActions={refreshDisabled ? undefined : [{ name: "refresh", label: t("refresh") }]}
        onAccessibilityAction={(event) => { if (event.nativeEvent.actionName === "refresh" && !refreshDisabled) p.onRefresh(); }}
        refreshControl={(
          <RefreshControl
            refreshing={p.refreshing}
            enabled={!refreshDisabled}
            colors={[ui.primary]}
            tintColor={ui.primary}
            onRefresh={() => { if (!refreshDisabled) p.onRefresh(); }}
          />
        )}
        data={data}
        keyExtractor={(entry) => entry.key}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ gap: spacing.xs, paddingBottom: spacing.md }}
        renderItem={({ item: entry }) => {
          if (entry.item) return <InterviewCard item={entry.item} onAction={p.onAction} onRetryDemo={p.onRetryDemo} onDelete={p.onDeleteDraft} />;
          if (entry.part === "empty") {
            if (!p.loaded) return <SkeletonCards count={3} />;
            // Register has its own tab: the empty state offers it (and Refresh, the tap for pull-down) as text links.
            // The copy follows the connection first and Register second. Offline, Register (which works offline) comes
            // first and Refresh stays in view but waits for the connection the hint asks for.
            return empty ? (
              <StateView
                title={t("stateEmptyTitle")}
                hint={p.offline ? t("stateEmptyHintRefresh") : p.canRegister ? t("stateEmptyHint") : t("stateEmptyHintNoRegister")}
                links={p.offline ? [
                  ...(p.canRegister ? [{ label: t("registerDeath"), onPress: p.onRegister }] : []),
                  { label: t("refresh"), onPress: p.onRefresh, disabled: true },
                ] : [
                  ...(refreshDisabled ? [] : [{ label: t("refresh"), onPress: p.onRefresh }]),
                  ...(p.canRegister ? [{ label: t("registerDeath"), onPress: p.onRegister }] : []),
                ]}
              />
            ) : <Text style={{ ...typography.body, color: ui.mutedForeground, paddingVertical: spacing.md }}>{t("noMatches")}</Text>;
          }
          return (
            <View style={{ gap: spacing.xs }}>
              {p.loadFailed ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{p.loadFailedText ?? (p.offline ? t("revisionsNeedConnection") : t("revisionRetry"))}</Text> : null}
              {p.hasMore ? <Button kind="secondary" loading={p.loadingMore} label={t("loadMore")} onPress={p.onLoadMore} /> : null}
              {p.offline ? <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{t("refreshNeedsConnection")}</Text> : null}
              {p.footer}
            </View>
          );
        }}
      />
    </View>
  );
}
