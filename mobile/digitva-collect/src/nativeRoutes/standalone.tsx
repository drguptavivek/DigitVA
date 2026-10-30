/**
 * Path C home: the standalone account's local interviews and offline coding in three tabs (In progress, Pending
 * coding, Coded; digitva-31ci), each row titled with the deceased's name, age and sex, an age warning on records older than
 * STANDALONE_AGE_WARNING_DAYS, and a backup reminder every BACKUP_REMINDER_DAYS whose button opens Settings. Export,
 * backup, restore and Enrol this phone live in Settings (digitva-axim); Lock now stays here as the one-tap safety
 * action. Standalone work remains local after enrollment too. "New interview" waits for a complete offline profile
 * (standaloneProfileMissing, digitva-0vz7); existing records are never gated.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { retryHeldDraft, type Db } from "../drafts";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { t } from "../i18n";
import { getOfflineProfile, standaloneProfileMissing, type StandaloneProfileField } from "../offlineProfile";
import { standaloneProfileMissingText } from "../offlineProfileForm";
import { backupReminder, isOverAgeLimit } from "../standalone/age";
import { heldText } from "../standalone/adopt";
import { sweepExportLeftovers } from "../standalone/shareFile";
import { STANDALONE_AGE_WARNING_DAYS } from "../standalone/config";
import { STANDALONE_SITE_ID, standaloneProjectId } from "../standalone/project";
import { lastBackupAt, listStandaloneRecords, type StandaloneRecord } from "../standalone/records";
import { Button, errorText, Screen, useUiStyles } from "../ui";
import { sexLabel } from "../ui/CaseCard";

type RecordTab = "progress" | "pending" | "coded";
const TABS: Array<{ key: RecordTab; label: "standaloneDraft" | "standaloneTabPending" | "standaloneCoded"; empty: "standaloneNoInProgress" | "standaloneNoPending" | "standaloneNoCoded" }> = [
  { key: "progress", label: "standaloneDraft", empty: "standaloneNoInProgress" },
  { key: "pending", label: "standaloneTabPending", empty: "standaloneNoPending" },
  { key: "coded", label: "standaloneCoded", empty: "standaloneNoCoded" },
];
const tabOf = (record: StandaloneRecord): RecordTab => (!record.completed ? "progress" : record.coding_status === "coded" ? "coded" : "pending");

export default function StandaloneHome() {
  const styles = useUiStyles();
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { accounts, lockVersion, lockNow, uiLocale } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [records, setRecords] = useState<StandaloneRecord[]>();
  const [db, setDb] = useState<Db>();
  const [backupAt, setBackupAt] = useState<string | null>(null);
  const [error, setError] = useState("");
  // Undefined until the user picks one; then the default is Pending coding when it has records, else In progress.
  const [pickedTab, setPickedTab] = useState<RecordTab>();
  const [now, setNow] = useState(() => new Date());
  // Undefined until read; re-read on every return to this screen (from "Complete profile" or Settings).
  const [profileMissing, setProfileMissing] = useState<StandaloneProfileField[]>();
  useFocusEffect(useCallback(() => {
    let live = true;
    void getOfflineProfile().catch(() => null).then((profile) => {
      if (live) setProfileMissing(standaloneProfileMissing(profile));
    });
    return () => { live = false; };
  }, []));
  // Export and backup moved to Settings, but a crash leftover (it can hold PII) is still cleared on every home mount.
  useEffect(sweepExportLeftovers, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const load = useCallback(async () => {
    if (!account?.standalone || !isUnlocked(account.user_id)) return;
    try {
      const store = await openInterviewerDb(account.user_id);
      setDb(store);
      const loaded = await listStandaloneRecords(store, standaloneProjectId(account.user_id));
      setRecords(loaded);
      // The first load picks the tab; it then stays put, so coding the last pending record does not hide it.
      setPickedTab((picked) => picked ?? (loaded.some((r) => tabOf(r) === "pending") ? "pending" : "progress"));
      setBackupAt(await lastBackupAt(store));
    } catch (caught) {
      setError(errorText(caught));
    }
  }, [account]);
  // Also on every return to this screen: a backup made in Settings clears the reminder.
  useFocusEffect(useCallback(() => { void load(); }, [load, lockVersion]));

  if (!account?.standalone) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  if (!records || !db) return error ? <Text style={styles.error}>{error}</Text> : <ActivityIndicator style={{ flex: 1 }} />;

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
  const inTab = (key: RecordTab) => records.filter((r) => tabOf(r) === key);
  const tab = pickedTab ?? "progress";
  const tabInfo = TABS.find((entry) => entry.key === tab)!;
  const shown = inTab(tab);
  const openSettings = () => router.push({ pathname: "/settings", params: { userId: account.user_id } });

  return (
    <Screen title={t("standaloneHomeTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.muted}>{t("standaloneClockNotice")}</Text>
      <Text style={styles.text}>{now.toLocaleString(uiLocale, { dateStyle: "medium", timeStyle: "short" })}</Text>
      {reminder.due ? (
        <View style={[styles.card, { gap: 8 }]}>
          <Text style={styles.text}>{reminder.days === null ? t("standaloneBackupNever") : t("standaloneBackupReminder", { days: reminder.days })}</Text>
          <Button kind="secondary" label={t("standaloneBackupOpenSettings")} onPress={openSettings} />
        </View>
      ) : null}
      <Button
        label={t("standaloneNewInterview")}
        disabled={profileMissing?.length !== 0}
        onPress={() => router.push({ pathname: "/form", params: formParams(randomUUID()) })}
      />
      {profileMissing?.length ? (
        <View style={[styles.card, { gap: 8 }]}>
          <Text accessibilityRole="alert" style={styles.error}>{standaloneProfileMissingText(profileMissing)}</Text>
          <Button kind="secondary" label={t("standaloneProfileComplete")} onPress={() => router.push("/offline-profile")} />
        </View>
      ) : null}
      <View accessibilityRole="tablist" style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {TABS.map((entry) => (
          <Button
            key={entry.key}
            kind={entry.key === tab ? "primary" : "secondary"}
            selected={entry.key === tab}
            label={t("standaloneTabCount", { label: t(entry.label), count: inTab(entry.key).length })}
            onPress={() => setPickedTab(entry.key)}
          />
        ))}
      </View>
      {records.length === 0 ? <Text style={styles.muted}>{t("standaloneNoRecords")}</Text> : null}
      {records.length > 0 && shown.length === 0 ? <Text style={styles.muted}>{t(tabInfo.empty)}</Text> : null}
      {shown.map((record) => {
        const sex = sexLabel(record.sex);
        const title = [record.name || record.id, record.age_years === null ? "" : t("metaAgeYears", { value: record.age_years }), sex].filter(Boolean).join(" · ");
        return (
        <View key={record.id} style={[styles.card, { gap: 8 }]}>
          {/* The name line is the title; the UUID (still selectable) is the title itself when nothing is answered yet. */}
          <Text style={styles.text}>{title}</Text>
          {record.name ? <Text style={styles.muted} selectable>{record.id}</Text> : null}
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
            // Coded rows get Revise coding only; View and prefill come with digitva-9cll.24.
            <Button
              kind="secondary"
              label={t(tab === "coded" ? "standaloneReviseCoding" : "standaloneCodeIt")}
              onPress={() => router.push({ pathname: "/offline-coding", params: { userId: account.user_id, caseId: record.id } })}
            />
          ) : (
            <Button kind="secondary" label={t("standaloneDraft")} onPress={() => router.push({ pathname: "/form", params: formParams(record.id) })} />
          )}
        </View>
        );
      })}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("settings")} onPress={openSettings} />
      <Button kind="secondary" label={t("lockNow")} onPress={() => void lockNow()} />
    </Screen>
  );
}
