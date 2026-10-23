/**
 * Phone Settings, in sections: Account, Language, Security, Sync, Help & support, About. The enrolled server is
 * shown read-only and changed only by re-enrolling (src/reEnrolConfirm.ts). The questionnaire's own language is
 * chosen in the form's menu.
 */
import { useRouter } from "expo-router";
import { useEffect, useState, type ReactNode } from "react";
import { canUseBiometricAuthentication } from "expo-secure-store";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { APP_VERSION } from "../appVersion";
import { IDLE_LOCK_MS } from "../autoLock";
import { exportErrors } from "../errorExport";
import { t, UI_LOCALES } from "../i18n";
import { clock, useShell } from "../nativeShell/shellContext";
import { confirmReEnrol, reEnrolDevice } from "../reEnrolConfirm";
import { useToast } from "../toast";
import { Button, errorText, Screen, useUiStyles } from "../ui";
import { biometricEnabled } from "../vault";

function Section({ title, children }: { title: string; children: ReactNode }) {
  const styles = useUiStyles();
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>{title}</Text>
      {children}
    </View>
  );
}

export default function NativeSettings() {
  const router = useRouter();
  const toast = useToast();
  const shell = useShell();
  const { device, accounts, uiLocale, chooseUiLocale, lockNow, reload } = useAppState();
  const styles = useUiStyles();
  const [biometricUsers, setBiometricUsers] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    let active = true;
    void Promise.all(accounts.map(async (account) => [account.user_id, await biometricEnabled(account.user_id)] as const))
      .then((entries) => {
        if (active) setBiometricUsers(new Set(entries.filter(([, enabled]) => enabled).map(([userId]) => userId)));
      })
      .catch(() => {
        if (!active) return;
        setBiometricUsers(new Set());
        setError(t("errGeneric"));
      });
    return () => {
      active = false;
    };
  }, [accounts]);
  const biometricAvailable = canUseBiometricAuthentication();
  const account = accounts.find((item) => item.user_id === shell.userId);
  async function requestBiometric(userId: string) {
    setBusy(true);
    setError("");
    try {
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      router.push({ pathname: "/unlock", params: { userId, enableBiometric: "1" } });
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  async function reEnrol() {
    setBusy(true);
    setError("");
    try {
      await reEnrolDevice(accounts);
      await reload();
      // Settings sits above Home, so Home's redirect to /enrol would not run.
      router.replace("/enrol");
    } catch (caught) {
      setError(caught instanceof Error && caught.message === "unsent_work" ? t("reEnrolBlocked") : t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  function requestReEnrol() {
    setError("");
    confirmReEnrol(accounts, () => void reEnrol()).catch(() => setError(t("errGeneric")));
  }
  async function shareErrors() {
    setExporting(true);
    try {
      const count = await exportErrors();
      toast.show(count ? { kind: "success", text: t("exportErrorsShared", { count }) } : { kind: "info", text: t("exportErrorsNone") });
    } catch (caught) {
      toast.show({ kind: "error", text: errorText(caught) });
    } finally {
      setExporting(false);
    }
  }
  const { sync } = shell;
  return (
    <Screen title={t("settings")}>
      <Section title={t("settingsAccount")}>
        {account ? <Text style={styles.text}>{account.name}</Text> : accounts.map((item) => <Text key={item.user_id} style={styles.text}>{item.name}</Text>)}
        {device ? (
          <>
            <Text style={styles.muted}>{t("enrolledServer")}</Text>
            <Text style={styles.text} selectable>{device.server}</Text>
            <Text style={styles.muted}>{t("deviceLabel")}</Text>
            <Text style={styles.text} selectable>{device.device_id}</Text>
          </>
        ) : null}
      </Section>
      <Section title={t("settingsLanguage")}>
        <Text style={styles.muted}>{t("appLanguage")}</Text>
        {UI_LOCALES.map((locale) => (
          <Button
            key={locale.code}
            kind={locale.code === uiLocale ? "primary" : "secondary"}
            label={locale.label}
            onPress={() => void chooseUiLocale(locale.code)}
          />
        ))}
        <Text style={styles.muted}>{t("questionnaireLanguageNote")}</Text>
      </Section>
      <Section title={t("settingsSecurity")}>
        <Text style={styles.text}>{t("autoLockInfo", { minutes: Math.round(IDLE_LOCK_MS / 60_000) })}</Text>
        {biometricAvailable && accounts.map((item) => biometricUsers.has(item.user_id) ? (
          <Text key={`biometric-on-${item.user_id}`} style={styles.muted}>{`${t("biometricOn")}: ${item.name}`}</Text>
        ) : (
          <Button
            key={`biometric-${item.user_id}`}
            kind="secondary"
            label={`${t("biometricEnable")}: ${item.name}`}
            loading={busy}
            disabled={busy}
            onPress={() => void requestBiometric(item.user_id)}
          />
        ))}
      </Section>
      <Section title={t("tabSync")}>
        <Text style={styles.text}>{sync.lastAt ? t("syncChipSynced", { time: clock(sync.lastAt) }) : t("syncChipNever")}</Text>
        <Text style={styles.text}>{sync.unsent === undefined ? t("syncUnsentUnknown") : t("syncUnsentCount", { count: sync.unsent })}</Text>
        <Button label={t("sendNow")} loading={sync.busy} disabled={sync.busy || !shell.userId} onPress={() => void shell.sendNow()} />
      </Section>
      <Section title={t("settingsHelp")}>
        <Button kind="secondary" label={t("helpGuide")} onPress={() => shell.openSheet("help")} />
        <Button kind="secondary" label={t("exportErrors")} loading={exporting} disabled={exporting} onPress={() => void shareErrors()} />
      </Section>
      <Section title={t("settingsAbout")}>
        <Text style={styles.text}>{t("appVersionLabel", { version: APP_VERSION })}</Text>
        <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
      </Section>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {device ? <Button kind="danger" label={t("reEnrol")} loading={busy} disabled={busy} onPress={requestReEnrol} /> : null}
    </Screen>
  );
}
