/**
 * Interviewer sign-in on this device. "I have a sign-in code" redeems the code in the app as the welcome screen does
 * (src/SignInCodeSteps.tsx) and signs in with the generated password through this screen's own submit; "Forgot
 * password" posts the identifier (POST /auth/forgot-password) and shows the server's answer. Neither opens a server
 * page (docs/policy/mobile-sign-in.md, owner 2026-11-19).
 */
import Constants from "expo-constants";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { ApiError } from "../api";
import { APP_VERSION } from "../appVersion";
import { useAppState } from "../AppState";
import {
  forgetDevice, loadActiveSlot, loadDevice, passwordEnrolAndSignIn, recoverSignOut, redeemSignInCode, requestPasswordReset, signIn,
  verifyPasswordForDelete,
  WrongAccountError, type Slot
} from "../auth";
import { normalizeUsername } from "../demoRules";
import { DeviceLimitChoice, deviceLimitPhones, type LimitPhone } from "../DeviceLimitChoice";
import { EnrolmentError, isDemoServer } from "../enrolment";
import { t } from "../i18n";
import { MOBILE_MAX_CHARS, nextMobileDigits, normalizeMobileIdentifier } from "../nativeAuthLinks";
import { CodeAccepted, SignInCodeForm, signInCodeErrorText } from "../SignInCodeSteps";
import { Button, errorText, FieldLabel, Notice, PasswordInput, Screen, SegmentedControl, TextField, TextLink, useUiStyles } from "../ui";
import { spacing } from "../theme";
import { displayProjectName } from "../projectName";
import { deviceFamilyLabel } from "../platformFamily";

export default function SignIn() {
  const styles = useUiStyles();
  const router = useRouter();
  // "Sign in again" names the account it came from; signIn never wipes a store. `resetPin` comes from "Forgot PIN?".
  // `recover` (no reset copy) and `deleteProfile` check the password for `userId` only and store no session
  // (docs/policy/mobile-sign-in.md section 10).
  const { userId, resetPin, recover, deleteProfile } =
    useLocalSearchParams<{ userId?: string; resetPin?: string; recover?: string; deleteProfile?: string }>();
  const { reload, accounts, device, lockNow } = useAppState();
  // The public demo signs in by username and has no code or password-reset links.
  const demo = isDemoServer(device?.server, __DEV__, process.env.EXPO_PUBLIC_DEMO_SERVER);
  const returning = accounts.find((account) => account.user_id === userId);
  const [mode, setMode] = useState<"email" | "mobile">("email");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /** The account's phones after a `409 device_limit`: pick one to sign out and retry this sign-in. */
  const [limitPhones, setLimitPhones] = useState<LimitPhone[]>();
  /** "Sign in again" found this phone no longer enrolled (revoked or removed): the password to re-enrol with once
   * the person agrees, kept only while the prompt or its device-limit choice is open. */
  const [reEnrolSecret, setReEnrolSecret] = useState<string>();
  /** The server to enrol on again: the returning account's, or the revoked device's, read before it is forgotten. */
  const [reEnrolServer, setReEnrolServer] = useState("");

  /** The sign-in form, the sign-in code form (then Code accepted) or Forgot password. */
  const [view, setView] = useState<"form" | "code" | "forgot">("form");
  const [signInCode, setSignInCode] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);
  /** A redeemed code's generated password, shown once until it signs in or Cancel; kept when that sign-in fails. */
  const [generated, setGenerated] = useState<string>();
  /** The server's Forgot password answer. */
  const [resetMessage, setResetMessage] = useState("");

  const typedIdentifier = () => demo
    ? normalizeUsername(identifier)
    : mode === "mobile" ? normalizeMobileIdentifier(identifier) : identifier.trim();
  const identifierReady = !!identifier.trim() && (demo || mode !== "mobile" || !!normalizeMobileIdentifier(identifier));
  const requestError = (caught: unknown) => caught instanceof EnrolmentError ? t(caught.key) : errorText(caught);
  // A forgotten (revoked) device has no server: the returning account keeps the one it signed in on.
  const enrolledServer = async () => (await loadDevice())?.server ?? returning?.server ?? "";
  function showForm() {
    setView("form");
    setSignInCode("");
    setAcceptTerms(false);
    setGenerated(undefined);
    setResetMessage("");
    setError("");
  }

  /** Redeem the code on this device's server; nothing is stored, and the code is kept on a refusal. */
  async function submitCode() {
    const submittedIdentifier = typedIdentifier();
    if (!submittedIdentifier) {
      setError(t("errMobile"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      setGenerated(await redeemSignInCode(await enrolledServer(), submittedIdentifier, signInCode));
      setSignInCode("");
      setAcceptTerms(false);
    } catch (caught) {
      setError(signInCodeErrorText(caught, requestError));
    } finally {
      setBusy(false);
    }
  }

  async function submitForgot() {
    const submittedIdentifier = typedIdentifier();
    if (!submittedIdentifier) {
      setError(t("errMobile"));
      return;
    }
    setBusy(true);
    setError("");
    setResetMessage("");
    try {
      setResetMessage(await requestPasswordReset(await enrolledServer(), submittedIdentifier));
    } catch (caught) {
      setError(requestError(caught));
    } finally {
      setBusy(false);
    }
  }

  /** `secret` is the typed password, or a redeemed code's generated one ("I have saved it"). */
  async function submit(replaceDeviceId?: string, secret = password) {
    const submittedIdentifier = typedIdentifier();
    if (!submittedIdentifier) {
      setError(t("errMobile"));
      return;
    }
    setBusy(true);
    setError("");
    // The slot this sign-in uses, pinned: a revoked device is forgotten there, not in a slot chosen meanwhile.
    let slot: Slot | undefined;
    try {
      slot = await loadActiveSlot();
      if (userId && recover === "1") {
        await recoverSignOut(userId, submittedIdentifier, secret);
        await reload();
        router.replace("/");
        return;
      }
      if (userId && deleteProfile === "1") {
        await verifyPasswordForDelete(userId, submittedIdentifier, secret);
        router.dismissTo({ pathname: "/unlock", params: { userId, delete: "1" } });
        return;
      }
      const account = await signIn(submittedIdentifier, secret, slot, { forPinReset: resetPin === "1" && !!userId, replaceDeviceId });
      setLimitPhones(undefined);
      await reload();
      // Forgot PIN: a new PIN only for the account that just signed in (interviewerDb.resetInterviewerPin checks it too).
      if (resetPin === "1" && account.user_id === userId) {
        router.replace({ pathname: "/pin-setup", params: { userId: account.user_id, reset: "1", refresh: "1" } });
        return;
      }
      // Unlock sends an interviewer without a PIN yet to PIN setup.
      router.dismissTo({ pathname: "/unlock", params: { userId: account.user_id, refresh: "1" } });
    } catch (caught) {
      // Only the plain sign-in can retry with a phone signed out; recovery and delete keep the plain message.
      const plainSignIn = recover !== "1" && deleteProfile !== "1";
      const phones = plainSignIn ? deviceLimitPhones(caught) : undefined;
      setLimitPhones(phones);
      if (phones) return;
      // Retrying cannot work without a device: offer to enrol this phone again on the account's own server.
      if (plainSignIn && slot === "active" && returning?.server && caught instanceof Error && caught.message === "not_enrolled") {
        setReEnrolServer(returning.server);
        setReEnrolSecret(secret);
        return;
      }
      // Revoked: the device and its server are forgotten below, so keep the server now. On a plain sign-in (Add
      // profile too, which has no returning account) offer the same re-enrol prompt: the bare "Enrol it again"
      // offered no way to, and a retry then had no server ("Could not reach the server", digitva-koe3).
      const revokedServer = caught instanceof ApiError && caught.code === "device_revoked" ? (await loadDevice())?.server ?? returning?.server ?? "" : "";
      // Forgetting the Demo device hands the phone back to Active, a slot change: lock first, or keep it.
      if (caught instanceof ApiError && caught.code === "device_revoked" && slot !== undefined
        && (slot === "active" || await lockNow())) {
        await forgetDevice(slot);
        await reload();
        if (plainSignIn && slot === "active" && revokedServer) {
          setReEnrolServer(revokedServer);
          setReEnrolSecret(secret);
          return;
        }
      }
      setError(caught instanceof WrongAccountError ? t("signInWrongAccount") : errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  /** Enrol this phone again for the returning account (the same password enrolment as the welcome screen's), then
   * unlock. Enrolment stores a new device and this account's tokens; the account's encrypted store is keyed by its
   * own store secret and PIN, not the device, so its unsent work opens as before. */
  async function reEnrol(secret: string, replaceDeviceId?: string) {
    const submittedIdentifier = typedIdentifier();
    if (!reEnrolServer || !submittedIdentifier) return;
    setBusy(true);
    setError("");
    try {
      if (!(await lockNow())) return;
      const enrolled = await passwordEnrolAndSignIn(reEnrolServer, submittedIdentifier, secret,
        Constants.deviceName ?? deviceFamilyLabel(), APP_VERSION, replaceDeviceId);
      setLimitPhones(undefined);
      setReEnrolSecret(undefined);
      await reload();
      router.dismissTo({ pathname: "/unlock", params: { userId: enrolled.account.user_id, refresh: "1" } });
    } catch (caught) {
      const phones = deviceLimitPhones(caught);
      setLimitPhones(phones);
      if (phones) return;
      setReEnrolSecret(undefined);
      setError(caught instanceof EnrolmentError ? t(caught.key) : errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  if (limitPhones) {
    return <DeviceLimitChoice phones={limitPhones} busy={busy}
      onPick={(id) => void (reEnrolSecret !== undefined ? reEnrol(reEnrolSecret, id) : submit(id))}
      onCancel={() => { setLimitPhones(undefined); setReEnrolSecret(undefined); }} />;
  }

  if (reEnrolSecret !== undefined) {
    return (
      <Screen title={t("notEnrolledTitle")}>
        <Text style={styles.text}>{t("notEnrolledBody")}</Text>
        <Button label={t("notEnrolledConfirm")} loading={busy} disabled={busy} onPress={() => void reEnrol(reEnrolSecret)} />
        <TextLink label={t("cancel")} disabled={busy} onPress={() => setReEnrolSecret(undefined)} />
      </Screen>
    );
  }

  // Email | Mobile (or the demo's username) and its field: the sign-in form's, the code form's and Forgot password's.
  const identifierFields = (
    <>
      {/* The segmented control names its own choice (Email | Mobile): no "Sign in with" label above it. */}
      {demo ? null : (
        <SegmentedControl
          accessibilityLabel={t("signInIdentifierType")}
          options={[{ value: "email", label: t("email") }, { value: "mobile", label: t("mobile") }]}
          value={mode}
          onChange={(next) => {
            setMode(next);
            setIdentifier("");
            setError("");
          }}
        />
      )}
      <FieldLabel label={demo ? t("demoSignInUsername") : mode === "mobile" ? t("mobile") : t("email")} />
      {demo ? (
        <TextField
          accessibilityLabel={t("demoSignInUsername")}
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="username"
          value={identifier}
          onChangeText={setIdentifier}
        />
      ) : mode === "mobile" ? (
        <View style={styles.phoneInputRow}>
          <Text style={styles.phonePrefix} accessibilityLabel={t("countryCodeIndia")}>
            +91
          </Text>
          <TextField
            style={styles.phoneInput}
            accessibilityLabel={t("mobile")}
            autoCapitalize="none"
            autoComplete="tel"
            keyboardType="phone-pad"
            maxLength={MOBILE_MAX_CHARS}
            value={identifier}
            onChangeText={(value) => setIdentifier((previous) => nextMobileDigits(previous, value))}
          />
        </View>
      ) : (
        <TextField
          accessibilityLabel={t("email")}
          // The expected shape before entry (WCAG 3.3.2).
          placeholder={t("emailPlaceholder")}
          autoCapitalize="none"
          autoComplete="username"
          keyboardType="default"
          value={identifier}
          onChangeText={setIdentifier}
        />
      )}
    </>
  );
  const errorNotice = error ? <Notice tone="error">{error}</Notice> : null;

  if (generated) {
    return (
      <CodeAccepted password={generated} busy={busy} error={errorNotice} onCancel={() => { setPassword(""); showForm(); }} onContinue={() => {
        // The device-limit retry signs in again with the password field: it holds the generated password.
        setPassword(generated);
        void submit(undefined, generated);
      }} />
    );
  }

  if (view === "code") {
    return (
      <SignInCodeForm identifierFields={identifierFields} identifierReady={identifierReady} code={signInCode}
        onCodeChange={setSignInCode} acceptTerms={acceptTerms} onAcceptTermsChange={setAcceptTerms} busy={busy}
        error={errorNotice} onSubmit={() => void submitCode()} onCancel={showForm} />
    );
  }

  if (view === "forgot") {
    return (
      <Screen title={t("forgotPassword")}>
        <Text style={styles.muted}>{t("forgotPasswordIntro")}</Text>
        {identifierFields}
        {resetMessage ? <Notice tone="info">{resetMessage}</Notice> : null}
        {errorNotice}
        <Button label={t("forgotPasswordSend")} loading={busy} disabled={busy || !identifierReady} onPress={() => void submitForgot()} />
        <TextLink label={resetMessage ? t("back") : t("cancel")} disabled={busy} onPress={showForm} />
      </Screen>
    );
  }

  return (
    <Screen title={t("signInTitle")}>
      {/* Which server project this signs into, under the title (design sheet 11). */}
      {device?.project_id ? <Text style={styles.muted}>{[device.project_id, displayProjectName(device.project_name)].filter(Boolean).join(" · ")}</Text> : null}
      {returning ? <Text style={styles.text}>{t("signInAgainAs", { name: returning.name })}</Text> : null}
      {identifierFields}
      <FieldLabel label={t("password")} />
      <PasswordInput accessibilityLabel={t("password")} autoComplete="current-password" value={password} onChangeText={setPassword} />
      {errorNotice}
      <Button
        label={t("signIn")}
        loading={busy}
        disabled={busy || !identifierReady || !password}
        onPress={() => void submit()}
      />
      {/* Secondary ways in are text links, so Sign in stays the one button on the screen. No Cancel: it only went
          back, and Back (or the back swipe) returns to the screen this came from. */}
      {demo ? null : (
        <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.lg, marginTop: spacing.sm }}>
          <TextLink label={t("redeemCode")} disabled={busy} onPress={() => { setError(""); setView("code"); }} />
          <TextLink label={t("forgotPassword")} disabled={busy} onPress={() => { setError(""); setView("forgot"); }} />
        </View>
      )}
    </Screen>
  );
}
