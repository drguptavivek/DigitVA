/**
 * App language picker (the questionnaire's own language is chosen on the form),
 * biometric unlock, and the enrolled server: shown read-only, changed only by
 * re-enrolling (src/reEnrolConfirm.ts).
 */
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { canUseBiometricAuthentication } from "expo-secure-store";
import { Platform, Text } from "react-native";

import { useAppState } from "../src/AppState";
import { confirmReEnrol, reEnrolDevice } from "../src/reEnrolConfirm";
import { t, UI_LOCALES } from "../src/i18n";
import { Button, Screen, useUiStyles } from "../src/ui";
import { biometricEnabled } from "../src/vault";
import { SettingsScreen as WebSettings } from "../src/browserScreens";

export default function Settings() {
  return Platform.OS === "web" ? <WebSettings /> : <NativeSettings />;
}

function NativeSettings() {
  const router = useRouter();
  const { device, accounts, uiLocale, chooseUiLocale, lockNow, reload } = useAppState();
  const styles = useUiStyles();
  const [biometricUsers, setBiometricUsers] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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
  return (
    <Screen title={t("appLanguage")}>
      {UI_LOCALES.map((locale) => (
        <Button
          key={locale.code}
          kind={locale.code === uiLocale ? "primary" : "secondary"}
          label={locale.label}
          onPress={() => void chooseUiLocale(locale.code)}
        />
      ))}
      {biometricAvailable && accounts.map((account) => biometricUsers.has(account.user_id) ? null : (
        <Button
          key={`biometric-${account.user_id}`}
          kind="secondary"
          label={`${t("biometricEnable")}: ${account.name}`}
          loading={busy}
          disabled={busy}
          onPress={() => void requestBiometric(account.user_id)}
        />
      ))}
      {device ? (
        <>
          <Text style={styles.muted}>{t("enrolledServer")}</Text>
          <Text style={styles.text} selectable>{device.server}</Text>
          <Button kind="danger" label={t("reEnrol")} loading={busy} disabled={busy} onPress={requestReEnrol} />
        </>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
    </Screen>
  );
}
