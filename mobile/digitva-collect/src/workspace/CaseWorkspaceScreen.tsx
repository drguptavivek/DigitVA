import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState as NativeAppState, Pressable, ScrollView, Text, View } from "react-native";

import { ApiError } from "../api";
import { Button, Screen, errorText, styles } from "../ui";
import { CategoryPanel, CategoryValue } from "./CategoryPanel";
import { PrivateNotePanel } from "./PrivateNotePanel";
import { QualityPanels } from "./QualityPanels";
import { SimpleCodPanel } from "./SimpleCodPanel";
import { WorkflowHistory } from "./WorkflowHistory";
import type { WorkspaceApi } from "./api";
import type { CategoryPayload, WorkspaceIdentity, WorkspacePayload, WorkflowEvents } from "./contracts";

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
  const [loadedEvents, setLoadedEvents] = useState<{ vaSid: string; api: WorkspaceApi; payload: WorkflowEvents } | null>(null);
  const [loading, setLoading] = useState(true);
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [qualityError, setQualityError] = useState("");
  const generation = useRef(0);
  const categoryGeneration = useRef(0);
  const suspended = useRef(false);
  const context = useRef({ api, vaSid: identity.vaSid, mode: identity.mode });
  context.current = { api, vaSid: identity.vaSid, mode: identity.mode };
  const callbacks = useRef({ onExit, onDone });
  callbacks.current = { onExit, onDone };
  const workspace = loadedWorkspace?.vaSid === identity.vaSid && loadedWorkspace.mode === identity.mode && loadedWorkspace.api === api ? loadedWorkspace.payload : null;
  const category = loadedCategory?.vaSid === identity.vaSid && loadedCategory.mode === identity.mode && loadedCategory.api === api ? loadedCategory.payload : null;
  const events = loadedEvents?.vaSid === identity.vaSid && loadedEvents.api === api ? loadedEvents.payload : null;

  const finish = useCallback(() => {
    (callbacks.current.onDone ?? callbacks.current.onExit)();
  }, []);

  const loseAllocation = useCallback(() => {
    generation.current += 1;
    categoryGeneration.current += 1;
    setLoadedWorkspace(null);
    setLoadedCategory(null);
    setLoadedEvents(null);
    setError(identity.mode === "view" ? "You no longer have access to this case." : "Your case allocation is no longer active.");
    callbacks.current.onExit();
  }, [identity.mode]);

  const loadCategory = useCallback(async (code: string, workspaceRequest: number) => {
    const request = ++categoryGeneration.current;
    const current = () => generation.current === workspaceRequest
      && categoryGeneration.current === request
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    setSelectedCode(code);
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
  }, [api, identity.mode, identity.vaSid, loseAllocation]);

  const loadWorkspace = useCallback(async () => {
    if (suspended.current) return;
    const request = ++generation.current;
    const current = () => generation.current === request
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    categoryGeneration.current += 1;
    setLoading(true);
    setCategoryLoading(false);
    setLoadedWorkspace(null);
    setLoadedCategory(null);
    setLoadedEvents(null);
    setError("");
    setQualityError("");
    try {
      const result = await api.getWorkspace(identity.vaSid, identity.mode);
      if (!current()) return;
      setLoadedWorkspace({ vaSid: identity.vaSid, mode: identity.mode, api, payload: result });
      setLoading(false);
      const defaultCategory = result.categories.find((item) => item.code === result.default_category) ?? result.categories[0];
      if (defaultCategory) void loadCategory(defaultCategory.code, request);
      if (identity.mode === "view") {
        setHistoryLoading(true);
        void api.getWorkflowEvents(identity.vaSid).then((nextEvents) => {
          if (current()) setLoadedEvents({ vaSid: identity.vaSid, api, payload: nextEvents });
        }).catch((historyError) => {
          if (!current()) return;
          if (historyError instanceof ApiError && historyError.status === 403) loseAllocation();
          else setError(errorText(historyError));
        }).finally(() => {
          if (current()) setHistoryLoading(false);
        });
      }
    } catch (loadError) {
      if (!current()) return;
      setLoading(false);
      if (loadError instanceof ApiError && loadError.status === 403) loseAllocation();
      else setError(errorText(loadError));
    }
  }, [api, identity.mode, identity.vaSid, loadCategory, loseAllocation]);

  const reloadAfterCodSave = useCallback(async (blockedMessage?: string) => {
    await loadWorkspace();
    if (blockedMessage && !suspended.current) setQualityError(blockedMessage);
  }, [loadWorkspace]);

  useEffect(() => {
    void loadWorkspace();
    return () => {
      generation.current += 1;
      categoryGeneration.current += 1;
    };
  }, [loadWorkspace]);

  useEffect(() => {
    const suspend = () => {
      suspended.current = true;
      generation.current += 1;
      categoryGeneration.current += 1;
      setLoadedWorkspace(null);
      setLoadedCategory(null);
      setLoadedEvents(null);
      setLoading(true);
      setCategoryLoading(false);
    };
    let wasHidden = false;
    const native = NativeAppState.addEventListener("change", (state) => {
      if (state !== "active") {
        suspend();
        wasHidden = true;
      } else if (wasHidden) {
        wasHidden = false;
        suspended.current = false;
        void loadWorkspace();
      }
    });
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState !== "visible") {
        suspend();
        wasHidden = true;
      } else if (wasHidden) {
        wasHidden = false;
        suspended.current = false;
        void loadWorkspace();
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
      await loadWorkspace();
    } catch (saveError) {
      if (!current()) return;
      if (saveError instanceof ApiError && saveError.status === 403) loseAllocation();
      else setQualityError(errorText(saveError));
    }
  };

  const identityKey = `${identity.mode}:${identity.vaSid}`;
  if (loading || !workspace) {
    return <Screen title="Case workspace" headerAction={<Button label="Exit" kind="secondary" onPress={onExit} />}>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : <Text style={styles.muted}>Loading case…</Text>}
    </Screen>;
  }

  return (
    <Screen title={workspace.case.instance_name} headerAction={<Button label="Exit" kind="secondary" onPress={onExit} />} sidebar={(
      <ScrollView accessibilityLabel="Case categories" style={styles.card}>
        {workspace.categories.map((item) => (
          <Pressable key={item.code} accessibilityRole="button" accessibilityState={{ selected: selectedCode === item.code }} onPress={() => void loadCategory(item.code, generation.current)}>
            <Text style={selectedCode === item.code ? styles.headline : styles.text}>{item.nav_label}</Text>
          </Pressable>
        ))}
      </ScrollView>
    )}>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {categoryLoading ? <Text style={styles.muted}>Loading category…</Text> : null}
      {category ? <CategoryPanel category={category} renderMedia={renderMedia} /> : null}
      {selectedCode === "vacodassessment" && identity.mode !== "view" ? (
        <View key={identityKey}>
          {workspace.case.project_mode.endsWith("_doris") ? (
            renderDoris ? renderDoris(workspace, loadWorkspace, finish) : <Text style={styles.muted}>DORIS coding editor is not available.</Text>
          ) : (
            <SimpleCodPanel workspace={workspace} identity={{ vaSid: identity.vaSid, mode: identity.mode }} api={api} onSaved={reloadAfterCodSave} onAllocationLost={loseAllocation} onDone={finish} />
          )}
          <QualityPanels
            narrative={workspace.narrative_qa}
            socialAutopsy={workspace.social_autopsy}
            onSaveNarrative={(body) => saveQuality(() => api.saveNarrativeQuality(identity.vaSid, body, identity.mode as "coding" | "reviewing"))}
            onSaveSocialAutopsy={(body) => saveQuality(() => api.saveSocialAutopsy(identity.vaSid, body, identity.mode as "coding" | "reviewing"))}
          />
          {qualityError ? <Text accessibilityRole="alert" style={styles.error}>{qualityError}</Text> : null}
          <PrivateNotePanel key={identityKey} identity={{ vaSid: identity.vaSid, mode: identity.mode as "coding" | "reviewing" }} api={api} onAllocationLost={loseAllocation} />
        </View>
      ) : null}
      {identity.mode === "view" ? (
        <>
          <CaseReference workspace={workspace} />
          {historyLoading ? <Text style={styles.muted}>Loading workflow history…</Text> : <WorkflowHistory events={events} />}
        </>
      ) : null}
    </Screen>
  );
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
