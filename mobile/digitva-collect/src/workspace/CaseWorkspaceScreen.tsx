import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState as NativeAppState, Platform, Text, View } from "react-native";

import { ApiError } from "../api";
import { Button, Screen, errorText, styles } from "../ui";
import { CategoryPanel, CategoryValue } from "./CategoryPanel";
import { PrivateNotePanel } from "./PrivateNotePanel";
import { QualityPanels } from "./QualityPanels";
import { SimpleCodPanel } from "./SimpleCodPanel";
import { SmartvaStatusPanel } from "./SmartvaStatusPanel";
import { WorkflowHistory } from "./WorkflowHistory";
import type { WorkspaceApi } from "./api";
import type { CategoryPayload, NotePayload, WorkspaceIdentity, WorkspacePayload, WorkflowEvents } from "./contracts";
import { WorkspaceLayout } from "./WorkspaceLayout";

/** Own the secured, allocation-scoped workspace lifecycle and render its ordered categories. */
export function CaseWorkspaceScreen({
  identity,
  api,
  onExit,
  onDone,
  renderDoris,
  renderMedia,
}: {
  identity: WorkspaceIdentity;
  api: WorkspaceApi;
  onExit: () => void;
  onDone?: () => void;
  renderDoris?: (workspace: WorkspacePayload, onSaved: () => Promise<void>, onDone: () => void) => ReactNode;
  renderMedia?: (attachmentPath: string) => ReactNode;
}) {
  const [loadedWorkspace, setLoadedWorkspace] = useState<{ vaSid: string; mode: WorkspaceIdentity["mode"]; api: WorkspaceApi; payload: WorkspacePayload } | null>(null);
  const [loadedCategory, setLoadedCategory] = useState<{ vaSid: string; mode: WorkspaceIdentity["mode"]; api: WorkspaceApi; payload: CategoryPayload } | null>(null);
  const [selectedCode, setSelectedCode] = useState("");
  const selectedCategory = useRef("");
  const [savedNote, setSavedNote] = useState<{ api: WorkspaceApi; vaSid: string; mode: WorkspaceIdentity["mode"]; note: NotePayload } | null>(null);
  const [loadedEvents, setLoadedEvents] = useState<{ vaSid: string; mode: "view"; api: WorkspaceApi; cursor: string | null; payload: WorkflowEvents } | null>(null);
  const [loading, setLoading] = useState(true);
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyRetryCursor, setHistoryRetryCursor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [qualityError, setQualityError] = useState("");
  const generation = useRef(0);
  const categoryGeneration = useRef(0);
  const eventGeneration = useRef(0);
  const eventInFlight = useRef<number | null>(null);
  const suspended = useRef(false);
  const nativeActive = useRef(NativeAppState.currentState === "active");
  const browserVisible = useRef(typeof document === "undefined" || document.visibilityState === "visible");
  /** Keep private case data scoped to a foreground, visible screen. */
  const canReadPrivateData = useCallback(() => !suspended.current
    && nativeActive.current
    && NativeAppState.currentState === "active"
    && browserVisible.current
    && (typeof document === "undefined" || document.visibilityState === "visible"), []);
  const context = useRef({ api, vaSid: identity.vaSid, mode: identity.mode });
  context.current = { api, vaSid: identity.vaSid, mode: identity.mode };
  const callbacks = useRef({ onExit, onDone });
  callbacks.current = { onExit, onDone };
  const workspace = loadedWorkspace?.vaSid === identity.vaSid && loadedWorkspace.mode === identity.mode && loadedWorkspace.api === api ? loadedWorkspace.payload : null;
  const category = loadedCategory?.vaSid === identity.vaSid && loadedCategory.mode === identity.mode && loadedCategory.api === api ? loadedCategory.payload : null;
  const currentEvents = loadedEvents?.vaSid === identity.vaSid && loadedEvents.mode === identity.mode && loadedEvents.api === api ? loadedEvents : null;
  const events = currentEvents?.payload ?? null;

  const finish = useCallback(() => {
    (callbacks.current.onDone ?? callbacks.current.onExit)();
  }, []);

  const loseAllocation = useCallback(() => {
    generation.current += 1;
    categoryGeneration.current += 1;
    eventGeneration.current += 1;
    eventInFlight.current = null;
    setLoadedWorkspace(null);
    setLoadedCategory(null);
    setLoadedEvents(null);
    setSavedNote(null);
    setHistoryLoading(false);
    setHistoryRetryCursor(null);
    setError(identity.mode === "view" ? "You no longer have access to this case." : "Your case allocation is no longer active.");
    callbacks.current.onExit();
  }, [identity.mode]);

  const loadEvents = useCallback(async (cursor: string | undefined, workspaceRequest: number) => {
    if (eventInFlight.current !== null || identity.mode !== "view" || !canReadPrivateData()) return;
    const request = ++eventGeneration.current;
    const current = () => eventGeneration.current === request
      && generation.current === workspaceRequest
      && canReadPrivateData()
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    if (!current()) return;
    eventInFlight.current = request;
    setHistoryLoading(true);
    setHistoryError("");
    setHistoryRetryCursor(cursor ?? null);
    try {
      const options = cursor === undefined ? { limit: 50 } : { limit: 50, cursor };
      const payload = await api.getWorkflowEvents(identity.vaSid, options);
      if (current()) {
        setLoadedEvents({ vaSid: identity.vaSid, mode: "view", api, cursor: cursor ?? null, payload });
        setHistoryRetryCursor(null);
      }
    } catch (historyError) {
      if (!current()) return;
      if (historyError instanceof ApiError && historyError.status === 403) loseAllocation();
      else setHistoryError(errorText(historyError));
    } finally {
      if (eventInFlight.current === request) eventInFlight.current = null;
      if (current()) setHistoryLoading(false);
    }
  }, [api, canReadPrivateData, identity.mode, identity.vaSid, loseAllocation]);

  const loadCategory = useCallback(async (code: string, workspaceRequest: number) => {
    if (!canReadPrivateData()) return;
    const request = ++categoryGeneration.current;
    const current = () => generation.current === workspaceRequest
      && categoryGeneration.current === request
      && canReadPrivateData()
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    setSelectedCode(code);
    selectedCategory.current = code;
    setLoadedCategory(null);
    setCategoryLoading(true);
    setError("");
    try {
      const result = await api.getCategory(identity.vaSid, code, identity.mode);
      if (current()) setLoadedCategory({ vaSid: identity.vaSid, mode: identity.mode, api, payload: result });
    } catch (loadError) {
      if (!current()) return;
      if (loadError instanceof ApiError && loadError.status === 403) loseAllocation();
      else setError(errorText(loadError));
    } finally {
      if (current()) setCategoryLoading(false);
    }
  }, [api, canReadPrivateData, identity.mode, identity.vaSid, loseAllocation]);

  const loadWorkspace = useCallback(async (preserveCategory?: string) => {
    if (!canReadPrivateData()) return;
    const request = ++generation.current;
    eventGeneration.current += 1;
    eventInFlight.current = null;
    const current = () => generation.current === request
      && canReadPrivateData()
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    categoryGeneration.current += 1;
    setLoading(preserveCategory === undefined);
    setCategoryLoading(false);
    if (preserveCategory === undefined) {
      setLoadedWorkspace(null);
      setLoadedCategory(null);
      setSavedNote(null);
    }
    setLoadedEvents(null);
    setHistoryLoading(false);
    setHistoryError("");
    setHistoryRetryCursor(null);
    setError("");
    setQualityError("");
    try {
      const result = await api.getWorkspace(identity.vaSid, identity.mode);
      if (!current()) return;
      setLoadedWorkspace({ vaSid: identity.vaSid, mode: identity.mode, api, payload: result });
      setLoading(false);
      const preferred = preserveCategory === undefined ? result.default_category : selectedCategory.current || preserveCategory;
      const defaultCategory = result.categories.find((item) => item.code === preferred)
        ?? result.categories.find((item) => item.code === result.default_category) ?? result.categories[0];
      if (defaultCategory) void loadCategory(defaultCategory.code, request);
      if (identity.mode === "view") {
        void loadEvents(undefined, request);
      }
    } catch (loadError) {
      if (!current()) return;
      setLoading(false);
      if (loadError instanceof ApiError && loadError.status === 403) loseAllocation();
      else setError(errorText(loadError));
    }
  }, [api, canReadPrivateData, identity.mode, identity.vaSid, loadCategory, loadEvents, loseAllocation]);

  const reloadAfterCodSave = useCallback(async (blockedMessage?: string) => {
    await loadWorkspace();
    if (blockedMessage && !suspended.current) setQualityError(blockedMessage);
  }, [loadWorkspace]);

  useEffect(() => {
    void loadWorkspace();
    return () => {
      generation.current += 1;
      categoryGeneration.current += 1;
      eventGeneration.current += 1;
      eventInFlight.current = null;
    };
  }, [loadWorkspace]);

  useEffect(() => {
    const suspend = () => {
      suspended.current = true;
      generation.current += 1;
      categoryGeneration.current += 1;
      eventGeneration.current += 1;
      eventInFlight.current = null;
      setHistoryLoading(false);
      setHistoryError("");
      setHistoryRetryCursor(null);
      setLoadedWorkspace(null);
      setLoadedCategory(null);
      setLoadedEvents(null);
      setSavedNote(null);
      setLoading(true);
      setCategoryLoading(false);
    };
    let wasNativeHidden = !nativeActive.current;
    let wasBrowserHidden = !browserVisible.current;
    const resumeIfVisible = () => {
      if (!nativeActive.current || !browserVisible.current || (!wasNativeHidden && !wasBrowserHidden)) return;
      wasNativeHidden = false;
      wasBrowserHidden = false;
      suspended.current = false;
      void loadWorkspace();
    };
    const native = NativeAppState.addEventListener("change", (state) => {
      nativeActive.current = state === "active";
      if (state !== "active") {
        suspend();
        wasNativeHidden = true;
      } else {
        resumeIfVisible();
      }
    });
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      browserVisible.current = document.visibilityState === "visible";
      if (document.visibilityState !== "visible") {
        suspend();
        wasBrowserHidden = true;
      } else {
        resumeIfVisible();
      }
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      native.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [loadWorkspace]);

  const saveQuality = async (save: () => Promise<unknown>) => {
    const request = generation.current;
    const current = () => generation.current === request
      && !suspended.current
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    setQualityError("");
    try {
      await save();
      if (!current()) return;
      await loadWorkspace(Platform.OS === "web" ? selectedCategory.current : undefined);
    } catch (saveError) {
      if (!current()) return;
      if (saveError instanceof ApiError && saveError.status === 403) loseAllocation();
      else setQualityError(errorText(saveError));
    }
  };

  const noteChanged = useCallback((note: NotePayload | null) => {
    if (!canReadPrivateData() || context.current.api !== api || context.current.vaSid !== identity.vaSid || context.current.mode !== identity.mode) return;
    setSavedNote(note ? { api, vaSid: identity.vaSid, mode: identity.mode, note } : null);
  }, [api, canReadPrivateData, identity.mode, identity.vaSid]);

  const identityKey = `${identity.mode}:${identity.vaSid}`;
  if (loading || !workspace) {
    return <Screen title="Case workspace" headerAction={<Button label="Exit" kind="secondary" onPress={onExit} />}>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : <Text style={styles.muted}>Loading case…</Text>}
    </Screen>;
  }

  const privateNotes = identity.mode !== "view" ? (
    <PrivateNotePanel key={identityKey} identity={{ vaSid: identity.vaSid, mode: identity.mode as "coding" | "reviewing" }} api={api} onAllocationLost={loseAllocation} onNoteChanged={noteChanged} />
  ) : null;
  const browser = Platform.OS === "web";
  const selectedMode = workspace.categories.find((item) => item.code === selectedCode)?.render_mode;
  const qualityPanels = identity.mode !== "view" ? <>
    <QualityPanels
      narrative={!browser || selectedMode === "attachments" ? workspace.narrative_qa : null}
      socialAutopsy={!browser || selectedCode === "social_autopsy" ? workspace.social_autopsy : null}
      onSaveNarrative={(body) => saveQuality(() => api.saveNarrativeQuality(identity.vaSid, body, identity.mode as "coding" | "reviewing"))}
      onSaveSocialAutopsy={(body) => saveQuality(() => api.saveSocialAutopsy(identity.vaSid, body, identity.mode as "coding" | "reviewing"))}
    />
    {qualityError ? <Text accessibilityRole="alert" style={styles.error}>{qualityError}</Text> : null}
  </> : null;
  const currentNote = savedNote?.api === api && savedNote.vaSid === identity.vaSid && savedNote.mode === identity.mode ? savedNote.note : null;
  const noteSummary = identity.mode !== "view" ? <View style={styles.card}>
    <Text style={styles.text}>{!currentNote ? "Open Notes to view your saved note." : currentNote.content ? noteText(currentNote.content) : "No note saved for this submission yet."}</Text>
  </View> : undefined;
  const nextBlockedReason = identity.mode !== "view" && category?.blocked_by?.length
    ? category.blocked_by.map((code) => code === "narrative_qa" ? "Complete the Narrative Quality Assessment before proceeding." : code === "social_autopsy" ? "Save the Social Autopsy Analysis before proceeding to the next category." : `Complete the required assessment (${code}) before proceeding.`).join(" ")
    : undefined;

  return (
    <WorkspaceLayout
      identity={identity}
      workspace={workspace}
      categories={workspace.categories}
      selectedCode={selectedCode}
      categoryLoading={categoryLoading}
      onSelectCategory={(code) => void loadCategory(code, generation.current)}
      onExit={onExit}
      notes={Platform.OS === "web" ? privateNotes : undefined}
      nextBlockedReason={nextBlockedReason}
      smartvaPanel={browser ? <SmartvaStatusPanel api={api} identity={identity} status={workspace.smartva_status} canRun={workspace.smartva_can_run} resultVisible={workspace.smartva !== null} onChanged={() => loadWorkspace(selectedCategory.current)} /> : undefined}
    >
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {category ? <CategoryPanel category={category} iconName={workspace.categories.find((item) => item.code === selectedCode)?.icon_name} renderMedia={renderMedia} categoryNav={workspace.categories} workspaceIdentity={`${identityKey}:${selectedCode}`} notesSummary={noteSummary} afterContent={browser ? qualityPanels : undefined} /> : null}
      {selectedCode === "vacodassessment" && identity.mode !== "view" ? (
        <View key={identityKey}>
          {workspace.case.project_mode.endsWith("_doris") ? (
            renderDoris ? renderDoris(workspace, loadWorkspace, finish) : <Text style={styles.muted}>DORIS coding editor is not available.</Text>
          ) : (
            <SimpleCodPanel workspace={workspace} identity={{ vaSid: identity.vaSid, mode: identity.mode }} api={api} onSaved={reloadAfterCodSave} onAllocationLost={loseAllocation} onDone={finish} />
          )}
          {browser ? null : qualityPanels}
          {Platform.OS === "web" ? null : privateNotes}
        </View>
      ) : null}
      {identity.mode === "view" ? (
        <>
          <CaseReference workspace={workspace} />
          <WorkflowHistory
            events={events}
            cursor={currentEvents?.cursor ?? null}
            loading={historyLoading}
            error={historyError}
            onOlder={() => {
              if (events?.next_cursor) void loadEvents(events.next_cursor, generation.current);
            }}
            onLatest={() => void loadEvents(undefined, generation.current)}
            onRetry={() => void loadEvents(historyRetryCursor ?? undefined, generation.current)}
          />
        </>
      ) : null}
    </WorkspaceLayout>
  );
}

/** Existing rich-text notes use Quill insert operations; render their text without HTML. */
function noteText(content: string): string {
  try {
    const parsed: unknown = JSON.parse(content);
    if (parsed && typeof parsed === "object" && "ops" in parsed && Array.isArray(parsed.ops)) {
      return parsed.ops.map((operation: unknown) => operation && typeof operation === "object" && "insert" in operation && typeof operation.insert === "string" ? operation.insert : "").join("") || content;
    }
  } catch {
    // Plain-text notes are also supported.
  }
  return content;
}

/** Show only assessment and SmartVA reference fields actually served by the API. */
function CaseReference({ workspace }: { workspace: WorkspacePayload }) {
  const artifacts = [
    ["Final COD", workspace.assessments.final],
    ["Reviewer final", workspace.assessments.reviewer_final],
    ["Coder initial", workspace.assessments.coder_initial],
    ["Not codeable", workspace.assessments.not_codeable],
  ] as const;
  const hasArtifacts = artifacts.some(([, value]) => value !== null);
  return (
    <View>
      {hasArtifacts ? <View style={styles.card}>
        <Text accessibilityRole="header" style={styles.headline}>COD reference</Text>
        {artifacts.map(([label, assessment]) => assessment ? (
          <View key={label}>
            <Text style={styles.muted}>{label}</Text>
            {assessment.conclusive_cod ? <Text style={styles.text}>Conclusive cause: {assessment.conclusive_cod}</Text> : null}
            {assessment.immediate_cod ? <Text style={styles.text}>Immediate cause: {assessment.immediate_cod}</Text> : null}
            {assessment.antecedent_cod ? <Text style={styles.text}>Antecedent cause: {assessment.antecedent_cod}</Text> : null}
            {assessment.reason ? <Text style={styles.text}>Reason: {assessment.reason}</Text> : null}
            {assessment.other ? <Text style={styles.text}>Other: {assessment.other}</Text> : null}
            {assessment.remark ? <Text style={styles.text}>Remark: {assessment.remark}</Text> : null}
          </View>
        ) : null)}
      </View> : null}
      {workspace.smartva !== null ? <View style={styles.card}>
        <Text accessibilityRole="header" style={styles.headline}>SmartVA reference</Text>
        <CategoryValue value={workspace.smartva} />
      </View> : null}
    </View>
  );
}
