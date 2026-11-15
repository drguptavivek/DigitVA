/**
 * Training onboarding on the phone (docs/policy/training-session-types.md, "Training mode"): the notice the web
 * Training page shows, then Start, which records `onboarded_at` with the bearer `POST /api/v1/training/me/start`
 * (idempotent) and refreshes access so `training_pending` clears.
 */
import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { useAppState } from "../AppState";
import { authedRequest, refreshAccessSummary } from "../auth";
import { t } from "../i18n";
import { icons } from "../Icon";
import { TRAINING_ROUTES } from "../training";
import { Button, Card, errorText, ListRow, useUiStyles } from "../ui";

/** The post-PIN choice of the training project's coding queue (online only), with the "Training mode" label. */
export function TrainingCodingEntry({ userId }: { userId: string }) {
  const router = useRouter();
  return (
    <Card grouped testID="training-coding-entry">
      <ListRow
        icon={icons.code}
        label={t("trainingMode")}
        secondary={t("trainingCoding")}
        onPress={() => router.push({ pathname: TRAINING_ROUTES.coding, params: { userId } } as never)}
      />
    </Card>
  );
}

export function TrainingOnboarding({ userId }: { userId: string }) {
  const styles = useUiStyles();
  const { reload } = useAppState();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>();

  async function start() {
    setBusy(true);
    setMessage(undefined);
    try {
      await authedRequest<unknown>(userId, "/api/v1/training/me/start", { method: "POST" });
      await refreshAccessSummary(userId);
      await reload();
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card testID="training-onboarding" label={t("trainingMode")}>
      <Text style={styles.text}>{t("trainingPractice")}</Text>
      <Text style={styles.text}>{t("trainingConfidentialCases")}</Text>
      <Text style={styles.text}>{t("trainingConfidentialMedia")}</Text>
      {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
      <Button label={t("trainingStart")} loading={busy} disabled={busy} onPress={() => void start()} />
    </Card>
  );
}
