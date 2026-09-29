/**
 * First PIN for an interviewer on this device (after their first sign-in):
 * creates their encrypted store, then offers biometric unlock when the
 * device has a strong biometric enrolled.
 */
import { canUseBiometricAuthentication } from "expo-secure-store";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Text, TextInput } from "react-native";

import { useAppState } from "../src/AppState";
import { t } from "../src/i18n";
import { createInterviewerDb } from "../src/interviewerDb";
import { Button, Screen, styles } from "../src/ui";
import { enableBiometric, pinProblem } from "../src/vault";

export default function PinSetup() {
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { accounts, unlocked } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [pin, setPin] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [offerBiometric, setOfferBiometric] = useState(false);

  if (!account) return <Redirect href="/" />;
  const toWorklist = () => router.replace({ pathname: "/worklist", params: { userId: account.user_id } });

  async function submit() {
    if (!account) return;
    const problem = pinProblem(pin, confirm);
    if (problem) {
      setError(t(problem));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createInterviewerDb(account.user_id, pin);
      unlocked();
      if (canUseBiometricAuthentication()) setOfferBiometric(true);
      else toWorklist();
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }

  async function turnOnBiometric() {
    if (!account) return;
    try {
      await enableBiometric(account.user_id, pin, t("biometricPrompt"));
    } catch {
      // Cancelled or unavailable: the PIN alone still unlocks.
    }
    toWorklist();
  }

  if (offerBiometric) {
    return (
      <Screen title={t("pinSetupTitle")}>
        <Text style={styles.text}>{t("biometricOffer")}</Text>
        <Button label={t("biometricEnable")} onPress={() => void turnOnBiometric()} />
        <Button kind="secondary" label={t("biometricSkip")} onPress={toWorklist} />
      </Screen>
    );
  }

  return (
    <Screen title={t("pinSetupTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.text}>{t("pinSetupHint")}</Text>
      <Text style={styles.muted}>{t("pin")}</Text>
      <TextInput style={styles.input} secureTextEntry keyboardType="number-pad" value={pin} onChangeText={setPin} />
      <Text style={styles.muted}>{t("pinConfirm")}</Text>
      <TextInput
        style={styles.input}
        secureTextEntry
        keyboardType="number-pad"
        value={confirm}
        onChangeText={setConfirm}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button label={t("pinSave")} disabled={busy || !pin || !confirm} onPress={() => void submit()} />
    </Screen>
  );
}
