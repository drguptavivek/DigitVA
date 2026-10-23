/** The Training screens' shared parts: the participation hook, the confidentiality notice and each area's checklist. */
import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Text, View } from "react-native";

import type { TrainingArea } from "../api";
import { useAppState } from "../AppState";
import { t, type StringKey } from "../i18n";
import { getTrainingMe, type TrainingMe } from "../training";
import { spacing } from "../theme";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { openServerPage } from "./roleHome";

/** The caller's own participations (`GET /api/v1/training/me`); `undefined` while loading. */
export function useTrainingMe(): { me?: TrainingMe; error: string; setMe: (me: TrainingMe) => void } {
  const { bootstrap } = useAppState();
  const [me, setMe] = useState<TrainingMe>();
  const [error, setError] = useState("");
  const csrf = bootstrap?.csrf;
  const userId = bootstrap?.user.user_id;
  useEffect(() => {
    if (!csrf) return undefined;
    let active = true;
    setMe(undefined);
    setError("");
    getTrainingMe(csrf)
      .then((reply) => { if (active) setMe(reply); })
      .catch((caught) => { if (active) setError(browserErrorText(caught)); });
    return () => { active = false; };
    // Keyed on the account, not the csrf object: an access re-read keeps what is shown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);
  return { me, error, setMe };
}

/** The confidentiality notice: what the trainee may and may not do with the cases (the policy text). */
export function ConfidentialityNotice() {
  const styles = useUiStyles();
  return (
    <View style={styles.card} accessibilityRole="summary">
      <Text style={styles.headline}>{t("trainingConfidentialTitle")}</Text>
      <Text style={styles.text}>{t("trainingConfidentialCases")}</Text>
      <Text style={styles.text}>{t("trainingConfidentialMedia")}</Text>
    </View>
  );
}

const INTERVIEW_STEPS: Array<[string, StringKey]> = [
  ["death_reporter", "trainingInterviewDeathReporter"],
  ["interviewer", "trainingInterviewInterviewer"],
  ["interview_supervisor", "trainingInterviewSupervisor"],
];

/** One area's checklist: a line per training role held there, the coder slot, and the report links for review. */
export function TrainingChecklist({ area }: { area: TrainingArea }) {
  const { me, error } = useTrainingMe();
  return <TrainingChecklistView area={area} me={me} error={error} />;
}

/** The checklist of a caller that already holds `GET /training/me` (one fetch per screen). */
export function TrainingChecklistView({ area, me, error = "" }: { area: TrainingArea; me?: TrainingMe; error?: string }) {
  const styles = useUiStyles();
  const { bootstrap } = useAppState();
  const roles = new Set((me?.participations ?? []).map((part) => part.role));
  const slot = me?.participations.find((part) => part.role === "coder")?.coder_slot;
  const steps: StringKey[] = area === "interview"
    ? INTERVIEW_STEPS.filter(([role]) => roles.has(role)).map(([, key]) => key)
    : area === "coding" ? ["trainingCodingStep"] : ["trainingReviewStep"];
  return (
    <View style={styles.card} testID={`training-checklist-${area}`}>
      <Text style={styles.headline}>{t("trainingChecklist")}</Text>
      <Text style={styles.muted}>{t("trainingOnlyHere")}</Text>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {steps.map((key) => <Text key={key} style={styles.text}>{`• ${t(key)}`}</Text>)}
      {area === "coding" && slot ? <Text style={styles.muted}>{t("trainingCoderSlot", { slot })}</Text> : null}
      {area === "review" && bootstrap ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
          <Button kind="secondary" size="sm" label={t("trainingReadReport")} onPress={() => openServerPage(bootstrap.user.user_id, "/data-management/training")} />
        </View>
      ) : null}
    </View>
  );
}

/** A queue shell (QueueScreen's `Shell`) that puts an area's checklist above the queue. */
export function TrainingShell(area: TrainingArea): ComponentType<{ title: string; headerAction?: ReactNode; children: ReactNode }> {
  return function TrainingAreaShell({ title, headerAction, children }) {
    return (
      <WebShell title={title} headerAction={headerAction}>
        <TrainingChecklist area={area} />
        {children}
      </WebShell>
    );
  };
}

/** What a user without an active participation sees on a Training route. */
export function TrainingNone() {
  const styles = useUiStyles();
  return (
    <WebShell title={t("trainingTitle")}>
      <Text style={styles.text}>{t("trainingNone")}</Text>
    </WebShell>
  );
}
