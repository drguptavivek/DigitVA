/**
 * Unlock one interviewer's store: the biometric prompt first when it is on,
 * the PIN always. Warns from the third wrong PIN; the fifth in a row erases
 * that interviewer's store and signs them out (src/auth.ts unlockInterviewer).
 * An interviewer with no PIN yet goes to PIN setup.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Alert, Text, TextInput } from "react-native";

import { useAppState } from "../src/AppState";
import { unlockInterviewer } from "../src/auth";
import { t } from "../src/i18n";
import { hasInterviewerStore, isUnlocked } from "../src/interviewerDb";
import { Button, Screen, styles } from "../src/ui";
import {
  biometricEnabled,
  failedAttempts,
  readBiometricPin,
  WARN_AFTER_FAILURES,
  WIPE_AFTER_FAILURES
} from "../src/vault";

const wrongPinText = (failures: number) =>
  failures >= WARN_AFTER_FAILURES
    ? t("pinWrongWarn", { left: WIPE_AFTER_FAILURES - failures })
    : t("pinWrong");

export default function Unlock() {
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { accounts, reload, unlocked } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [biometric, setBiometric] = useState(false);

  const toWorklist = useCallback(
    () => router.replace({ pathname: "/worklist", params: { userId: userId ?? "" } }),
    [router, userId]
  );

  const tryPin = useCallback(
    async (candidate: string) => {
      if (!userId) return;
      setBusy(true);
      setError("");
      try {
        const result = await unlockInterviewer(userId, candidate);
        if (result.ok) {
          unlocked();
          toWorklist();
          return;
        }
        setPin("");
        if (result.wipe) {
          Alert.alert(t("pinWiped"));
          await reload();
          router.replace("/");
          return;
        }
        setError(wrongPinText(result.failures));
      } catch {
        setError(t("errGeneric"));
      } finally {
        setBusy(false);
      }
    },
    [userId, unlocked, toWorklist, reload, router]
  );

  const tryBiometric = useCallback(async () => {
    if (!userId) return;
    try {
      const released = await readBiometricPin(userId, t("biometricPrompt"));
      if (released) await tryPin(released);
      else setBiometric(false);
    } catch {
      // Prompt cancelled: the PIN field stays.
    }
  }, [userId, tryPin]);

  useEffect(() => {
    if (!userId) return;
    if (isUnlocked(userId)) {
      toWorklist();
      return;
    }
    void (async () => {
      if (!(await hasInterviewerStore(userId))) {
        router.replace({ pathname: "/pin-setup", params: { userId } });
        return;
      }
      const failures = await failedAttempts(userId);
      if (failures > 0) setError(wrongPinText(failures));
      if (await biometricEnabled(userId)) {
        setBiometric(true);
        await tryBiometric();
      }
    })();
    // Once per screen: a failed biometric must not re-prompt on every render.
  }, [userId]);

  if (!account) return <Redirect href="/" />;
  return (
    <Screen title={t("unlockTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.muted}>{t("pin")}</Text>
      <TextInput
        style={styles.input}
        secureTextEntry
        keyboardType="number-pad"
        value={pin}
        onChangeText={setPin}
        onSubmitEditing={() => void tryPin(pin)}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button label={t("unlock")} disabled={busy || !pin} onPress={() => void tryPin(pin)} />
      {biometric ? (
        <Button kind="secondary" label={t("biometricEnable")} disabled={busy} onPress={() => void tryBiometric()} />
      ) : null}
      <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
    </Screen>
  );
}
