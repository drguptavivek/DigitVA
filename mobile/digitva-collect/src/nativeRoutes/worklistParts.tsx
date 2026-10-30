/**
 * The views of the interviewer's /worklist route: Home (dashboard), Interviews (searchable list), the site/unit
 * picker and the project chooser. Presentational: worklist.tsx owns the data, sync and refresh logic and passes
 * what each view shows plus the handlers it calls.
 */
import { useCallback, useMemo, useState } from "react";
import { FlatList, Pressable, Text, TextInput, View } from "react-native";

import { t } from "../i18n";
import { clock } from "../nativeShell/shellContext";
import { controlText, controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
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
import { pickerModel, recentTarget, type PickerTarget } from "../ui/sitePicker";
import { OfflineNotice, SkeletonCards, StateView } from "../ui/StateView";
import type { RecentTarget } from "../recentTarget";

/** "Hamirpur · Dr A. Sharma"; tapping it opens the project chooser when the account has more than one project. */
export function ProjectLine({ project, name, onPress }: { project?: string; name?: string; onPress?: () => void }) {
  const { ui } = useTheme();
  const text = [project, name].filter(Boolean).join(" · ");
  if (!text) return null;
  const label = <Text style={{ ...typography.subhead, color: ui.mutedForeground, flexShrink: 1 }}>{text}{onPress ? "  ▾" : ""}</Text>;
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

/** The site/unit picker: unit names only, grouped under a site header only across several sites. */
export function SitePickerSheet({ visible, targets, recent, onPick, onClose }: {
  visible: boolean; targets: PickerTarget[]; recent?: RecentTarget; onPick(target: PickerTarget): void; onClose(): void;
}) {
  const build = useCallback((query: string): ChoiceList => {
    const model = pickerModel(targets, query);
    const last = recentTarget(targets, recent);
    const row = (target: PickerTarget, label: string) => ({ key: target.key, label, onPick: () => onPick(target) });
    return {
      recent: last ? row(last, pickerModel([last]).groups[0]?.rows[0]?.label ?? last.label) : undefined,
      sections: model.groups.map((group) => ({ key: group.siteId, title: group.title, rows: group.rows.map((item) => row(item.target, item.label)) })),
    };
  }, [targets, recent, onPick]);
  return <ChoiceSheet visible={visible} title={t("chooseSite")} searchLabel={t("pickerSearch")} onClose={onClose} build={build} />;
}

/** A muted line for sync outcomes and paused-project notes. */
export function Notice({ children }: { children: React.ReactNode }) {
  const { ui } = useTheme();
  return <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{children}</Text>;
}

function Card({ children, testID }: { children: React.ReactNode; testID?: string }) {
  const styles = useUiStyles();
  return <View style={[styles.card, { gap: spacing.xs }]} testID={testID}>{children}</View>;
}

function Metric({ value, label, note, actionLabel, onAction, disabled, loading }: { value: number | string; label: string; note?: string; actionLabel: string; onAction(): void; disabled?: boolean; loading?: boolean }) {
  const { ui } = useTheme();
  return (
    <View style={{ flex: 1 }}>
      <Card>
        <Text style={{ ...typography.largeTitle, color: ui.foreground }}>{value}</Text>
        <Text style={{ ...typography.body, color: ui.foreground }}>{label}</Text>
        {note ? <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{note}</Text> : null}
        <Button kind="secondary" size="sm" label={actionLabel} onPress={onAction} disabled={disabled} loading={loading} />
      </Card>
    </View>
  );
}

export interface HomeViewProps {
  loaded: boolean;
  offline: boolean;
  summary: HomeSummary;
  /** Ready to send from this phone (shared count, src/unsentWork.ts); undefined while not counted. */
  unsent: number | undefined;
  /** Attached files waiting beside those records (shown as a note, not added to the count). */
  unsentFiles?: number;
  canStart: boolean;
  canRegister: boolean;
  busy: boolean;
  onResume(item: InterviewItem): void;
  onStart(): void;
  onRegister(): void;
  onSend(): void;
  onViewTodo(): void;
  children?: React.ReactNode;
}

/** Home: the next step, the two numbers that need action, and Register a death. */
export function HomeView(p: HomeViewProps) {
  const { ui } = useTheme();
  if (!p.loaded) return <SkeletonCards count={2} />;
  const latest = p.summary.inProgress[0];
  const count = p.summary.inProgress.length;
  const edited = latest ? new Date(latest.updatedAt) : undefined;
  return (
    <View style={{ gap: spacing.sm }}>
      {p.offline ? <OfflineNotice /> : null}
      <Card testID="home-next-step">
        <Text style={{ ...typography.caption, fontWeight: "600", textTransform: "uppercase", color: ui.mutedForeground }}>{t("homeNextStep")}</Text>
        {latest ? (
          <>
            <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{count === 1 ? t("homeDraftsOne") : t("homeDraftsMany", { count })}</Text>
            <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>
              {edited && !Number.isNaN(edited.getTime()) ? t("homeLastEdited", { name: latest.title, time: clock(edited.getTime()) }) : latest.title}
            </Text>
            <Button label={t("homeResumeDraft")} onPress={() => p.onResume(latest)} />
            {p.canStart ? <Button kind="secondary" label={t("newInterview")} onPress={p.onStart} /> : null}
          </>
        ) : (
          <>
            <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{t("homeStartHint")}</Text>
            <Button label={t("homeStartInterview")} disabled={!p.canStart} onPress={p.onStart} />
          </>
        )}
      </Card>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <Metric value={p.unsent ?? "–"} label={t("homeUnsent")} note={p.unsentFiles ? t("homeUnsentFiles", { count: p.unsentFiles }) : undefined} actionLabel={t("homeSendNow")} onAction={p.onSend} disabled={p.busy} loading={p.busy} />
        <Metric value={p.summary.needVisit} label={t("homeNeedVisit")} actionLabel={t("homeView")} onAction={p.onViewTodo} />
      </View>
      {p.canRegister ? <Button label={t("registerDeath")} onPress={p.onRegister} /> : null}
      {p.children}
    </View>
  );
}

const CHIPS: Array<{ key: InterviewFilter; label: () => string }> = [
  { key: "all", label: () => t("filterAll") },
  { key: "drafts", label: () => t("filterDrafts") },
  { key: "todo", label: () => t("filterTodo") },
  { key: "sent", label: () => t("filterSent") },
  { key: "revisions", label: () => t("filterRevisions") },
];

function FilterChips({ value, counts, onChange }: { value: InterviewFilter; counts: Record<InterviewFilter, number>; onChange(filter: InterviewFilter): void }) {
  const { ui } = useTheme();
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
            onPress={() => onChange(chip.key)}
            style={{ minHeight: controls.minTouchTarget, paddingHorizontal: spacing.sm, alignItems: "center", justifyContent: "center", borderRadius: radius.full, borderWidth: 1, borderColor: on ? ui.primary : ui.input, backgroundColor: on ? ui.primary : ui.background }}
          >
            <Text numberOfLines={1} style={{ ...typography.subhead, ...controlText, lineHeight: 22, fontWeight: on ? "600" : "400", color: on ? ui.primaryForeground : ui.foreground }}>{text}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Delete draft: a small outlined danger action, never the loudest thing on the card. */
function DeleteDraftButton({ onPress }: { onPress(): void }) {
  const { ui } = useTheme();
  const label = t("deleteDraft");
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={{ minHeight: controls.minTouchTarget, paddingHorizontal: spacing.sm, alignItems: "center", justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: ui.destructiveText }}
    >
      <Text style={{ ...typography.subhead, ...controlText, lineHeight: 22, fontWeight: "500", color: ui.destructiveText }}>{label}</Text>
    </Pressable>
  );
}

/** One Interviews row: the shared CaseCard with the ID under the title, a status badge and one action. */
export function InterviewCard({ item, onAction, onRetryDemo, onDelete }: { item: InterviewItem; onAction(action: InterviewAction): void; onRetryDemo(item: InterviewItem): void; onDelete?(item: InterviewItem): void }) {
  const { colors } = useTheme();
  const styles = useUiStyles();
  return (
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
          {item.deletable && onDelete ? <DeleteDraftButton onPress={() => onDelete(item)} /> : null}
        </>
      )}
    >
      {item.timeText ? <Text testID="time-line" style={{ ...typography.subhead, color: colors.textMuted }}>{item.timeText}</Text> : null}
      {item.lines.map((line, index) => (
        <Text key={index} style={line.tone === "error" ? styles.error : { ...typography.subhead, color: colors.textMuted }}>{line.text}</Text>
      ))}
      {item.retryDemo ? <Button kind="secondary" size="sm" label={item.retryLabel ?? t("demoDraftRetry")} onPress={() => onRetryDemo(item)} /> : null}
    </CaseCard>
  );
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
  onRefresh(): void;
  onSend(): void;
  onLoadMore(): void;
  header?: React.ReactNode;
  footer?: React.ReactNode;
}

/** Interviews: search, filter chips with counts, then a virtualised list of cards (the one scroller on the screen). */
export function InterviewsView(p: InterviewsViewProps) {
  const { ui } = useTheme();
  const [filter, setFilter] = useState<InterviewFilter>(() => parseInterviewFilter(p.initialFilter));
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
  return (
    <View style={{ flex: 1, gap: spacing.xs }}>
      {p.header}
      {p.offline ? <OfflineNotice /> : null}
      {!empty || !p.loaded ? (
        <>
          <TextInput
            accessibilityLabel={t("searchInterviewsLabel")}
            placeholder={t("searchInterviews")}
            placeholderTextColor={ui.mutedForeground}
            value={query}
            onChangeText={setQuery}
            autoCorrect={false}
            style={{ minHeight: 48, borderWidth: 1, borderColor: ui.input, borderRadius: radius.md, paddingHorizontal: spacing.sm, ...typography.body, color: ui.foreground, backgroundColor: ui.background }}
          />
          <FilterChips value={filter} counts={counts} onChange={setFilter} />
        </>
      ) : null}
      <FlatList keyboardDismissMode="on-drag"
        style={{ flex: 1 }}
        data={data}
        keyExtractor={(entry) => entry.key}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ gap: spacing.xs, paddingBottom: spacing.md }}
        renderItem={({ item: entry }) => {
          if (entry.item) return <InterviewCard item={entry.item} onAction={p.onAction} onRetryDemo={p.onRetryDemo} onDelete={p.onDeleteDraft} />;
          if (entry.part === "empty") {
            if (!p.loaded) return <SkeletonCards count={3} />;
            return empty ? (
              <StateView
                title={t("stateEmptyTitle")}
                hint={p.canRegister ? t("stateEmptyHint") : t("stateEmptyHintRefresh")}
                actionLabel={p.canRegister ? t("registerDeath") : undefined}
                onAction={p.canRegister ? p.onRegister : undefined}
              />
            ) : <Text style={{ ...typography.body, color: ui.mutedForeground, paddingVertical: spacing.md }}>{t("noMatches")}</Text>;
          }
          return (
            <View style={{ gap: spacing.xs }}>
              {p.loadFailed ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{p.loadFailedText ?? (p.offline ? t("revisionsNeedConnection") : t("revisionRetry"))}</Text> : null}
              {p.hasMore ? <Button kind="secondary" loading={p.loadingMore} label={t("loadMore")} onPress={p.onLoadMore} /> : null}
              <Button kind="secondary" label={t("homeSendNow")} disabled={p.busy || !p.canRefresh} onPress={p.onSend} />
              <Button kind="secondary" label={t("refresh")} loading={p.refreshing} disabled={refreshDisabled} onPress={p.onRefresh} />
              {p.offline ? <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{t("refreshNeedsConnection")}</Text> : null}
              {p.footer}
            </View>
          );
        }}
      />
    </View>
  );
}
