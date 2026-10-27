/**
 * Path C home: the standalone account's local interviews and offline coding, an age warning on records older than
 * STANDALONE_AGE_WARNING_DAYS, a backup reminder every BACKUP_REMINDER_DAYS, and the export, backup and restore
 * actions (src/standalone/DataActions.tsx). Once the phone is enrolled, the adoption offer and push
 * (src/standalone/AdoptionCard.tsx) are the only part that calls a server, and only after the user confirms.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { retryHeldDraft, type Db } from "../drafts";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { t } from "../i18n";
import { backupReminder, isOverAgeLimit } from "../standalone/age";
import { AdoptionCard } from "../standalone/AdoptionCard";
import { heldText } from "../standalone/adopt";
import { DataActions } from "../standalone/DataActions";
import { dataActionsAllowed } from "../standalone/export";
import { STANDALONE_AGE_WARNING_DAYS } from "../standalone/config";
import { STANDALONE_SITE_ID, standaloneProjectId } from "../standalone/project";
import { lastBackupAt, listStandaloneRecords, type StandaloneRecord } from "../standalone/records";
import { Button, errorText, Screen, useUiStyles } from "../ui";

export default function StandaloneHome() {
  const styles = useUiStyles();
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { accounts, lockVersion, lockNow } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [records, setRecords] = useState<StandaloneRecord[]>();
  const [db, setDb] = useState<Db>();
  const [backupAt, setBackupAt] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!account?.standalone || !isUnlocked(account.user_id)) return;
    try {
      const store = await openInterviewerDb(account.user_id);
      setDb(store);
      setRecords(await listStandaloneRecords(store, standaloneProjectId(account.user_id)));
      setBackupAt(await lastBackupAt(store));
    } catch (caught) {
      setError(errorText(caught));
    }
  }, [account]);
  useEffect(() => void load(), [load, lockVersion]);

  if (!account?.standalone) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  if (!records || !db) return error ? <Text style={styles.error}>{error}</Text> : <ActivityIndicator style={{ flex: 1 }} />;

  const now = new Date();
  const reminder = backupReminder(
    {
      lastBackupAt: backupAt,
      oldestRecordAt: records.reduce<string | null>((oldest, r) => (r.started_at && (!oldest || r.started_at < oldest) ? r.started_at : oldest), null),
      recordCount: records.length,
    },
    now,
  );
  const formParams = (draftId: string) => ({
    userId: account.user_id, draftId, projectId: standaloneProjectId(account.user_id), siteId: STANDALONE_SITE_ID,
  });

  return (
    <Screen title={t("standaloneHomeTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.muted}>{t("standaloneClockNotice")}</Text>
      {reminder.due ? (
        <View style={styles.card}>
          <Text style={styles.text}>{reminder.days === null ? t("standaloneBackupNever") : t("standaloneBackupReminder", { days: reminder.days })}</Text>
        </View>
      ) : null}
      <AdoptionCard db={db} refresh={records.length} onChanged={() => void load()} />
      {dataActionsAllowed(account) ? <DataActions db={db} userId={account.user_id} onChanged={() => void load()} /> : null}
      <Button label={t("standaloneNewInterview")} onPress={() => router.push({ pathname: "/form", params: formParams(randomUUID()) })} />
      {records.length === 0 ? <Text style={styles.muted}>{t("standaloneNoRecords")}</Text> : null}
      {records.map((record) => (
        <View key={record.id} style={[styles.card, { gap: 8 }]}>
          <Text style={styles.text} selectable>{record.id}</Text>
          <Text style={styles.muted}>
            {record.completed ? t("standaloneCompleted") : t("standaloneDraft")} · {(record.completed_at ?? record.updated_at).slice(0, 10)}
            {record.coding_status === "coded" ? ` · ${t("standaloneCoded")}` : ""}
          </Text>
          {record.upload_issue ? (
            <>
              <Text accessibilityRole="alert" style={styles.error}>{heldText(record.refusal_code)}</Text>
              <Button kind="secondary" label={t("standaloneRetry")} onPress={() => void retryHeldDraft(db, record.id).then(load)} />
            </>
          ) : null}
          {isOverAgeLimit(record.started_at ?? record.updated_at, now) ? (
            <Text accessibilityRole="alert" style={styles.error}>{t("standaloneAgeWarning", { days: STANDALONE_AGE_WARNING_DAYS })}</Text>
          ) : null}
          {record.completed ? (
            <Button kind="secondary" label={t("standaloneCodeIt")} onPress={() => router.push({ pathname: "/offline-coding", params: { userId: account.user_id, caseId: record.id } })} />
          ) : (
            <Button kind="secondary" label={t("standaloneDraft")} onPress={() => router.push({ pathname: "/form", params: formParams(record.id) })} />
          )}
        </View>
      ))}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("standaloneEnrol")} onPress={() => router.push("/enrol")} />
      <Button kind="secondary" label={t("settings")} onPress={() => router.push("/settings")} />
      <Button kind="secondary" label={t("lockNow")} onPress={() => void lockNow()} />
    </Screen>
  );
}
