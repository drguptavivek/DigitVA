import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react";
import { ActivityIndicator, Alert, AppState, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { ConfirmDialog } from "../ConfirmDialog";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, Screen, errorText, useUiStyles } from "../ui";
import { t, type StringKey } from "../i18n";
import { ContextualHelpBanner } from "../web/ContextualHelp";
import { formatDisplayTimestamp } from "../web/DeathsList";
import type { WorkspaceApi } from "./api";
import type { QueueView } from "./viewState";
import type { CodingHistoryCache, CodingHistoryIdentity } from "../codingHistoryCache";
import type {
  AllocationSnapshot,
  CoderAvailableCase,
  CoderHistory,
  CoderHistoryCase,
  CoderProjects,
  CoderQueue,
  CodingStats,
  ProjectOptions,
  QueueCase,
  ReviewerHistory,
  ReviewerQueue,
  ReviewerStats,
  WorkspaceIdentity,
} from "./contracts";

const PAGE_SIZE = 50;
const MAX_OFFSET = 1_000_000;

type QueueScope = { api: WorkspaceApi; mode: "coding" | "reviewing"; projectId?: string; offset: number; showHistory: boolean };
type GenderFilter = "all" | "female" | "male";
type AnyQueueCase = CoderAvailableCase | CoderHistoryCase | QueueCase;

function normalizeGenderKey(raw: string | null | undefined): "female" | "male" | "other" | null {
  if (!raw) return null;
  const lower = raw.trim().toLowerCase();
  if (lower === "f" || lower === "female") return "female";
  if (lower === "m" || lower === "male") return "male";
  return "other";
}

type QueueData = {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  projectId?: string;
  offset: number;
  showHistory: boolean;
  stats?: CodingStats | ReviewerStats;
  coderAvailable?: CoderQueue;
  coderHistory?: CoderHistory;
  available?: ReviewerQueue;
  history?: ReviewerHistory;
  cachedHistoryAt?: string;
};

type AllocationData = { api: WorkspaceApi; mode: "coding" | "reviewing"; generation: number; verified: boolean; snapshot: AllocationSnapshot | null };
type QueueMessage = { scope: QueueScope; text: string };

function useQueueStyles() {
  const { colors, ui } = useTheme();
  return useMemo(() => StyleSheet.create({
    field: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm },
    fieldText: { flex: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.5)" },
    sheet: { maxHeight: "80%", backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.sm, gap: spacing.xs, width: "100%", maxWidth: controls.contentMaxWidth, alignSelf: "center" },
    option: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 48, paddingVertical: spacing.xs, paddingHorizontal: spacing.sm, borderRadius: radius.md },
    optionOn: { backgroundColor: colors.accentSoft },
    optionText: { flex: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    titleMain: { flex: 1, minWidth: 0, flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", columnGap: spacing.xs },
    iconButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    segmentedTrack: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, padding: spacing.xxs, borderRadius: radius.md, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
    actionBtn: { flexGrow: 1, flexBasis: 132 },
    pager: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    pagerBtn: { flex: 1 },
    pageText: { flex: 1, textAlign: "center", ...typography.subhead, color: colors.textMuted, fontFamily: controls.fontFamily },
    statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    statTile: { flexGrow: 1, flexBasis: 96, paddingVertical: spacing.xxs, paddingHorizontal: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted, gap: 2 },
    statValue: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    statLabel: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
    filterBox: { gap: spacing.xs, padding: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    searchInput: { minHeight: 38, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm, paddingVertical: spacing.xxs, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    chip: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
    chipActive: { borderColor: colors.accent, backgroundColor: colors.accent },
    chipText: { ...typography.caption, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    chipTextActive: { color: colors.onAccent },
    caseCard: { gap: spacing.xxs },
    caseHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, flexWrap: "wrap" },
    caseHeaderMain: { flex: 1, minWidth: 160, gap: 2 },
    badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    badge: { paddingVertical: 2, paddingHorizontal: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    badgeAccent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
    badgeText: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    badgeAccentText: { color: ui.accentForeground },
    metaGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs },
    metaChip: { paddingVertical: 2, paddingHorizontal: spacing.xs, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    metaChipText: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
  }), [colors, ui]);
}

function isInternalPlaceholderArea(name: string | null | undefined): boolean {
  return !name || /^sites_in_project_/i.test(name.trim());
}

function formatQueueDate(raw: string | null | undefined): string {
  if (!raw) return "";
  const trimmed = raw.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const match = /^(\d{4}-\d{2}-\d{2})T/.exec(trimmed);
  if (match) return match[1];
  return trimmed;
}

/**
 * The offline station's line for a coded case the server has answered: held ("waiting for the
 * server's DORIS") or refused with a plain reason per code. Null when there is nothing to say.
 */
export function codingServerStatusText(item: Pick<CoderHistoryCase, "server_status" | "server_code">): string | null {
  if (item.server_status === "pending") return t("codingServerPending");
  if (item.server_status !== "refused") return null;
  const code = item.server_code ?? "";
  const key = `codingRefused_${code}` as StringKey;
  // t() answers the key itself for a code this release has no words for.
  const known = /^[a-z_]+$/.test(code) ? t(key) : key;
  const reason = known !== key ? known : t("codingRefused_unknown", { code: code || "?" });
  return t("codingServerRefused", { reason });
}

/**
 * The recode deadline line on a coded case: "Recode until <local time>" while the Recode action
 * is offered, "Recode window closed" once `recode_until` has passed, else null (the window is the
 * project's, docs/policy/coding-workflow-state-machine.md "Recode Window").
 */
export function recodeDeadlineText(item: Pick<CoderHistoryCase, "recodeable" | "recode_until">, now: number = Date.now()): string | null {
  if (!item.recode_until) return null;
  if (item.recodeable) return t("codingRecodeUntil", { date: formatDisplayTimestamp(item.recode_until) });
  const until = Date.parse(item.recode_until);
  return !Number.isNaN(until) && until <= now ? t("codingRecodeClosed") : null;
}

function CaseCardDetails({ item }: { item: AnyQueueCase }) {
  const q = useQueueStyles();
  const hasAge = item.va_deceased_age != null && String(item.va_deceased_age).trim() !== "";
  const hasGender = Boolean(item.va_deceased_gender);
  const collector = "va_data_collector" in item && item.va_data_collector ? item.va_data_collector : null;
  const formId = item.va_form_id ? item.va_form_id : null;
  const codingDate = "va_coding_date" in item && item.va_coding_date ? formatQueueDate(item.va_coding_date) : null;
  const reviewedAt = "va_reviewed_at" in item && item.va_reviewed_at ? formatQueueDate(item.va_reviewed_at) : null;

  if (!hasAge && !hasGender && !collector && !formId && !codingDate && !reviewedAt) return null;

  return (
    <View style={q.metaGrid}>
      {hasAge ? (
        <View style={q.metaChip}>
          <Text style={q.metaChipText}>{`Age: ${item.va_deceased_age}`}</Text>
        </View>
      ) : null}
      {hasGender ? (
        <View style={q.metaChip}>
          <Text style={q.metaChipText}>{`Sex: ${item.va_deceased_gender}`}</Text>
        </View>
      ) : null}
      {collector ? (
        <View style={q.metaChip}>
          <Text style={q.metaChipText}>{t("queueInterviewer", { name: collector })}</Text>
        </View>
      ) : null}
      {formId ? (
        <View style={q.metaChip}>
          <Text style={q.metaChipText}>{`Form: ${formId}`}</Text>
        </View>
      ) : null}
      {codingDate ? (
        <View style={q.metaChip}>
          <Text style={q.metaChipText}>{`Coded: ${codingDate}`}</Text>
        </View>
      ) : null}
      {reviewedAt ? (
        <View style={q.metaChip}>
          <Text style={q.metaChipText}>{`Reviewed: ${reviewedAt}`}</Text>
        </View>
      ) : null}
    </View>
  );
}

function Chevron({ color }: { color: string }) {
  return <Svg width={14} height={14} viewBox="0 0 14 14"><Path d="M2 5l5 5 5-5" stroke={color} strokeWidth={1.8} fill="none" strokeLinecap="round" strokeLinejoin="round" /></Svg>;
}

function CheckMark({ color }: { color: string }) {
  return <Svg width={16} height={16} viewBox="0 0 16 16"><Path d="M3 8.5l3.5 3.5L13 4.5" stroke={color} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" /></Svg>;
}

function RefreshIcon({ onPress, disabled }: { onPress: () => void; disabled: boolean }) {
  const { colors } = useTheme();
  const q = useQueueStyles();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel="Refresh cases" accessibilityState={{ disabled }} disabled={disabled} onPress={onPress} style={[q.iconButton, disabled && { opacity: 0.5 }]}>
      <Svg width={20} height={20} viewBox="0 0 20 20">
        <Path d="M16 10a6 6 0 1 1-1.8-4.3" stroke={colors.text} strokeWidth={1.8} fill="none" strokeLinecap="round" />
        <Path d="M16.5 3v4h-4" stroke={colors.text} strokeWidth={1.8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}

/** One field-like control that opens a sheet; names wrap in the list but stay on one line in the field. */
function ProjectPicker({ options, value, disabled, onSelect }: {
  options: { project_id: string; project_name: string }[];
  value?: string;
  disabled: boolean;
  onSelect: (projectId: string | undefined) => void;
}) {
  const { colors } = useTheme();
  const q = useQueueStyles();
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.project_id === value);
  const name = selected?.project_name ?? "All projects";
  const choose = (projectId: string | undefined) => { setOpen(false); onSelect(projectId); };
  const row = (key: string, label: string, projectId: string | undefined, on: boolean) => (
    <Pressable key={key} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected: on }} onPress={() => choose(projectId)} style={[q.option, on && q.optionOn]}>
      <Text style={q.optionText}>{label}</Text>
      {on ? <CheckMark color={colors.accent} /> : <View style={{ width: 16 }} />}
    </Pressable>
  );
  return (
    <>
      <Pressable accessibilityRole="button" accessibilityLabel={`Project: ${name}`} accessibilityState={{ expanded: open, disabled }} disabled={disabled} onPress={() => setOpen(true)} style={[q.field, disabled && { opacity: 0.5 }]}>
        <Text numberOfLines={1} ellipsizeMode="tail" style={q.fieldText}>Project: {name}</Text>
        <Chevron color={colors.text} />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <View style={q.backdrop}>
          <Pressable accessibilityRole="button" accessibilityLabel="Close project list" onPress={() => setOpen(false)} style={StyleSheet.absoluteFill} />
          <View style={q.sheet} accessibilityViewIsModal>
            <ScrollView>
              {row("all", "All projects", undefined, !value)}
              {options.map((option) => row(option.project_id, option.project_name, option.project_id, option.project_id === value))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  );
}

/**
 * Load and operate the coder or reviewer queue without reading the unbounded
 * coder pick/history routes. Requests are discarded when scope or app state changes.
 */
export function QueueScreen({
  api,
  mode,
  onOpen,
  onExit,
  initialView,
  onViewChange,
  Shell,
  historyCache,
  historyIdentity,
}: {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  onOpen: (identity: WorkspaceIdentity) => void;
  onExit?: () => void;
  /** Project, tab and page from the URL, already parsed; the project is checked against the catalogue before use. */
  initialView?: QueueView;
  /** Reports the settled project, tab and page so the route can keep them in the URL across a reload. */
  onViewChange?: (view: { projectId?: string; showHistory: boolean; offset: number }) => void;
  /** Optional shell component (e.g. WebShell on web) to wrap the queue with left navigation and language switcher. */
  Shell?: ComponentType<{ title: string; headerAction?: ReactNode; children: ReactNode }>;
  /** Native only; web leaves this unset. */
  historyCache?: CodingHistoryCache;
  historyIdentity?: CodingHistoryIdentity;
}) {
  const ActiveShell = Shell ?? Screen;
  const styles = useUiStyles();
  const q = useQueueStyles();
  const { colors } = useTheme();
  const [projectId, setProjectId] = useState<string | undefined>(initialView?.projectId);
  const [offset, setOffset] = useState(initialView?.offset ?? 0);
  const [showHistory, setShowHistory] = useState(initialView?.showHistory ?? false);
  const startedOnAll = useRef(initialView?.allProjects === true);
  const startedOnProject = useRef(initialView?.projectId !== undefined);
  const [data, setData] = useState<QueueData | null>(null);
  const [allocationData, setAllocationData] = useState<AllocationData | null>(null);
  const [catalog, setCatalog] = useState<{ api: WorkspaceApi; mode: "coding" | "reviewing"; projects?: ProjectOptions } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmRelease, setConfirmRelease] = useState<{ warning: string; proceed: () => void } | null>(null);
  const [message, setMessage] = useState<QueueMessage | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [genderFilter, setGenderFilter] = useState<GenderFilter>("all");
  const [siteFilter, setSiteFilter] = useState<string | undefined>(undefined);
  const [recodeableOnly, setRecodeableOnly] = useState(false);
  const generation = useRef(0);
  // null until the first coder stats answer; load() uses it to pick the tab before fetching a page.
  const lastPickMode = useRef<boolean | null>(null);
  // Same for random mode, so the card title does not flip while a project's stats load.
  const lastRandomMode = useRef<boolean | null>(null);
  const actionInFlight = useRef(false);
  const cachedHistoryOnly = useRef(false);
  const actionError = useRef<QueueMessage | null>(null);
  const scopeRef = useRef<QueueScope>({ api, mode, projectId, offset, showHistory });
  scopeRef.current = { api, mode, projectId, offset, showHistory };
  const activeRef = useRef(AppState.currentState !== "background" && AppState.currentState !== "inactive" && (typeof document === "undefined" || document.visibilityState !== "hidden"));

  function clearMessage() {
    actionError.current = null;
    setMessage(null);
  }

  useEffect(() => {
    setSearchQuery("");
    setGenderFilter("all");
    setSiteFilter(undefined);
    setRecodeableOnly(false);
  }, [projectId, showHistory, offset, mode]);

  function isCurrent(requestGeneration: number, requestScope: typeof scopeRef.current) {
    const current = scopeRef.current;
    return generation.current === requestGeneration
      && activeRef.current
      && AppState.currentState !== "background"
      && AppState.currentState !== "inactive"
      && (typeof document === "undefined" || document.visibilityState !== "hidden")
      && current.api === requestScope.api
      && current.mode === requestScope.mode
      && current.projectId === requestScope.projectId
      && current.offset === requestScope.offset
      && current.showHistory === requestScope.showHistory;
  }

  // The queue waits for the project catalogue, so the first load already uses the last project.
  const catalogReady = catalog?.api === api && catalog.mode === mode;

  const load = useCallback(async () => {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (!isCurrent(generation.current, requestScope) || !catalogReady) return;
    const requestGeneration = ++generation.current;
    cachedHistoryOnly.current = false;
    setAllocationData({ api, mode, generation: requestGeneration, verified: false, snapshot: null });
    setLoading(true);
    const allocationRequest = mode === "coding" ? api.getCodingAllocation() : api.getReviewerAllocation();
    void allocationRequest.then((snapshot) => {
      if (isCurrent(requestGeneration, requestScope)) {
        setAllocationData({ api, mode, generation: requestGeneration, verified: true, snapshot });
      }
    }).catch((error: unknown) => {
      if (isCurrent(requestGeneration, requestScope)) {
        setAllocationData(null);
        if (!actionError.current && !cachedHistoryOnly.current) setMessage({ scope: requestScope, text: errorText(error) });
      }
    });
    try {
      let next: QueueData;
      if (mode === "coding") {
        if (!showHistory && lastPickMode.current === null) {
          // Pick mode unknown: ask stats first so a random-only coder never fetches the available page.
          const first = await api.getCodingStats(projectId);
          if (!isCurrent(requestGeneration, requestScope)) return;
          if ((first as { has_pick_mode?: boolean }).has_pick_mode === false) {
            lastPickMode.current = false;
            setOffset(0);
            setShowHistory(true);
            return;
          }
        }
        const [stats, page] = await Promise.all([
          api.getCodingStats(projectId),
          showHistory
            ? api.getCodingHistory({ projectId, limit: PAGE_SIZE, offset })
            : api.getCodingAvailable({ projectId, limit: PAGE_SIZE, offset }),
        ]);
        next = {
          api,
          mode,
          projectId,
          offset,
          showHistory,
          stats,
          ...(showHistory ? { coderHistory: page as CoderHistory } : { coderAvailable: page as CoderQueue }),
        };
      } else {
        const [stats, page] = await Promise.all([
          api.getReviewerStats(projectId),
          showHistory
            ? api.getReviewerHistory({ projectId, limit: PAGE_SIZE, offset })
            : api.getReviewerAvailable({ projectId, limit: PAGE_SIZE, offset }),
        ]);
        next = {
          api,
          mode,
          projectId,
          offset,
          showHistory,
          stats,
          ...(showHistory ? { history: page as ReviewerHistory } : { available: page as ReviewerQueue }),
        };
      }
      if (isCurrent(requestGeneration, requestScope)) {
        setData(next);
        if (mode === "coding" && showHistory && projectId && historyCache && historyIdentity) {
          const fingerprint = historyCache.fingerprintForProject(projectId);
          if (fingerprint) void historyCache.writePage(historyIdentity, projectId, next.coderHistory!, fingerprint).catch(() => undefined);
        }
      }
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
        let cached: Awaited<ReturnType<CodingHistoryCache["readPage"]>> = null;
        if (error instanceof TypeError && mode === "coding" && showHistory && projectId && historyCache && historyIdentity) {
          try {
            cached = await historyCache.readPage(historyIdentity, projectId, offset);
          } catch {
            cached = null;
          }
        } else if (mode === "coding" && projectId && historyCache && historyIdentity) {
          // Authorization, malformed-response, and server errors must never fall back to old rows.
          try { await historyCache.invalidateProject(historyIdentity, projectId); } catch { /* cache cleanup is best effort */ }
        }
        if (cached && isCurrent(requestGeneration, requestScope)) {
          cachedHistoryOnly.current = true;
          setSearchQuery("");
          setGenderFilter("all");
          setSiteFilter(undefined);
          setRecodeableOnly(false);
          setData({
            api, mode, projectId, offset, showHistory, coderHistory: cached.page,
            cachedHistoryAt: cached.fetchedAt,
          });
          setMessage(null);
          return;
        }
        setData(null);
        const previousError = actionError.current;
        if (!previousError || previousError.scope.api !== requestScope.api || previousError.scope.mode !== requestScope.mode
          || previousError.scope.projectId !== requestScope.projectId || previousError.scope.offset !== requestScope.offset
          || previousError.scope.showHistory !== requestScope.showHistory) {
          actionError.current = null;
          setMessage({ scope: requestScope, text: errorText(error) });
        }
      }
    } finally {
      if (isCurrent(requestGeneration, requestScope)) setLoading(false);
    }
  }, [api, catalogReady, historyCache, historyIdentity, mode, offset, projectId, showHistory]);

  // Load the project catalogue once per api and mode. Default: the URL's project, else the last project
  // when still offered, else (reviewers) the first project with cases to review, else All projects.
  useEffect(() => {
    let active = true;
    const request = mode === "coding" ? api.getCodingProjects() : api.getReviewerProjects();
    void request.then(async (projects) => {
      if (!active) return;
      const offered = (id: string | null | undefined) => id != null && projects.project_options.some((option) => option.project_id === id);
      let fallback = !startedOnAll.current && offered(projects.last_project_id) ? projects.last_project_id ?? undefined : undefined;
      if (fallback === undefined && !startedOnAll.current && !startedOnProject.current
        && mode === "reviewing" && projects.project_options.length > 1) {
        // ponytail: one stats call per offered project, only on this fallback path; a per-project
        // `available` count on /reviewing/projects would remove the fan-out.
        const counts = await Promise.all(projects.project_options.map((option) => api.getReviewerStats(option.project_id).catch(() => null)));
        if (!active) return;
        fallback = projects.project_options.find((_, index) => (counts[index]?.available ?? 0) > 0)?.project_id;
      }
      // A project named by the URL that is not offered (stale or edited) falls back to All projects.
      setProjectId((current) => {
        if (current !== undefined) return offered(current) ? current : undefined;
        return fallback;
      });
      setCatalog({ api, mode, projects });
    }).catch(async (error) => {
      if (!active) return;
      if (error instanceof TypeError && mode === "coding" && historyCache && historyIdentity) {
        const cachedProjects: string[] = await historyCache.cachedProjects(historyIdentity).catch((): string[] => []);
        if (!active) return;
        if (cachedProjects.length) {
          const options = cachedProjects.map((projectId) => ({ project_id: projectId, project_name: projectId }));
          const cachedCatalog: CoderProjects = { project_options: options, projects: cachedProjects, last_project_id: cachedProjects[0] };
          const cachedProject = cachedProjects[0];
          setProjectId((current) => current && cachedProjects.includes(current) ? current : cachedProject);
          setShowHistory(true);
          setCatalog({ api, mode, projects: cachedCatalog });
          lastPickMode.current = false;
          return;
        }
      }
      setProjectId(undefined);
      setCatalog({ api, mode });
    });
    return () => {
      active = false;
    };
  }, [api, historyCache, historyIdentity, mode]);

  useEffect(() => {
    setData(null);
    setBusy(false);
    actionInFlight.current = false;
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load, refresh]);

  useEffect(() => {
    let previous = AppState.currentState;
    const invalidate = () => {
      activeRef.current = false;
      generation.current += 1;
      actionInFlight.current = false;
      setData(null);
      clearMessage();
      setBusy(false);
      setLoading(false);
    };
    const subscription = AppState.addEventListener("change", (next) => {
      activeRef.current = next === "active" && (typeof document === "undefined" || document.visibilityState !== "hidden");
      if (activeRef.current && previous !== "active") {
        if (scopeRef.current.mode === "coding") {
          setShowHistory(false);
          setOffset(0);
        }
        setRefresh((value) => value + 1);
      }
      if (next !== "active") invalidate();
      previous = next;
    });
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "hidden") invalidate();
      else if (AppState.currentState === "active") {
        activeRef.current = true;
        if (scopeRef.current.mode === "coding") {
          setShowHistory(false);
          setOffset(0);
        }
        setRefresh((value) => value + 1);
      }
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      subscription.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  const currentData = activeRef.current && AppState.currentState !== "background" && AppState.currentState !== "inactive"
    && (typeof document === "undefined" || document.visibilityState !== "hidden")
    && data?.api === api && data.mode === mode && data.projectId === projectId
    && data.offset === offset && data.showHistory === showHistory ? data : null;
  const currentMessage = activeRef.current && AppState.currentState !== "background" && AppState.currentState !== "inactive"
    && (typeof document === "undefined" || document.visibilityState !== "hidden")
    && message?.scope.api === api && message.scope.mode === mode
    && message.scope.projectId === projectId && message.scope.offset === offset
    && message.scope.showHistory === showHistory ? message.text : "";

  function openCurrent(identity: WorkspaceIdentity) {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (isCurrent(generation.current, requestScope)) onOpen(identity);
  }

  const refreshAfterError = useCallback(async (error: unknown, requestScope: QueueScope) => {
    setBusy(false);
    actionInFlight.current = false;
    if (requestScope.mode === "coding") {
      const nextMessage = { scope: { ...requestScope, offset: 0, showHistory: false }, text: errorText(error) };
      actionError.current = nextMessage;
      setMessage(nextMessage);
      setOffset(0);
      setShowHistory(false);
      setRefresh((value) => value + 1);
    } else {
      const nextMessage = { scope: requestScope, text: errorText(error) };
      actionError.current = nextMessage;
      setMessage(nextMessage);
      await load();
    }
  }, [load]);

  async function allocateRandom() {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (busy || actionInFlight.current || mode !== "coding" || !allocationVerified || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.allocateCoding(undefined, projectId);
      if (!isCurrent(requestGeneration, requestScope)) return;
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  async function allocateReviewer(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (busy || actionInFlight.current || mode !== "reviewing" || !allocationVerified || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.allocateReviewer(vaSid);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "reviewing" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  async function releaseAllocation(requestGeneration: number, requestScope: typeof scopeRef.current) {
    if (busy || actionInFlight.current || !isCurrent(requestGeneration, requestScope)) return;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      if (mode === "coding") await api.releaseCoding();
      else await api.releaseReviewer();
      if (!isCurrent(requestGeneration, requestScope)) return;
      actionError.current = null;
      setMessage({ scope: requestScope, text: mode === "coding" ? "Coding case released." : "Review case released. Step 1 is kept; NQA and Social Autopsy are cleared." });
      setBusy(false);
      actionInFlight.current = false;
      await load();
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
        setBusy(false);
        actionInFlight.current = false;
        await refreshAfterError(error, requestScope);
      }
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  function askRelease() {
    const requestGeneration = generation.current;
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (!isCurrent(requestGeneration, requestScope)) return;
    const warning = t(mode === "reviewing" ? "releaseReviewWarning" : "releaseCodingWarning");
    const proceed = () => {
      if (isCurrent(requestGeneration, requestScope)) void releaseAllocation(requestGeneration, requestScope);
    };
    if (Platform.OS === "web") {
      setConfirmRelease({ warning, proceed });
      return;
    }
    Alert.alert(
      t("releaseCaseTitle"),
      warning,
      [
        { text: t("cancel"), style: "cancel" },
        { text: t("releaseCaseAction"), style: "destructive", onPress: proceed },
      ],
    );
  }

  const allocation = allocationData?.api === api && allocationData.mode === mode
    && allocationData.generation === generation.current ? allocationData.snapshot : null;
  const allocationVerified = allocationData?.api === api && allocationData.mode === mode
    && allocationData.generation === generation.current && allocationData.verified;
  const stats = currentData?.stats;
  const projects = catalogReady ? catalog?.projects : undefined;

  // The allocation snapshot carries only the SID; one workspace read per held case names its form and project.
  const [heldCase, setHeldCase] = useState<{ api: WorkspaceApi; mode: "coding" | "reviewing"; vaSid: string; formId: string; deceasedName: string | null; projectCode: string | null; siteCode: string | null } | null>(null);
  const heldCaseRef = useRef(heldCase);
  heldCaseRef.current = heldCase;
  const allocationSid = allocation?.va_sid;
  useEffect(() => {
    const known = heldCaseRef.current;
    if (!allocationSid || (known?.api === api && known.mode === mode && known.vaSid === allocationSid)) return undefined;
    let active = true;
    void Promise.resolve()
      .then(() => api.getWorkspace(allocationSid, mode))
      .then((workspace) => {
        if (active) setHeldCase({ api, mode, vaSid: allocationSid, formId: workspace.case.instance_name, deceasedName: workspace.case.deceased_name ?? null, projectCode: workspace.case.project_code ?? null, siteCode: workspace.case.site_code ?? null });
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [allocationSid, api, mode]);
  const heldLabel = allocation && heldCase?.api === api && heldCase.mode === mode && heldCase.vaSid === allocation.va_sid ? heldCase : null;
  // Same "Project / Site" the case workspace shows; the project's name when its code is also a catalogue id.
  const heldProjectName = heldLabel?.projectCode
    ? projects?.project_options.find((option) => option.project_id === heldLabel.projectCode)?.project_name ?? null
    : null;
  const heldText = heldLabel
    ? [heldLabel.deceasedName, heldLabel.formId, `Project / Site: ${heldLabel.projectCode ?? "-"}/${heldLabel.siteCode ?? "-"}`, heldProjectName].filter(Boolean).join(" · ")
    : "";
  const coderStats = mode === "coding" && stats && "random_ready" in stats ? stats : undefined;
  const reviewerStats = mode === "reviewing" && stats && "available" in stats ? stats : undefined;
  const randomReady = coderStats?.random_ready;
  const canAllocateRandom = mode === "coding"
    && allocationVerified
    && coderStats?.has_random_mode === true
    && typeof randomReady === "number"
    && randomReady > 0;
  const coderCount = showHistory ? currentData?.coderHistory?.history.length : currentData?.coderAvailable?.forms.length;
  const reviewerRows = showHistory ? currentData?.history?.history : currentData?.available?.cases;
  const canGoNext = mode === "coding"
    ? showHistory ? currentData?.coderHistory?.has_more : currentData?.coderAvailable?.has_more
    : showHistory ? currentData?.history?.has_more : currentData?.available?.has_more;

  // Random-only coders have nothing to pick by hand, so their list is the coded-case history.
  // lastPickMode (declared above load) keeps the tab row from flickering while page loads clear stats.
  if (coderStats) lastPickMode.current = coderStats.has_pick_mode === true;
  const pickMode = coderStats ? coderStats.has_pick_mode === true : lastPickMode.current === true;
  if (coderStats) lastRandomMode.current = coderStats.has_random_mode === true;
  const randomMode = coderStats ? coderStats.has_random_mode === true : lastRandomMode.current !== false;
  const pickReady = typeof coderStats?.pick_ready === "number" ? coderStats.pick_ready : undefined;
  let readyText = "Availability is loading.";
  if (typeof randomReady === "number" || pickReady !== undefined) {
    if (randomMode && pickMode && typeof randomReady === "number" && pickReady !== undefined) readyText = `${randomReady} random · ${pickReady} to pick`;
    else readyText = `${(randomMode ? randomReady : pickReady) ?? 0} ready`;
  }
  useEffect(() => {
    if (coderStats && (!pickMode || (pickReady === 0 && randomMode && typeof randomReady === "number" && randomReady > 0)) && !showHistory) {
      setOffset(0);
      setShowHistory(true);
    }
  }, [coderStats, pickMode, pickReady, randomMode, randomReady, showHistory]);
  // A project that has pick mode (after one that had not) must not stay stuck on the history tab.
  const wasPickMode = useRef(pickMode || showHistory);
  useEffect(() => {
    if (pickMode && (pickReady === undefined || pickReady > 0) && !wasPickMode.current && showHistory) {
      setOffset(0);
      setShowHistory(false);
    }
    wasPickMode.current = pickMode && (pickReady === undefined || pickReady > 0);
  }, [pickMode, pickReady, showHistory]);

  const viewChanged = useRef(onViewChange);
  viewChanged.current = onViewChange;
  useEffect(() => {
    if (catalogReady) viewChanged.current?.({ projectId, showHistory, offset });
  }, [catalogReady, projectId, showHistory, offset]);

  const activeItems = useMemo<AnyQueueCase[]>(() => {
    if (mode === "coding") {
      return showHistory
        ? (currentData?.coderHistory?.history ?? [])
        : (currentData?.coderAvailable?.forms ?? []);
    }
    return reviewerRows ?? [];
  }, [currentData, mode, reviewerRows, showHistory]);

  const siteOptions = useMemo(() => {
    const sites = new Set<string>();
    for (const item of activeItems) {
      if (item.site_id && !isInternalPlaceholderArea(item.site_id)) sites.add(item.site_id);
    }
    return Array.from(sites);
  }, [activeItems]);

  const hasGenderData = useMemo(
    () => activeItems.some((item) => Boolean(item.va_deceased_gender)),
    [activeItems],
  );

  const hasRecodeableData = useMemo(
    () => mode === "coding" && showHistory && activeItems.some((item) => "recodeable" in item && item.recodeable === true),
    [activeItems, mode, showHistory],
  );

  const matchesCase = useCallback((item: AnyQueueCase): boolean => {
    if (siteFilter === "__within_area__") {
      const primaryArea = siteOptions[0];
      if (primaryArea && item.site_id !== primaryArea) return false;
    } else if (siteFilter && item.site_id !== siteFilter) {
      return false;
    }
    if (genderFilter !== "all" && normalizeGenderKey(item.va_deceased_gender) !== genderFilter) return false;
    if (recodeableOnly && mode === "coding" && showHistory) {
      if (!("recodeable" in item && item.recodeable === true)) return false;
    }
    const query = searchQuery.trim().toLowerCase();
    if (!query) return true;
    const haystack = [
      item.va_uniqueid_masked,
      "deceased_name" in item ? item.deceased_name : undefined,
      item.va_form_id,
      item.project_id,
      item.site_id,
      item.va_submission_date,
      "va_data_collector" in item ? item.va_data_collector : undefined,
      "va_code_status" in item ? item.va_code_status : undefined,
      "va_narration_language" in item ? item.va_narration_language : undefined,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  }, [genderFilter, mode, recodeableOnly, searchQuery, showHistory, siteFilter, siteOptions]);

  const filteredCoderHistory = useMemo(
    () => (currentData?.coderHistory?.history ?? []).filter(matchesCase),
    [currentData?.coderHistory?.history, matchesCase],
  );
  const filteredCoderAvailable = useMemo(
    () => (currentData?.coderAvailable?.forms ?? []).filter(matchesCase),
    [currentData?.coderAvailable?.forms, matchesCase],
  );
  const filteredReviewerRows = useMemo(
    () => (reviewerRows ?? []).filter(matchesCase),
    [matchesCase, reviewerRows],
  );

  const hasActiveFilters = searchQuery.trim().length > 0 || genderFilter !== "all" || siteFilter !== undefined || recodeableOnly;
  const filteredCount = mode === "coding"
    ? (showHistory ? filteredCoderHistory.length : filteredCoderAvailable.length)
    : filteredReviewerRows.length;

  function renderFilterControls() {
    if (activeItems.length === 0) return null;
    return (
      <View style={q.filterBox}>
        <TextInput
          accessibilityLabel="Filter cases"
          placeholder="Filter by ID, area, collector, or form..."
          placeholderTextColor={colors.textMuted}
          value={searchQuery}
          onChangeText={setSearchQuery}
          style={q.searchInput}
        />
        {(hasGenderData || hasRecodeableData) ? (
          <View style={q.chipRow}>
            {hasGenderData ? (
              <>
                {([
                  { key: "all" as const, label: "All sexes" },
                  { key: "female" as const, label: "Female" },
                  { key: "male" as const, label: "Male" },
                ]).map((opt) => {
                  const active = genderFilter === opt.key;
                  return (
                    <Pressable
                      key={opt.key}
                      hitSlop={spacing.xs}
                      accessibilityRole="button"
                      accessibilityLabel={`Filter sex: ${opt.label}`}
                      accessibilityState={{ selected: active }}
                      onPress={() => setGenderFilter(opt.key)}
                      style={[q.chip, active && q.chipActive]}
                    >
                      <Text style={[q.chipText, active && q.chipTextActive]}>{opt.label}</Text>
                    </Pressable>
                  );
                })}
              </>
            ) : null}
            {hasRecodeableData ? (
              <Pressable
                hitSlop={spacing.xs}
                accessibilityRole="button"
                accessibilityLabel="Filter recodeable only"
                accessibilityState={{ selected: recodeableOnly }}
                onPress={() => setRecodeableOnly((prev) => !prev)}
                style={[q.chip, recodeableOnly && q.chipActive]}
              >
                <Text style={[q.chipText, recodeableOnly && q.chipTextActive]}>Recodeable only</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {siteOptions.length > 1 ? (
          <View style={q.chipRow}>
            <Pressable
              hitSlop={spacing.xs}
              accessibilityRole="button"
              accessibilityLabel="Filter area: Within Area"
              accessibilityState={{ selected: siteFilter === "__within_area__" }}
              onPress={() => setSiteFilter(siteFilter === "__within_area__" ? undefined : "__within_area__")}
              style={[q.chip, siteFilter === "__within_area__" && q.chipActive]}
            >
              <Text style={[q.chipText, siteFilter === "__within_area__" && q.chipTextActive]}>Within Area</Text>
            </Pressable>
            <Pressable
              hitSlop={spacing.xs}
              accessibilityRole="button"
              accessibilityLabel="Filter area: All"
              accessibilityState={{ selected: siteFilter === undefined }}
              onPress={() => setSiteFilter(undefined)}
              style={[q.chip, siteFilter === undefined && q.chipActive]}
            >
              <Text style={[q.chipText, siteFilter === undefined && q.chipTextActive]}>All</Text>
            </Pressable>
            {siteOptions.map((site) => {
              const active = siteFilter === site;
              return (
                <Pressable
                  key={site}
                  hitSlop={spacing.xs}
                  accessibilityRole="button"
                  accessibilityLabel={`Filter area: ${site}`}
                  accessibilityState={{ selected: active }}
                  onPress={() => setSiteFilter(active ? undefined : site)}
                  style={[q.chip, active && q.chipActive]}
                >
                  <Text style={[q.chipText, active && q.chipTextActive]}>{site}</Text>
                </Pressable>
              );
            })}
          </View>
        ) : null}
        {hasActiveFilters ? (
          <View style={q.chipRow}>
            <Text style={styles.muted}>Showing {filteredCount} of {activeItems.length} cases</Text>
            <Pressable
              hitSlop={spacing.xs}
              accessibilityRole="button"
              accessibilityLabel="Clear filters"
              onPress={() => {
                setSearchQuery("");
                setGenderFilter("all");
                setSiteFilter(undefined);
                setRecodeableOnly(false);
              }}
              style={q.chip}
            >
              <Text style={q.chipText}>Clear filters</Text>
            </Pressable>
          </View>
        ) : null}
      </View>
    );
  }

  /** Allocate a SID from the current server page; mismatches fail and action errors survive refresh. */
  async function allocatePicked(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (busy || actionInFlight.current || mode !== "coding" || showHistory || !allocationVerified || allocation || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.allocateCoding(vaSid, projectId);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  /** Recode a server-marked history SID; mismatches fail and action errors survive refresh. */
  async function recodeCase(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (busy || actionInFlight.current || mode !== "coding" || !showHistory || !allocationVerified || allocation || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.recode(vaSid);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  /** Why the reviewer list is empty, in plain words; the counts alone do not say. */
  function reviewerEmptyText(): string {
    if (showHistory) return "No reviewed cases yet.";
    if (offset > 0) return "No more cases to review.";
    const where = projectId === undefined ? "in your projects" : "in this project";
    if (reviewerStats?.in_scope === 0) return `No cases ${where} yet.`;
    if (reviewerStats && reviewerStats.available === 0) {
      return `Nothing to review ${where} yet: cases appear here after a coder finalises them.`;
    }
    return "No cases to review right now.";
  }

  function refreshCases() {
    clearMessage();
    setShowHistory(false);
    setOffset(0);
    setRefresh((value) => value + 1);
  }

  return (
    <ActiveShell
      title={mode === "coding" ? "Coding queue" : "Review queue"}
      headerAction={onExit ? <Button label="Back" kind="secondary" size="sm" onPress={onExit} /> : undefined}
    >
      <ContextualHelpBanner screen={mode === "coding" ? "coding" : "reviewing"} />
      {loading ? <ActivityIndicator accessibilityLabel="Loading queue" /> : null}
      {currentMessage ? <Text accessibilityRole="alert" style={styles.error}>{currentMessage}</Text> : null}

      {allocation && !currentData?.cachedHistoryAt ? (
        <View style={styles.card}>
          <Text style={styles.headline}>{`You have an active ${mode === "coding" ? "coding" : "review"} case`}</Text>
          {heldText ? <Text style={styles.text}>{heldText}</Text> : null}
          <Text style={styles.muted}>Resume it, or release it, before you start another case.</Text>
          <View style={q.actions}>
            <Button label="Resume case" size="sm" style={q.actionBtn} disabled={busy || loading} onPress={() => openCurrent({ vaSid: allocation.va_sid, mode })} />
            <Button label="Release case" kind="danger" size="sm" style={q.actionBtn} disabled={busy || loading} onPress={askRelease} />
          </View>
        </View>
      ) : null}

      {projects?.project_options.length ? (
        <View style={styles.card}>
          {projects.project_options.length > 1 || (projectId === undefined && (startedOnAll.current || initialView?.projectId !== undefined)) ? (
            <ProjectPicker
              options={projects.project_options}
              value={projectId}
              disabled={busy}
              onSelect={(next) => { clearMessage(); setOffset(0); setProjectId(next); }}
            />
          ) : (
            <Text style={styles.text}>Project: {projects.project_options[0].project_name}</Text>
          )}
        </View>
      ) : null}

      {mode === "coding" ? (
        <View style={styles.card}>
          <View style={q.titleRow}>
            <View style={q.titleMain}>
              <Text style={styles.headline}>{randomMode ? "Random allocation" : "Pick a case"}</Text>
              <Text style={styles.muted}>{readyText}</Text>
            </View>
            <RefreshIcon disabled={busy || loading} onPress={refreshCases} />
          </View>
          {coderStats ? (
            <View style={q.statsGrid}>
              {randomMode && typeof coderStats.random_ready === "number" ? (
                <View style={q.statTile}>
                  <Text style={q.statValue}>{coderStats.random_ready}</Text>
                  <Text style={q.statLabel}>Random pool</Text>
                </View>
              ) : null}
              {pickMode && typeof coderStats.pick_ready === "number" ? (
                <View style={q.statTile}>
                  <Text style={q.statValue}>{coderStats.pick_ready}</Text>
                  <Text style={q.statLabel}>Ready to pick</Text>
                </View>
              ) : null}
              {typeof coderStats.completed === "number" ? (
                <View style={q.statTile}>
                  <Text style={q.statValue}>{coderStats.completed}</Text>
                  <Text style={q.statLabel}>Coded</Text>
                </View>
              ) : null}
              {typeof coderStats.not_codeable === "number" && coderStats.not_codeable > 0 ? (
                <View style={q.statTile}>
                  <Text style={q.statValue}>{coderStats.not_codeable}</Text>
                  <Text style={q.statLabel}>Not codeable</Text>
                </View>
              ) : null}
            </View>
          ) : null}
          {randomMode && !currentData?.cachedHistoryAt ? <Button label="Start a random case" size="sm" disabled={busy || loading || !canAllocateRandom || Boolean(allocation)} loading={busy} onPress={() => void allocateRandom()} /> : null}
          {pickMode ? (
            <View style={q.segmentedTrack}>
              <Button label="Available" size="sm" kind={!showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(false); setOffset(0); }} />
              <Button label="My coded cases" size="sm" accessibilityLabel="History" kind={showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(true); setOffset(0); }} />
            </View>
          ) : <Text style={styles.muted}>My coded cases</Text>}
          {currentData?.cachedHistoryAt ? <Text style={styles.muted} testID="cached-coding-history">Saved on this phone · last updated {formatDisplayTimestamp(currentData.cachedHistoryAt)} · read only</Text> : null}
          {renderFilterControls()}
          {showHistory ? filteredCoderHistory.map((item) => (
            <View key={item.va_sid} style={[styles.card, q.caseCard]}>
              <View style={q.caseHeader}>
                <View style={q.caseHeaderMain}>
                  <Text style={styles.headline}>{item.va_uniqueid_masked}</Text>
                  <Text style={styles.muted}>{[item.project_id, !isInternalPlaceholderArea(item.site_id) ? item.site_id : null, item.va_submission_date].filter(Boolean).join(" · ")}</Text>
                </View>
                {(item.va_code_status || item.recodeable) ? (
                  <View style={q.badgeRow}>
                    {item.va_code_status ? (
                      <View style={[q.badge, q.badgeAccent]}>
                        <Text style={[q.badgeText, q.badgeAccentText]}>{item.va_code_status}</Text>
                      </View>
                    ) : null}
                    {item.recodeable ? (
                      <View style={[q.badge, q.badgeAccent]}>
                        <Text style={[q.badgeText, q.badgeAccentText]}>Recodeable</Text>
                      </View>
                    ) : null}
                  </View>
                ) : null}
              </View>
              <CaseCardDetails item={item} />
              {codingServerStatusText(item) ? <Text style={styles.muted} testID={`coding-server-status-${item.va_sid}`}>{codingServerStatusText(item)}</Text> : null}
              {recodeDeadlineText(item) ? <Text style={styles.muted} testID={`recode-deadline-${item.va_sid}`}>{recodeDeadlineText(item)}</Text> : null}
              {!currentData?.cachedHistoryAt ? <View style={q.actions}>
                <Button label="View case" kind="secondary" size="sm" style={q.actionBtn} disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
                {item.recodeable ? <Button label="Recode" size="sm" style={q.actionBtn} disabled={busy || loading || !allocationVerified || Boolean(allocation)} loading={busy} onPress={() => void recodeCase(item.va_sid)} /> : null}
              </View> : null}
            </View>
          )) : filteredCoderAvailable.map((item) => (
            <View key={item.va_sid} style={[styles.card, q.caseCard]}>
              <View style={q.caseHeader}>
                <View style={q.caseHeaderMain}>
                  {item.deceased_name ? <Text style={styles.headline}>{item.deceased_name}</Text> : null}
                  <Text style={item.deceased_name ? styles.muted : styles.headline}>{item.va_uniqueid_masked}</Text>
                  <Text style={styles.muted}>{[item.project_id, !isInternalPlaceholderArea(item.site_id) ? item.site_id : null, item.va_submission_date].filter(Boolean).join(" · ")}</Text>
                </View>
              </View>
              <CaseCardDetails item={item} />
              <Button label="Pick case" size="sm" disabled={busy || loading || !allocationVerified || Boolean(allocation) || coderStats?.has_pick_mode !== true} loading={busy} onPress={() => void allocatePicked(item.va_sid)} />
            </View>
          ))}
          {(projects as CoderProjects | undefined)?.station_coding_disabled ? <Text style={styles.muted} testID="coding-done-on-server">{t("codingDoneOnServer")}</Text> : null}
          {coderCount === 0 ? <Text style={styles.muted}>{showHistory ? "No coded cases yet." : pickMode ? "No cases to pick right now." : "No available cases on this page."}</Text> : null}
          {(coderCount ?? 0) > 0 && filteredCount === 0 ? <Text style={styles.muted}>No cases match your filters.</Text> : null}
          <View style={q.pager}>
            <Button label="Previous" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={q.pageText}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </View>
        </View>
      ) : (
        <View style={styles.card}>
          <View style={q.titleRow}>
            <View style={q.titleMain}>
              <Text style={styles.headline}>Reviewer queue</Text>
              <Text style={styles.muted}>
                {reviewerStats ? `${reviewerStats.available} available · ${reviewerStats.completed} completed` : "Queue counts are loading."}
              </Text>
            </View>
            <RefreshIcon disabled={busy || loading} onPress={refreshCases} />
          </View>
          {reviewerStats ? (
            <View style={q.statsGrid}>
              <View style={q.statTile}>
                <Text style={q.statValue}>{String(reviewerStats.available ?? 0)}</Text>
                <Text style={q.statLabel}>Available to review</Text>
              </View>
              <View style={q.statTile}>
                <Text style={q.statValue}>{String(reviewerStats.completed ?? 0)}</Text>
                <Text style={q.statLabel}>Reviewed</Text>
              </View>
              {typeof reviewerStats.in_scope === "number" ? (
                <View style={q.statTile}>
                  <Text style={q.statValue}>{reviewerStats.in_scope}</Text>
                  <Text style={q.statLabel}>In scope</Text>
                </View>
              ) : null}
            </View>
          ) : null}
          <View style={q.segmentedTrack}>
            <Button label="Available" size="sm" kind={!showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(false); setOffset(0); }} />
            <Button label="My reviewed cases" size="sm" accessibilityLabel="History" kind={showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(true); setOffset(0); }} />
          </View>
          {renderFilterControls()}
          {filteredReviewerRows.map((item) => (
            <View key={item.va_sid} style={[styles.card, q.caseCard]}>
              <View style={q.caseHeader}>
                <View style={q.caseHeaderMain}>
                  <Text style={styles.headline}>{item.va_uniqueid_masked}</Text>
                  <Text style={styles.muted}>{[item.project_id, !isInternalPlaceholderArea(item.site_id) ? item.site_id : null, item.va_submission_date].filter(Boolean).join(" · ")}</Text>
                </View>
                {item.va_narration_language ? (
                  <View style={q.badgeRow}>
                    <View style={[q.badge, q.badgeAccent]}>
                      <Text style={[q.badgeText, q.badgeAccentText]}>{item.va_narration_language}</Text>
                    </View>
                  </View>
                ) : null}
              </View>
              <CaseCardDetails item={item} />
              {showHistory ? (
                <Button label="View case" kind="secondary" size="sm" disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
              ) : (
                <Button label="Review case" size="sm" disabled={busy || loading || !allocationVerified || Boolean(allocation)} loading={busy} onPress={() => void allocateReviewer(item.va_sid)} />
              )}
            </View>
          ))}
          {reviewerRows?.length === 0 ? <Text style={styles.muted}>{reviewerEmptyText()}</Text> : null}
          {(reviewerRows?.length ?? 0) > 0 && filteredReviewerRows.length === 0 ? <Text style={styles.muted}>No cases match your filters.</Text> : null}
          <View style={q.pager}>
            <Button label="Previous" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={q.pageText}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </View>
        </View>
      )}
      {confirmRelease ? <ConfirmDialog
        destructive
        title={t("releaseCaseTitle")}
        message={confirmRelease.warning}
        confirmLabel={t("releaseCaseAction")}
        onCancel={() => setConfirmRelease(null)}
        onConfirm={() => {
          const pending = confirmRelease;
          setConfirmRelease(null);
          pending.proceed();
        }}
      /> : null}
    </ActiveShell>
  );
}
