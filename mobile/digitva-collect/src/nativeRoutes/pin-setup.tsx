/**
 * First PIN for an interviewer on this device (after their first sign-in):
 * creates their encrypted store (six PIN boxes, entered and confirmed), then
 * offers fingerprint and phone screen lock unlock (src/UnlockOffer.tsx).
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { createInterviewerDb } from "../interviewerDb";
import { homeRoute } from "../standalone/home";
import { PinBoxes } from "../PinBoxes";
import { Button, Notice, Screen, useUiStyles } from "../ui";
import { pendingUnlockOffer, UnlockOffer } from "../UnlockOffer";
import { pinProblem, recordPinLength } from "../vault";

export default function PinSetup() {
  const styles = useUiStyles();
  const router = useRouter();
  const { userId, refresh } = useLocalSearchParams<{ userId: string; refresh?: string }>();
  const { accounts, unlocked } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [pin, setPin] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [offer, setOffer] = useState<{ biometric: boolean; screenLock: boolean }>();
  // Bumped when the PIN row fills: only then does the Confirm row take focus, so each row keeps its own digits.
  const [confirmFocus, setConfirmFocus] = useState(0);

  if (!account) return <Redirect href="/" />;
  const toWorklist = () => router.replace({ pathname: homeRoute(account), params: { userId: account.user_id, ...(refresh === "1" ? { refresh: "1" } : {}) } });

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
      await recordPinLength(account.user_id, pin.length).catch(() => undefined);
      unlocked();
      const pending = await pendingUnlockOffer(account.user_id).catch(() => null);
      if (pending) setOffer(pending);
      else toWorklist();
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }

  if (offer) {
    return (
      <Screen title={t("pinSetupTitle")}>
        <UnlockOffer userId={account.user_id} pin={pin} options={offer} onDone={toWorklist} />
      </Screen>
    );
  }

  return (
    <Screen title={t("pinSetupTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.muted}>{t("pin")}</Text>
      <PinBoxes value={pin} onChange={(value) => { setPin(value); setError(""); }} label={t("pin")} onFilled={() => setConfirmFocus((n) => n + 1)} />
      <Text style={styles.muted}>{t("pinConfirm")}</Text>
      <PinBoxes value={confirm} onChange={(value) => { setConfirm(value); setError(""); }} label={t("pinConfirm")} autoFocus={false} focusSignal={confirmFocus} />
      <Notice tone="info">{t(account.standalone ? "pinSetupHintStandalone" : "pinSetupHint")}</Notice>
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Button label={t("pinSave")} disabled={busy || !pin || !confirm} onPress={() => void submit()} />
    </Screen>
  );
}
