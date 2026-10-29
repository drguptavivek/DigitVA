/**
 * Unlock one interviewer's store: the biometric prompt first when it is on, else
 * the phone screen-lock prompt when that is on; the PIN (six boxes) always. Warns from the third wrong PIN; the fifth in a row erases
 * that interviewer's store and signs them out (src/auth.ts unlockInterviewer).
 * An interviewer with no PIN yet goes to PIN setup. A signed-out profile goes
 * to sign-in instead: its PIN alone never opens the kept store.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Alert, Pressable, Text, TextInput } from "react-native";

import { useAppState } from "../AppState";
import { unlockInterviewer } from "../auth";
import { t } from "../i18n";
import { hasInterviewerStore, isUnlocked, resetMissingStore } from "../interviewerDb";
import { homeRoute } from "../standalone/home";
import { PIN_BOXES, PinBoxes } from "../PinBoxes";
import { Button, Screen, useUiStyles } from "../ui";
import { pendingUnlockOffer, UnlockOffer } from "../UnlockOffer";
import {
  biometricEnabled,
  enableBiometric,
  enableScreenLock,
  failedAttempts,
  readBiometricPin,
  PIN_MAX_LENGTH,
  readScreenLockPin,
  screenLockEnabled,
  storedPinLength,
  WARN_AFTER_FAILURES,
  WIPE_AFTER_FAILURES
} from "../vault";

const wrongPinText = (failures: number) =>
  failures >= WARN_AFTER_FAILURES
    ? t("pinWrongWarn", { left: WIPE_AFTER_FAILURES - failures })
    : t("pinWrong");

export default function Unlock() {
  const styles = useUiStyles();
  const router = useRouter();
  const { userId, refresh, enableBiometric: enableBiometricParam, enableScreenLock: enableScreenLockParam } =
    useLocalSearchParams<{ userId: string; refresh?: string; enableBiometric?: string; enableScreenLock?: string }>();
  const enabling = enableBiometricParam === "1" || enableScreenLockParam === "1";
  const { accounts, reload, unlocked, lockNow } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const signedOut = account?.signed_out === true;
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [storeMissing, setStoreMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [biometric, setBiometric] = useState(false);
  const [screenLock, setScreenLock] = useState(false);
  const [shake, setShake] = useState(0);
  // The vault allows 6 to 16 digits; the boxes take 6, so a longer PIN is typed in one field (never cut silently).
  const [longPin, setLongPin] = useState(false);
  const [offer, setOffer] = useState<{ pin: string; options: { biometric: boolean; screenLock: boolean } }>();

  const toWorklist = useCallback(
    () => router.replace({ pathname: homeRoute(account), params: { userId: userId ?? "", ...(refresh === "1" ? { refresh: "1" } : {}) } }),
    [router, userId, refresh, account]
  );

  const tryPin = useCallback(
    async (candidate: string) => {
      if (!userId || signedOut) return;
      setBusy(true);
      setError("");
      try {
        if (enabling && isUnlocked(userId)) {
          await lockNow();
          if (isUnlocked(userId)) {
            setError(t("errGeneric"));
            return;
          }
        }
        const result = await unlockInterviewer(userId, candidate);
        if (result.ok) {
          let setupFailed = false;
          try {
            if (enableBiometricParam === "1" && !(await biometricEnabled(userId))) {
              await enableBiometric(userId, candidate, t("biometricPrompt"));
            }
            if (enableScreenLockParam === "1" && !(await screenLockEnabled(userId))) {
              await enableScreenLock(userId, candidate, t("screenLockPrompt"));
            }
          } catch {
            setupFailed = true;
            setError(t("errGeneric"));
          }
          unlocked();
          if (setupFailed) return;
          const options = enabling ? null : await pendingUnlockOffer(userId).catch(() => null);
          if (options) setOffer({ pin: candidate, options });
          else toWorklist();
          return;
        }
        if ("storeMissing" in result) {
          setPin("");
          setStoreMissing(true);
          return;
        }
        setPin("");
        setShake((n) => n + 1);
        if (result.wipe) {
          Alert.alert(t(result.revoked ? "sessionRevoked" : account?.standalone ? "pinWipedStandalone" : "pinWiped"));
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
    [userId, signedOut, enableBiometricParam, enableScreenLockParam, enabling, unlocked, toWorklist, reload, router, lockNow]
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

  const tryScreenLock = useCallback(async () => {
    if (!userId) return;
    try {
      const released = await readScreenLockPin(userId, t("screenLockPrompt"));
      if (released) await tryPin(released);
      else setScreenLock(false);
    } catch {
      // Prompt cancelled or refused: the PIN boxes stay.
    }
  }, [userId, tryPin]);

  useEffect(() => {
    // Signed out: no biometric or screen-lock prompt; the render below sends it to sign-in.
    if (!userId || signedOut) return;
    if (isUnlocked(userId) && !enabling) {
      toWorklist();
      return;
    }
    let active = true;
    void (async () => {
      try {
        if (!(await hasInterviewerStore(userId))) {
          router.replace({ pathname: "/pin-setup", params: { userId, ...(refresh === "1" ? { refresh: "1" } : {}) } });
          return;
        }
        const failures = await failedAttempts(userId);
        if (active && failures > 0) setError(wrongPinText(failures));
        const [bio, lock] = await Promise.all([biometricEnabled(userId), screenLockEnabled(userId)]);
        if (active) {
          setBiometric(bio);
          setScreenLock(lock);
        }
        const length = await storedPinLength(userId);
        if (active && length !== null && length > PIN_BOXES) setLongPin(true);
        if (enabling) return;
        if (bio) await tryBiometric();
        else if (lock) await tryScreenLock();
      } catch {
        if (active) setError(t("errGeneric"));
      }
    })();
    return () => {
      active = false;
    };
    // Once per screen: a failed biometric must not re-prompt on every render.
  }, [userId, enabling, lockNow, signedOut]);

  if (!account) return <Redirect href="/" />;
  if (signedOut) return <Redirect href={{ pathname: "/sign-in", params: { userId: account.user_id } }} />;
  if (offer) {
    return (
      <Screen title={t("unlockTitle")}>
        <UnlockOffer userId={account.user_id} pin={offer.pin} options={offer.options} onDone={toWorklist} />
      </Screen>
    );
  }
  if (storeMissing) {
    const resetStore = () => Alert.alert(t("storeMissingTitle"), t(account.standalone ? "storeMissingConfirmStandalone" : "storeMissingConfirm"), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("storeMissingReset"),
        style: "destructive",
        onPress: () => {
          void resetMissingStore(account.user_id)
            .then(() => router.replace({ pathname: "/pin-setup", params: { userId: account.user_id } }))
            .catch(() => setError(t("errGeneric")));
        },
      },
    ]);
    return (
      <Screen title={t("unlockTitle")}>
        <Text style={styles.muted}>{account.name}</Text>
        <Text style={styles.error} testID="store-missing">{t(account.standalone ? "storeMissingStandalone" : "storeMissing")}</Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Button kind="danger" label={t("storeMissingReset")} onPress={resetStore} />
      </Screen>
    );
  }
  return (
    <Screen title={t("unlockTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      <Text style={styles.muted}>{t("pin")}</Text>
      {longPin ? (
        <TextInput
          style={styles.input}
          accessibilityLabel={t("pin")}
          secureTextEntry
          autoComplete="off"
          importantForAutofill="no"
          keyboardType="number-pad"
          autoFocus
          maxLength={PIN_MAX_LENGTH}
          value={pin}
          onChangeText={(text) => setPin(text.replace(/\D/g, "").slice(0, PIN_MAX_LENGTH))}
          onSubmitEditing={() => pin.length >= PIN_BOXES && void tryPin(pin)}
        />
      ) : (
        <>
          <PinBoxes value={pin} onChange={setPin} label={t("pin")} shakeSignal={shake} />
          <Pressable accessibilityRole="link" onPress={() => setLongPin(true)} hitSlop={8}>
            <Text style={styles.muted}>{t("pinLonger")}</Text>
          </Pressable>
        </>
      )}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button label={t("unlock")} disabled={busy || pin.length < PIN_BOXES} onPress={() => void tryPin(pin)} />
      {biometric ? (
        <Button kind="secondary" label={t("biometricEnable")} disabled={busy} onPress={() => void tryBiometric()} />
      ) : null}
      {screenLock ? (
        <Button kind="secondary" label={t("screenLockEnable")} disabled={busy} onPress={() => void tryScreenLock()} />
      ) : null}
      <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
    </Screen>
  );
}
