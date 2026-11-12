/**
 * Unlock one interviewer's store: the biometric prompt first when it is on, else
 * the phone screen-lock prompt when that is on; the PIN (six boxes) always. Warns from the third wrong PIN; from the fifth in a
 * row the store refuses PINs for a growing wait (src/vault.ts pinLockMs) and erases nothing. "Forgot PIN?" signs in with the
 * password and then sets a new PIN, keeping the interviews (pin-setup reset; digitva-kfi).
 * An interviewer with no PIN yet goes to PIN setup. A signed-out profile goes
 * to sign-in instead: its PIN alone never opens the kept store.
 * Under "Switch profile" a recovery link always shows for a server profile (docs/policy/mobile-sign-in.md section 10):
 * "Forgot PIN?" when a reset copy exists, else a password sign-in that signs the profile out and keeps its store.
 * "Delete profile" (also `?delete=1` from the profiles list) needs the PIN or a password check (sign-in
 * `deleteProfile=1`, a memory-only grant): a known unsent count above zero refuses; an unknown one needs the
 * typed confirmation. A signed-out or unlocked profile stays here while deleting instead of redirecting.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";

import { ConfirmDialog } from "../ConfirmDialog";
import { clearProfileDeleteGrant } from "../pinResetGrant";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { deleteProfile, hasProfileDeleteGrant, ProfileDeleteRefusedError, unlockInterviewer, wipeInterviewer } from "../auth";
import { t } from "../i18n";
import { hasInterviewerStore, isUnlocked, resetMissingStore, unsentWorkCount } from "../interviewerDb";
import { homeRoute } from "../standalone/home";
import { PIN_BOXES, PinBoxes } from "../PinBoxes";
import { controls, spacing, useTheme } from "../theme";
import { Button, Notice, PasswordInput, Screen, TextField, TextLink, useUiStyles } from "../ui";
import { biometricText, pendingUnlockOffer, UnlockOffer, useBiometricKind } from "../UnlockOffer";
import {
  biometricEnabled,
  enableBiometric,
  enableScreenLock,
  FREE_PIN_ATTEMPTS,
  pinUnlockState,
  readBiometricPin,
  PIN_MAX_LENGTH,
  readScreenLockPin,
  screenLockEnabled,
  storedPinLength,
  WARN_AFTER_FAILURES
} from "../vault";

const wrongPinText = (failures: number) =>
  failures >= WARN_AFTER_FAILURES && failures < FREE_PIN_ATTEMPTS
    ? t("pinWrongWarn", { left: FREE_PIN_ATTEMPTS - failures })
    : t("pinWrong");

export default function Unlock() {
  const styles = useUiStyles();
  const { ui, typography } = useTheme();
  const bioKind = useBiometricKind();
  const router = useRouter();
  const { userId, refresh, enableBiometric: enableBiometricParam, enableScreenLock: enableScreenLockParam, delete: deleteParam } =
    useLocalSearchParams<{ userId: string; refresh?: string; enableBiometric?: string; enableScreenLock?: string; delete?: string }>();
  const enabling = enableBiometricParam === "1" || enableScreenLockParam === "1";
  const { accounts, reload, unlocked, lockNow } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  // Delete profile: undefined = not deleting; "auth" = waiting for the PIN or password; a number or null = the
  // unsent count after the check (null: unknown, the store stayed locked).
  const [deleting, setDeleting] = useState<"auth" | number | null | undefined>(deleteParam === "1" ? "auth" : undefined);
  const [deleteWord, setDeleteWord] = useState("");
  const signedOut = account?.signed_out === true && deleting === undefined;
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
  // Wall-clock end of the wrong-PIN wait (0 = none) and a tick that redraws the minutes left.
  const [lockedUntil, setLockedUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [canReset, setCanReset] = useState(false);
  // Wrong PINs in a row, to know when a standalone account may erase (all free tries used).
  const [failures, setFailures] = useState(0);
  const [erasing, setErasing] = useState(false);
  const [eraseWord, setEraseWord] = useState("");
  const locked = lockedUntil > now;

  useEffect(() => {
    if (!lockedUntil) return;
    const timer = setInterval(() => {
      const tick = Date.now();
      setNow(tick);
      if (tick >= lockedUntil) {
        setLockedUntil(0);
        setError("");
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lockedUntil]);

  const showLock = useCallback((ms: number) => {
    const start = Date.now();
    setNow(start);
    setLockedUntil(start + ms);
  }, []);

  // A standalone account has no server to reset the PIN, so after the free tries it may erase the phone's store by typed choice.
  const eraseOffered = account?.standalone === true && failures >= FREE_PIN_ATTEMPTS;
  const closeErase = () => {
    setErasing(false);
    setEraseWord("");
  };
  const erase = async () => {
    if (!userId) return;
    setBusy(true);
    try {
      await wipeInterviewer(userId);
      closeErase();
      await reload();
      router.replace("/standalone-setup");
    } catch {
      closeErase();
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  };

  const closeDelete = () => {
    setDeleting(undefined);
    setDeleteWord("");
    if (userId) clearProfileDeleteGrant(userId);
    setError("");
    // A PIN check opened the store without marking it unlocked: close it again.
    void lockNow().catch(() => undefined);
  };
  const confirmDelete = async () => {
    if (!userId || deleting === undefined || deleting === "auth") return;
    setBusy(true);
    setError("");
    try {
      await deleteProfile(userId, deleting, deleting === null);
      await reload();
      router.replace("/");
    } catch (caught) {
      setError(
        caught instanceof ProfileDeleteRefusedError || (caught instanceof ApiError && caught.code === "unsent_work")
          ? t("profileDeleteRefused")
          : caught instanceof ApiError && (caught.status === 400 || caught.status === 409) ? t("profileDeleteServerRefused") : t("errGeneric"),
      );
    } finally {
      setBusy(false);
    }
  };

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
        if (result.ok && deleting !== undefined) {
          // The PIN is the check; the now-open store gives the count. Not marked unlocked: Cancel locks it again.
          setPin("");
          setDeleting((await unsentWorkCount(userId)) ?? null);
          return;
        }
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
          // Only a revoke wipes (nothing unsent was left); wrong PINs never do.
          Alert.alert(t("sessionRevoked"));
          await reload();
          router.replace("/");
          return;
        }
        setFailures(result.failures);
        if (result.lockedMs) showLock(result.lockedMs);
        else setError(wrongPinText(result.failures));
      } catch {
        setError(t("errGeneric"));
      } finally {
        setBusy(false);
      }
    },
    [userId, signedOut, deleting, enableBiometricParam, enableScreenLockParam, enabling, unlocked, toWorklist, reload, router, lockNow, showLock]
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
    // Opened to delete (the first render's value): no redirect and no automatic prompt.
    const deletingAtOpen = deleting !== undefined;
    if (deletingAtOpen && hasProfileDeleteGrant(userId)) {
      // Back from the password check (sign-in deleteProfile=1): the count is known only if the store is open.
      void unsentWorkCount(userId).then((count) => setDeleting(count ?? null));
    }
    if (isUnlocked(userId) && !enabling && !deletingAtOpen) {
      toWorklist();
      return;
    }
    let active = true;
    void (async () => {
      try {
        if (!(await hasInterviewerStore(userId))) {
          if (deletingAtOpen) return;
          router.replace({ pathname: "/pin-setup", params: { userId, ...(refresh === "1" ? { refresh: "1" } : {}) } });
          return;
        }
        const state = await pinUnlockState(userId);
        if (active) {
          setCanReset(state.canReset);
          setFailures(state.failures);
          if (state.lockedMs) showLock(state.lockedMs);
          else if (state.failures > 0) setError(wrongPinText(state.failures));
        }
        const [bio, lock] = await Promise.all([biometricEnabled(userId), screenLockEnabled(userId)]);
        if (active) {
          setBiometric(bio);
          setScreenLock(lock);
        }
        const length = await storedPinLength(userId);
        if (active && length !== null && length > PIN_BOXES) setLongPin(true);
        if (enabling || state.lockedMs || deletingAtOpen) return;
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
        <Notice tone="error" testID="store-missing">{t(account.standalone ? "storeMissingStandalone" : "storeMissing")}</Notice>
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button kind="danger" label={t("storeMissingReset")} onPress={resetStore} />
      </Screen>
    );
  }
  if (deleting !== undefined && deleting !== "auth") {
    const word = t("profileDeleteWord");
    const typed = deleteWord.trim().toLowerCase() === word.toLowerCase();
    return (
      <Screen title={t("profileDeleteTitle")}>
        <Text testID="unlock-name" style={{ ...typography.body, color: ui.foreground }}>{account.name}</Text>
        {deleting !== null && deleting > 0 ? (
          <Notice tone="error" testID="profile-delete-refused">{t("profileDeleteUnsent", { count: deleting })}</Notice>
        ) : (
          <>
            <Text style={styles.text}>{t(deleting === null ? "profileDeleteBodyUnknown" : "profileDeleteBody")}</Text>
            {deleting === null ? (
              <TextField
                testID="profile-delete-confirm-input"
                accessibilityLabel={t("pinErasePrompt", { word })}
                placeholder={t("pinErasePrompt", { word })}
                autoCapitalize="characters"
                autoCorrect={false}
                value={deleteWord}
                onChangeText={setDeleteWord}
              />
            ) : null}
            {error ? <Notice tone="error">{error}</Notice> : null}
            <Button
              testID="profile-delete-confirm"
              kind="danger"
              label={t("profileDeleteConfirm")}
              loading={busy}
              disabled={busy || (deleting === null && !typed)}
              onPress={() => void confirmDelete()}
            />
          </>
        )}
        <TextLink label={t("cancel")} disabled={busy} onPress={closeDelete} />
      </Screen>
    );
  }
  // One heading per screen (the "Unlock" title): the profile name is a body line in ink over one line saying what
  // to do. Rhythm measured to the links' text, not their 44pt boxes: boxes 12pt to "My PIN is longer", that link
  // 24pt to Unlock, Unlock 24pt to Switch profile (the "longer PIN" link belongs to the boxes).
  // A TextLink centres its text line in a 44pt box, and the line box has leading around the glyphs (half of
  // lineHeight - fontSize above, half below): the space above and below the visible text that the link adds.
  // Roboto's cap top sits a little lower in the line than its descender rises (about 1/16 em each way,
  // measured on the emulator in round 5), so the inset above the text is larger than the one below it.
  const linkBox = Math.max(0, (controls.minTouchTarget - typography.body.lineHeight) / 2) + (typography.body.lineHeight - typography.body.fontSize) / 2;
  const glyphShift = typography.body.fontSize / 16;
  const linkOffsetAbove = (rhythm: number) => rhythm - (linkBox + glyphShift);
  const linkOffsetBelow = (rhythm: number) => rhythm - (linkBox - glyphShift);
  return (
    <Screen title={t(deleting ? "profileDeleteTitle" : "unlockTitle")}>
      <View style={{ gap: spacing.lg }}>
        <View style={{ gap: spacing.xxs }}>
          <Text testID="unlock-name" style={{ ...typography.body, color: ui.foreground }}>{account.name}</Text>
          <Text style={styles.muted}>{t(deleting ? "profileDeleteAuth" : "unlockSubtitle")}</Text>
        </View>
        <View style={{ gap: spacing.sm }}>
          {longPin ? (
            <PasswordInput
              accessibilityLabel={t("pin")}
              showLabel={t("pinShow")}
              hideLabel={t("pinHide")}
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
              <View testID="pin-longer-link" style={{ marginTop: linkOffsetAbove(spacing.sm) - spacing.sm }}>
                <TextLink label={t("pinLonger")} onPress={() => setLongPin(true)} />
              </View>
            </>
          )}
          {locked ? (
            <Notice tone="error" testID="pin-locked">{t("pinLocked", { minutes: Math.ceil((lockedUntil - now) / 60_000) })}</Notice>
          ) : error ? <Notice tone="error">{error}</Notice> : null}
        </View>
        <View testID="unlock-actions" style={{ gap: spacing.sm, marginTop: longPin || error || locked ? 0 : linkOffsetBelow(spacing.lg) - spacing.lg }}>
          <Button testID="unlock-submit" label={t("unlock")} disabled={busy || locked || pin.length < PIN_BOXES} onPress={() => void tryPin(pin)} />
          {biometric ? (
            <Button kind="secondary" label={biometricText("biometricEnable", bioKind)} disabled={busy || locked} onPress={() => void tryBiometric()} />
          ) : null}
          {screenLock ? (
            <Button kind="secondary" label={t("screenLockEnable")} disabled={busy || locked} onPress={() => void tryScreenLock()} />
          ) : null}
          {/* A standalone account has no password, and a store that never unlocked on this version has no reset copy. */}
          {deleting && !account.standalone ? (
            <TextLink
              label={t("profileDeleteWithPassword")}
              disabled={busy}
              onPress={() => router.push({ pathname: "/sign-in", params: { userId: account.user_id, deleteProfile: "1" } })}
            />
          ) : null}
          {eraseOffered ? <TextLink label={t("pinForgotStandalone")} disabled={busy} onPress={() => setErasing(true)} /> : null}
          {erasing ? (
            <ConfirmDialog
              title={t("pinEraseTitle")}
              message={t("pinEraseBody")}
              confirmLabel={t("pinEraseConfirm")}
              destructive
              confirmDisabled={busy || eraseWord.trim().toLowerCase() !== t("pinEraseWord").toLowerCase()}
              onConfirm={() => void erase()}
              onCancel={closeErase}
            >
              <TextField
                accessibilityLabel={t("pinErasePrompt", { word: t("pinEraseWord") })}
                placeholder={t("pinErasePrompt", { word: t("pinEraseWord") })}
                autoCapitalize="characters"
                autoCorrect={false}
                value={eraseWord}
                onChangeText={setEraseWord}
              />
            </ConfirmDialog>
          ) : null}
          {/* The accounts list: while locked, Home is behind this lock, so the way out is to another profile. */}
          {deleting ? <TextLink label={t("cancel")} disabled={busy} onPress={closeDelete} /> : (
            <>
              <View testID="switch-profile-link" style={{ marginTop: linkOffsetAbove(spacing.lg) - spacing.sm }}>
                <TextLink label={t("switchInterviewer")} onPress={() => router.replace("/")} />
              </View>
              {/* Always, for a server profile (section 10): with a reset copy "Forgot PIN?", else sign in and sign out,
                  keeping the store. A standalone profile has no password; its erase offer is above. */}
              {account.standalone ? null : (
                <TextLink
                  testID="unlock-recover"
                  label={t(canReset ? "pinForgot" : "pinForgotSignOut")}
                  disabled={busy}
                  onPress={() => router.push({ pathname: "/sign-in", params: { userId: account.user_id, ...(canReset ? { resetPin: "1" } : { recover: "1" }) } })}
                />
              )}
              {/* Rare and destructive: small, set apart at the very bottom (owner 2026-11-13). */}
              <View style={{ marginTop: spacing.xl }}>
                <TextLink testID="profile-delete" size="sm" label={t("profileDelete")} tone="destructive" disabled={busy} onPress={() => { setError(""); setDeleting("auth"); }} />
              </View>
            </>
          )}
        </View>
      </View>
    </Screen>
  );
}
