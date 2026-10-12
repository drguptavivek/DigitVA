import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, AppState, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, Screen, errorText, useUiStyles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { QueueView } from "./viewState";
import type { AllocationSnapshot, CoderHistory, CoderQueue, ProjectOptions, CodingStats, ReviewerHistory, ReviewerQueue, ReviewerStats, WorkspaceIdentity } from "./contracts";

const PAGE_SIZE = 50;
const MAX_OFFSET = 1_000_000;

type QueueScope = { api: WorkspaceApi; mode: "coding" | "reviewing"; projectId?: string; offset: number; showHistory: boolean };

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
};

type AllocationData = { api: WorkspaceApi; mode: "coding" | "reviewing"; generation: number; verified: boolean; snapshot: AllocationSnapshot | null };
type QueueMessage = { scope: QueueScope; text: string };

function useQueueStyles() {
  const { colors } = useTheme();
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
    actionBtn: { flexGrow: 1, flexBasis: 140, minHeight: 44 },
    pager: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    pagerBtn: { flex: 1, minHeight: 44 },
    pageText: { flex: 1, textAlign: "center", ...typography.body, color: colors.text, fontFamily: controls.fontFamily },
  }), [colors]);
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
}: {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  onOpen: (identity: WorkspaceIdentity) => void;
  onExit?: () => void;
  /** Project, tab and page from the URL, already parsed; the project is checked against the catalogue before use. */
  initialView?: QueueView;
  /** Reports the settled project, tab and page so the route can keep them in the URL across a reload. */
  onViewChange?: (view: { projectId?: string; showHistory: boolean; offset: number }) => void;
}) {
  const styles = useUiStyles();
  const q = useQueueStyles();
  const [projectId, setProjectId] = useState<string | undefined>(initialView?.projectId);
  const [offset, setOffset] = useState(initialView?.offset ?? 0);
  const [showHistory, setShowHistory] = useState(initialView?.showHistory ?? false);
  const startedOnAll = useRef(initialView?.allProjects === true);
  const [data, setData] = useState<QueueData | null>(null);
  const [allocationData, setAllocationData] = useState<AllocationData | null>(null);
  const [catalog, setCatalog] = useState<{ api: WorkspaceApi; mode: "coding" | "reviewing"; projects?: ProjectOptions } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<QueueMessage | null>(null);
  const [refresh, setRefresh] = useState(0);
  const generation = useRef(0);
  // null until the first coder stats answer; load() uses it to pick the tab before fetching a page.
  const lastPickMode = useRef<boolean | null>(null);
  // Same for random mode, so the card title does not flip while a project's stats load.
  const lastRandomMode = useRef<boolean | null>(null);
  const actionInFlight = useRef(false);
  const actionError = useRef<QueueMessage | null>(null);
  const scopeRef = useRef<QueueScope>({ api, mode, projectId, offset, showHistory });
  scopeRef.current = { api, mode, projectId, offset, showHistory };
  const activeRef = useRef(AppState.currentState !== "background" && AppState.currentState !== "inactive" && (typeof document === "undefined" || document.visibilityState !== "hidden"));

  function clearMessage() {
    actionError.current = null;
    setMessage(null);
  }

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
        if (!actionError.current) setMessage({ scope: requestScope, text: errorText(error) });
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
      if (isCurrent(requestGeneration, requestScope)) setData(next);
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
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
  }, [api, catalogReady, mode, offset, projectId, showHistory]);

  // Load the project catalogue once per api and mode; the last project is the default, when still offered.
  useEffect(() => {
    let active = true;
    const request = mode === "coding" ? api.getCodingProjects() : api.getReviewerProjects();
    void request.then((projects) => {
      if (!active) return;
      const offered = (id: string | null | undefined) => id != null && projects.project_options.some((option) => option.project_id === id);
      // A project named by the URL that is not offered (stale or edited) falls back to All projects.
      setProjectId((current) => {
        if (current !== undefined) return offered(current) ? current : undefined;
        return !startedOnAll.current && offered(projects.last_project_id) ? projects.last_project_id ?? undefined : undefined;
      });
      setCatalog({ api, mode, projects });
    }).catch(() => {
      if (!active) return;
      setProjectId(undefined);
      setCatalog({ api, mode });
    });
    return () => {
      active = false;
    };
  }, [api, mode]);

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

  function confirmRelease() {
    const requestGeneration = generation.current;
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (!isCurrent(requestGeneration, requestScope)) return;
    const warning = mode === "reviewing"
      ? "The saved Step 1 is kept. Your Narrative QA and Social Autopsy analysis are cleared."
      : "An unfinished saved Step 1 will be discarded. Unsaved work may also be lost.";
    const proceed = () => {
      if (isCurrent(requestGeneration, requestScope)) void releaseAllocation(requestGeneration, requestScope);
    };
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(`Release this case?\n\n${warning}`)) proceed();
      return;
    }
    Alert.alert(
      "Release this case?",
      warning,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Release", style: "destructive", onPress: proceed },
      ],
    );
  }

  const allocation = allocationData?.api === api && allocationData.mode === mode
    && allocationData.generation === generation.current ? allocationData.snapshot : null;
  const allocationVerified = allocationData?.api === api && allocationData.mode === mode
    && allocationData.generation === generation.current && allocationData.verified;
  const stats = currentData?.stats;
  const projects = catalogReady ? catalog?.projects : undefined;
  const coderStats = mode === "coding" && stats && "random_ready" in stats ? stats : undefined;
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
    if (coderStats && !pickMode && !showHistory) { setOffset(0); setShowHistory(true); }
  }, [coderStats, pickMode, showHistory]);
  // A project that has pick mode (after one that had not) must not stay stuck on the history tab.
  const wasPickMode = useRef(pickMode || showHistory);
  useEffect(() => {
    if (pickMode && !wasPickMode.current && showHistory) { setOffset(0); setShowHistory(false); }
    wasPickMode.current = pickMode;
  }, [pickMode, showHistory]);

  const viewChanged = useRef(onViewChange);
  viewChanged.current = onViewChange;
  useEffect(() => {
    if (catalogReady) viewChanged.current?.({ projectId, showHistory, offset });
  }, [catalogReady, projectId, showHistory, offset]);

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

  function refreshCases() {
    clearMessage();
    setShowHistory(false);
    setOffset(0);
    setRefresh((value) => value + 1);
  }

  return (
    <Screen
      title={mode === "coding" ? "Coding queue" : "Review queue"}
      headerAction={onExit ? <Button label="Back" kind="secondary" onPress={onExit} /> : undefined}
    >
      {loading ? <ActivityIndicator accessibilityLabel="Loading queue" /> : null}
      {currentMessage ? <Text accessibilityRole="alert" style={styles.error}>{currentMessage}</Text> : null}

      {projects?.project_options.length ? (
        <View style={styles.card}>
          {projects.project_options.length > 1 ? (
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

      {allocation ? (
        <View style={styles.card}>
          <Text style={styles.headline}>You have an active {mode === "coding" ? "coding" : "review"} case</Text>
          <View style={q.actions}>
            <Button label="Resume case" style={q.actionBtn} disabled={busy || loading} onPress={() => openCurrent({ vaSid: allocation.va_sid, mode })} />
            <Button label="Release case" kind="danger" style={q.actionBtn} disabled={busy || loading} onPress={confirmRelease} />
          </View>
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
          {randomMode ? <Button label="Start a random case" disabled={busy || loading || !canAllocateRandom || Boolean(allocation)} loading={busy} onPress={() => void allocateRandom()} /> : null}
          {pickMode ? (
            <View style={q.actions}>
              <Button label="Available" kind={!showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(false); setOffset(0); }} />
              <Button label="My coded cases" accessibilityLabel="History" kind={showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(true); setOffset(0); }} />
            </View>
          ) : <Text style={styles.muted}>My coded cases</Text>}
          {showHistory ? currentData?.coderHistory?.history.map((item) => (
            <View key={item.va_sid} style={styles.card}>
              <Text style={styles.headline}>{item.va_uniqueid_masked}</Text>
              <Text style={styles.text}>{item.project_id} · {item.site_id} · {item.va_submission_date}</Text>
              <Button label="View case" kind="secondary" disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
              {item.recodeable ? <Button label="Recode" disabled={busy || loading || !allocationVerified || Boolean(allocation)} loading={busy} onPress={() => void recodeCase(item.va_sid)} /> : null}
            </View>
          )) : currentData?.coderAvailable?.forms.map((item) => (
            <View key={item.va_sid} style={styles.card}>
              <Text style={styles.headline}>{item.va_uniqueid_masked}</Text>
              <Text style={styles.text}>{item.project_id} · {item.site_id} · {item.va_submission_date}</Text>
              <Button label="Pick case" disabled={busy || loading || !allocationVerified || Boolean(allocation) || coderStats?.has_pick_mode !== true} loading={busy} onPress={() => void allocatePicked(item.va_sid)} />
            </View>
          ))}
          {coderCount === 0 ? <Text style={styles.muted}>{showHistory ? "No coded cases yet." : pickMode ? "No cases to pick right now." : "No available cases on this page."}</Text> : null}
          <View style={q.pager}>
            <Button label="Previous" kind="secondary" style={q.pagerBtn} disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={q.pageText}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" style={q.pagerBtn} disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </View>
        </View>
      ) : (
        <View style={styles.card}>
          <View style={q.titleRow}>
            <View style={q.titleMain}>
              <Text style={styles.headline}>Reviewer queue</Text>
              <Text style={styles.muted}>
                {stats && "available" in stats ? `${stats.available} available · ${stats.completed} completed` : "Queue counts are loading."}
              </Text>
            </View>
            <RefreshIcon disabled={busy || loading} onPress={refreshCases} />
          </View>
          <View style={q.actions}>
            <Button label="Available" kind={!showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(false); setOffset(0); }} />
            <Button label="My reviewed cases" accessibilityLabel="History" kind={showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => { clearMessage(); setShowHistory(true); setOffset(0); }} />
          </View>
          {reviewerRows?.map((item) => (
            <View key={item.va_sid} style={styles.card}>
              <Text style={styles.headline}>{item.va_uniqueid_masked}</Text>
              <Text style={styles.text}>{item.project_id} · {item.site_id} · {item.va_submission_date}</Text>
              {showHistory ? (
                <Button label="View case" kind="secondary" disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
              ) : (
                <Button label="Review case" disabled={busy || loading || !allocationVerified || Boolean(allocation)} loading={busy} onPress={() => void allocateReviewer(item.va_sid)} />
              )}
            </View>
          ))}
          {reviewerRows?.length === 0 ? <Text style={styles.muted}>{showHistory ? "No reviewed cases yet." : "No available cases on this page."}</Text> : null}
          <View style={q.pager}>
            <Button label="Previous" kind="secondary" style={q.pagerBtn} disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={q.pageText}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" style={q.pagerBtn} disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </View>
        </View>
      )}
    </Screen>
  );
}
