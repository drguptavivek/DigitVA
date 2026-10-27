/**
 * Collect Plus only (APP_VARIANT=plus, src/appVariant.ts): pure-offline coding. Lists the signed-in interviewer's
 * completed-but-unsent interviews from the local store and opens one in the DORIS editor over the on-device ICD-11
 * engine (src/workspace/offlineDoris.ts). A confirmed save lands in the store's offline_coding table and the draft
 * keeps syncing as the interview; nothing syncs the coding in this phase. Only what the coder collected themselves
 * is shown: the local id, dates, org unit and coding status — names and answers stay in the form.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";

import { ApiError } from "../api";
import { useAppState } from "../AppState";
import { isPlusVariant } from "../appVariant";
import {
  getOfflineCoding,
  getOfflineCodingCase,
  listOfflineCodingCases,
  saveOfflineCoding,
  type Db,
  type DeviceTimedDraft,
  type OfflineCodingCase,
  type OfflineCodingCaseRow,
  type OfflineCodingRow
} from "../drafts";
import { isUnlocked, openInterviewerDb, StoreLockedError } from "../interviewerDb";
import { getOrCreatePlusDeviceIdentity } from "../offlineIdentity";
import { getOfflineProfile } from "../offlineProfile";
import allowabilityPack from "../../assets/icd11-allowability-2026-01.json";
import { codingContextFromInterview, createAllowabilityIndex, type AllowabilityPack } from "../coding/icd11Allowability";
import { errorText, Button, Screen, useUiStyles } from "../ui";
import { createOfflineDorisEditor, certificateSeedFromInterview, OfflineAllowabilityError, type OfflineCodingStore, type OfflineDorisEditor } from "../workspace/offlineDoris";
import type { WorkspaceApi } from "../workspace/api";
import type { CodingWriteReply, DorisProcessReply, WorkspaceIdentity, WorkspacePayload } from "../workspace/contracts";
import { offlineEngine } from "../offlineEngine";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { draftAnswersSha256 } from "../sync";

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

/** The drafts.ts accessors, seen through the editor's store interface. */
function offlineCodingStore(db: Db): OfflineCodingStore {
  return {
    save: (row) => saveOfflineCoding(db, row),
    get: (clientDraftId) => getOfflineCoding(db, clientDraftId),
  };
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
  editor: OfflineDorisEditor,
  reply: { current: DorisProcessReply | null },
  vaSid: string,
  answersHash: (draftId: string) => Promise<string | null>,
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
      return editor.onTerms(query, options?.limit, options?.subtreeUris);
    },
    getDorisCodeInfo: (_vaSid, code) => editor.onCodeInfo(code),
    checkDorisSelection: (_vaSid, code, uri) => editor.onSelectionCheck(code, uri),
    getVaDefinitionForIcd: async () => null,
    async processDoris(_vaSid, _role, clientRevision, certificate) {
      const processed = await editor.onProcess(clientRevision, certificate);
      reply.current = processed;
      return processed;
    },
    async saveInitial(_vaSid, body): Promise<CodingWriteReply> {
      const { deviceUuid, coderProfileUpdatedAt } = await resolveOfflineSaveContext();
      try {
        const answersSha256 = await answersHash(vaSid);
        await editor.save({ clientDraftId: vaSid, body, reply: reply.current, deviceUuid, coderProfileUpdatedAt, answersSha256 });
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
function OfflineCase({ db, userId, clientDraftId, onDone }: { db: Db; userId: string; clientDraftId: string; onDone: () => Promise<void> }) {
  const styles = useUiStyles();
  const engine = offlineEngine();
  const [loaded, setLoaded] = useState<{ row: OfflineCodingCase; draft: DeviceTimedDraft; coding: OfflineCodingRow | null } | undefined>();
  const [failed, setFailed] = useState("");
  const lastReply = useRef<DorisProcessReply | null>(null);

  // The engine takes ~18 s to start; begin now so the first Process does not wait for a cold start.
  useEffect(() => { void engine.init(); }, [engine]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const row = await getOfflineCodingCase(db, clientDraftId);
        if (!row) throw new Error("offline_case_missing");
        const coding = await getOfflineCoding(db, clientDraftId);
        if (live) setLoaded({ row, draft: JSON.parse(row.envelope) as DeviceTimedDraft, coding });
      } catch (error) {
        if (live) setFailed(errorText(error));
      }
    })();
    return () => { live = false; };
  }, [db, clientDraftId]);

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
      offlineCodingStore(db),
      loaded ? { index: packIndex(), context: codingContextFromInterview(loaded.draft.data ?? {}), confirmedBy: userId } : undefined,
    ),
    [engine, db, loaded, userId],
  );
  const api = useMemo(
    () => offlineWorkspaceApi(editor, lastReply, clientDraftId, (draftId) => draftAnswersSha256(db, draftId)),
    [editor, clientDraftId, db],
  );
  const request = useMemo(() => async () => { throw new Error("offline_server_unavailable"); }, []);

  if (failed) {
    return (
      <Screen title="Offline coding">
        <Text accessibilityRole="alert" style={styles.error}>{failed}</Text>
        <Button kind="secondary" label="Back to the list" onPress={onDone} />
      </Screen>
    );
  }
  if (!loaded || !workspace) {
    return (
      <Screen title="Offline coding">
        <Text style={styles.muted}>Opening the case…</Text>
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
      <DorisPanel
        workspace={workspace}
        identity={identity}
        api={api}
        request={request}
        onSaved={onDone}
        onDone={onDone}
      />
      <Button kind="secondary" label="Back to the list" onPress={onDone} />
    </Screen>
  );
}

/** The list of completed-but-unsent interviews; opening one starts the offline editor. */
function OfflineCaseList({ db, onOpen }: { db: Db; onOpen: (clientDraftId: string) => void }) {
  const styles = useUiStyles();
  const [rows, setRows] = useState<OfflineCodingCaseRow[] | undefined>(undefined);
  const [failed, setFailed] = useState("");

  useEffect(() => {
    let live = true;
    listOfflineCodingCases(db)
      .then((cases) => { if (live) setRows(cases); })
      .catch((error) => { if (live) setFailed(errorText(error)); });
    return () => { live = false; };
  }, [db]);

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
  const userId = useOfflineUserId();
  // A deep link (?caseId=) opens the case directly; otherwise the coder picks one from the list.
  const [selected, setSelected] = useState<string | null>(() => first(caseId) ?? null);
  const [db, setDb] = useState<Db | undefined>(undefined);
  const [storeMissing, setStoreMissing] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    // The gate above still mounts these hooks (they run before its return), so the store is only ever opened on Plus.
    if (!isPlusVariant() || !userId) return;
    let live = true;
    setDb(undefined);
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
  }, [userId, reloadTick, router]);

  if (!isPlusVariant()) return <Redirect href="/" />;
  if (!userId) return <Redirect href="/" />;
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
  return (
    <Screen title="Offline coding">
      {selected ? (
        <OfflineCase key={selected} db={db} userId={userId} clientDraftId={selected} onDone={closeCase} />
      ) : (
        <OfflineCaseList key={reloadTick} db={db} onOpen={setSelected} />
      )}
    </Screen>
  );
}
