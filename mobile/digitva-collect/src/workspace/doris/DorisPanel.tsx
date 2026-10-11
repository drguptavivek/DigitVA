import { useCallback, useEffect, useRef, useState } from "react";
import { AppState as NativeAppState, Text, TextInput, View } from "react-native";
import { WhoVaQuestionControls } from "@drguptavivek/who-2022-va/native";
import type { InstrumentQuestion } from "@drguptavivek/who-2022-va";

import { ApiError } from "../../api";
import { Button, errorText, styles } from "../../ui";
import type { JsonRequester, WorkspaceApi } from "../api";
import type { DorisProcessReply, JsonObject, JsonValue, WorkspaceIdentity, WorkspacePayload } from "../contracts";
import { parseDorisProcess } from "../contracts";
import { IcdSelector } from "./IcdSelector";

type CertificateState = {
  owner: { api: WorkspaceApi; request: JsonRequester; vaSid: string; mode: WorkspaceIdentity["mode"]; step: WorkspacePayload["step"]; projectMode: WorkspacePayload["case"]["project_mode"] };
  certificate: JsonObject;
  revision: number;
  processing: DorisProcessReply | null;
  selectedCause: { code: string; title: string; uri: string } | null;
  error: string;
  notice: string;
  busy: boolean;
  reconfirm: boolean;
  cleared: boolean;
};

type CertificateLine = JsonObject & { Conditions: JsonObject[] };
const NOT_SET_VALUE = "__not_set__";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function object(value: unknown): JsonObject {
  return isRecord(value) ? value as JsonObject : {};
}

function array(value: unknown): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

function text(value: JsonValue | undefined): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function copy(value: JsonObject): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject;
}

function lineConditions(value: JsonValue | undefined): JsonObject[] {
  return array(object(value).Conditions).filter(isRecord) as JsonObject[];
}

function initialCertificate(workspace: WorkspacePayload): JsonObject {
  const seed = workspace.doris?.initial_certificate;
  const certificate = seed ? copy(seed) : { ICDVersion: "ICD11", Part1: [] };
  if (!Array.isArray(certificate.Part1) || certificate.Part1.length === 0) certificate.Part1 = [{ Conditions: [] }];
  return certificate;
}

function initialState(owner: CertificateState["owner"], workspace: WorkspacePayload): CertificateState {
  const maskedStepTwo = workspace.case.project_mode === "masked_doris" && workspace.step === "final";
  return {
    owner,
    certificate: maskedStepTwo ? {} : initialCertificate(workspace),
    revision: 0,
    processing: null,
    selectedCause: null,
    error: "",
    notice: "",
    busy: false,
    reconfirm: false,
    cleared: false,
  };
}

function sameOwner(left: CertificateState["owner"] | undefined, right: CertificateState["owner"]): boolean {
  return left?.api === right.api && left.request === right.request && left.vaSid === right.vaSid && left.mode === right.mode && left.step === right.step && left.projectMode === right.projectMode;
}

function codeFromResult(result: JsonObject | null): string {
  if (!result) return "";
  return typeof result.stemCode === "string" ? result.stemCode : typeof result.code === "string" ? result.code : "";
}

function processingResult(processing: DorisProcessReply | null, engine: "doris" | "codedit"): JsonObject {
  return object(processing?.[engine].result);
}

/** Removes only fields made inapplicable by the WHO sex/pregnancy rules. */
function processCertificate(certificate: JsonObject): JsonObject {
  const result = copy(certificate);
  const sex = object(result.AdministrativeData).Sex;
  const maternal = object(result.MaternalDeath);
  if (sex !== undefined && sex !== 2 && sex !== 9) delete result.MaternalDeath;
  else if (maternal.WasPregnant === 9 || maternal.WasPregnant === 0) {
    delete maternal.TimeFromPregnancy;
    delete maternal.PregnancyContribute;
    if (Object.keys(maternal).length) result.MaternalDeath = maternal;
  }
  result.Part1 = array(result.Part1).filter((raw) => lineConditions(raw).length > 0);
  return result;
}

function makeSaveError(error: unknown): string {
  if (!(error instanceof ApiError) || !error.payload) return errorText(error);
  const body = error.payload;
  const messages = Array.isArray(body.messages) ? body.messages.filter((item) => typeof item === "string") : [];
  const blocked = Array.isArray(body.blocked_by) ? body.blocked_by.filter((item) => typeof item === "string") : [];
  return [...messages, ...blocked].join(" ") || errorText(error);
}

/** DORIS editor and process proof stay in component memory and are allocation-scoped. */
export function DorisPanel({
  workspace,
  identity,
  api,
  request,
  onSaved,
  onDone,
}: {
  workspace: WorkspacePayload;
  identity: WorkspaceIdentity;
  api: WorkspaceApi;
  request: JsonRequester;
  onSaved: () => Promise<void>;
  onDone: () => void;
}) {
  const owner = { api, request, vaSid: identity.vaSid, mode: identity.mode, step: workspace.step, projectMode: workspace.case.project_mode };
  const [stored, setStored] = useState<CertificateState>(() => initialState(owner, workspace));
  const [notCodeableReason, setNotCodeableReason] = useState("");
  const [notCodeableOther, setNotCodeableOther] = useState("");
  const state = sameOwner(stored.owner, owner) ? stored : initialState(owner, workspace);
  const stateRef = useRef(state);
  stateRef.current = state;
  const ownerRef = useRef(owner);
  ownerRef.current = owner;
  const workspaceRef = useRef(workspace);
  const generation = useRef(0);
  const live = useRef(true);
  const identityKey = `${identity.vaSid}:${identity.mode}:${workspace.step}:${workspace.case.project_mode}`;
  const masked = workspace.case.project_mode === "masked_doris";
  const isInitial = workspace.step === "initial";
  const canEdit = identity.mode !== "view" && (workspace.step === "initial" || (workspace.step === "final" && !masked));
  const certificate = state.certificate;
  const revision = state.revision;

  const update = useCallback((change: (current: CertificateState) => CertificateState) => {
    setStored((current) => {
      if (!live.current || !sameOwner(ownerRef.current, owner)) return current;
      const base = sameOwner(current.owner, owner) ? current : initialState(owner, workspace);
      return change(base);
    });
  }, [api, identity.mode, identity.vaSid, request, workspace]);

  const invalidate = useCallback((nextCertificate: JsonObject, message = "Certificate changed. Process it again before saving.") => {
    update((current) => ({ ...current, certificate: nextCertificate, revision: current.revision + 1, processing: null, selectedCause: null, reconfirm: false, notice: message, error: "" }));
  }, [update]);

  const setField = (section: string, key: string, value: JsonValue | undefined) => {
    const next = copy(certificate);
    if (!isRecord(next[section])) next[section] = {};
    const target = next[section] as JsonObject;
    if (value === undefined || value === "") delete target[key];
    else target[key] = value;
    if (!Object.keys(target).length) delete next[section];
    invalidate(next);
  };

  const updatePart1 = (nextLines: JsonObject[]) => {
    const next = copy(certificate);
    next.Part1 = nextLines;
    invalidate(next);
  };

  useEffect(() => {
    generation.current += 1;
    live.current = true;
    setStored(initialState(owner, workspace));
    return () => {
      live.current = false;
      generation.current += 1;
    };
  }, [api, identityKey, request]);

  useEffect(() => {
    if (workspaceRef.current === workspace) return;
    workspaceRef.current = workspace;
    if (stateRef.current.cleared) {
      live.current = true;
      setStored(initialState(owner, workspace));
    }
  }, [owner, workspace]);

  useEffect(() => {
    const clear = () => {
      generation.current += 1;
      live.current = false;
      const blank = initialState(owner, workspace);
      blank.certificate = {};
      blank.cleared = true;
      setStored(blank);
    };
    const native = NativeAppState.addEventListener("change", (next) => {
      if (next !== "active") clear();
      else void onSaved().catch(() => undefined);
    });
    const onVisibility = () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") clear();
      else void onSaved().catch(() => undefined);
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisibility);
    return () => {
      native.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [api, identityKey, onSaved, request, workspace]);

  const currentRequest = (requestId: number, sentRevision: number) => live.current && sameOwner(ownerRef.current, owner) && generation.current === requestId && stateRef.current.revision === sentRevision;

  const clearAllocation = () => {
    generation.current += 1;
    live.current = false;
    setStored((current) => sameOwner(current.owner, owner) ? { ...current, certificate: {}, processing: null, selectedCause: null, busy: false, cleared: true } : current);
    onDone();
  };

  const process = async () => {
    const requestId = ++generation.current;
    const sentRevision = revision;
    const currentCertificate = processCertificate(certificate);
    const sourceLines = array(certificate.Part1).map(lineConditions);
    const lastFilledLine = sourceLines.reduce((last, conditions, index) => conditions.length ? index : last, -1);
    if (sourceLines.slice(0, lastFilledLine + 1).some((conditions) => conditions.length === 0)) {
      update((current) => ({ ...current, error: "Complete each Part I line before the next line, or remove the empty line." }));
      return;
    }
    if (sourceLines.some((conditions) => conditions.some((condition) => conditions.some((other) => other.Interval !== condition.Interval)))) {
      update((current) => ({ ...current, error: "Conditions on the same Part I line must share one interval." }));
      return;
    }
    if (!Array.isArray(currentCertificate.Part1) || currentCertificate.Part1.length === 0) {
      update((current) => ({ ...current, error: "Enter at least one Part I condition." }));
      return;
    }
    if (!text(sourceLines[0]?.[0]?.Text).trim()) {
      update((current) => ({ ...current, error: "Enter the immediate cause text in the first Part I line." }));
      return;
    }
    update((current) => ({ ...current, busy: true, error: "", notice: "Processing with DORIS and CoDEdit…" }));
    try {
      const processing = await api.processDoris(identity.vaSid, identity.mode === "reviewing" ? "reviewer" : "coder", sentRevision, currentCertificate);
      if (!currentRequest(requestId, sentRevision)) return;
      update((current) => ({ ...current, processing, selectedCause: null, busy: false, notice: "Review both results, then independently confirm the final underlying cause." }));
    } catch (processError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (processError instanceof ApiError && processError.status === 403) {
        clearAllocation();
      } else update((current) => ({ ...current, busy: false, error: makeSaveError(processError) }));
    }
  };

  const save = async () => {
    const requestId = ++generation.current;
    const sentRevision = revision;
    const processing = state.processing;
    if (!processing || processing.client_revision !== sentRevision || !state.selectedCause) {
      update((current) => ({ ...current, error: "Process the current certificate and confirm the final underlying cause before saving." }));
      return;
    }
    const dorisFields: JsonObject = {
      doris_certificate: processing.certificate,
      doris_result: { status: processing.doris.status, result: processing.doris.result },
      codedit_result: { status: processing.codedit.status, result: processing.codedit.result },
      doris_process_token: processing.process_token,
      doris_result_digest: processing.result_digest,
      doris_client_revision: processing.client_revision,
    };
    update((current) => ({ ...current, busy: true, error: "" }));
    try {
      if (isInitial) {
        await api.saveInitial(identity.vaSid, {
          antecedent_cod: state.selectedCause.code,
          ...dorisFields,
        }, identity.mode === "reviewing" ? "reviewing" : "coding");
        if (!currentRequest(requestId, sentRevision)) return;
        await onSaved();
      } else {
        const body: JsonObject = { conclusive_cod: state.selectedCause.code };
        Object.assign(body, dorisFields);
        await api.saveFinal(identity.vaSid, body, identity.mode === "reviewing" ? "reviewing" : "coding");
        if (!currentRequest(requestId, sentRevision)) return;
        onDone();
      }
    } catch (saveError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (saveError instanceof ApiError && saveError.status === 403) {
        clearAllocation();
        return;
      }
      if (saveError instanceof ApiError && saveError.status === 409 && saveError.code === "DORIS_CERTIFICATE_CHANGED" && saveError.payload?.processing) {
        try {
          const fresh = parseDorisProcess(saveError.payload.processing);
          update((current) => ({ ...current, certificate: fresh.certificate, revision: fresh.client_revision, processing: fresh, selectedCause: null, reconfirm: true, busy: false, notice: "", error: "The certificate changed on the server. Review the fresh results and confirm the final cause again." }));
          return;
        } catch { /* malformed conflict result is shown below */ }
      }
      const message = makeSaveError(saveError);
      if (saveError instanceof ApiError && (saveError.status === 422 || saveError.code === "final_blocked")) {
        try { await onSaved(); } catch { /* preserve the original validation response */ }
      }
      if (!currentRequest(requestId, sentRevision)) return;
      update((current) => ({ ...current, busy: false, error: message }));
    }
  };

  const reportNotCodeable = async () => {
    if (!notCodeableReason || (notCodeableReason === "others" && !notCodeableOther.trim())) return;
    const requestId = ++generation.current;
    const sentRevision = revision;
    update((current) => ({ ...current, busy: true, error: "" }));
    try {
      await api.saveNotCodeable(identity.vaSid, { reason: notCodeableReason, other: notCodeableReason === "others" ? notCodeableOther.trim() : "" });
      if (!currentRequest(requestId, sentRevision)) return;
      onDone();
    } catch (reportError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (reportError instanceof ApiError && reportError.status === 403) {
        clearAllocation();
      } else update((current) => ({ ...current, busy: false, error: makeSaveError(reportError) }));
    }
  };

  const chooseFinalCause = (choice: { code: string; title: string; uri: string } | null) => {
    update((current) => ({ ...current, selectedCause: choice, error: "", notice: choice ? "Final underlying cause selected independently from the DORIS result." : "" }));
  };

  const loseAllocation = clearAllocation;

  if (identity.mode === "view" || workspace.doris === null || (workspace.step !== "initial" && workspace.step !== "final") || state.cleared) return null;

  if (masked && workspace.step === "final") {
    const step1 = workspace.doris.step1_processing;
    const ownFinal = identity.mode === "reviewing" ? workspace.assessments.reviewer_final : workspace.assessments.final;
    const selected = state.selectedCause;
    return (
      <View style={styles.card}>
        <Text accessibilityRole="header" style={styles.headline}>Final underlying cause</Text>
        {step1 ? <ProcessingSummary processing={null} saved={step1} /> : <Text style={styles.muted}>No Step 1 DORIS result was saved.</Text>}
        <CertificateReference certificate={workspace.doris.step1_certificate ?? null} />
        {workspace.smartva !== null ? <SmartVaReference value={workspace.smartva} /> : null}
        {ownFinal?.conclusive_cod ? <Text style={styles.muted}>Previously saved final: {ownFinal.conclusive_cod}</Text> : null}
        <IcdSelector key={identityKey} label="Choose and confirm the final underlying cause" api={api} request={request} identity={identity} value={selected} onSelect={chooseFinalCause} onEdit={() => undefined} initialQuery={ownFinal?.conclusive_cod ?? ""} onForbidden={loseAllocation} />
        {state.error ? <Text accessibilityRole="alert" style={styles.error}>{state.error}</Text> : null}
        <Button label="Save final cause" disabled={!selected || state.busy} loading={state.busy} onPress={() => void saveMaskedFinal()} />
        {identity.mode === "coding" ? <NotCodeableAction reason={notCodeableReason} other={notCodeableOther} busy={state.busy} onReason={setNotCodeableReason} onOther={setNotCodeableOther} onSubmit={() => void reportNotCodeable()} /> : null}
      </View>
    );
  }

  const part1 = array(certificate.Part1).filter(isRecord) as CertificateLine[];
  const processing = state.processing;
  const ownFinal = identity.mode === "reviewing" ? workspace.assessments.reviewer_final : workspace.assessments.final;

  async function saveMaskedFinal() {
    const requestId = ++generation.current;
    const sentRevision = revision;
    if (!state.selectedCause) return;
    update((current) => ({ ...current, busy: true, error: "" }));
    try {
      await api.saveFinal(identity.vaSid, { conclusive_cod: state.selectedCause.code }, identity.mode === "reviewing" ? "reviewing" : "coding");
      if (!currentRequest(requestId, sentRevision)) return;
      onDone();
    } catch (saveError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (saveError instanceof ApiError && saveError.status === 403) {
        clearAllocation();
      } else {
        const message = makeSaveError(saveError);
        if (saveError instanceof ApiError && (saveError.status === 422 || saveError.code === "final_blocked")) {
          try { await onSaved(); } catch { /* keep the save refusal visible */ }
        }
        if (currentRequest(requestId, sentRevision)) update((current) => ({ ...current, busy: false, error: message }));
      }
    }
  }

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>{isInitial ? "DORIS certificate — Step 1" : "DORIS certificate and final cause"}</Text>
      {state.notice ? <Text style={styles.muted}>{state.notice}</Text> : null}
      {workspace.doris.saved_processing ? <ProcessingSummary processing={null} saved={workspace.doris.saved_processing} /> : null}
      {workspace.doris.prefill_provenance && Object.keys(object(workspace.doris.prefill_provenance)).length ? <Text style={styles.muted}>Some fields were prefilled from the interview.</Text> : null}
      {Object.keys(object(certificate.AdministrativeData)).length ? <AdministrativeFields certificate={certificate} onChange={setField} /> : <Text style={styles.muted}>Administrative data was not supplied for this certificate.</Text>}
      <Text style={styles.headline}>Part I — causal sequence</Text>
      {part1.map((line, index) => (
        <CertificateLine key={`${identityKey}:${index}`} index={index} line={line} api={api} request={request} identity={identity} onForbidden={loseAllocation} isLast={index === part1.length - 1} onChange={(next) => updatePart1(part1.map((item, itemIndex) => itemIndex === index ? next : item))} onRemove={() => updatePart1(part1.filter((_item, itemIndex) => itemIndex !== index))} onMove={(direction) => {
          if ((direction < 0 && index === 0) || (direction > 0 && index === part1.length - 1)) return;
          const next = [...part1];
          [next[index + direction], next[index]] = [next[index], next[index + direction]];
          updatePart1(next);
        }} />
      ))}
      {part1.length < 5 ? <Button label="Add Part I line" kind="secondary" onPress={() => updatePart1([...part1, { Conditions: [] }])} /> : null}
      <CertificateLine key={`${identityKey}:part2`} index={0} line={object(certificate.Part2) as CertificateLine} part2 api={api} request={request} identity={identity} onForbidden={loseAllocation} onChange={(next) => { const copyCert = copy(certificate); copyCert.Part2 = next; invalidate(copyCert); }} onRemove={() => { const next = copy(certificate); delete next.Part2; invalidate(next); }} />
      <CertificateDetails certificate={certificate} onChange={setField} />
      {processing ? <ProcessingSummary processing={processing} /> : null}
      {processing ? (
        <IcdSelector key={identityKey} label={isInitial ? "Confirm Step 1 underlying cause" : "Choose and confirm the final underlying cause"} api={api} request={request} identity={identity} value={state.selectedCause} onSelect={chooseFinalCause} onEdit={() => undefined} initialQuery={isInitial ? codeFromResult(processingResult(processing, "doris")) : ownFinal?.conclusive_cod ?? ""} onForbidden={loseAllocation} />
      ) : null}
      {state.reconfirm ? <Text accessibilityRole="alert" style={styles.error}>Fresh processing replaced the previous result; confirm your final cause again.</Text> : null}
      {state.error ? <Text accessibilityRole="alert" style={styles.error}>{state.error}</Text> : null}
      <Button label="Process current certificate" kind="secondary" disabled={!canEdit || state.busy} loading={state.busy} onPress={() => void process()} />
      <Button label={isInitial ? "Save Step 1" : "Save final COD"} disabled={!state.processing || !state.selectedCause || state.busy} loading={state.busy} onPress={() => void save()} />
      {identity.mode === "coding" ? <NotCodeableAction reason={notCodeableReason} other={notCodeableOther} busy={state.busy} onReason={setNotCodeableReason} onOther={setNotCodeableOther} onSubmit={() => void reportNotCodeable()} /> : null}
    </View>
  );
}

/** Shows the five server-supported not-codeable reasons to coders only. */
function NotCodeableAction({ reason, other, busy, onReason, onOther, onSubmit }: {
  reason: string;
  other: string;
  busy: boolean;
  onReason: (value: string) => void;
  onOther: (value: string) => void;
  onSubmit: () => void;
}) {
  const reasons = [
    ["narration_language", "Narration language"],
    ["narration_doesnt_match", "Narration does not match"],
    ["no_info", "No information"],
    ["form_is_empty", "Form is empty"],
    ["others", "Other"],
  ] as const;
  return (
    <View>
      <Text style={styles.muted}>Report not codeable</Text>
      <WhoVaQuestionControls.SingleChoice
        question={choiceQuestion("doris_not_codeable", "Not-codeable reason", reasons.map(([value, label]) => ({ value, label })), busy)}
        value={reason || undefined}
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={(value) => { if (typeof value === "string") onReason(value); }}
      />
      {reason === "others" ? <TextInput accessibilityLabel="Other not-codeable reason" placeholder="Reason" value={other} onChangeText={onOther} style={styles.input} /> : null}
      <Button label="Submit not-codeable report" kind="secondary" disabled={busy || !reason || (reason === "others" && !other.trim())} loading={busy} onPress={onSubmit} />
    </View>
  );
}

function CertificateLine({ index, line, part2 = false, api, request, identity, onForbidden, isLast, onChange, onRemove, onMove }: {
  index: number;
  line: CertificateLine;
  part2?: boolean;
  api: WorkspaceApi;
  request: JsonRequester;
  identity: WorkspaceIdentity;
  onForbidden: () => void;
  isLast?: boolean;
  onChange: (line: CertificateLine) => void;
  onRemove: () => void;
  onMove?: (direction: -1 | 1) => void;
}) {
  const [uncodedText, setUncodedText] = useState("");
  const conditions = lineConditions(line);
  const interval = text(conditions[0]?.Interval);
  const updateCondition = (conditionIndex: number, update: JsonObject | null) => {
    const next = conditions.flatMap((condition, current) => current === conditionIndex ? update ? [update] : [] : [condition]);
    onChange({ ...line, Conditions: next });
  };
  const editCondition = (conditionIndex: number, key: string, value: JsonValue | undefined) => {
    const next = conditions.map((condition, current) => {
      if (current !== conditionIndex) return condition;
      const updated = { ...condition };
      if (value === undefined || value === "") delete updated[key]; else updated[key] = value;
      return updated;
    });
    onChange({ ...line, Conditions: next });
  };
  const addCondition = (choice: { code: string; title: string; uri: string }) => {
    onChange({ ...line, Conditions: [...conditions, { Text: choice.title, Code: choice.code, LinearizationURI: choice.uri, ...(interval ? { Interval: interval } : {}) }] });
  };
  const setInterval = (value: string) => onChange({ ...line, Conditions: conditions.map((condition) => {
    const next = { ...condition };
    if (value) next.Interval = value; else delete next.Interval;
    return next;
  }) });

  return (
    <View style={styles.card}>
      <Text style={styles.headline}>{part2 ? "Part II — contributing conditions" : `${index === 0 ? "Immediate cause" : "Due to"} (line ${index + 1})`}</Text>
      {conditions.map((condition, conditionIndex) => {
        const selected = typeof condition.Code === "string" && typeof condition.LinearizationURI === "string"
          ? { code: condition.Code, title: text(condition.Text), uri: condition.LinearizationURI }
          : null;
        return (
          <View key={`${conditionIndex}:${selected?.code ?? "uncoded"}`} style={styles.card}>
            <TextInput accessibilityLabel={`${part2 ? "Part II" : `Part I line ${index + 1}`} condition text ${conditionIndex + 1}`} placeholder="Condition text" value={text(condition.Text)} onChangeText={(value) => editCondition(conditionIndex, "Text", value)} style={styles.input} />
            {selected ? (
              <IcdSelector key={`${identity.vaSid}:${identity.mode}:${conditionIndex}`} label={`Condition ${conditionIndex + 1} WHO code`} api={api} request={request} identity={identity} onForbidden={onForbidden} value={selected} onSelect={(choice) => {
                const next = { ...condition };
                if (choice) { next.Code = choice.code; next.LinearizationURI = choice.uri; next.Text = choice.title || next.Text; }
                else { delete next.Code; delete next.LinearizationURI; }
                updateCondition(conditionIndex, next);
              }} onEdit={() => undefined} />
            ) : (
              <IcdSelector key={`${identity.vaSid}:${identity.mode}:empty:${conditionIndex}`} label={`Add WHO code to condition ${conditionIndex + 1}`} api={api} request={request} identity={identity} onForbidden={onForbidden} onSelect={(choice) => { if (choice) addCondition(choice); }} onEdit={() => undefined} />
            )}
            <Button label={`Remove condition ${conditionIndex + 1}`} kind="secondary" onPress={() => updateCondition(conditionIndex, null)} />
          </View>
        );
      })}
      {conditions.length < 8 ? <IcdSelector key={`${identity.vaSid}:${identity.mode}:add`} label="Add a coded condition" api={api} request={request} identity={identity} onForbidden={onForbidden} onSelect={(choice) => { if (choice) addCondition(choice); }} onEdit={() => undefined} /> : null}
      {conditions.length ? <TextInput accessibilityLabel={`${part2 ? "Part II" : `Part I line ${index + 1}`} interval`} placeholder="Interval, ISO 8601 duration (for example P2D)" value={interval} onChangeText={setInterval} style={styles.input} /> : null}
      <TextInput accessibilityLabel={part2 ? "Part II uncoded condition" : `Part I line ${index + 1} uncoded condition`} placeholder="Uncoded condition text" value={uncodedText} onChangeText={setUncodedText} style={styles.input} />
      {uncodedText.trim() ? <Button label="Add uncoded condition" kind="secondary" onPress={() => {
        onChange({ ...line, Conditions: [...conditions, { Text: uncodedText.trim(), ...(interval ? { Interval: interval } : {}) }] });
        setUncodedText("");
      }} disabled={conditions.length >= 8} /> : null}
      {!part2 ? (
        <View>
          {onMove ? <Button label={`Move Part I line ${index + 1} up`} kind="secondary" disabled={index === 0} onPress={() => onMove(-1)} /> : null}
          {onMove ? <Button label={`Move Part I line ${index + 1} down`} kind="secondary" disabled={isLast} onPress={() => onMove(1)} /> : null}
          <Button label={`Remove Part I line ${index + 1}`} kind="secondary" onPress={onRemove} disabled={index === 0} />
        </View>
      ) : conditions.length === 0 ? null : <Button label="Remove Part II" kind="secondary" onPress={onRemove} />}
    </View>
  );
}

function AdministrativeFields({ certificate, onChange }: { certificate: JsonObject; onChange: (section: string, key: string, value: JsonValue | undefined) => void }) {
  const data = object(certificate.AdministrativeData);
  return (
    <View>
      <Text style={styles.headline}>Administrative data</Text>
      <ChoiceField label="Sex" value={data.Sex} options={[[1, "Male"], [2, "Female"], [9, "Undetermined"]]} onChange={(value) => onChange("AdministrativeData", "Sex", value)} />
      <TextInput accessibilityLabel="Date of birth" placeholder="Date of birth (WHO date)" value={text(data.DateBirth)} onChangeText={(value) => onChange("AdministrativeData", "DateBirth", value)} style={styles.input} />
      <TextInput accessibilityLabel="Date of death" placeholder="Date of death (WHO date)" value={text(data.DateDeath)} onChangeText={(value) => onChange("AdministrativeData", "DateDeath", value)} style={styles.input} />
      <TextInput accessibilityLabel="Estimated age" placeholder="Estimated age (ISO 8601 duration)" value={text(data.EstimatedAge)} onChangeText={(value) => onChange("AdministrativeData", "EstimatedAge", value)} style={styles.input} />
    </View>
  );
}

function CertificateDetails({ certificate, onChange }: { certificate: JsonObject; onChange: (section: string, key: string, value: JsonValue | undefined) => void }) {
  const sex = object(certificate.AdministrativeData).Sex;
  const maternalApplies = sex === undefined || sex === 2 || sex === 9;
  const pregnancy = object(certificate.MaternalDeath).WasPregnant;
  return (
    <View>
      <Text style={styles.headline}>Certificate context</Text>
      <ChoiceField label="Manner of death" value={object(certificate.MannerOfDeath).MannerOfDeath} options={[[1, "Natural"], [2, "Accident"], [3, "Suicide"], [4, "Homicide"], [5, "Legal intervention"], [6, "War"], [7, "Pending investigation"], [8, "Undetermined"], [9, "Unknown"]]} onChange={(value) => onChange("MannerOfDeath", "MannerOfDeath", value)} />
      <TextInput accessibilityLabel="External cause date" placeholder="Date of external cause or poisoning" value={text(object(certificate.MannerOfDeath).DateOfExternalCauseOrPoisoning)} onChangeText={(value) => onChange("MannerOfDeath", "DateOfExternalCauseOrPoisoning", value)} style={styles.input} />
      <TextInput accessibilityLabel="External cause description" placeholder="Description of external cause" value={text(object(certificate.MannerOfDeath).DescriptionExternalCause)} onChangeText={(value) => onChange("MannerOfDeath", "DescriptionExternalCause", value)} style={styles.input} />
      <ChoiceField label="Place of external cause" value={object(certificate.MannerOfDeath).PlaceOfOccuranceExternalCause} options={[[1, "Home"], [2, "Residential institution"], [3, "School or public area"], [4, "Sports area"], [5, "Street or highway"], [6, "Trade or service area"], [7, "Industrial or construction area"], [8, "Farm"], [9, "Other or unknown"]]} onChange={(value) => onChange("MannerOfDeath", "PlaceOfOccuranceExternalCause", value)} />
      <ChoiceField label="Surgery performed" value={object(certificate.Surgery).WasPerformed} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("Surgery", "WasPerformed", value)} />
      <TextInput accessibilityLabel="Surgery date" placeholder="Surgery date" value={text(object(certificate.Surgery).Date)} onChangeText={(value) => onChange("Surgery", "Date", value)} style={styles.input} />
      <TextInput accessibilityLabel="Surgery reason" placeholder="Reason for surgery" value={text(object(certificate.Surgery).Reason)} onChangeText={(value) => onChange("Surgery", "Reason", value)} style={styles.input} />
      <ChoiceField label="Autopsy requested" value={object(certificate.Autopsy).WasRequested} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("Autopsy", "WasRequested", value)} />
      <ChoiceField label="Autopsy findings used" value={object(certificate.Autopsy).Findings} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("Autopsy", "Findings", value)} />
      <ChoiceField label="Stillborn" value={object(certificate.FetalOrInfantDeath).Stillborn} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("FetalOrInfantDeath", "Stillborn", value)} />
      <ChoiceField label="Multiple pregnancy" value={object(certificate.FetalOrInfantDeath).MultiplePregnancy} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("FetalOrInfantDeath", "MultiplePregnancy", value)} />
      {(["DeathWithin24h", "BirthWeight", "PregnancyWeeks", "AgeMother"] as const).map((field) => <TextInput key={field} accessibilityLabel={field} placeholder={field} keyboardType="numeric" value={text(object(certificate.FetalOrInfantDeath)[field])} onChangeText={(value) => onChange("FetalOrInfantDeath", field, value === "" ? undefined : Number(value))} style={styles.input} />)}
      <TextInput accessibilityLabel="Perinatal description" placeholder="Perinatal description" value={text(object(certificate.FetalOrInfantDeath).PerinatalDescription)} onChangeText={(value) => onChange("FetalOrInfantDeath", "PerinatalDescription", value)} style={styles.input} />
      {maternalApplies ? (
        <View>
          <ChoiceField label="Was the deceased pregnant?" value={object(certificate.MaternalDeath).WasPregnant} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("MaternalDeath", "WasPregnant", value)} />
          {pregnancy === 1 ? (
            <>
              <ChoiceField label="Time from pregnancy" value={object(certificate.MaternalDeath).TimeFromPregnancy} options={[[1, "During pregnancy"], [2, "Delivery"], [3, "Within 42 days"], [4, "43 days to 1 year"]]} onChange={(value) => onChange("MaternalDeath", "TimeFromPregnancy", value)} />
              <ChoiceField label="Pregnancy contributed to death" value={object(certificate.MaternalDeath).PregnancyContribute} options={[[1, "Yes"], [0, "No"], [9, "Unknown"]]} onChange={(value) => onChange("MaternalDeath", "PregnancyContribute", value)} />
            </>
          ) : null}
        </View>
      ) : <Text style={styles.muted}>Pregnancy fields are not applicable for this sex; existing follow-up answers will be excluded from processing.</Text>}
      {maternalApplies && pregnancy !== 1 && pregnancy !== undefined ? <Text style={styles.muted}>Pregnancy follow-up answers are excluded from processing unless pregnancy is Yes.</Text> : null}
    </View>
  );
}

function ChoiceField({ label, value, options, onChange }: { label: string; value: JsonValue | undefined; options: ReadonlyArray<readonly [number, string]>; onChange: (value: JsonValue | undefined) => void }) {
  return (
    <View>
      <Text style={styles.text}>{label}</Text>
      <WhoVaQuestionControls.SingleChoice
        question={choiceQuestion(`doris_${label.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`, label, options.map(([code, title]) => ({ value: String(code), label: title })), false, true)}
        value={value === undefined ? NOT_SET_VALUE : String(value)}
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={(next) => onChange(typeof next === "string" && next !== NOT_SET_VALUE ? Number(next) : undefined)}
      />
    </View>
  );
}

/** Adapt DORIS metadata to the same WHO choice control used by the VA interview. */
function choiceQuestion(name: string, label: string, options: Array<{ value: string; label: string }>, readOnly = false, includeNotSet = false): InstrumentQuestion {
  const choices = includeNotSet ? [{ value: NOT_SET_VALUE, label: "Not set" }, ...options] : options;
  return {
    name,
    order: 0,
    sourceRow: 0,
    sourceType: "doris_certificate",
    dataType: "string",
    control: "singleChoice",
    label: { en: label },
    hint: {},
    guidance: {},
    required: false,
    readOnly,
    constraintMessage: {},
    sectionPath: [],
    choices: choices.map((choice, index) => ({ ...choice, label: { en: choice.label }, sourceRow: index })),
  };
}

function ProcessingSummary({ processing, saved }: { processing: DorisProcessReply | null; saved?: JsonObject }) {
  const savedDoris = object(saved?.doris);
  const savedCodedit = object(saved?.codedit);
  const dorisStatus = processing?.doris.status ?? (typeof savedDoris.status === "string" ? savedDoris.status : undefined);
  const codeditStatus = processing?.codedit.status ?? (typeof savedCodedit.status === "string" ? savedCodedit.status : undefined);
  const dr = object(processing?.doris.result ?? savedDoris.result);
  const cr = object(processing?.codedit.result ?? savedCodedit.result);
  return (
    <View>
      <Text style={styles.headline}>DORIS and CoDEdit</Text>
      <Text style={styles.text}>DORIS: {dorisStatus ?? "not processed"}</Text>
      {typeof dr.warning === "string" ? <Text style={styles.muted}>Warning: {dr.warning}</Text> : null}
      {typeof dr.error === "string" ? <Text style={styles.error}>{dr.error}</Text> : null}
      {dr.reject === true ? <Text style={styles.error}>DORIS rejected the certificate result.</Text> : null}
      {typeof dr.code === "string" ? <Text style={styles.text}>Computed UCOD: {dr.code}</Text> : null}
      {typeof dr.stemCode === "string" ? <Text style={styles.text}>Computed stem: {dr.stemCode}</Text> : null}
      {typeof dr.uri === "string" ? <Text style={styles.muted}>Computed URI: {dr.uri}</Text> : null}
      {typeof dr.report === "string" ? <Text style={styles.muted}>{dr.report}</Text> : null}
      <Text style={styles.text}>CoDEdit: {codeditStatus ?? "not processed"}</Text>
      {typeof cr.report === "string" ? <Text style={styles.muted}>{cr.report}</Text> : null}
      {typeof cr.tabularReport === "string" ? <Text style={styles.muted}>{cr.tabularReport}</Text> : null}
      {saved && typeof saved.final_choice === "string" ? <Text style={styles.text}>Saved Step 1 choice: {saved.final_choice}</Text> : null}
    </View>
  );
}

/** Renders only the owner's Step 1 conditions for masked Step 2 review. */
function CertificateReference({ certificate }: { certificate: JsonObject | null }) {
  if (!certificate) return null;
  const part1 = array(certificate.Part1).filter(isRecord) as CertificateLine[];
  const part2 = lineConditions(certificate.Part2);
  return (
    <View>
      <Text style={styles.headline}>Your Step 1 certificate</Text>
      {part1.map((line, index) => (
        <View key={`p1:${index}`}>
          <Text style={styles.text}>Part I, line {index + 1}</Text>
          {lineConditions(line).map((condition, conditionIndex) => (
            <Text key={conditionIndex} style={styles.muted}>{text(condition.Text)}{text(condition.Code) ? ` — ${text(condition.Code)}` : ""}{text(condition.Interval) ? ` (${text(condition.Interval)})` : ""}</Text>
          ))}
        </View>
      ))}
      {part2.length ? (
        <View>
          <Text style={styles.text}>Part II</Text>
          {part2.map((condition, index) => <Text key={index} style={styles.muted}>{text(condition.Text)}{text(condition.Code) ? ` — ${text(condition.Code)}` : ""}</Text>)}
        </View>
      ) : null}
    </View>
  );
}

function SmartVaReference({ value }: { value: JsonValue }) {
  const data = object(value);
  const causes = array(data.causes).filter((item): item is JsonObject => isRecord(item));
  return (
    <View>
      <Text style={styles.headline}>SmartVA reference</Text>
      {text(data.age) ? <Text style={styles.text}>Age: {text(data.age)}</Text> : null}
      {text(data.gender) ? <Text style={styles.text}>Gender: {text(data.gender)}</Text> : null}
      {causes.map((cause, index) => <Text key={index} style={styles.muted}>{text(cause.cause as JsonValue)} — ICD-11 {text(cause.icd11 as JsonValue)}</Text>)}
    </View>
  );
}
