import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { WhoVaQuestionControls } from "../whoControls";

import {
  chooseInterview,
  CHOOSE_INTERVIEW_REASONS,
  getCaseDetail,
  getPossibleDuplicates,
  REVISION_REASONS,
  reopenForRevision,
  type PossibleDuplicate,
  type SupervisedCase,
  type SupervisedCaseDetail,
} from "../supervision/api";
import { t, type StringKey } from "../i18n";
import type { JsonRequester } from "../workspace/api";
import { choiceQuestion } from "../workspace/QualityPanels";
import { Button, stateLabel, useUiStyles } from "../ui";
import { AddIdentifierAction, IdentifierFacts } from "./CaseIdentifiers";
import { SupervisionActions, supervisionErrorText } from "./SupervisionActions";

/** Reason labels, keyed by the API's reason codes. */
const REASON_LABELS: Record<string, StringKey> = {
  better_quality: "supervisionReason_better_quality",
  more_complete: "supervisionReason_more_complete",
  original_incorrect: "supervisionReason_original_incorrect",
  switch_back: "supervisionReason_switch_back",
  cod_review_requested: "supervisionReason_cod_review_requested",
  new_information: "supervisionReason_new_information",
  data_correction: "supervisionReason_data_correction",
};

function whenText(iso: string | null | undefined): string {
  const parsed = iso ? new Date(iso) : null;
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toLocaleString() : t("emptyDash");
}

/** The list row's fields (parity with the Flask supervision page). */
export function CaseSummary({ row, variant = "card" }: { row: SupervisedCase; variant?: "card" | "detail" }) {
  const styles = useUiStyles();
  const name = row.details_pending ? t("supervisionDetailsPending") : row.deceased_name ?? t("emptyDash");
  const facts = [
    row.unique_id,
    row.deceased_sex ?? t("emptyDash"),
    row.age_years != null ? t("supervisionAge", { years: row.age_years }) : t("emptyDash"),
    t("supervisionDied", { date: row.date_of_death ?? t("emptyDash") }),
    t("supervisionReported", { date: whenText(row.created_at) }),
    row.unit_name ?? t("supervisionNoUnit"),
  ].join(" · ");
  return (
    <View style={{ gap: 4 }}>
      <View style={styles.row}>
        <Text style={styles.headline}>{name}</Text>
        <Text style={styles.muted}>{stateLabel(row.state)}</Text>
      </View>
      <Text style={styles.muted}>{facts}</Text>
      <IdentifierFacts identifiers={row.identifiers} variant={variant} />
      <Text style={styles.muted}>
        {t("supervisionByline", {
          registered: row.registered_by_name ?? t("emptyDash"),
          started: row.started_by_name ?? t("emptyDash"),
          updated: whenText(row.updated_at),
        })}
      </Text>
      {row.pending_flag ? (
        <Text style={styles.error}>
          {t(row.pending_flag === "duplicate" ? "supervisionPendingDuplicate" : "supervisionPendingCancel")}
        </Text>
      ) : null}
    </View>
  );
}

/** A case's detail: visit note, possible duplicates, and the submitted-case choices (choose interview, reopen for revision). */
export function SupervisionCaseDetail({
  request,
  deathId,
  onBack,
  onDone,
}: {
  request: JsonRequester;
  deathId: string;
  onBack: () => void;
  onDone: (message: string) => void;
}) {
  const styles = useUiStyles();
  const [detail, setDetail] = useState<SupervisedCaseDetail | undefined>();
  const [duplicates, setDuplicates] = useState<PossibleDuplicate[]>([]);
  const [chooseReason, setChooseReason] = useState<string | undefined>();
  const [revisionReason, setRevisionReason] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    void Promise.all([getCaseDetail(request, deathId), getPossibleDuplicates(request, deathId)])
      .then(([loaded, possible]) => {
        if (!active) return;
        setDetail(loaded);
        setDuplicates(possible);
      })
      .catch((caught) => {
        if (active) setError(supervisionErrorText(caught));
      });
    return () => {
      active = false;
    };
  }, [request, deathId, reloads]);

  if (!detail) {
    return (
      <View style={styles.card}>
        <Button kind="secondary" label={t("supervisionBack")} onPress={onBack} />
        {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : <Text style={styles.muted}>{t("loading")}</Text>}
      </View>
    );
  }

  const { case: row, candidates, visit_note: note } = detail;
  const submitted = row.state === "submitted";

  async function choose(draftId: string) {
    setBusy(true);
    setError("");
    try {
      await chooseInterview(request, row.death_id, draftId, chooseReason ?? "");
      onDone(t("supervisionSaved", { unique_id: row.unique_id }));
    } catch (caught) {
      setError(supervisionErrorText(caught));
      setBusy(false);
    }
  }

  async function revise() {
    setBusy(true);
    setError("");
    try {
      await reopenForRevision(request, row.va_sid ?? "", revisionReason ?? "");
      onDone(t("supervisionRevisionDone"));
    } catch (caught) {
      setError(supervisionErrorText(caught));
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: 12 }}>
      <Button kind="secondary" label={t("supervisionBack")} onPress={onBack} />
      <Text style={styles.headline}>{t("supervisionCaseDetail")}</Text>
      <View style={styles.card}>
        <CaseSummary row={row} variant="detail" />
        <SupervisionActions request={request} row={row} onDone={onDone} />
        <AddIdentifierAction row={row} onChanged={() => setReloads((count) => count + 1)} />
      </View>

      <View style={styles.card}>
        <Text style={styles.headline}>{t("supervisionVisitNote")}</Text>
        {!note ? <Text style={styles.muted}>{t("supervisionNoVisitNote")}</Text> : null}
        {note?.date ? <Text style={styles.text}>{t("supervisionVisitDate", { date: note.date })}</Text> : null}
        {note?.redacted ? <Text style={styles.muted}>{t("supervisionVisitWithheld")}</Text> : null}
        {note && !note.redacted && note.address ? <Text style={styles.text}>{t("supervisionVisitAddress", { address: note.address })}</Text> : null}
        {note && !note.redacted && note.remarks ? <Text style={styles.text}>{t("supervisionVisitRemarks", { remarks: note.remarks })}</Text> : null}
      </View>

      <View style={styles.card}>
        <Text style={styles.headline}>{t("supervisionPossibleDuplicates")}</Text>
        {duplicates.length === 0 ? <Text style={styles.muted}>{t("supervisionNoPossibleDuplicates")}</Text> : null}
        {duplicates.map((match) => (
          <Text key={match.death_id} style={styles.text}>
            {[match.unique_id, match.deceased_name ?? t("emptyDash"), match.date_of_death ?? t("emptyDash")].join(" · ")}
          </Text>
        ))}
      </View>

      {submitted ? (
        <View style={styles.card}>
          <Text style={styles.headline}>{t("supervisionCandidates")}</Text>
          {candidates.length === 0 ? <Text style={styles.muted}>{t("supervisionNoCandidates")}</Text> : null}
          {candidates.length > 0 ? (
            <WhoVaQuestionControls.SingleChoice
              question={choiceQuestion("supervision-choose-reason", t("supervisionReasonChoice"), "singleChoice", reasonOptions(CHOOSE_INTERVIEW_REASONS))}
              value={chooseReason}
              data={{}}
              locale="en"
              issues={[]}
              choiceColumns={1}
              onAnswer={(value) => {
                if (typeof value === "string") setChooseReason(value);
              }}
            />
          ) : null}
          {candidates.map((candidate) => (
            <View key={candidate.draft_id} style={{ gap: 4 }}>
              <Text style={styles.text}>
                {t("supervisionCandidateLine", { name: candidate.interviewer_name ?? t("emptyDash"), completed: whenText(candidate.completed_at) })}
              </Text>
              <Button
                label={t("supervisionChooseInterview")}
                onPress={() => void choose(candidate.draft_id)}
                disabled={busy || !chooseReason}
              />
            </View>
          ))}
        </View>
      ) : null}

      {submitted && row.va_sid && row.source !== "odk" ? (
        <View style={styles.card}>
          <WhoVaQuestionControls.SingleChoice
            question={choiceQuestion("supervision-revision-reason", t("supervisionReasonRevision"), "singleChoice", reasonOptions(REVISION_REASONS))}
            value={revisionReason}
            data={{}}
            locale="en"
            issues={[]}
            choiceColumns={1}
            onAnswer={(value) => {
              if (typeof value === "string") setRevisionReason(value);
            }}
          />
          <Button
            kind="secondary"
            label={t("supervisionReopenRevision")}
            onPress={() => void revise()}
            disabled={busy || !revisionReason}
          />
        </View>
      ) : null}

      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
    </View>
  );
}

function reasonOptions(codes: readonly string[]): Array<{ value: string; label: string }> {
  return codes.map((code) => ({ value: code, label: t(REASON_LABELS[code]) }));
}
