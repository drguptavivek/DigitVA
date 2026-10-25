/** `/training` (overview with Start) and `/training/interview` (the Interview checklist and work list). */
import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { startTraining, TRAINING_ROUTES } from "../training";
import { spacing } from "../theme";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { DeathsListPanel } from "./DeathsList";
import { SupervisionPanel } from "./SupervisionPanel";
import { TrainingScope } from "../AppState";
import { DeathRegistrationScreen } from "./LazyInterviewScreen";
import { ConfidentialityNotice, TrainingChecklistView, TrainingNone, useTrainingMe } from "./TrainingChecklist";

const AREA_LABELS = { interview: "trainingInterview", coding: "trainingCoding", review: "trainingReview" } as const;

/** The overview: confidentiality notice, the session, the Start button, and a button per training area. */
export function TrainingOverviewScreen() {
  const router = useRouter();
  const styles = useUiStyles();
  const { bootstrap, reload } = useAppState();
  const { me, error, setMe } = useTrainingMe();
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState("");
  const sessions = Array.from(new Map((me?.participations ?? []).map((part) => [part.session_code, part.session_name])));
  const slot = me?.participations.find((part) => part.role === "coder")?.coder_slot;

  async function start() {
    if (!bootstrap) return;
    setBusy(true);
    setStartError("");
    try {
      setMe(await startTraining(bootstrap.csrf));
      await reload();
    } catch (caught) {
      setStartError(browserErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <WebShell title={t("trainingTitle")}>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!me && !error ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {me && me.participations.length === 0 ? <Text style={styles.text}>{t("trainingNone")}</Text> : null}
      {me && me.participations.length > 0 ? (
        <>
          <ConfidentialityNotice />
          <View style={styles.card}>
            {sessions.map(([code, name]) => <Text key={code} style={styles.headline}>{t("trainingSession", { code, name })}</Text>)}
            {slot ? <Text style={styles.muted}>{t("trainingCoderSlot", { slot })}</Text> : null}
            {me.pending ? (
              <View style={{ flexDirection: "row", gap: spacing.xs }}>
                <Button label={t("trainingStart")} loading={busy} onPress={() => void start()} />
              </View>
            ) : <Text style={styles.muted}>{t("trainingStarted")}</Text>}
            {startError ? <Text style={styles.error} accessibilityRole="alert">{startError}</Text> : null}
          </View>
          <View style={styles.card}>
            <Text style={styles.headline}>{t("trainingAreasTitle")}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
              {me.areas.map((area) => (
                <Button key={area} kind="secondary" label={`${t("trainingOpen")}: ${t(AREA_LABELS[area])}`}
                  onPress={() => router.push(TRAINING_ROUTES[area] as never)} />
              ))}
            </View>
          </View>
        </>
      ) : null}
    </WebShell>
  );
}

/** The Interview area: its checklist, then the training project's deaths (and, for a supervisor, the supervised cases). */
export function TrainingInterviewScreen() {
  return <TrainingScope fallback={<TrainingNone />}><TrainingInterview /></TrainingScope>;
}

/** Report a death in the training project: the ordinary registration screen in the training scope. */
export function TrainingRegisterScreen() {
  return <TrainingScope fallback={<TrainingNone />}><DeathRegistrationScreen /></TrainingScope>;
}

function TrainingInterview() {
  const router = useRouter();
  const styles = useUiStyles();
  const { bootstrap } = useAppState();
  const { me, error } = useTrainingMe();
  const roles = new Set((me?.participations ?? []).map((part) => part.role));
  const registers = roles.has("death_reporter") || roles.has("interviewer");
  const supervises = roles.has("interview_supervisor");
  return (
    <WebShell title={t("trainingInterview")}>
      <TrainingChecklistView area="interview" me={me} error={error} />
      {bootstrap && me ? (
        <>
          {supervises ? <SupervisionPanel /> : null}
          <Text style={styles.headline}>{t("trainingWorkList")}</Text>
          <DeathsListPanel
            headerAction={registers ? (
              <Button size="sm" label={t("trainingReportDeath")} onPress={() => router.push("/training/register" as never)} />
            ) : undefined}
          />
        </>
      ) : null}
    </WebShell>
  );
}
