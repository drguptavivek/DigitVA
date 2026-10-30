/**
 * Collect Plus only (APP_VARIANT=plus, src/appVariant.ts): pure-offline coding. Lists the signed-in interviewer's
 * completed-but-unsent interviews from the local store and opens one in the DORIS editor over the on-device ICD-11
 * engine (src/workspace/offlineDoris.ts). A confirmed save lands in the store's offline_coding table and the draft
 * keeps syncing as the interview; nothing syncs the coding in this phase. Only what the coder collected themselves
 * is shown: the local id, dates, org unit and coding status — names and answers stay in the form.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";

import { ApiError } from "../api";
import { accountStoreIdentityIsInSelectedMode } from "../accountStoreIdentity";
import { loadAccounts, loadActiveSlot } from "../auth";
import { useAppState } from "../AppState";
import { isPlusVariant } from "../appVariant";
import { canUseOfflineCoding } from "../codingCapabilities";
import type { Account } from "../auth";
import {
  getOfflineCoding,
  getOfflineCodingCase,
  getMeta,
  listDrafts,
  listOfflineCodingCases,
  saveOfflineCoding,
  setMeta,
  type Db,
  type DeviceTimedDraft,
  type OfflineCodingCase,
  type OfflineCodingCaseRow,
  type OfflineCodingRow
} from "../drafts";
import { isUnlocked, openInterviewerDb, StoreLockedError } from "../interviewerDb";
import { getOrCreatePlusDeviceIdentity } from "../offlineIdentity";
import { getOfflineProfile } from "../offlineProfile";
import { getCachedReferenceData } from "../sync";
import allowabilityPack from "../../assets/icd11-allowability-2026-01.json";
import { codingContextFromInterview, createAllowabilityIndex, extractIcd11CodeExpression, isCluster, type AllowabilityPack } from "../coding/icd11Allowability";
import { getBundledVaDefinition } from "../coding/bundledVaDefinitions";
import { errorText, Button, Screen, useUiStyles } from "../ui";
import { t } from "../i18n";
import { createGuidanceRequester, createOfflineDorisEditor, certificateSeedFromInterview, OfflineAllowabilityError, type OfflineCodingStore, type OfflineDorisEditor } from "../workspace/offlineDoris";
import type { JsonRequester, WorkspaceApi } from "../workspace/api";
import type { CodingWriteReply, DorisProcessReply, WorkspaceIdentity, WorkspacePayload } from "../workspace/contracts";
import { offlineEngine } from "../offlineEngine";
import { isIcd11DorisEnabled, useIcd11DorisPreference } from "../icd11DorisPreference";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { draftAnswersSha256 } from "../sync";
import { recordCodingTimeline } from "../draftSync";
import { acquireLocalCodingEditor } from "../localCodingLeases";
import { localDateTimeWithOffset } from "../client/localDateTime";
import { appendWorkflowEvent, workflowTimeline, type WorkflowTimelineEvent } from "../workflowTimeline";
import { isSmartVaOptionsSnapshot, projectSmartVaSnapshot, standaloneSmartVaSnapshot, type SmartVaOptionsSnapshot, type SmartVaTarget } from "../smartva/options";
import { getLocalSmartVa, isLocalSmartVaCurrent, type LocalSmartVaRow } from "../smartva/localStore";
import { runLocalSmartVa } from "../smartva/localApi";
import { ensureLocalSmartVa } from "../smartva/ensureLocal";
import { offlineSmartvaEngine } from "../smartva/nativeEngine";
import { SmartVaReference } from "../workspace/SmartVaReference";
import { DEFAULT_COVERED_FIELDS, consentForDraft } from "../consentStore";
import { isRefused } from "../refusalBoundary";

type Params = { userId?: string | string[]; caseId?: string | string[] };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The interviewer whose store the screen codes from: the route's `userId`, else the only signed-in account. */
function useOfflineUserId(): string | undefined {
  const { userId } = useLocalSearchParams<Params>();
  const { accounts } = useAppState();
  const wanted = first(userId);
  if (wanted) return accounts.some((account) => account.user_id === wanted) ? wanted : undefined;
  return accounts.length === 1 ? accounts[0].user_id : undefined;
}

function statusLabel(status: OfflineCodingStatusLike): string {
  return status === "coded" ? "Coded" : status === "rejected" ? "Rejected" : status === "draft" ? "Draft (engine did not complete)" : "Not coded";
}
type OfflineCodingStatusLike = OfflineCodingRow["status"] | null;

function datePart(iso: string | null | undefined): string {
  return typeof iso === "string" && iso.length >= 10 ? iso.slice(0, 10) : "";
}

/** The drafts.ts accessors, seen through the editor's store interface; recheck access at the write boundary. */
function offlineCodingStore(db: Db, assertAllowed: () => Promise<void>): OfflineCodingStore {
  return {
    save: async (row) => { await assertAllowed(); return saveOfflineCoding(db, row); },
    get: (clientDraftId) => getOfflineCoding(db, clientDraftId),
  };
}

/** Keep DorisPanel's in-memory request state tied to its open local store across account refreshes. */
const requesters = new WeakMap<Db, { target: { route: JsonRequester }; request: JsonRequester }>();
const CODING_EVENTS = new Set(["coding_opened", "doris_processed", "initial_saved", "final_saved"]);
const CODING_CLIENT_EVENTS = ["coding_opened", "doris_processed", "initial_saved"] as const;

function codingTimeline(value: unknown): WorkflowTimelineEvent[] {
  const events = workflowTimeline(value);
  if (events.length > 6 || events.some((event) => !CODING_EVENTS.has(event.event))) {
    throw new Error("offline_timeline_invalid");
  }
  return events;
}

/**
 * The requester DorisPanel keys its in-memory drafts on, so its identity stays one per open store across account
 * refreshes; what it answers with (the guidance routes of the current editor, see createGuidanceRequester) is swapped in.
 */
function offlineRequester(db: Db, route: JsonRequester): JsonRequester {
  let entry = requesters.get(db);
  if (!entry) {
    const target = { route };
    entry = { target, request: (path, init) => target.route(path, init) };
    requesters.set(db, entry);
  }
  entry.target.route = route;
  return entry.request;
}

/** Device + coder-profile references a save records for a future sync's provenance (never the profile itself). */
async function resolveOfflineSaveContext(): Promise<{ deviceUuid: string; coderProfileUpdatedAt: string | null }> {
  const identity = await getOrCreatePlusDeviceIdentity();
  if (!identity) throw new Error("offline_device_identity_unavailable");
  const profile = await getOfflineProfile();
  return { deviceUuid: identity.uuid, coderProfileUpdatedAt: profile?.updated_at ?? null };
}

/**
 * The workspace API surface DorisPanel touches, answered locally: the four
 * DORIS data callbacks run on the engine, a Step 1 save is stored in
 * offline_coding, VA definitions (a server crosswalk) answer none. Every
 * server-only call refuses, so an offline screen can never half-talk to a server.
 */
function offlineWorkspaceApi(
  db: Db,
  editor: OfflineDorisEditor,
  reply: { current: DorisProcessReply | null },
  timeline: { current: WorkflowTimelineEvent[] },
  vaSid: string,
  answersHash: (draftId: string) => Promise<string | null>,
  assertAllowed: () => Promise<void>,
): WorkspaceApi {
  const unavailable = (_name: string): never => { throw new Error("offline_server_unavailable"); };
  return {
    getWorkspace: () => unavailable("getWorkspace"),
    getCategory: () => unavailable("getCategory"),
    getCodingStats: () => unavailable("getCodingStats"),
    getCodingAvailable: () => unavailable("getCodingAvailable"),
    getCodingHistory: () => unavailable("getCodingHistory"),
    getCodingProjects: () => unavailable("getCodingProjects"),
    getCodingAllocation: () => unavailable("getCodingAllocation"),
    getReviewerProjects: () => unavailable("getReviewerProjects"),
    getReviewerStats: () => unavailable("getReviewerStats"),
    getReviewerAvailable: () => unavailable("getReviewerAvailable"),
    getReviewerHistory: () => unavailable("getReviewerHistory"),
    getReviewerAllocation: () => unavailable("getReviewerAllocation"),
    allocateCoding: () => unavailable("allocateCoding"),
    codeOwnSubmission: () => unavailable("codeOwnSubmission"),
    recode: () => unavailable("recode"),
    releaseCoding: () => unavailable("releaseCoding"),
    allocateReviewer: () => unavailable("allocateReviewer"),
    releaseReviewer: () => unavailable("releaseReviewer"),
    searchIcd: () => unavailable("searchIcd"),
    runSmartva: () => unavailable("runSmartva"),
    getSmartvaStatus: () => unavailable("getSmartvaStatus"),
    saveNarrativeQuality: () => unavailable("saveNarrativeQuality"),
    saveSocialAutopsy: () => unavailable("saveSocialAutopsy"),
    getNote: () => unavailable("getNote"),
    saveNote: () => unavailable("saveNote"),
    getWorkflowEvents: () => unavailable("getWorkflowEvents"),
    saveFinal: () => unavailable("saveFinal"),
    saveNotCodeable: () => unavailable("saveNotCodeable"),
    async searchDorisTerms(_vaSid, query, options) {
      await assertAllowed();
      return editor.onTerms(query, options?.limit, options?.subtreeUris);
    },
    async getDorisCodeInfo(_vaSid, code) { await assertAllowed(); return editor.onCodeInfo(code); },
    async checkDorisSelection(_vaSid, code, uri) { await assertAllowed(); return editor.onSelectionCheck(code, uri); },
    async getVaDefinitionForIcd(code) {
      await assertAllowed();
      const expression = extractIcd11CodeExpression(code);
      if (expression && isCluster(expression)) {
        return getBundledVaDefinition(expression, await editor.primaryStem(expression));
      }
      return getBundledVaDefinition(code);
    },
    async processDoris(_vaSid, _role, clientRevision, certificate) {
      await assertAllowed();
      const processed = await editor.onProcess(clientRevision, certificate);
      reply.current = processed;
      if (processed.doris.status === "completed") {
        const at = localDateTimeWithOffset();
        await assertAllowed();
        if (!await recordCodingTimeline(db, vaSid, "doris_processed", at)) throw new Error("offline_timeline_save_failed");
        timeline.current = codingTimeline(appendWorkflowEvent(timeline.current, "doris_processed", at));
      }
      return processed;
    },
    async saveInitial(_vaSid, body): Promise<CodingWriteReply> {
      await assertAllowed();
      const { deviceUuid, coderProfileUpdatedAt } = await resolveOfflineSaveContext();
      try {
        const answersSha256 = await answersHash(vaSid);
        await assertAllowed();
        const saved = await editor.save({
          clientDraftId: vaSid, body, reply: reply.current, deviceUuid, coderProfileUpdatedAt, answersSha256,
          workflowTimelineV1: timeline.current,
          codingTimelineV1: timeline.current,
        });
        await assertAllowed();
        if (!await recordCodingTimeline(db, vaSid, "initial_saved", saved.updated_at)) {
          throw new Error("offline_timeline_save_failed");
        }
        const local = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [vaSid]);
        if (!local) throw new Error("offline_case_missing");
        const localEnvelope = JSON.parse(local.envelope) as Record<string, unknown>;
        const persistedTimeline = codingTimeline(localEnvelope.codingTimelineV1);
        timeline.current = persistedTimeline;
        const coding = await getOfflineCoding(db, vaSid);
        if (coding) {
          const provenance: unknown = coding.provenance ? JSON.parse(coding.provenance) : {};
          if (!provenance || typeof provenance !== "object" || Array.isArray(provenance)) throw new Error("offline_save_invalid");
          await assertAllowed();
          await saveOfflineCoding(db, {
            ...coding,
            provenance: JSON.stringify({ ...(provenance as Record<string, unknown>), codingTimelineV1: persistedTimeline }),
          });
        }
      } catch (error) {
        // The shapes DorisPanel handles for the server's 400 invalid_cod and 422 age confirmation.
        if (!(error instanceof OfflineAllowabilityError)) throw error;
        if (error.kind === "age_confirm") {
          throw new ApiError(422, "AGE_RESTRICTION_CONFIRMATION_REQUIRED", undefined, undefined, { error: error.message, age_restriction: { ...error.restriction } });
        }
        throw new ApiError(400, "invalid_cod", undefined, undefined, { error: error.message, messages: [error.message] });
      }
      return { va_sid: vaSid };
    },
  };
}

// Built once: the bundled pack is indexed on first use and refuses to load if it is not understood.
let allowabilityIndex: ReturnType<typeof createAllowabilityIndex> | undefined;
const packIndex = () => (allowabilityIndex ??= createAllowabilityIndex(allowabilityPack as AllowabilityPack));

/** The editor's one case: minimal header (no PII beyond what this coder collected) plus the offline editor. */
function OfflineCase({ db, userId, clientDraftId, account, onDone }: { db: Db; userId: string; clientDraftId: string; account: Account; onDone: () => Promise<void> }) {
  const styles = useUiStyles();
  const engine = offlineEngine();
  const [loaded, setLoaded] = useState<{ row: OfflineCodingCase; draft: DeviceTimedDraft; coding: OfflineCodingRow | null; projectId: string; smartvaOptions: SmartVaOptionsSnapshot | null } | undefined>();
  const [smartvaCache, setSmartvaCache] = useState<LocalSmartVaRow | null>(null);
  const [smartvaAnswersHash, setSmartvaAnswersHash] = useState<string | null>(null);
  const [smartvaBusy, setSmartvaBusy] = useState(false);
  const [smartvaFailure, setSmartvaFailure] = useState("");
  const [smartvaAvailable, setSmartvaAvailable] = useState<boolean | undefined>(undefined);
  const [smartvaVersion, setSmartvaVersion] = useState<string | null>(null);
  const [failed, setFailed] = useState("");
  const [busy, setBusy] = useState(false);
  const [engineReady, setEngineReady] = useState(false);
  const [retry, setRetry] = useState(0);
  const lastReply = useRef<DorisProcessReply | null>(null);
  const timeline = useRef<WorkflowTimelineEvent[]>([]);
  const accountRef = useRef(account);
  accountRef.current = account;
  const releaseLease = useRef<(() => void) | null>(null);
  const initStarted = useRef(false);
  const smartvaEntryStarted = useRef(false);
  const allowed = !!loaded && canUseOfflineCoding(account, loaded.projectId);
  const assertNotRefused = useCallback(async () => {
    const row = await db.getFirstAsync<{ envelope: string; death_id: string | null; client_death_id: string | null }>(
      "SELECT envelope, death_id, client_death_id FROM drafts WHERE id = ?", [clientDraftId],
    );
    if (!row) throw new Error("offline_case_missing");
    const consent = await consentForDraft(db, { id: clientDraftId, death_id: row.death_id, client_death_id: row.client_death_id });
    if (await getMeta<boolean>(db, `consent:server-refused:${clientDraftId}`) === true || isRefused((JSON.parse(row.envelope) as DeviceTimedDraft).data, consent?.record.envelope.decision)) throw new Error("consent_refused");
  }, [db, clientDraftId]);
  const assertAllowed = useCallback(async () => {
    await assertNotRefused();
    if (!await isIcd11DorisEnabled()) throw new Error("icd11_doris_disabled");
    const slot = await loadActiveSlot();
    if (!await accountStoreIdentityIsInSelectedMode(userId)) throw new Error("offline_case_access_revoked");
    const currentAccount = (await loadAccounts(slot)).find((item) => item.user_id === userId);
    const draft = await db.getFirstAsync<{ project_id: string | null }>("SELECT project_id FROM drafts WHERE id = ?", [clientDraftId]);
    if (!currentAccount || !draft?.project_id || !canUseOfflineCoding(currentAccount, draft.project_id) || await loadActiveSlot() !== slot) {
      throw new Error("offline_case_access_revoked");
    }
  }, [db, clientDraftId, userId, assertNotRefused]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        if (releaseLease.current) return;
        const draft = await db.getFirstAsync<{ project_id: string | null; site_id: string }>("SELECT project_id, site_id FROM drafts WHERE id = ?", [clientDraftId]);
        if (!draft?.project_id || !canUseOfflineCoding(accountRef.current, draft.project_id)) {
          if (live) setFailed("offline_case_access_revoked");
          return;
        }
        await assertNotRefused();
        if (!smartvaEntryStarted.current) {
          smartvaEntryStarted.current = true;
          try {
            const result = await ensureLocalSmartVa({ db, userId, draftId: clientDraftId });
            if (result.status === "skipped" && result.reason === "busy") smartvaEntryStarted.current = false;
            if (result.status === "failed" && live) setSmartvaFailure(t("localSmartVaFailed"));
          } catch {
            if (live) setSmartvaFailure(t("localSmartVaFailed"));
          }
          if (!live) return;
        }
        const release = acquireLocalCodingEditor(userId, clientDraftId);
        if (!release) {
          if (live) setBusy(true);
          return;
        }
        if (!live) { release(); return; }
        releaseLease.current = release;
        setBusy(false);
        setFailed("");
        const row = await getOfflineCodingCase(db, clientDraftId);
        if (!row) throw new Error("offline_case_missing");
        const coding = await getOfflineCoding(db, clientDraftId);
        if (live) {
          const provenance: unknown = coding?.provenance ? JSON.parse(coding.provenance) : undefined;
          const storedTimeline = provenance && typeof provenance === "object" && !Array.isArray(provenance)
            ? codingTimeline((provenance as Record<string, unknown>).codingTimelineV1 ?? (provenance as Record<string, unknown>).workflowTimelineV1)
            : [];
          const envelope = JSON.parse(row.envelope) as DeviceTimedDraft & { codingTimelineV1?: WorkflowTimelineEvent[] };
          const envelopeTimeline = codingTimeline(envelope.codingTimelineV1);
          timeline.current = codingTimeline([...envelopeTimeline, ...storedTimeline, ...timeline.current]);
          for (const event of CODING_CLIENT_EVENTS) {
            const legacy = storedTimeline.find((item) => item.event === event);
            const persistedEvent = envelopeTimeline.find((item) => item.event === event);
            if (legacy && !persistedEvent && !await recordCodingTimeline(db, clientDraftId, event, legacy.at, legacy.elapsed_ms)) {
              throw new Error("offline_timeline_save_failed");
            }
          }
          const openedAt = localDateTimeWithOffset();
          if (!await recordCodingTimeline(db, clientDraftId, "coding_opened", openedAt)) throw new Error("offline_timeline_save_failed");
          timeline.current = codingTimeline(appendWorkflowEvent(timeline.current, "coding_opened", openedAt));
          const persisted = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [clientDraftId]);
          if (!persisted) throw new Error("offline_case_missing");
          const persistedEnvelope = JSON.parse(persisted.envelope) as Record<string, unknown>;
          envelope.codingTimelineV1 = codingTimeline(persistedEnvelope.codingTimelineV1);
          timeline.current = envelope.codingTimelineV1;
          const configKey = `draft-config:${clientDraftId}`;
          const draftConfig = await getMeta<Record<string, unknown>>(db, configKey);
          const options = isSmartVaOptionsSnapshot(draftConfig?.smartva) ? draftConfig.smartva : null;
          const answersHash = await draftAnswersSha256(db, clientDraftId);
          const cached = await getLocalSmartVa(db, clientDraftId);
          setSmartvaAnswersHash(answersHash);
          setSmartvaCache(cached);
          setLoaded({ row, draft: envelope, coding, projectId: draft.project_id, smartvaOptions: options });
        }
      } catch (error) {
        releaseLease.current?.();
        releaseLease.current = null;
        if (live) setFailed(errorText(error));
      }
    })();
    return () => { live = false; };
  }, [db, clientDraftId, retry, userId]);

  useEffect(() => () => { releaseLease.current?.(); releaseLease.current = null; }, []);

  // This capability probe does not initialize or load the SmartVA model; scoring remains an explicit action.
  useEffect(() => {
    let live = true;
    if (!loaded?.smartvaOptions) {
      setSmartvaAvailable(false);
      return () => { live = false; };
    }
    void offlineSmartvaEngine().init().then((result) => {
      if (live) { setSmartvaAvailable(result.ok && !!result.version); setSmartvaVersion(result.version ?? null); }
    });
    return () => { live = false; };
  }, [loaded?.smartvaOptions]);

  // Start only after the selected draft passes its project check and holds the editor lease.
  useEffect(() => {
    if (!loaded || !allowed || busy || initStarted.current) return;
    initStarted.current = true;
    void assertAllowed().then(async () => {
      const result = await engine.init();
      if (!result.ok) throw new Error(result.error);
      setEngineReady(true);
    }).catch((error) => {
      initStarted.current = false;
      releaseLease.current?.();
      releaseLease.current = null;
      setFailed(errorText(error));
    });
  }, [allowed, assertAllowed, busy, engine, loaded]);

  const workspace: WorkspacePayload | undefined = useMemo(() => {
    if (!loaded) return undefined;
    const seed = certificateSeedFromInterview(loaded.draft.data ?? {});
    return {
      case: {
        va_sid: clientDraftId,
        instance_name: clientDraftId,
        form_type_code: loaded.draft.instrumentId,
        project_mode: "unmasked_doris",
        icd_classification: "icd11",
        workflow_state: "coding",
        narrative_qa_enabled: false,
        social_autopsy_enabled: false,
      },
      categories: [],
      default_category: "",
      step: "initial",
      assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
      smartva: null,
      other_conditions_options: null,
      doris: { initial_certificate: seed.certificate, prefill_provenance: seed.provenance, saved_processing: null },
      narrative_qa: null,
      social_autopsy: null,
    };
  }, [loaded, clientDraftId]);

  const identity: WorkspaceIdentity = useMemo(() => ({ vaSid: clientDraftId, mode: "coding" }), [clientDraftId]);
  const editor = useMemo(
    () => createOfflineDorisEditor(
      engine,
      offlineCodingStore(db, assertAllowed),
      loaded ? { index: packIndex(), context: codingContextFromInterview(loaded.draft.data ?? {}), confirmedBy: userId } : undefined,
    ),
    [engine, db, loaded, userId, assertAllowed],
  );
  const api = useMemo(
    () => offlineWorkspaceApi(db, editor, lastReply, timeline, clientDraftId, (draftId) => draftAnswersSha256(db, draftId), assertAllowed),
    [editor, clientDraftId, db, assertAllowed],
  );
  const request = offlineRequester(db, createGuidanceRequester(editor, clientDraftId, assertAllowed));

  const smartvaIsCurrent = smartvaAvailable === true && !!loaded?.smartvaOptions &&
    isLocalSmartVaCurrent(smartvaCache, smartvaAnswersHash, loaded.smartvaOptions.optionsDigest, smartvaVersion);
  const repairSmartVaOptions = async () => {
    if (!loaded || smartvaBusy) return;
    setSmartvaBusy(true);
    setSmartvaFailure("");
    try {
      await assertAllowed();
      const draft = await db.getFirstAsync<{ project_id: string; site_id: string }>("SELECT project_id, site_id FROM drafts WHERE id = ?", [clientDraftId]);
      if (!draft || draft.project_id !== loaded.projectId) throw new Error("offline_case_access_revoked");
      let options: SmartVaOptionsSnapshot | null;
      if (accountRef.current.standalone) {
        options = await standaloneSmartVaSnapshot(await getOfflineProfile(), loaded.draft.instrumentId, loaded.draft.instrumentVersion);
      } else {
        const references = await getCachedReferenceData(db);
        const project = references?.projects.find((item) => item.project.project_id === draft.project_id)?.project;
        options = projectSmartVaSnapshot((project as (typeof project & { smartva_targets?: SmartVaTarget[] }) | undefined)?.smartva_targets,
          { siteId: draft.site_id, orgUnitId: loaded.row.org_unit_id });
      }
      if (!options) throw new Error("options_unavailable");
      await assertAllowed();
      const key = `draft-config:${clientDraftId}`;
      const config = await getMeta<Record<string, unknown>>(db, key);
      if (config?.smartva != null) {
        if (!isSmartVaOptionsSnapshot(config.smartva)) throw new Error("options_unavailable");
        options = config.smartva;
      } else {
        await setMeta(db, key, { ...config, smartva: options });
      }
      setLoaded((current) => current ? { ...current, smartvaOptions: options } : current);
    } catch {
      setSmartvaFailure(t("localSmartVaOptionsNeeded"));
    } finally {
      setSmartvaBusy(false);
    }
  };
  const runSmartVa = async () => {
    if (!loaded || smartvaBusy) return;
    setSmartvaBusy(true);
    setSmartvaFailure("");
    try {
      await assertNotRefused();
      const draftConsentKeys = await db.getFirstAsync<{ death_id: string | null; client_death_id: string | null }>(
        "SELECT death_id, client_death_id FROM drafts WHERE id = ?",
        [clientDraftId],
      );
      const consent = await consentForDraft(db, {
        id: clientDraftId,
        death_id: draftConsentKeys?.death_id,
        client_death_id: draftConsentKeys?.client_death_id,
      });
      const row = await runLocalSmartVa({
        db,
        draftId: clientDraftId,
        envelope: JSON.stringify(loaded.draft),
        options: loaded.smartvaOptions,
        sealedFields: !consent || consent.record.envelope.decision === "refused"
          ? consent?.record.covered_fields ?? [...DEFAULT_COVERED_FIELDS]
          : [],
        answersHash: () => draftAnswersSha256(db, clientDraftId),
        engine: offlineSmartvaEngine(),
        assertAllowed,
      });
      setSmartvaCache(row);
      setSmartvaAnswersHash(await draftAnswersSha256(db, clientDraftId));
    } catch (error) {
      setSmartvaFailure(t("localSmartVaFailed"));
      setSmartvaCache(await getLocalSmartVa(db, clientDraftId));
    } finally {
      setSmartvaBusy(false);
    }
  };

  if (failed) {
    return (
      <Screen title="Offline coding">
        <Text accessibilityRole="alert" style={styles.error}>{failed}</Text>
        <Button kind="secondary" label="Retry" onPress={() => {
          setFailed("");
          setLoaded(undefined);
          setEngineReady(false);
          setRetry((value) => value + 1);
        }} />
        <Button kind="secondary" label="Back to the list" onPress={onDone} />
      </Screen>
    );
  }
  if (!loaded || !workspace) {
    return (
      <Screen title="Offline coding">
        {busy ? <>
          <Text style={styles.muted}>This case is being sent.</Text>
          <Button kind="secondary" label="Retry" onPress={() => setRetry((value) => value + 1)} />
        </> : <Text style={styles.muted}>{failed ? "This case is not available for offline coding." : "Opening the case…"}</Text>}
      </Screen>
    );
  }
  const { row, coding } = loaded;
  return (
    <Screen title="Offline coding">
      <View style={[styles.card, { gap: 4 }]}>
        <Text style={styles.text} selectable>{row.client_draft_id}</Text>
        <Text style={styles.muted}>Org unit: {row.org_unit_id ?? "—"}</Text>
        <Text style={styles.muted}>Interview started: {datePart(row.started_at) || "—"}</Text>
        <Text style={styles.muted}>Interview completed: {datePart(row.completed_at) || "—"}</Text>
        <Text style={styles.muted}>Instrument: {loaded.draft.instrumentId} {loaded.draft.instrumentVersion}</Text>
        <Text style={styles.muted}>Coding: {coding ? `${statusLabel(coding.status)}${coding.ucod_code ? ` — ${coding.ucod_code}` : ""}` : statusLabel(null)}</Text>
      </View>
      {loaded.smartvaOptions ? <View style={[styles.card, { gap: 8 }]}>
        <Text style={styles.text}>{t("localSmartVaTitle")}</Text>
        <Text style={styles.muted}>{t("localSmartVaNote")}</Text>
        {smartvaIsCurrent && smartvaCache?.status === "ready" && smartvaCache.result_json
          ? <>
            <Text style={styles.muted}>{t("localSmartVaUpdated", { date: new Date(smartvaCache.updated_at).toLocaleString() })} · {t("localSmartVaVersion", { version: smartvaCache.engine_version ?? "—" })}</Text>
            <SmartVaReference value={JSON.parse(smartvaCache.result_json)} />
          </>
          : smartvaIsCurrent && smartvaCache?.status === "error"
            ? <Text accessibilityRole="alert" style={styles.error}>{t("localSmartVaFailed")}</Text>
            : null}
        {smartvaFailure ? <Text accessibilityRole="alert" style={styles.error}>{smartvaFailure}</Text> : null}
        <Button kind="secondary" label={t(smartvaIsCurrent && smartvaCache?.status === "ready" ? "localSmartVaRegenerate" : "localSmartVaRun")} onPress={() => { void runSmartVa(); }} disabled={smartvaBusy || smartvaAvailable !== true} />
        {smartvaBusy ? <Text style={styles.muted}>{t("localSmartVaWorking")}</Text> : null}
        {smartvaAvailable === false ? <Text style={styles.muted}>{t("localSmartVaUnavailable")}</Text> : null}
      </View> : <View style={[styles.card, { gap: 8 }]}>
        <Text style={styles.muted}>{t("localSmartVaOptionsNeeded")}</Text>
        {smartvaFailure && smartvaFailure !== t("localSmartVaOptionsNeeded") ? <Text accessibilityRole="alert" style={styles.error}>{smartvaFailure}</Text> : null}
        <Button kind="secondary" label={t("localSmartVaUseCurrentSettings")} onPress={() => { void repairSmartVaOptions(); }} disabled={smartvaBusy || !allowed} />
      </View>}
      <View style={{ display: allowed && engineReady ? "flex" : "none" }}>
        <DorisPanel workspace={workspace} identity={identity} api={api} request={request} onSaved={onDone} onDone={onDone} />
      </View>
      {!allowed && <Text accessibilityRole="alert" style={styles.error}>Offline coding access for this project is unavailable.</Text>}
      <Button kind="secondary" label="Back to the list" onPress={onDone} />
    </Screen>
  );
}

/** The list of completed-but-unsent interviews; opening one starts the offline editor. */
function OfflineCaseList({ db, onOpen, account }: { db: Db; onOpen: (clientDraftId: string) => void; account: Account }) {
  const styles = useUiStyles();
  const [rows, setRows] = useState<OfflineCodingCaseRow[] | undefined>(undefined);
  const [failed, setFailed] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([
      listOfflineCodingCases(db),
      typeof listDrafts === "function" ? listDrafts(db) : Promise.resolve([]),
    ])
      .then(([cases, drafts]) => {
        if (!live) return;
        if (account.standalone) {
          setRows(cases);
          return;
        }
        const projectByDraft = new Map(drafts.map((draft) => [draft.id, draft.project_id]));
        setRows(cases.filter((row) => {
          const projectId = projectByDraft.get(row.client_draft_id);
          return typeof projectId === "string" && canUseOfflineCoding(account, projectId);
        }));
      })
      .catch((error) => { if (live) setFailed(errorText(error)); });
    return () => { live = false; };
  }, [account, db]);

  if (failed) return <Text accessibilityRole="alert" style={styles.error}>{failed}</Text>;
  if (!rows) return <Text style={styles.muted}>Loading…</Text>;
  if (rows.length === 0) return <Text style={styles.muted}>No completed interviews waiting to be sent.</Text>;
  return (
    <View style={{ gap: 8 }}>
      {rows.map((row) => (
        <Button
          key={row.client_draft_id}
          kind="secondary"
          label={`${row.client_draft_id} · ${datePart(row.completed_at ?? row.updated_at)} · ${row.org_unit_id ?? "—"} · ${statusLabel(row.offline_status)}`}
          onPress={() => onOpen(row.client_draft_id)}
        />
      ))}
    </View>
  );
}

export default function OfflineCoding() {
  const router = useRouter();
  const styles = useUiStyles();
  const { caseId } = useLocalSearchParams<Params>();
  const { accounts } = useAppState();
  const icd11Preference = useIcd11DorisPreference();
  const [enabledOnEntry, setEnabledOnEntry] = useState<boolean | undefined>(undefined);
  const userId = useOfflineUserId();
  const account = accounts.find((item) => item.user_id === userId);
  const canOpenOffline = account ? canUseOfflineCoding(account) : false;
  // A deep link (?caseId=) opens the case directly; otherwise the coder picks one from the list.
  const [selected, setSelected] = useState<string | null>(() => first(caseId) ?? null);
  const [db, setDb] = useState<Db | undefined>(undefined);
  const [storeMissing, setStoreMissing] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  useEffect(() => {
    if (enabledOnEntry === undefined && icd11Preference.ready) setEnabledOnEntry(icd11Preference.enabled);
  }, [enabledOnEntry, icd11Preference.enabled, icd11Preference.ready]);
  useEffect(() => {
    if (icd11Preference.ready && !icd11Preference.enabled) {
      setEnabledOnEntry(false);
    }
  }, [icd11Preference.enabled, icd11Preference.ready]);
  useEffect(() => {
    // Turning the preference on from Settings must not start the native engine as a side effect.
    // Return to the local case list; opening a case again is the explicit coding action.
    if (icd11Preference.ready && icd11Preference.enabled && enabledOnEntry === false) {
      if (selected) setSelected(null);
      setReloadTick((tick) => tick + 1);
      setEnabledOnEntry(true);
    }
  }, [enabledOnEntry, icd11Preference.enabled, icd11Preference.ready, selected]);
  const canEnterCoding = icd11Preference.enabled && enabledOnEntry === true;

  useEffect(() => {
    // Do not open the interviewer database or enumerate local cases while ICD-11/DORIS is off.
    if (!isPlusVariant() || !canEnterCoding || !userId || !account || (!canOpenOffline && !selected) || db) return;
    let live = true;
    setStoreMissing(false);
    openInterviewerDb(userId)
      .then((opened) => { if (live) setDb(opened); })
      .catch((error) => {
        if (!live) return;
        // The store locked while the screen was up: send the coder to the PIN screen like the workspace does.
        if (error instanceof StoreLockedError || !isUnlocked(userId)) router.replace({ pathname: "/unlock", params: { userId } });
        else setStoreMissing(true);
      });
    return () => { live = false; };
  }, [account, canEnterCoding, canOpenOffline, db, reloadTick, router, selected, userId]);

  if (!isPlusVariant()) return <Redirect href="/" />;
  if (!userId || !account || (!canOpenOffline && !selected)) return <Redirect href="/" />;
  if (!canEnterCoding) {
    return <Screen title={t("icd11DorisDisabledTitle")}>
      <Text accessibilityRole="alert" style={styles.text}>{t("icd11DorisDisabledBody")}</Text>
      <Button label={t("icd11DorisOpenSettings")} onPress={() => router.push({ pathname: "/settings", params: { userId } })} />
      <Button kind="secondary" label={t("icd11DorisGoBack")} onPress={() => {
        setSelected(null);
        setReloadTick((tick) => tick + 1);
      }} />
    </Screen>;
  }
  if (storeMissing) {
    return (
      <Screen title="Offline coding">
        <Text accessibilityRole="alert" style={styles.error}>{errorText(new Error("offline_store_unavailable"))}</Text>
        <Button kind="secondary" label="Back" onPress={() => router.back()} />
      </Screen>
    );
  }
  if (!db) {
    return (
      <Screen title="Offline coding">
        <Text style={styles.muted}>Opening…</Text>
      </Screen>
    );
  }
  const closeCase = async () => {
    setSelected(null);
    // The list reopens after a save: its statuses come from the store again.
    setReloadTick((tick) => tick + 1);
  };
  // The case renders its own Screen (title and banner); wrapping it here would show both twice.
  if (selected) return <OfflineCase key={selected} db={db} userId={userId} clientDraftId={selected} account={account} onDone={closeCase} />;
  return (
    <Screen title="Offline coding">
      <OfflineCaseList key={reloadTick} db={db} account={account} onOpen={setSelected} />
    </Screen>
  );
}
