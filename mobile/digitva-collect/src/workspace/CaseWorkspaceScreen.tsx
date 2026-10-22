import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState as NativeAppState, Platform, Pressable, Text, View } from "react-native";

import { ApiError } from "../api";
import { Button, Screen, errorText, useUiStyles } from "../ui";
import { CategoryPanel } from "./CategoryPanel";
import { SmartVaReference } from "./SmartVaReference";
import { PrivateNotePanel } from "./PrivateNotePanel";
import { QualityPanels } from "./QualityPanels";
import { SimpleCodPanel } from "./SimpleCodPanel";
import { SmartvaStatusPanel } from "./SmartvaStatusPanel";
import { WorkflowHistory } from "./WorkflowHistory";
import type { WorkspaceApi } from "./api";
import type { CategoryPayload, NotePayload, WorkspaceAssessment, WorkspaceIdentity, WorkspacePayload, WorkflowEvents } from "./contracts";
import { browserSessionStore, clearScroll, resolveSection } from "./viewState";
import { WorkspaceLayout } from "./WorkspaceLayout";
import { ContextualHelpBanner } from "../web/ContextualHelp";

const VIEW_FINAL_CATEGORIES: WorkspacePayload["categories"] = [
  { code: "smartva_section", label: "SmartVA Analysis", nav_label: "SmartVA", render_mode: "table_sections", icon_name: "fa-chart-pie" },
  { code: "allocated_cod_section", label: "Allocated Causes of Death", nav_label: "Allocated Causes of Death", render_mode: "table_sections", icon_name: "fa-stethoscope" },
  { code: "audit_log_section", label: "Audit Log", nav_label: "Audit Log", render_mode: "table_sections", icon_name: "fa-history" },
];
const VIEW_FINAL_CODES = new Set(VIEW_FINAL_CATEGORIES.map((c) => c.code));

/** Own the secured, allocation-scoped workspace lifecycle and render its ordered categories. */
export function CaseWorkspaceScreen({
  identity,
  api,
  onExit,
  onDone,
  renderDoris,
  renderMedia,
  section,
  onSectionChange,
}: {
  identity: WorkspaceIdentity;
  api: WorkspaceApi;
  onExit: () => void;
  onDone?: () => void;
  renderDoris?: (workspace: WorkspacePayload, onSaved: () => Promise<void>, onDone: () => void) => ReactNode;
  renderMedia?: (attachmentPath: string) => ReactNode;
  /** Section code from the route (`?section=`); unknown or missing falls back to the server default. */
  section?: string;
  /** Called when the user picks a section, so the route can record it (replace, not push). */
  onSectionChange?: (code: string) => void;
}) {
  const styles = useUiStyles();
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
  const pendingSection = useRef(section);
  const callbacks = useRef({ onExit, onDone, onSectionChange });
  callbacks.current = { onExit, onDone, onSectionChange };
  /** Leaving the case forgets its saved scroll offsets. */
  const leave = useCallback(() => clearScroll(browserSessionStore(), context.current.mode, context.current.vaSid), []);
  const workspace = loadedWorkspace?.vaSid === identity.vaSid && loadedWorkspace.mode === identity.mode && loadedWorkspace.api === api ? loadedWorkspace.payload : null;
  const category = loadedCategory?.vaSid === identity.vaSid && loadedCategory.mode === identity.mode && loadedCategory.api === api ? loadedCategory.payload : null;
  const currentEvents = loadedEvents?.vaSid === identity.vaSid && loadedEvents.mode === identity.mode && loadedEvents.api === api ? loadedEvents : null;
  const events = currentEvents?.payload ?? null;

  const finish = useCallback(() => {
    leave();
    (callbacks.current.onDone ?? callbacks.current.onExit)();
  }, [leave]);

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
    leave();
    callbacks.current.onExit();
  }, [identity.mode, leave]);

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

  const loadCategory = useCallback(async (code: string, workspaceRequest: number, keepContent = false) => {
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
    // A refresh of the section already on screen (after a save) keeps its content until the new one
    // arrives, so the page does not collapse and jump to the top.
    if (!keepContent) {
      setLoadedCategory(null);
      setCategoryLoading(true);
    }
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
      // An intake-only view (the submitter or a supervisor) gets the answers, not the coding sections or history.
      const isWebViewMode = Platform.OS === "web" && identity.mode === "view" && result.case.history_available !== false;
      const allCategories = isWebViewMode ? [...result.categories, ...VIEW_FINAL_CATEGORIES] : result.categories;
      const wanted = preserveCategory === undefined ? resolveSection(allCategories, pendingSection.current) : undefined;
      pendingSection.current = undefined;
      const preferred = preserveCategory === undefined ? wanted ?? result.default_category : selectedCategory.current || preserveCategory;
      if (isWebViewMode && preferred && VIEW_FINAL_CODES.has(preferred)) {
        setSelectedCode(preferred);
        selectedCategory.current = preferred;
        setLoadedCategory(null);
        setCategoryLoading(false);
      } else {
        const defaultCategory = result.categories.find((item) => item.code === preferred)
          ?? result.categories.find((item) => item.code === result.default_category) ?? result.categories[0];
        if (defaultCategory) void loadCategory(defaultCategory.code, request, preserveCategory !== undefined);
      }
      if (identity.mode === "view" && result.case.history_available !== false) {
        void loadEvents(undefined, request);
      }
    } catch (loadError) {
      if (!current()) return;
      setLoading(false);
      if (loadError instanceof ApiError && loadError.status === 403) loseAllocation();
      else setError(errorText(loadError));
    }
  }, [api, canReadPrivateData, identity.mode, identity.vaSid, loadCategory, loadEvents, loseAllocation]);

  // Keeps the section the coder is in (VA COD Assessment after Save Step 1), not the first section.
  const reloadAfterCodSave = useCallback(async (blockedMessage?: string) => {
    await loadWorkspace(selectedCategory.current || undefined);
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
      // Coming back from the background keeps the section the user was on.
      pendingSection.current = selectedCategory.current || pendingSection.current;
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
    <PrivateNotePanel key={`${identityKey}:notes`} identity={{ vaSid: identity.vaSid, mode: identity.mode as "coding" | "reviewing" }} api={api} onAllocationLost={loseAllocation} onNoteChanged={noteChanged} />
  ) : null;
  const browser = Platform.OS === "web";
  const effectiveCategories = browser && identity.mode === "view" && workspace.case.history_available !== false
    ? [...workspace.categories, ...VIEW_FINAL_CATEGORIES]
    : workspace.categories;
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
  const reviewing = identity.mode === "reviewing";
  // Reviewers get the COD entry form right under the coder's COD, above the long reference content.
  const codEditor = selectedCode === "vacodassessment" && identity.mode !== "view" ? (
    <View key={`${identityKey}:cod`}>
      {workspace.case.project_mode.endsWith("_doris") ? (
        renderDoris ? renderDoris(workspace, loadWorkspace, finish) : <Text style={styles.muted}>DORIS coding editor is not available.</Text>
      ) : (
        <SimpleCodPanel workspace={workspace} identity={{ vaSid: identity.vaSid, mode: identity.mode }} api={api} onSaved={reloadAfterCodSave} onAllocationLost={loseAllocation} onDone={finish} />
      )}
    </View>
  ) : null;
  const nextBlockedReason = identity.mode !== "view" && category?.blocked_by?.length
    ? category.blocked_by.map((code) => code === "narrative_qa" ? "Complete the Narrative Quality Assessment before proceeding." : code === "social_autopsy" ? "Save the Social Autopsy Analysis before proceeding to the next category." : `Complete the required assessment (${code}) before proceeding.`).join(" ")
    : undefined;

  return (
    <WorkspaceLayout
      identity={identity}
      workspace={workspace}
      categories={effectiveCategories}
      selectedCode={selectedCode}
      categoryLoading={categoryLoading}
      onSelectCategory={(code) => {
        if (browser && identity.mode === "view" && VIEW_FINAL_CODES.has(code)) {
          setSelectedCode(code);
          selectedCategory.current = code;
          setCategoryLoading(false);
          callbacks.current.onSectionChange?.(code);
          return;
        }
        void loadCategory(code, generation.current);
        callbacks.current.onSectionChange?.(code);
      }}
      onExit={() => { leave(); onExit(); }}
      notes={Platform.OS === "web" ? privateNotes : undefined}
      nextBlockedReason={nextBlockedReason}
      smartvaPanel={browser && identity.mode !== "view" ? <SmartvaStatusPanel api={api} identity={identity} status={workspace.smartva_status} canRun={workspace.smartva_can_run} resultVisible={workspace.smartva !== null} onChanged={() => loadWorkspace(selectedCategory.current)} /> : undefined}
    >
      <ContextualHelpBanner
        screen={
          identity.mode === "coding"
            ? "caseCoding"
            : identity.mode === "reviewing"
              ? "caseReviewing"
              : "caseView"
        }
      />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {browser && identity.mode === "view" ? (
        selectedCode === "smartva_section" ? (
          workspace.smartva !== null ? (
            <SmartVaReference value={workspace.smartva} />
          ) : (
            <View style={styles.card}>
              <Text accessibilityRole="header" style={styles.headline}>SmartVA Analysis</Text>
              <Text style={styles.muted}>No SmartVA results are available for this submission.</Text>
            </View>
          )
        ) : selectedCode === "allocated_cod_section" ? (
          <AllocatedCodReference workspace={workspace} />
        ) : selectedCode === "audit_log_section" ? (
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
        ) : category ? (
          <CategoryPanel
            category={category}
            iconName={workspace.categories.find((item) => item.code === selectedCode)?.icon_name}
            renderMedia={renderMedia}
            categoryNav={workspace.categories}
            workspaceIdentity={`${identityKey}:${selectedCode}`}
            notesSummary={noteSummary}
            afterContent={qualityPanels}
          />
        ) : null
      ) : (
        <>
          {reviewing ? (
            // The web section heading pulls itself up by the card padding to sit flush with the card top;
            // the bottom padding here absorbs that so the heading never covers the coder's COD or the form.
            <View style={[{ gap: 12 }, browser ? ({ paddingBottom: "calc(var(--digitva-card-pad, 14px) + 12px)" } as object) : null]}>
              <CoderCodReference workspace={workspace} />
              {codEditor}
            </View>
          ) : null}
          {category ? <CategoryPanel category={category} iconName={workspace.categories.find((item) => item.code === selectedCode)?.icon_name} renderMedia={renderMedia} categoryNav={workspace.categories} workspaceIdentity={`${identityKey}:${selectedCode}`} notesSummary={noteSummary} afterContent={browser ? qualityPanels : undefined} /> : null}
          {selectedCode === "vacodassessment" && identity.mode !== "view" ? (
            <View key={identityKey}>
              {reviewing ? null : codEditor}
              {browser ? null : qualityPanels}
              {Platform.OS === "web" ? null : privateNotes}
            </View>
          ) : null}
          {identity.mode === "view" ? (
            <>
              <CaseReference workspace={workspace} />
              {workspace.case.history_available === false ? null : <WorkflowHistory
                events={events}
                cursor={currentEvents?.cursor ?? null}
                loading={historyLoading}
                error={historyError}
                onOlder={() => {
                  if (events?.next_cursor) void loadEvents(events.next_cursor, generation.current);
                }}
                onLatest={() => void loadEvents(undefined, generation.current)}
                onRetry={() => void loadEvents(historyRetryCursor ?? undefined, generation.current)}
              />}
            </>
          ) : null}
        </>
      )}
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

type Artifact = readonly [label: string, assessment: WorkspaceAssessment | null | undefined];

/** COD assessments as served, one block per non-null artifact; `empty` shows when none is present. */
function CodArtifacts({ title, artifacts, empty }: { title: string; artifacts: readonly Artifact[]; empty?: string }) {
  const styles = useUiStyles();
  if (!artifacts.some(([, value]) => value) && !empty) return null;
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>{title}</Text>
      <ArtifactList artifacts={artifacts} empty={empty} />
    </View>
  );
}

function ArtifactList({ artifacts, empty }: { artifacts: readonly Artifact[]; empty?: string }) {
  const styles = useUiStyles();
  const present = artifacts.filter(([, value]) => value);
  return (
    <>
      {present.length ? present.map(([label, assessment]) => assessment ? (
        <View key={label}>
          <Text style={styles.muted}>{label}</Text>
          {assessment.conclusive_cod ? <Text style={styles.text}>Conclusive cause: {assessment.conclusive_cod}</Text> : null}
          {assessment.immediate_cod ? <Text style={styles.text}>Immediate cause: {assessment.immediate_cod}</Text> : null}
          {assessment.antecedent_cod ? <Text style={styles.text}>Antecedent cause: {assessment.antecedent_cod}</Text> : null}
          {assessment.doris_code || assessment.doris_status ? <Text style={styles.text}>DORIS computed code: {assessment.doris_code || "-"}{assessment.doris_status ? ` (${assessment.doris_status})` : ""}</Text> : null}
          {assessment.reason ? <Text style={styles.text}>Reason: {assessment.reason}</Text> : null}
          {assessment.other ? <Text style={styles.text}>Other: {assessment.other}</Text> : null}
          {assessment.remark ? <Text style={styles.text}>Remark: {assessment.remark}</Text> : null}
        </View>
      ) : null) : empty ? <Text style={styles.muted}>{empty}</Text> : null}
    </>
  );
}

function referenceArtifacts(workspace: WorkspacePayload): Artifact[] {
  return [
    ["Final COD", workspace.assessments.final],
    ["Reviewer final", workspace.assessments.reviewer_final],
    ["Coder initial", workspace.assessments.coder_initial],
    ["Not codeable", workspace.assessments.not_codeable],
  ];
}

/** Show only assessment and SmartVA reference fields actually served by the API. */
function CaseReference({ workspace }: { workspace: WorkspacePayload }) {
  return (
    <View>
      <CodArtifacts title="COD reference" artifacts={referenceArtifacts(workspace)} />
      {workspace.smartva !== null ? <SmartVaReference value={workspace.smartva} /> : null}
    </View>
  );
}

function AllocatedCodReference({ workspace }: { workspace: WorkspacePayload }) {
  return <CodArtifacts title="Allocated Causes of Death" artifacts={referenceArtifacts(workspace)} empty="No cause-of-death assessments have been recorded for this submission yet." />;
}

/**
 * The coder's saved COD, read-only, shown to a reviewer in every section. Collapsed by default to one
 * line naming the coder's final cause; expanding shows every served artifact.
 */
function CoderCodReference({ workspace }: { workspace: WorkspacePayload }) {
  const styles = useUiStyles();
  const [open, setOpen] = useState(false);
  const { final, coder_initial: initial, not_codeable: notCodeable } = workspace.assessments;
  const summary = final?.conclusive_cod || final?.immediate_cod || (notCodeable ? "Not codeable" : "") || "Not recorded";
  return (
    <View style={styles.card}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Coder's cause of death: ${summary}`}
        accessibilityHint={open ? "Hides the coder's assessments" : "Shows the coder's assessments"}
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((value) => !value)}
        style={{ flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44 }}
      >
        <Text style={[styles.headline, { flex: 1, minWidth: 0 }]} numberOfLines={open ? undefined : 2}>Coder's cause of death: {summary}</Text>
        <Text style={styles.muted}>{open ? "Hide ▲" : "Details ▼"}</Text>
      </Pressable>
      {open ? <ArtifactList artifacts={[
        ["Coder final", final],
        ["Coder initial", initial],
        ["Not codeable", notCodeable],
      ]} empty="The coder has not saved an assessment." /> : null}
    </View>
  );
}
