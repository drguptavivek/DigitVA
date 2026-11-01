import { useEffect, useRef, useState } from "react";
import { Linking, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { getRandomValues } from "expo-crypto";
import { WhoVaQuestionControls } from "../whoControls";
import type { InstrumentQuestion } from "@drguptavivek/who-2022-va";

import { ApiError } from "../api";
import { t } from "../i18n";
import { controls } from "../theme";
import { Button, errorText, useUiStyles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { IcdSearchItem, VaDefinition, VaDefinitionListItem, WorkspaceAssessment, WorkspacePayload } from "./contracts";
import { definitionPlainText } from "./doris/CodeDetailsSheet";

type FieldName = "immediate_cod" | "antecedent_cod" | "conclusive_cod";
type Codes = Record<FieldName, string>;
type Classification = "icd10" | "icd11";
/** A code picked from a search's results: Flask forwards these as cod_search_id, cod_chosen_code and cod_chosen_rank. */
type SearchChoice = { searchId: string; code: string; rank: number };

// The Flask coding screens' reference links (_icd_classification_switch.html, vainitialasses.html).
const ICD_BROWSERS = {
  icd10: { url: "https://icd.who.int/browse10/2019/en", label: "ICD-10 Browser" },
  icd11: { url: "https://icd.who.int/browse/2026-01/mms/en", label: "ICD-11 Browser" },
} as const;
const SELECTED_CODES_PATH = "/static/WHO_2022_VA_CODES.pdf";
const MIN_QUERY = 2;
const touchRow = { minHeight: controls.minTouchTarget, justifyContent: "center" as const, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 };
const box = { padding: 12, borderRadius: 8, gap: 4 };

/** Collects and saves simple COD using only codes returned by the case's ICD edition, worded as the Flask Step 1 and Step 2 screens. */
export function SimpleCodPanel({
  workspace,
  identity,
  api,
  serverOrigin,
  onSaved,
  onAllocationLost,
  onDone,
}: {
  workspace: WorkspacePayload;
  identity: { vaSid: string; mode: "coding" | "reviewing" };
  api: WorkspaceApi;
  /** The server for the Selected ICD Codes PDF on a phone; the browser resolves the path against its own origin. */
  serverOrigin?: string;
  onSaved: (blockedMessage?: string) => Promise<void>;
  onAllocationLost: () => void;
  onDone: () => void;
}) {
  const styles = useUiStyles();
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
  const [conclusiveChoice, setConclusiveChoice] = useState<SearchChoice | null>(null);
  const [notCodeableReason, setNotCodeableReason] = useState("");
  const [notCodeableOther, setNotCodeableOther] = useState("");
  const [screen, setScreen] = useState<"assessment" | "not_codeable">("assessment");
  const [definitionsOpen, setDefinitionsOpen] = useState(false);
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
    setConclusiveChoice(null);
  }, [source]);

  const isDoris = workspace.case.project_mode.endsWith("_doris");
  const isInitial = workspace.step === "initial";
  const unmasked = workspace.case.project_mode.startsWith("unmasked_");
  const classification = workspace.case.icd_classification;
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
        // Only a pick from a search links back to it; a prefilled code stays unlinked, as in Flask.
        const choice = conclusiveChoice && conclusiveChoice.code === codes.conclusive_cod ? conclusiveChoice : null;
        const body = {
          conclusive_cod: codes.conclusive_cod,
          remark,
          ...(unmasked ? { immediate_cod: codes.immediate_cod, other_conditions: otherConditions.join(" | ") } : {}),
          ...(choice ? { cod_search_id: choice.searchId, cod_chosen_code: choice.code, cod_chosen_rank: choice.rank } : {}),
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

  const errorLine = error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null;
  if (screen === "not_codeable") {
    return (
      <View style={styles.card}>
        <NotCodeablePanel api={api} vaSid={identity.vaSid} reason={notCodeableReason} other={notCodeableOther} onReason={setNotCodeableReason} onOther={setNotCodeableOther} onDone={onDone} onError={setError} />
        {errorLine}
        <Button kind="secondary" label="Back to assessment" onPress={() => { setError(""); setScreen("assessment"); }} />
      </View>
    );
  }

  const required = isInitial
    ? Boolean(codes.immediate_cod && codes.antecedent_cod)
    : Boolean(codes.conclusive_cod && (!unmasked || codes.immediate_cod));
  const field = (name: FieldName, label: string, hint?: string, onChoice?: (choice: SearchChoice | null) => void) => (
    <IcdCodeField
      label={label}
      hint={hint}
      value={codes[name]}
      api={api}
      identity={identity}
      classification={classification}
      serverOrigin={serverOrigin}
      onShowDefinitions={api.listVaDefinitions ? () => setDefinitionsOpen(true) : undefined}
      onAllocationLost={onAllocationLost}
      onChange={(value) => setCodes((old) => ({ ...old, [name]: value }))}
      onChoice={onChoice}
    />
  );
  const setConclusive = (choice: SearchChoice | null) => setConclusiveChoice(choice);
  const step1 = identity.mode === "reviewing" ? workspace.assessments.reviewer_initial : workspace.assessments.initial;
  const previousFinal = identity.mode === "coding" ? workspace.assessments.final?.conclusive_cod : null;

  return (
    <View style={styles.card}>
      {isInitial ? (
        <>
          <Text accessibilityRole="header" style={styles.headline}>Cause of Death Ascertainment - Step 1</Text>
          <Notice title="Important:" items={[
            "Please choose the most likely antecendent and immediate causes of death.",
            "You will have an opportunity to change the cause of death in second step.",
          ]} />
          {field("immediate_cod", "Immediate Cause of Death", "State the disease, injury or complication which caused death, not the mode of dying such as heart failure, asthenia.")}
          {field("antecedent_cod", "Antecedent Cause of Death", "Underlying condition giving rise to the above cause, copy the Immediate cause if no underlying cause of death can be identified.")}
          <ConditionPicker label="Other significant conditions (if any)" hint="Please select other underlying conditions, if any." options={choices} selected={otherConditions} onChange={setOtherConditions} />
        </>
      ) : unmasked ? (
        <>
          <Text accessibilityRole="header" style={styles.headline}>Final Cause of Death Assessment</Text>
          <Notice items={["Enter the immediate and underlying causes in one final assessment. Associated conditions are optional."]} />
          {field("immediate_cod", "Immediate cause")}
          {field("conclusive_cod", "Underlying cause", undefined, setConclusive)}
          <Text style={styles.fieldLabel}>Associated conditions (optional)</Text>
          <TextInput accessibilityLabel="Associated conditions (optional)" value={otherConditions.join(" | ")} onChangeText={(value) => setOtherConditions(value ? value.split("|").map((part) => part.trim()).filter(Boolean) : [])} style={styles.input} multiline />
        </>
      ) : (
        <>
          <Text accessibilityRole="header" style={styles.headline}>Cause of Death Ascertainment - Step 2</Text>
          <Notice title="Instructions:" items={[
            "Kindly review the SMART VA analysis presented above.",
            "Based on your interpretation and after reviewing SMART VA recommendations, assign your final underlying cause of death.",
          ]} />
          <SummaryCard title="Your Step 1 Assigned Causes:" rows={[
            ["Immediate COD:", step1?.immediate_cod ?? ""],
            ["Antecedent COD:", step1?.antecedent_cod ?? ""],
            ["Other Underlying Conditions (if any):", conditionList(step1).join(", ")],
          ]} />
          {previousFinal ? <SummaryCard title="Previous Final COD (Before This Recode):" rows={[["Final Underlying / Antecedent COD:", previousFinal]]} /> : null}
          {field("conclusive_cod", "Final Underlying / Antecedent Cause of Death", undefined, setConclusive)}
        </>
      )}
      {!isInitial ? (
        <>
          <Text style={styles.fieldLabel}>{unmasked ? "Remarks" : "Remarks (if any)"}</Text>
          <TextInput accessibilityLabel={unmasked ? "Remarks" : "Remarks (if any)"} placeholder={unmasked ? undefined : "Please enter the additional details here, if any."} value={remark} onChangeText={setRemark} style={styles.input} multiline />
        </>
      ) : null}
      {errorLine}
      <View style={styles.row}>
        <Button label={unmasked && !isInitial ? "Save final assessment" : "Save Assessment"} onPress={() => void save()} disabled={!required || busy} loading={busy} />
        {identity.mode === "coding" ? <Button kind="danger" label="Not Codeable" disabled={busy} onPress={() => { setError(""); setScreen("not_codeable"); }} /> : null}
      </View>
      {classification === "icd11" ? <Text testID="icd11-citation" style={styles.muted}>{t("icd11Citation")}</Text> : null}
      {definitionsOpen ? <VaDefinitionsModal api={api} onClose={() => setDefinitionsOpen(false)} /> : null}
    </View>
  );
}

/** The bordered note under a Flask step heading: an optional bold title over its bullet lines. */
function Notice({ title, items }: { title?: string; items: string[] }) {
  const styles = useUiStyles();
  return (
    <View style={[styles.secondary, box]}>
      {title ? <Text style={styles.fieldLabel}>{title}</Text> : null}
      {items.map((item) => <Text key={item} style={styles.text}>{items.length > 1 ? `• ${item}` : item}</Text>)}
    </View>
  );
}

/** Earlier causes shown read-only above the Step 2 field, label over value. */
function SummaryCard({ title, rows }: { title: string; rows: Array<[string, string]> }) {
  const styles = useUiStyles();
  return (
    <View style={[styles.secondary, box]}>
      <Text style={styles.muted}>{title}</Text>
      {rows.map(([label, value]) => (
        <View key={label}>
          <Text style={styles.muted}>{label}</Text>
          <Text style={styles.fieldLabel}>{value}</Text>
        </View>
      ))}
    </View>
  );
}

/** The Not Codeable screen (Flask vacoderreview.html); offers only the API's coder-supported reasons. */
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
  const styles = useUiStyles();
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  const requestGeneration = useRef(0);
  const context = useRef({ api, vaSid });
  context.current = { api, vaSid };
  useEffect(() => () => {
    active.current = false;
    requestGeneration.current += 1;
  }, []);
  // Flask's wording; form_is_empty is not in Flask's list but the API accepts it, so the app keeps offering it.
  const reasons = [
    ["narration_language", "I cannot read this narrative language."],
    ["narration_doesnt_match", "Narrative content doesn't match with the deceased whose VA form has been filled"],
    ["no_info", "There is no information available in Questions as well as Narration"],
    ["form_is_empty", "Form is empty"],
    ["others", "Others"],
  ] as const;
  return (
    <View style={{ gap: 8 }}>
      <Text accessibilityRole="header" style={styles.headline}>VA Form Not Codeable</Text>
      <Notice title="Please note:" items={[
        "Once reported an error, this VA form will be flagged for review by the Site PI.",
        "DigitVA saves the Not Codeable outcome locally first. ODK Central revision status is updated separately and any failure is logged for follow-up.",
      ]} />
      <RequiredLabel label="Please describe the reason for why the VA form could not be coded" />
      <WhoVaQuestionControls.SingleChoice
        question={choiceQuestion("simple_cod_not_codeable", "Not-codeable reason", reasons.map(([value, label]) => ({ value, label })), busy)}
        value={reason || undefined}
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={(value) => { if (typeof value === "string") onReason(value); }}
      />
      {reason === "others" ? (
        <>
          <RequiredLabel label="Please brief the other issue" />
          <TextInput accessibilityLabel="Please brief the other issue" placeholder="Brief about the issue here." value={other} onChangeText={onOther} style={styles.input} multiline />
        </>
      ) : null}
      <Button label="Report Issue" kind="danger" disabled={busy || !reason || (reason === "others" && !other.trim())} loading={busy} onPress={() => {
        const request = ++requestGeneration.current;
        const current = () => active.current
          && requestGeneration.current === request
          && context.current.api === api
          && context.current.vaSid === vaSid;
        setBusy(true);
        onError("");
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

function RequiredLabel({ label }: { label: string }) {
  const styles = useUiStyles();
  return <Text style={styles.fieldLabel}>{label}<Text style={styles.error}> *</Text></Text>;
}

/** WHO browser, the Selected ICD Codes PDF and the VA definitions list, beside each cause field as in Flask. */
function ReferenceLinks({ classification, serverOrigin, onShowDefinitions }: { classification: Classification; serverOrigin?: string; onShowDefinitions?: () => void }) {
  const styles = useUiStyles();
  const browser = ICD_BROWSERS[classification];
  // The PDF is a public static file, so the phone's system browser opens it without the app's session.
  const pdf = serverOrigin ? `${serverOrigin.replace(/\/+$/, "")}${SELECTED_CODES_PATH}` : Platform.OS === "web" ? SELECTED_CODES_PATH : null;
  return (
    <View style={styles.row}>
      <Button kind="secondary" size="sm" label={browser.label} onPress={() => void Linking.openURL(browser.url).catch(() => undefined)} />
      {pdf ? <Button kind="secondary" size="sm" label="Selected ICD Codes" onPress={() => void Linking.openURL(pdf).catch(() => undefined)} /> : null}
      {onShowDefinitions ? <Button kind="secondary" size="sm" label="VA Definitions" onPress={onShowDefinitions} /> : null}
    </View>
  );
}

/** Debounce case-specific catalogue lookup and discard replies from superseded queries. */
function IcdCodeField({
  label,
  hint,
  value,
  api,
  identity,
  classification,
  serverOrigin,
  onShowDefinitions,
  onAllocationLost,
  onChange,
  onChoice,
}: {
  label: string;
  hint?: string;
  value: string;
  api: WorkspaceApi;
  identity: { vaSid: string; mode: "coding" | "reviewing" };
  classification: Classification;
  serverOrigin?: string;
  onShowDefinitions?: () => void;
  onAllocationLost: () => void;
  onChange(value: string): void;
  /** The pick and the search it came from, or null once the coder edits it; only the field Flask links passes this. */
  onChoice?(choice: SearchChoice | null): void;
}) {
  const styles = useUiStyles();
  const [query, setQuery] = useState(value);
  const [reply, setReply] = useState<{ searchId: string; results: IcdSearchItem[]; excludedMessage?: string } | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [focused, setFocused] = useState(false);
  const requestId = useRef(0);
  // A pick keeps its display text in the box, as Select2 does; any other value change shows the code.
  const pickedDisplay = useRef<string | null>(null);

  useEffect(() => {
    setQuery(pickedDisplay.current ?? value);
    pickedDisplay.current = null;
  }, [value]);

  useEffect(() => {
    const sequence = ++requestId.current;
    const normalized = query.trim();
    setReply(null);
    setSearchError("");
    if (normalized.length < MIN_QUERY || normalized.length > 100 || value) {
      setSearching(false);
      return;
    }
    setSearching(true);
    const timer = setTimeout(() => {
      // A fresh id per request, as Flask's IcdCodingSearch.requestParams: a pick links to the search that listed it.
      const searchId = searchUuid();
      void api.searchIcd(identity.vaSid, classification, normalized, { searchId }).then((found) => {
        if (requestId.current === sequence) setReply({ searchId, ...found });
      }).catch((searchFailure) => {
        if (requestId.current !== sequence) return;
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

  const remaining = MIN_QUERY - query.trim().length;
  return (
    <View style={{ gap: 4 }}>
      <RequiredLabel label={label} />
      <ReferenceLinks classification={classification} serverOrigin={serverOrigin} onShowDefinitions={onShowDefinitions} />
      {hint ? <Text style={styles.muted}>{hint}</Text> : null}
      <TextInput
        accessibilityLabel={label}
        placeholder="Search ICD codes..."
        value={query}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChangeText={(text) => {
          setQuery(text.slice(0, 100));
          if (value) {
            onChange("");
            onChoice?.(null);
          }
        }}
        style={styles.input}
      />
      {/* Select2's inputTooShort wording (minimumInputLength 2). */}
      {!value && remaining > 0 && (focused || query.trim()) ? <Text style={styles.muted}>{`Please enter ${remaining} or more characters`}</Text> : null}
      {searching ? <Text style={styles.muted}>Searching…</Text> : null}
      {searchError ? <Text accessibilityRole="alert" style={styles.error}>{searchError}</Text> : null}
      {reply && !reply.results.length ? <Text style={styles.muted}>{reply.excludedMessage || "No results found"}</Text> : null}
      {reply ? tierGroups(reply.results).map((group) => (
        <View key={group.title} style={{ gap: 4 }}>
          <Text accessibilityRole="header" style={styles.muted}>{group.title}</Text>
          {group.rows.map(({ item, rank }) => (
            <Pressable
              key={`${item.icd_code ?? "none"}-${rank}`}
              accessibilityRole="button"
              accessibilityLabel={item.icd_to_display}
              onPress={() => {
                if (!item.icd_code) return;
                pickedDisplay.current = item.icd_to_display;
                onChange(item.icd_code);
                onChoice?.({ searchId: reply.searchId, code: item.icd_code, rank });
                setReply(null);
              }}
              style={[styles.secondary, touchRow]}
            >
              <Text style={styles.text}>{item.icd_to_display}</Text>
            </Pressable>
          ))}
        </View>
      )) : null}
      {value ? <Text style={styles.muted}>Selected code: {value}</Text> : null}
      {value ? <VaDefinitionNote api={api} code={value} classification={classification} fieldLabel={label} /> : null}
    </View>
  );
}

/**
 * Flask's two result groups by the API's `tier`: "focused" first, anything else (or no tier) under Term matches.
 * `rank` is the 0-based position in the server's list, the cod_chosen_rank Flask forwards.
 */
function tierGroups(results: IcdSearchItem[]) {
  const rows = results.slice(0, 30).map((item, rank) => ({ item, rank }));
  return [
    { title: "Focused matches", rows: rows.filter(({ item }) => item.tier === "focused") },
    { title: "Term matches", rows: rows.filter(({ item }) => item.tier !== "focused") },
  ].filter((group) => group.rows.length);
}

/** The VA cause a chosen code maps to, as Flask's floating definition panel; nothing when unmapped or the lookup fails. */
function VaDefinitionNote({ api, code, classification, fieldLabel }: { api: WorkspaceApi; code: string; classification: Classification; fieldLabel: string }) {
  const styles = useUiStyles();
  const [found, setFound] = useState<VaDefinition | null>(null);
  useEffect(() => {
    let live = true;
    setFound(null);
    // Information only, as CodeDetailsSheet: any failure, even a synchronous one, shows nothing.
    Promise.resolve().then(() => api.getVaDefinitionForIcd(code, classification))
      .then((definition) => { if (live) setFound(definition); }).catch(() => undefined);
    return () => { live = false; };
  }, [api, code, classification]);
  if (!found) return null;
  const bucket = found.bucket_label !== undefined;
  const text = bucket && found.has_definition === false ? "" : definitionPlainText(found.definition_html);
  return (
    <View testID="va-definition" style={[styles.secondary, box]}>
      <Text style={styles.muted}>{`VA definition · ${fieldLabel} · ${found.icd_code}`}</Text>
      {bucket && found.bucket_section ? <Text style={styles.muted}>{found.bucket_section}</Text> : null}
      <Text style={styles.fieldLabel}>{bucket ? `VA cause: ${found.bucket_label} (${found.va_code})` : `${found.va_code} ${found.title}`}</Text>
      {text ? <Text style={styles.text}>{text}</Text> : null}
      <Text style={styles.muted}>{t("digitvaAddition")}</Text>
    </View>
  );
}

/** Flask's "VA Codes, Titles and Definitions" modal: the whole list loaded once, filtered as the coder types. */
function VaDefinitionsModal({ api, onClose }: { api: WorkspaceApi; onClose: () => void }) {
  const styles = useUiStyles();
  const [items, setItems] = useState<VaDefinitionListItem[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    api.listVaDefinitions?.().then((list) => { if (live) setItems(list); }).catch((failure) => { if (live) setLoadError(errorText(failure)); });
    return () => { live = false; };
  }, [api]);
  const needle = filter.trim().toLowerCase().split(/\s+/).join(" ");
  const shown = (items ?? []).filter((item) => !needle || `${item.va_code} ${item.title} ${item.definition_text}`.toLowerCase().includes(needle));
  return (
    <Modal visible transparent={false} animationType="slide" onRequestClose={onClose}>
      {/* Themed page and a fixed header: the Modal paints white by default, and Close must not sit under ~60 rows. */}
      <View style={styles.safe}>
        <View testID="va-definitions-header" style={[styles.body, { gap: 8 }]}>
          <Text accessibilityRole="header" style={styles.headline}>VA Codes, Titles and Definitions</Text>
          <TextInput accessibilityLabel="Filter VA definitions" placeholder="Filter by VA cause name, code or definition" value={filter} onChangeText={setFilter} style={styles.input} />
          {loadError ? <Text accessibilityRole="alert" style={styles.error}>{loadError}</Text> : null}
          {items === null && !loadError ? <Text style={styles.muted}>Loading…</Text> : null}
          {items !== null ? <Text style={styles.muted}>{`${shown.length} of ${items.length}`}</Text> : null}
          <Button kind="secondary" label="Close" accessibilityLabel="Close" style={{ minHeight: controls.minTouchTarget }} onPress={onClose} />
        </View>
        <ScrollView testID="va-definitions-list" contentContainerStyle={[styles.body, { gap: 8 }]}>
          {shown.map((item) => (
            <View key={item.va_code} style={[styles.secondary, box]}>
              <Text style={styles.fieldLabel}>{`${item.va_code} ${item.title}`}</Text>
              {item.definition_text ? <Text style={styles.text}>{item.definition_text}</Text> : null}
            </View>
          ))}
          <Text style={styles.muted}>{t("digitvaAddition")}</Text>
        </ScrollView>
      </View>
    </Modal>
  );
}

/** Flask's Select2 multi-select for Step 1 other conditions: removable chips over a filtered list of the server's options. */
function ConditionPicker({ label, hint, options, selected, onChange }: { label: string; hint: string; options: string[]; selected: string[]; onChange(value: string[]): void }) {
  const styles = useUiStyles();
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
  if (!options.length) return null;
  const needle = filter.trim().toLowerCase();
  const available = options.filter((option) => !selected.includes(option) && option.toLowerCase().includes(needle));
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Text style={styles.muted}>{hint}</Text>
      {selected.length ? (
        <View style={styles.row}>
          {selected.map((option) => (
            <Pressable key={option} accessibilityRole="button" accessibilityLabel={`Remove ${option}`} testID={`other-condition-remove-${option}`} onPress={() => onChange(selected.filter((item) => item !== option))} style={[styles.secondary, touchRow]}>
              <Text style={styles.text}>{`${option} ×`}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      <TextInput accessibilityLabel={label} placeholder="Search conditions" value={filter} onFocus={() => setOpen(true)} onChangeText={(text) => { setFilter(text); setOpen(true); }} style={styles.input} />
      {open ? (
        <>
          {available.map((option) => (
            // Appended, so a saved value outside today's options is kept and the order is the coder's.
            <Pressable key={option} accessibilityRole="button" accessibilityLabel={`Add ${option}`} testID={`other-condition-option-${option}`} onPress={() => onChange([...selected, option])} style={[styles.secondary, touchRow]}>
              <Text style={styles.text}>{option}</Text>
            </Pressable>
          ))}
          {!available.length ? <Text style={styles.muted}>No results found</Text> : null}
          <Button kind="secondary" size="sm" label="Done" onPress={() => { setOpen(false); setFilter(""); }} />
        </>
      ) : null}
    </View>
  );
}

/** Adapt simple-COD metadata to the same WHO choice controls used by the VA interview. */
function choiceQuestion(name: string, label: string, options: Array<{ value: string; label: string }>, readOnly = false): InstrumentQuestion {
  return {
    name,
    order: 0,
    sourceRow: 0,
    sourceType: "simple_cod",
    dataType: "string",
    control: "singleChoice",
    label: { en: label },
    hint: {},
    guidance: {},
    required: false,
    readOnly,
    constraintMessage: {},
    sectionPath: [],
    choices: options.map((option, index) => ({ ...option, label: { en: option.label }, sourceRow: index })),
  };
}

/** A v4 UUID for `search_id`, made as Flask makes it: getRandomValues works where randomUUID needs a secure context. */
function searchUuid(): string {
  const bytes = getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
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
