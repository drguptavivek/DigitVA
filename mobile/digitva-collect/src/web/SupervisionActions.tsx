import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { WhoVaQuestionControls } from "../whoControls";

import {
  cancelCase,
  getPossibleDuplicates,
  listCases,
  markDuplicate,
  reopenCase,
  resolveFlag,
  type PossibleDuplicate,
  type SupervisedCase,
} from "../supervision/api";
import { ApiError } from "../api";
import { t, type StringKey } from "../i18n";
import type { JsonRequester } from "../workspace/api";
import { choiceQuestion } from "../workspace/QualityPanels";
import { Button, useUiStyles } from "../ui";
import { browserErrorText } from "./common";

// Mirror the Flask page (app/static/js/intake/intake_supervision.js) and the
// server's transitions, only to decide which buttons to show.
const CANCELLABLE = ["draft_identity", "registered", "scheduled", "in_progress", "paused"];
const TERMINAL = ["submitted", "duplicate", "cancelled"];
const DUPLICABLE = ["registered", "scheduled", "in_progress", "paused", "submitted"];
// A kept case is never itself a duplicate, cancelled or still-unnamed case.
const NOT_KEPT = ["duplicate", "cancelled", "draft_identity"];
const REASON_MAX = 200;
// Server refusal codes of the supervision routes (app/routes/api/intake.py) that
// the supervisor can act on; any other code falls back to the generic text.
const SUPERVISION_ERROR_KEYS = new Map<string, StringKey>([
  ["wrong_state", "supervisionErrWrongState"],
  ["not_a_candidate", "supervisionErrNotCandidate"],
  ["case_not_submitted", "supervisionErrNotSubmitted"],
  ["form_mismatch", "supervisionErrFormMismatch"],
  ["not_web_submission", "supervisionErrNotWeb"],
  ["invalid_reason", "supervisionErrInvalidReason"],
  ["conflict", "supervisionErrConflict"],
  ["invalid_request", "supervisionErrInvalid"],
]);

type Form = "confirm" | "reject" | "duplicate" | "cancel" | "reopen";

/** The server's reason for a refused supervision call, in words; never the server's English text. */
export function supervisionErrorText(error: unknown): string {
  const key = error instanceof ApiError && error.code ? SUPERVISION_ERROR_KEYS.get(error.code) : undefined;
  return key ? t(key) : browserErrorText(error);
}

/** The supervisor's row actions; the server decides again on every call. */
export function SupervisionActions({
  request,
  row,
  onDone,
}: {
  request: JsonRequester;
  row: SupervisedCase;
  onDone: (message: string) => void;
}) {
  const styles = useUiStyles();
  const [form, setForm] = useState<Form | undefined>();
  const actions: Array<{ form: Form; label: StringKey }> = [];
  if (row.pending_flag) {
    actions.push({ form: "confirm", label: "supervisionConfirmFlag" }, { form: "reject", label: "supervisionRejectFlag" });
  } else if (DUPLICABLE.includes(row.state)) {
    actions.push({ form: "duplicate", label: "supervisionMarkDuplicate" });
  }
  if (CANCELLABLE.includes(row.state)) actions.push({ form: "cancel", label: "supervisionCancelCase" });
  if (TERMINAL.includes(row.state)) actions.push({ form: "reopen", label: "supervisionReopen" });
  if (actions.length === 0) return null;

  const active = actions.find((action) => action.form === form);
  return (
    <View style={{ gap: 8 }}>
      <View style={styles.row}>
        {actions.map((action) => (
          <Button
            key={action.form}
            kind="secondary"
            label={t(action.label)}
            onPress={() => setForm((current) => (current === action.form ? undefined : action.form))}
          />
        ))}
      </View>
      {active ? (
        <ActionForm
          key={active.form}
          request={request}
          row={row}
          form={active.form}
          label={t(active.label)}
          onDone={onDone}
          onClose={() => setForm(undefined)}
        />
      ) : null}
    </View>
  );
}

/** Inline form under the row (no modal: easier on a phone). */
function ActionForm({
  request,
  row,
  form,
  label,
  onDone,
  onClose,
}: {
  request: JsonRequester;
  row: SupervisedCase;
  form: Form;
  label: string;
  onDone: (message: string) => void;
  onClose: () => void;
}) {
  const styles = useUiStyles();
  const required = form === "cancel" || form === "reopen";
  const [reason, setReason] = useState("");
  const [keep, setKeep] = useState<string | undefined>();
  const [keepOptions, setKeepOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (form !== "duplicate") return undefined;
    let active = true;
    setBusy(true);
    void Promise.all([
      getPossibleDuplicates(request, row.death_id),
      listCases(request, { flagsOnly: false, state: "", visitNotesOnly: false, limit: 200 }),
    ])
      .then(([possible, page]) => {
        if (!active) return;
        setKeepOptions(keepChoices(row, possible, page.cases));
      })
      .catch((caught) => {
        if (active) setError(supervisionErrorText(caught));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [form, request, row]);

  const trimmed = reason.trim();
  const disabled = busy || (required && !trimmed) || (form === "duplicate" && !keep);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const reply = await send();
      onDone(
        reply.case.pending_flag
          ? t("supervisionDuplicateWaiting", { unique_id: row.unique_id })
          : t("supervisionSaved", { unique_id: row.unique_id }),
      );
    } catch (caught) {
      setError(supervisionErrorText(caught));
      setBusy(false);
    }
  }

  function send(): Promise<{ case: SupervisedCase }> {
    if (form === "confirm") return resolveFlag(request, row.death_id, true, trimmed);
    if (form === "reject") return resolveFlag(request, row.death_id, false, trimmed);
    if (form === "duplicate") return markDuplicate(request, row.death_id, keep ?? "", trimmed);
    if (form === "cancel") return cancelCase(request, row.death_id, trimmed);
    return reopenCase(request, row.death_id, trimmed);
  }

  return (
    <View style={styles.card}>
      <Text style={styles.muted}>{t(required ? "supervisionReasonRequired" : "supervisionReasonOptional")}</Text>
      <TextInput
        accessibilityLabel={t(required ? "supervisionReasonRequired" : "supervisionReasonOptional")}
        value={reason}
        onChangeText={setReason}
        maxLength={REASON_MAX}
        autoCorrect={false}
        style={styles.input}
      />
      <Text style={styles.error}>{t("supervisionReasonWarning")}</Text>
      {form === "duplicate" ? (
        <>
          <Text style={styles.headline}>{t("supervisionKeptCase")}</Text>
          {row.state === "submitted" ? <Text style={styles.muted}>{t("supervisionSubmittedDupNote")}</Text> : null}
          {keepOptions.length === 0 && !busy ? (
            <Text style={styles.muted}>{t("supervisionNoOtherCase")}</Text>
          ) : keepOptions.length > 0 ? (
            <WhoVaQuestionControls.SingleChoice
              question={choiceQuestion("supervision-keep", t("supervisionKeepPicker"), "singleChoice", keepOptions)}
              value={keep}
              data={{}}
              locale="en"
              issues={[]}
              choiceColumns={1}
              onAnswer={(value) => {
                if (typeof value === "string") setKeep(value);
              }}
            />
          ) : (
            <Text style={styles.muted}>{t("supervisionLoadingCases")}</Text>
          )}
        </>
      ) : null}
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      <View style={styles.row}>
        <Button label={label} onPress={() => void submit()} disabled={disabled} loading={busy && form !== "duplicate"} />
        <Button kind="secondary" label={t("supervisionClose")} onPress={onClose} />
      </View>
    </View>
  );
}

/** Possible duplicates first, then the project's other cases; a case is never offered as its own duplicate. */
function keepChoices(
  row: SupervisedCase,
  possible: PossibleDuplicate[],
  cases: SupervisedCase[],
): Array<{ value: string; label: string }> {
  const seen = new Set<string>([row.death_id]);
  const options: Array<{ value: string; label: string }> = [];
  const add = (candidate: PossibleDuplicate) => {
    if (seen.has(candidate.death_id) || NOT_KEPT.includes(candidate.state)) return;
    seen.add(candidate.death_id);
    options.push({
      value: candidate.death_id,
      label: [candidate.unique_id, candidate.deceased_name ?? t("emptyDash"), candidate.date_of_death ?? t("emptyDash")].join(" — "),
    });
  };
  possible.forEach(add);
  cases.filter((candidate) => candidate.project_id === row.project_id).forEach(add);
  return options;
}
