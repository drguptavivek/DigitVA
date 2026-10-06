import { useEffect, useRef, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { ApiError } from "../api";
import { Button, errorText, styles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { IcdSearchItem, WorkspaceAssessment, WorkspacePayload } from "./contracts";

type FieldName = "immediate_cod" | "antecedent_cod" | "conclusive_cod";
type Codes = Record<FieldName, string>;

/** Collects and saves simple COD using only codes returned by the case's ICD edition. */
export function SimpleCodPanel({
  workspace,
  identity,
  api,
  onSaved,
  onAllocationLost,
  onDone,
}: {
  workspace: WorkspacePayload;
  identity: { vaSid: string; mode: "coding" | "reviewing" };
  api: WorkspaceApi;
  onSaved: (blockedMessage?: string) => Promise<void>;
  onAllocationLost: () => void;
  onDone: () => void;
}) {
  const source = workspace.step === "initial"
    ? identity.mode === "reviewing"
      ? workspace.assessments.reviewer_initial
      : workspace.assessments.initial_prefill ?? workspace.assessments.initial
    : identity.mode === "reviewing"
      ? workspace.assessments.reviewer_final
      : workspace.assessments.final;
  const [codes, setCodes] = useState<Codes>(() => initialCodes(source));
  const [otherConditions, setOtherConditions] = useState(() => conditionList(source));
  const [remark, setRemark] = useState(source?.remark ?? "");
  const [notCodeableReason, setNotCodeableReason] = useState("");
  const [notCodeableOther, setNotCodeableOther] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const initialSource = useRef(source);
  const active = useRef(true);
  const saveGeneration = useRef(0);
  const context = useRef({ api, vaSid: identity.vaSid, mode: identity.mode });
  context.current = { api, vaSid: identity.vaSid, mode: identity.mode };

  useEffect(() => () => {
    active.current = false;
    saveGeneration.current += 1;
  }, []);

  useEffect(() => {
    if (initialSource.current === source) return;
    initialSource.current = source;
    setCodes(initialCodes(source));
    setOtherConditions(conditionList(source));
    setRemark(source?.remark ?? "");
  }, [source]);

  const isDoris = workspace.case.project_mode.endsWith("_doris");
  const isInitial = workspace.step === "initial";
  const choices = workspace.other_conditions_options ?? [];

  const save = async () => {
    const request = ++saveGeneration.current;
    const current = () => active.current
      && saveGeneration.current === request
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    setBusy(true);
    setError("");
    try {
      if (isInitial) {
        await api.saveInitial(identity.vaSid, {
          immediate_cod: codes.immediate_cod,
          antecedent_cod: codes.antecedent_cod,
          other_conditions: otherConditions,
        }, identity.mode);
        if (!current()) return;
        await onSaved();
      } else {
        const body = {
          conclusive_cod: codes.conclusive_cod,
          remark,
          ...(workspace.case.project_mode.startsWith("unmasked_")
            ? { immediate_cod: codes.immediate_cod, other_conditions: otherConditions.join(" | ") }
            : {}),
        };
        await api.saveFinal(identity.vaSid, body, identity.mode);
        if (!current()) return;
        onDone();
      }
    } catch (saveError) {
      if (!current()) return;
      if (saveError instanceof ApiError && saveError.status === 422 && saveError.code === "final_blocked") {
        await onSaved(blockedMessages(saveError));
      } else if (saveError instanceof ApiError && saveError.status === 403) onDone();
      else setError(blockedMessages(saveError) || errorText(saveError));
    } finally {
      if (current()) setBusy(false);
    }
  };

  if (isDoris) return <Text style={styles.muted}>DORIS coding editor unavailable.</Text>;
  if (workspace.step !== "initial" && workspace.step !== "final") return null;

  const required = isInitial
    ? Boolean(codes.immediate_cod && codes.antecedent_cod)
    : Boolean(codes.conclusive_cod && (!workspace.case.project_mode.startsWith("unmasked_") || codes.immediate_cod));

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>{isInitial ? "Initial COD" : "Final COD"}</Text>
      {isInitial ? (
        <>
          <IcdCodeField label="Immediate cause" value={codes.immediate_cod} api={api} identity={identity} classification={workspace.case.icd_classification} onAllocationLost={onAllocationLost} onChange={(value) => setCodes((old) => ({ ...old, immediate_cod: value }))} />
          <IcdCodeField label="Antecedent cause" value={codes.antecedent_cod} api={api} identity={identity} classification={workspace.case.icd_classification} onAllocationLost={onAllocationLost} onChange={(value) => setCodes((old) => ({ ...old, antecedent_cod: value }))} />
          <ConditionChoices options={choices} selected={otherConditions} onChange={setOtherConditions} />
        </>
      ) : (
        <>
          <IcdCodeField label="Conclusive cause" value={codes.conclusive_cod} api={api} identity={identity} classification={workspace.case.icd_classification} onAllocationLost={onAllocationLost} onChange={(value) => setCodes((old) => ({ ...old, conclusive_cod: value }))} />
          {workspace.case.project_mode.startsWith("unmasked_") ? (
            <>
              <IcdCodeField label="Immediate cause" value={codes.immediate_cod} api={api} identity={identity} classification={workspace.case.icd_classification} onAllocationLost={onAllocationLost} onChange={(value) => setCodes((old) => ({ ...old, immediate_cod: value }))} />
              <TextInput accessibilityLabel="Other conditions" placeholder="Other conditions" value={otherConditions.join(" | ")} onChangeText={(value) => setOtherConditions(value ? value.split("|").map((part) => part.trim()).filter(Boolean) : [])} style={styles.input} />
            </>
          ) : null}
          <TextInput accessibilityLabel="COD remark" placeholder="Remark" value={remark} onChangeText={setRemark} style={styles.input} multiline />
        </>
      )}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Button label={isInitial ? "Save initial COD" : "Save final COD"} onPress={() => void save()} disabled={!required || busy} loading={busy} />
      {identity.mode === "coding" ? (
        <NotCodeablePanel api={api} vaSid={identity.vaSid} reason={notCodeableReason} other={notCodeableOther} onReason={setNotCodeableReason} onOther={setNotCodeableOther} onDone={onDone} onError={setError} />
      ) : null}
    </View>
  );
}

/** Offers only the API's coder-supported not-codeable reasons. */
function NotCodeablePanel({ api, vaSid, reason, other, onReason, onOther, onDone, onError }: {
  api: WorkspaceApi;
  vaSid: string;
  reason: string;
  other: string;
  onReason(value: string): void;
  onOther(value: string): void;
  onDone(): void;
  onError(value: string): void;
}) {
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  const requestGeneration = useRef(0);
  const context = useRef({ api, vaSid });
  context.current = { api, vaSid };
  useEffect(() => () => {
    active.current = false;
    requestGeneration.current += 1;
  }, []);
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
      {reasons.map(([value, label]) => (
        <Pressable key={value} accessibilityRole="radio" accessibilityLabel={`Not-codeable reason: ${label}`} accessibilityState={{ selected: reason === value }} onPress={() => onReason(value)}>
          <Text style={styles.text}>{reason === value ? "◉" : "○"} {label}</Text>
        </Pressable>
      ))}
      {reason === "others" ? <TextInput accessibilityLabel="Other not-codeable reason" placeholder="Reason" value={other} onChangeText={onOther} style={styles.input} /> : null}
      <Button label="Submit not-codeable report" kind="secondary" disabled={busy || !reason || (reason === "others" && !other.trim())} loading={busy} onPress={() => {
        const request = ++requestGeneration.current;
        const current = () => active.current
          && requestGeneration.current === request
          && context.current.api === api
          && context.current.vaSid === vaSid;
        setBusy(true);
        void api.saveNotCodeable(vaSid, { reason, other: reason === "others" ? other : "" }).then(() => {
          if (current()) onDone();
        }).catch((saveError) => {
          if (!current()) return;
          if (saveError instanceof ApiError && saveError.status === 403) onDone();
          else onError(errorText(saveError));
        }).finally(() => {
          if (current()) setBusy(false);
        });
      }} />
    </View>
  );
}

/** Debounce case-specific catalogue lookup and discard replies from superseded queries. */
function IcdCodeField({
  label,
  value,
  api,
  identity,
  classification,
  onAllocationLost,
  onChange,
}: {
  label: string;
  value: string;
  api: WorkspaceApi;
  identity: { vaSid: string; mode: "coding" | "reviewing" };
  classification: "icd10" | "icd11";
  onAllocationLost: () => void;
  onChange(value: string): void;
}) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<IcdSearchItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    setQuery(value);
  }, [value]);

  useEffect(() => {
    const sequence = ++requestId.current;
    const normalized = query.trim();
    setResults([]);
    setSearchError("");
    if (normalized.length < 2 || normalized.length > 100 || value) {
      setSearching(false);
      return;
    }
    setSearching(true);
    const timer = setTimeout(() => {
      void api.searchIcd(identity.vaSid, classification, normalized).then((items) => {
        if (requestId.current === sequence) setResults(items.slice(0, 30));
      }).catch((searchFailure) => {
        if (requestId.current !== sequence) return;
        setResults([]);
        if (searchFailure instanceof ApiError && searchFailure.status === 403) onAllocationLost();
        else setSearchError("Unable to search ICD codes. Try again.");
      }).finally(() => {
        if (requestId.current === sequence) setSearching(false);
      });
    }, 250);
    return () => {
      clearTimeout(timer);
      requestId.current += 1;
    };
  }, [api, classification, identity.vaSid, onAllocationLost, query, value]);

  return (
    <View>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholder={`Search ${classification.toUpperCase()} code`}
        value={query}
        onChangeText={(text) => {
          setQuery(text.slice(0, 100));
          if (value) onChange("");
        }}
        style={styles.input}
      />
      {searching ? <Text style={styles.muted}>Searching…</Text> : null}
      {searchError ? <Text accessibilityRole="alert" style={styles.error}>{searchError}</Text> : null}
      {results.map((item, index) => (
        <Pressable
          key={`${item.icd_code ?? "none"}-${index}`}
          accessibilityRole="button"
          accessibilityLabel={`${item.icd_code ?? ""} ${item.icd_to_display}`}
          onPress={() => {
            if (!item.icd_code) return;
            onChange(item.icd_code);
            setQuery(item.icd_to_display);
            setResults([]);
          }}
          style={styles.secondary}
        >
          <Text style={styles.text}>{item.icd_code ? `${item.icd_code} — ` : ""}{item.icd_to_display}</Text>
        </Pressable>
      ))}
      {value ? <Text style={styles.muted}>Selected code: {value}</Text> : null}
    </View>
  );
}

/** Render the server-provided Step 1 other-condition choices in their order. */
function ConditionChoices({ options, selected, onChange }: { options: string[]; selected: string[]; onChange(value: string[]): void }) {
  if (!options.length) return null;
  return (
    <View>
      <Text style={styles.muted}>Other conditions</Text>
      {options.map((option) => {
        const checked = selected.includes(option);
        return (
          <Pressable key={option} accessibilityRole="checkbox" accessibilityLabel={`Other condition: ${option}`} accessibilityState={{ checked }} onPress={() => onChange(checked ? selected.filter((value) => value !== option) : [...selected, option])}>
            <Text style={styles.text}>{checked ? "☑" : "☐"} {option}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Copy only the COD fields served for the caller's current step. */
function initialCodes(assessment: WorkspaceAssessment | null | undefined): Codes {
  return { immediate_cod: assessment?.immediate_cod ?? "", antecedent_cod: assessment?.antecedent_cod ?? "", conclusive_cod: assessment?.conclusive_cod ?? "" };
}

/** Normalize the API's list or legacy joined-string representation for the editor. */
function conditionList(assessment: WorkspaceAssessment | null | undefined): string[] {
  if (Array.isArray(assessment?.other_conditions)) return assessment.other_conditions;
  return assessment?.other_conditions?.split("|").map((value) => value.trim()).filter(Boolean) ?? [];
}

/** Read final-blocking messages from the documented 422 response without exposing other server text. */
function blockedMessages(error: unknown): string {
  if (!(error instanceof ApiError) || error.code !== "final_blocked" || !error.payload || typeof error.payload !== "object") return "";
  const messages = (error.payload as Record<string, unknown>).messages;
  return Array.isArray(messages) ? messages.filter((message): message is string => typeof message === "string").join("\n") : "";
}
