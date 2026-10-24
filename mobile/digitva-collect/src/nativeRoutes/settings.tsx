/**
 * Phone Settings, in sections: Account, Language, Security, Sync, Help & support, About. The enrolled server is
 * shown read-only and changed only by re-enrolling (src/reEnrolConfirm.ts). The questionnaire's own language is
 * chosen in the form's menu.
 */
import { useRouter } from "expo-router";
import { useEffect, useState, type ReactNode } from "react";
import { canUseBiometricAuthentication } from "expo-secure-store";
import { Linking, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { APP_VERSION } from "../appVersion";
import { isPlusVariant } from "../appVariant";
import { IDLE_LOCK_MS } from "../autoLock";
import { exportErrors } from "../errorExport";
import { t, UI_LOCALES } from "../i18n";
import { clock, useShell } from "../nativeShell/shellContext";
import { confirmReEnrol, reEnrolDevice } from "../reEnrolConfirm";
import { useToast } from "../toast";
import { checkForUpdate, type UpdateResult } from "../updateCheck";
import { Button, errorText, Screen, useUiStyles } from "../ui";
import { biometricEnabled, screenLockAvailable, screenLockEnabled, turnOffBiometric, turnOffScreenLock } from "../vault";

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
  const [screenLockUsers, setScreenLockUsers] = useState<Set<string>>(new Set());
  const [screenLockPossible, setScreenLockPossible] = useState(false);
  const [optionsVersion, setOptionsVersion] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [update, setUpdate] = useState<UpdateResult>();
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
    void Promise.all(accounts.map(async (account) => [account.user_id, await screenLockEnabled(account.user_id)] as const))
      .then((entries) => {
        if (active) setScreenLockUsers(new Set(entries.filter(([, enabled]) => enabled).map(([userId]) => userId)));
      })
      .catch(() => undefined);
    void screenLockAvailable().then((ok) => active && setScreenLockPossible(ok)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [accounts, optionsVersion]);
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
  /** Turn the screen-lock option on (needs the PIN, as fingerprint does) or either option off. */
  async function requestScreenLock(userId: string) {
    setBusy(true);
    setError("");
    try {
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      router.push({ pathname: "/unlock", params: { userId, enableScreenLock: "1" } });
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  async function turnOff(turnOffOption: (userId: string) => Promise<void>, userId: string) {
    setError("");
    try {
      await turnOffOption(userId);
      setOptionsVersion((n) => n + 1);
    } catch {
      setError(t("errGeneric"));
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
  async function checkNow() {
    setChecking(true);
    try {
      setUpdate(await checkForUpdate(device?.server));
    } finally {
      setChecking(false);
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
          <View key={`biometric-on-${item.user_id}`} style={{ gap: 8 }}>
            <Text style={styles.muted}>{`${t("biometricOn")}: ${item.name}`}</Text>
            <Button kind="secondary" label={`${t("biometricOff")}: ${item.name}`} onPress={() => void turnOff(turnOffBiometric, item.user_id)} />
          </View>
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
        {accounts.map((item) => screenLockUsers.has(item.user_id) ? (
          <View key={`screen-lock-on-${item.user_id}`} style={{ gap: 8 }}>
            <Text style={styles.muted}>{`${t("screenLockOn")}: ${item.name}`}</Text>
            <Button kind="secondary" label={`${t("screenLockOff")}: ${item.name}`} onPress={() => void turnOff(turnOffScreenLock, item.user_id)} />
          </View>
        ) : screenLockPossible ? (
          <Button
            key={`screen-lock-${item.user_id}`}
            kind="secondary"
            label={`${t("screenLockEnable")}: ${item.name}`}
            loading={busy}
            disabled={busy}
            onPress={() => void requestScreenLock(item.user_id)}
          />
        ) : null)}
      </Section>
      <Section title={t("tabSync")}>
        <Text style={styles.text}>{sync.lastAt ? t("syncChipSynced", { time: clock(sync.lastAt) }) : t("syncChipNever")}</Text>
        <Text style={styles.text}>{sync.work === undefined ? t("syncUnsentUnknown") : t("syncUnsentScoped", { count: sync.work.unsent })}</Text>
        <Button label={t("sendNow")} loading={sync.busy} disabled={sync.busy || !shell.userId} onPress={() => void shell.sendNow()} />
      </Section>
      {isPlusVariant() ? (
        <Section title="Collect Plus (experimental)">
          <Button kind="secondary" label="Coding queue" disabled={!shell.userId} onPress={() => router.push({ pathname: "/coding", params: { userId: shell.userId } })} />
          <Button kind="secondary" label="Review queue" disabled={!shell.userId} onPress={() => router.push({ pathname: "/reviewing", params: { userId: shell.userId } })} />
          <Button kind="secondary" label="Offline engine check" onPress={() => router.push("/engine-check")} />
          <Button kind="secondary" label="Update WHO files" onPress={() => router.push("/engine-check?update=1")} />
        </Section>
      ) : null}
      <Section title={t("settingsHelp")}>
        <Button kind="secondary" label={t("helpGuide")} onPress={() => shell.openSheet("help")} />
        <Button kind="secondary" label={t("faqOpenList")} onPress={() => shell.openSheet("help")} />
        <Button kind="secondary" label={t("exportErrors")} loading={exporting} disabled={exporting} onPress={() => void shareErrors()} />
      </Section>
      <Section title={t("settingsAbout")}>
        <Text style={styles.text}>{t("appVersionLabel", { version: APP_VERSION })}</Text>
        {update ? <Text style={styles.muted}>{update.status === "available" ? t("updateAvailable", { version: update.version }) : update.status === "current" ? t("updateCurrent") : t("updateUnknown")}</Text> : null}
        {update?.status === "available" ? <Button label={t("updateDownload")} onPress={() => void Linking.openURL(update.url).catch(() => undefined)} /> : null}
        <Button kind="secondary" label={t("updateCheck")} loading={checking} disabled={checking} onPress={() => void checkNow()} />
        <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
      </Section>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {device ? <Button kind="danger" label={t("reEnrol")} loading={busy} disabled={busy} onPress={requestReEnrol} /> : null}
    </Screen>
  );
}
