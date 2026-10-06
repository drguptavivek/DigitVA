import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, AppState, Platform, Text, View } from "react-native";

import { Button, Row, Screen, errorText, useUiStyles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { AllocationSnapshot, CodingStats, CoderProjects, ReviewerHistory, ReviewerQueue, ReviewerStats, WorkspaceIdentity } from "./contracts";

const PAGE_SIZE = 50;

type QueueData = {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  projectId?: string;
  offset: number;
  showHistory: boolean;
  stats?: CodingStats | ReviewerStats;
  allocation: AllocationSnapshot | null;
  projects?: CoderProjects;
  available?: ReviewerQueue;
  history?: ReviewerHistory;
};

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
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);
  const generation = useRef(0);
  const actionInFlight = useRef(false);
  const scopeRef = useRef({ api, mode, projectId, offset, showHistory });
  scopeRef.current = { api, mode, projectId, offset, showHistory };
  const activeRef = useRef(AppState.currentState !== "background" && AppState.currentState !== "inactive" && (typeof document === "undefined" || document.visibilityState !== "hidden"));

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
    setLoading(true);
    try {
      let next: QueueData;
      if (mode === "coding") {
        const [stats, allocation, projects] = await Promise.all([
          api.getCodingStats(projectId),
          api.getCodingAllocation(),
          api.getCodingProjects(),
        ]);
        next = { api, mode, projectId, offset, showHistory, stats, allocation, projects };
      } else {
        const [stats, allocation, page] = await Promise.all([
          api.getReviewerStats(),
          api.getReviewerAllocation(),
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
          allocation,
          ...(showHistory ? { history: page as ReviewerHistory } : { available: page as ReviewerQueue }),
        };
      }
      if (isCurrent(requestGeneration, requestScope)) setData(next);
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
        setData(null);
        setMessage(errorText(error));
      }
    } finally {
      if (isCurrent(requestGeneration, requestScope)) setLoading(false);
    }
  }, [api, mode, offset, projectId, showHistory]);

  useEffect(() => {
    setData(null);
    setBusy(false);
    actionInFlight.current = false;
    setMessage("");
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
      setBusy(false);
      setLoading(false);
    };
    const subscription = AppState.addEventListener("change", (next) => {
      activeRef.current = next === "active" && (typeof document === "undefined" || document.visibilityState !== "hidden");
      if (activeRef.current && previous !== "active") setRefresh((value) => value + 1);
      if (next !== "active") invalidate();
      previous = next;
    });
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "hidden") invalidate();
      else if (AppState.currentState === "active") {
        activeRef.current = true;
        setRefresh((value) => value + 1);
      }
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      subscription.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  const currentData = data?.api === api && data.mode === mode && data.projectId === projectId
    && data.offset === offset && data.showHistory === showHistory ? data : null;

  function openCurrent(identity: WorkspaceIdentity) {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (isCurrent(generation.current, requestScope)) onOpen(identity);
  }

  const refreshAfterError = useCallback(async (error: unknown) => {
    setMessage(errorText(error));
    setBusy(false);
    actionInFlight.current = false;
    await load();
  }, [load]);

  async function allocateRandom() {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (busy || actionInFlight.current || mode !== "coding" || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    setMessage("");
    try {
      const result = await api.allocateCoding(undefined, projectId);
      if (!isCurrent(requestGeneration, requestScope)) return;
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  async function allocateReviewer(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory };
    if (busy || actionInFlight.current || mode !== "reviewing" || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    setMessage("");
    try {
      const result = await api.allocateReviewer(vaSid);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "reviewing" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error);
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
    setMessage("");
    try {
      if (mode === "coding") await api.releaseCoding();
      else await api.releaseReviewer();
      if (!isCurrent(requestGeneration, requestScope)) return;
      setMessage(mode === "coding" ? "Coding case released." : "Review case released. Step 1 is kept; NQA and Social Autopsy are cleared.");
      setBusy(false);
      actionInFlight.current = false;
      await load();
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
        setBusy(false);
        actionInFlight.current = false;
        await refreshAfterError(error);
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

  const allocation = currentData?.allocation;
  const stats = currentData?.stats;
  const projects = currentData?.projects;
  const coderStats = mode === "coding" && stats && "random_ready" in stats ? stats : undefined;
  const randomReady = coderStats?.random_ready;
  const canAllocateRandom = mode === "coding"
    && coderStats?.has_random_mode === true
    && typeof randomReady === "number"
    && randomReady > 0;
  const reviewerRows = showHistory ? currentData?.history?.history : currentData?.available?.cases;
  const canGoNext = showHistory ? currentData?.history?.has_more : currentData?.available?.has_more;

  return (
    <Screen
      title={mode === "coding" ? "Coding queue" : "Review queue"}
      headerAction={onExit ? <Button label="Back" kind="secondary" onPress={onExit} /> : undefined}
    >
      {loading ? <ActivityIndicator accessibilityLabel="Loading queue" /> : null}
      {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}

      {mode === "coding" && projects?.project_options.length ? (
        <View style={styles.card}>
          <Text style={styles.headline}>Project</Text>
          <Row>
            <Button label="All projects" kind={projectId ? "secondary" : "primary"} disabled={busy} onPress={() => { setOffset(0); setProjectId(undefined); }} />
            {projects.project_options.map((project) => (
              <Button
                key={project.project_id}
                label={project.project_name}
                kind={projectId === project.project_id ? "primary" : "secondary"}
                disabled={busy}
                onPress={() => { setOffset(0); setProjectId(project.project_id); }}
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
          {coderStats?.has_pick_mode === true ? <Text style={styles.muted}>Pick from the case list when bounded queue paging is available.</Text> : null}
          <Text style={styles.muted}>Coding history is unavailable until bounded history paging is available.</Text>
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.headline}>Reviewer queue</Text>
          <Text style={styles.text}>
            {stats && "available" in stats ? `${stats.available} cases available · ${stats.completed} completed` : "Queue counts are loading."}
          </Text>
          <Row>
            <Button label="Available" kind={!showHistory ? "primary" : "secondary"} disabled={busy} onPress={() => { setShowHistory(false); setOffset(0); }} />
            <Button label="History" kind={showHistory ? "primary" : "secondary"} disabled={busy} onPress={() => { setShowHistory(true); setOffset(0); }} />
          </Row>
          {reviewerRows?.map((item) => (
            <View key={item.va_sid} style={styles.card}>
              <Text style={styles.headline}>{item.va_uniqueid_masked}</Text>
              <Text style={styles.text}>{item.project_id} · {item.site_id} · {item.va_submission_date}</Text>
              {showHistory ? (
                <Button label="View case" kind="secondary" disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
              ) : (
                <Button label="Review case" disabled={busy || loading || Boolean(allocation)} loading={busy} onPress={() => void allocateReviewer(item.va_sid)} />
              )}
            </View>
          ))}
          {reviewerRows?.length === 0 ? <Text style={styles.muted}>{showHistory ? "No review history on this page." : "No available cases on this page."}</Text> : null}
          <Row>
            <Button label="Previous" kind="secondary" disabled={busy || loading || offset === 0} onPress={() => setOffset(Math.max(0, offset - PAGE_SIZE))} />
            <Text style={styles.text}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" disabled={busy || loading || !canGoNext} onPress={() => setOffset(offset + PAGE_SIZE)} />
          </Row>
        </View>
      )}
    </Screen>
  );
}
