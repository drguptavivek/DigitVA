import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, AppState, Platform, Text, View } from "react-native";

import { Button, Row, Screen, errorText, useUiStyles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { AllocationSnapshot, CoderHistory, CoderProjects, CoderQueue, CodingStats, ReviewerHistory, ReviewerQueue, ReviewerStats, WorkspaceIdentity } from "./contracts";

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

/**
 * Load and operate the coder or reviewer queue without reading the unbounded
 * coder pick/history routes. Requests are discarded when scope or app state changes.
 */
export function QueueScreen({
  api,
  mode,
  onOpen,
  onExit,
}: {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  onOpen: (identity: WorkspaceIdentity) => void;
  onExit?: () => void;
}) {
  const styles = useUiStyles();
  const [projectId, setProjectId] = useState<string>();
  const [offset, setOffset] = useState(0);
  const [showHistory, setShowHistory] = useState(false);
  const [data, setData] = useState<QueueData | null>(null);
  const [allocationData, setAllocationData] = useState<AllocationData | null>(null);
  const [coderProjects, setCoderProjects] = useState<{ api: WorkspaceApi; projects: CoderProjects } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<QueueMessage | null>(null);
  const [refresh, setRefresh] = useState(0);
  const generation = useRef(0);
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

  const load = useCallback(async () => {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (!isCurrent(generation.current, requestScope)) return;
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
        const [stats, projects, page] = await Promise.all([
          api.getCodingStats(projectId),
          api.getCodingProjects(),
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
        if (isCurrent(requestGeneration, requestScope)) setCoderProjects({ api, projects });
      } else {
        const [stats, page] = await Promise.all([
          api.getReviewerStats(),
          showHistory
            ? api.getReviewerHistory({ limit: PAGE_SIZE, offset })
            : api.getReviewerAvailable({ limit: PAGE_SIZE, offset }),
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
  }, [api, mode, offset, projectId, showHistory]);

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
  const projects = coderProjects?.api === api && mode === "coding" ? coderProjects.projects : undefined;
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

      {mode === "coding" && projects?.project_options.length ? (
        <View style={styles.card}>
          <Text style={styles.headline}>Project</Text>
          <Row>
            <Button label="All projects" kind={projectId ? "secondary" : "primary"} disabled={busy} onPress={() => { clearMessage(); setOffset(0); setProjectId(undefined); }} />
            {projects.project_options.map((project) => (
              <Button
                key={project.project_id}
                label={project.project_name}
                kind={projectId === project.project_id ? "primary" : "secondary"}
                disabled={busy}
                onPress={() => { clearMessage(); setOffset(0); setProjectId(project.project_id); }}
              />
            ))}
          </Row>
        </View>
      ) : null}

      {allocation ? (
        <View style={styles.card}>
          <Text style={styles.headline}>You have an active {mode === "coding" ? "coding" : "review"} case</Text>
          <Button label="Resume case" disabled={busy || loading} onPress={() => openCurrent({ vaSid: allocation.va_sid, mode })} />
          <Button label="Release case" kind="danger" disabled={busy || loading} onPress={confirmRelease} />
        </View>
      ) : null}

      {mode === "coding" ? (
        <View style={styles.card}>
          <Text style={styles.headline}>Random allocation</Text>
          <Text style={styles.text}>
            {typeof randomReady === "number" ? `${randomReady} cases are ready.` : "Availability is loading."}
          </Text>
          <Button label="Start a random case" disabled={busy || loading || !canAllocateRandom || Boolean(allocation)} loading={busy} onPress={() => void allocateRandom()} />
          <Row>
            <Button label="Available" kind={!showHistory ? "primary" : "secondary"} disabled={busy} onPress={() => { clearMessage(); setShowHistory(false); setOffset(0); }} />
            <Button label="History" kind={showHistory ? "primary" : "secondary"} disabled={busy} onPress={() => { clearMessage(); setShowHistory(true); setOffset(0); }} />
            <Button label="Refresh cases" kind="secondary" disabled={busy || loading} onPress={refreshCases} />
          </Row>
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
          {coderCount === 0 ? <Text style={styles.muted}>{showHistory ? "No coding history on this page." : "No available cases on this page."}</Text> : null}
          <Row>
            <Button label="Previous" kind="secondary" disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={styles.text}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </Row>
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.headline}>Reviewer queue</Text>
          <Text style={styles.text}>
            {stats && "available" in stats ? `${stats.available} cases available · ${stats.completed} completed` : "Queue counts are loading."}
          </Text>
          <Row>
            <Button label="Available" kind={!showHistory ? "primary" : "secondary"} disabled={busy} onPress={() => { clearMessage(); setShowHistory(false); setOffset(0); }} />
            <Button label="History" kind={showHistory ? "primary" : "secondary"} disabled={busy} onPress={() => { clearMessage(); setShowHistory(true); setOffset(0); }} />
            <Button label="Refresh queue" kind="secondary" disabled={busy || loading} onPress={refreshCases} />
          </Row>
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
          {reviewerRows?.length === 0 ? <Text style={styles.muted}>{showHistory ? "No review history on this page." : "No available cases on this page."}</Text> : null}
          <Row>
            <Button label="Previous" kind="secondary" disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={styles.text}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </Row>
        </View>
      )}
    </Screen>
  );
}
