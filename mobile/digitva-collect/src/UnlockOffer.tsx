/**
 * The unlock-options offer (docs/policy/mobile-sign-in.md section 9): after the first PIN setup, and once more on a
 * later PIN unlock, offer fingerprint and phone screen lock, whichever the phone supports. Skippable. `pin` is the
 * PIN just typed or set; nothing here stores it except the chosen option's vault entry.
 */
import { canUseBiometricAuthentication } from "expo-secure-store";
import { useEffect, useState } from "react";
import { Text } from "react-native";

import { t } from "./i18n";
import { Button, useUiStyles } from "./ui";
import {
  biometricEnabled,
  enableBiometric,
  enableScreenLock,
  noteUnlockOffer,
  screenLockAvailable,
  screenLockEnabled,
  unlockOfferCount,
  UNLOCK_OFFER_MAX
} from "./vault";

/** Which options the offer would show now: none when already offered enough, or one is on, or the phone has neither. */
export async function pendingUnlockOffer(userId: string): Promise<{ biometric: boolean; screenLock: boolean } | null> {
  if ((await unlockOfferCount(userId)) >= UNLOCK_OFFER_MAX) return null;
  if ((await biometricEnabled(userId)) || (await screenLockEnabled(userId))) return null;
  const options = { biometric: canUseBiometricAuthentication(), screenLock: await screenLockAvailable() };
  return options.biometric || options.screenLock ? options : null;
}

export function UnlockOffer({
  userId,
  pin,
  options,
  onDone
}: {
  userId: string;
  pin: string;
  options: { biometric: boolean; screenLock: boolean };
  onDone: () => void;
}) {
  const styles = useUiStyles();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void noteUnlockOffer(userId).catch(() => undefined);
  }, [userId]);

  async function turnOn(enable: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await enable();
      onDone();
    } catch {
      // Cancelled or refused: stay on the offer; Skip or the PIN alone still works.
      setError(t("unlockOptionFailed"));
      setBusy(false);
    }
  }

  return (
    <>
      <Text style={styles.text}>{t("unlockOptionsOffer")}</Text>
      {options.biometric ? (
        <Button label={t("biometricEnable")} disabled={busy} onPress={() => void turnOn(() => enableBiometric(userId, pin, t("biometricPrompt")))} />
      ) : null}
      {options.screenLock ? (
        <Button label={t("screenLockEnable")} disabled={busy} onPress={() => void turnOn(() => enableScreenLock(userId, pin, t("screenLockPrompt")))} />
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("biometricSkip")} disabled={busy} onPress={onDone} />
    </>
  );
}
