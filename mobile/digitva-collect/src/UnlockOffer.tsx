/**
 * The unlock-options offer (docs/policy/mobile-sign-in.md section 9): after the first PIN setup, and once more on a
 * later PIN unlock, offer the biometric (fingerprint, Face ID or Touch ID) and phone screen lock, whichever the phone supports. Skippable. `pin` is the
 * PIN just typed or set; nothing here stores it except the chosen option's vault entry.
 */
import { canUseBiometricAuthentication } from "expo-secure-store";
import { useEffect, useState } from "react";
import { Text } from "react-native";

import { t, type StringKey } from "./i18n";
import { Button, useUiStyles } from "./ui";
import {
  biometricKind,
  type BiometricKind,
  biometricEnabled,
  enableBiometric,
  enableScreenLock,
  noteUnlockOffer,
  screenLockAvailable,
  screenLockEnabled,
  unlockOfferCount,
  UNLOCK_OFFER_MAX
} from "./vault";

type BiometricText = "unlockOptionsOffer" | "biometricEnable" | "biometricOn" | "biometricOff";

/** `key` as this phone's biometric is called: the plain key says fingerprint; `_face` / `_touch` say Face ID / Touch ID. */
export function biometricText(key: BiometricText, kind: BiometricKind): string {
  return t(kind === "fingerprint" ? key : (`${key}_${kind}` satisfies StringKey));
}

/** This phone's biometric kind for labels; fingerprint until known. */
export function useBiometricKind(): BiometricKind {
  const [kind, setKind] = useState<BiometricKind>("fingerprint");
  useEffect(() => {
    let active = true;
    void biometricKind().then((value) => active && setKind(value));
    return () => {
      active = false;
    };
  }, []);
  return kind;
}

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
  const kind = useBiometricKind();
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
      <Text style={styles.text}>{biometricText("unlockOptionsOffer", kind)}</Text>
      {options.biometric ? (
        <Button label={biometricText("biometricEnable", kind)} disabled={busy} onPress={() => void turnOn(() => enableBiometric(userId, pin, t("biometricPrompt")))} />
      ) : null}
      {options.screenLock ? (
        <Button label={t("screenLockEnable")} disabled={busy} onPress={() => void turnOn(() => enableScreenLock(userId, pin, t("screenLockPrompt")))} />
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("biometricSkip")} disabled={busy} onPress={onDone} />
    </>
  );
}
