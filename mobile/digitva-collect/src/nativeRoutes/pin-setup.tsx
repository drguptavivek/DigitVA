/**
 * First PIN for an interviewer on this device (after their first sign-in):
 * creates their encrypted store (six PIN boxes, entered and confirmed), then
 * offers fingerprint and phone screen lock unlock (src/UnlockOffer.tsx).
 * With `reset=1` (after "Forgot PIN?" and a password sign-in) it sets a new
 * PIN on the existing store instead, keeping every interview; the permission
 * is checked in src/interviewerDb.ts resetInterviewerPin, not by this param.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { createInterviewerDb, resetInterviewerPin } from "../interviewerDb";
import { homeRoute } from "../standalone/home";
import { PinBoxes } from "../PinBoxes";
import { Button, Notice, Screen, useUiStyles } from "../ui";
import { pendingUnlockOffer, UnlockOffer } from "../UnlockOffer";
import { clearPinResetGrant } from "../pinResetGrant";
import { pinProblem, recordPinLength } from "../vault";

export default function PinSetup() {
  const styles = useUiStyles();
  const router = useRouter();
  const { userId, refresh, reset: resetParam } = useLocalSearchParams<{ userId: string; refresh?: string; reset?: string }>();
  const reset = resetParam === "1";
  // Leaving the reset flow without finishing it drops the grant.
  useEffect(() => (reset && userId ? () => clearPinResetGrant(userId) : undefined), [reset, userId]);
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
      if (reset) {
        await resetInterviewerPin(account.user_id, pin);
      } else {
        await createInterviewerDb(account.user_id, pin);
        await recordPinLength(account.user_id, pin.length).catch(() => undefined);
      }
      unlocked();
      const pending = await pendingUnlockOffer(account.user_id).catch(() => null);
      if (pending) setOffer(pending);
      else toWorklist();
    } catch (caught) {
      setError(t(caught instanceof Error && caught.message === "pin_reset_not_allowed" ? "pinResetSignInAgain" : "errGeneric"));
    } finally {
      setBusy(false);
    }
  }

  if (offer) {
    return (
      <Screen title={t(reset ? "pinResetTitle" : "pinSetupTitle")}>
        <UnlockOffer userId={account.user_id} pin={pin} options={offer} onDone={toWorklist} />
      </Screen>
    );
  }

  return (
    <Screen title={t(reset ? "pinResetTitle" : "pinSetupTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.muted}>{t("pin")}</Text>
      <PinBoxes value={pin} onChange={(value) => { setPin(value); setError(""); }} label={t("pin")} onFilled={() => setConfirmFocus((n) => n + 1)} />
      <Text style={styles.muted}>{t("pinConfirm")}</Text>
      <PinBoxes value={confirm} onChange={(value) => { setConfirm(value); setError(""); }} label={t("pinConfirm")} autoFocus={false} focusSignal={confirmFocus} />
      <Notice tone="info">{t(reset ? "pinResetHint" : account.standalone ? "pinSetupHintStandalone" : "pinSetupHint")}</Notice>
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Button label={t("pinSave")} disabled={busy || !pin || !confirm} onPress={() => void submit()} />
    </Screen>
  );
}
