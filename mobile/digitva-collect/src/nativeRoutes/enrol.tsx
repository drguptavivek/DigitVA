/**
 * Enrol: scan the one-time QR from the project's Devices page, validate its
 * server against the compiled rule (src/enrolment.ts), show that server's host
 * and wait for the user to confirm, then POST /enroll. A sign-in QR (docs/policy/mobile-sign-in.md section 8)
 * is taken the same way but redeems its token, which enrols the phone and signs the person in; they go
 * on to PIN setup. Pasting the JSON is a
 * debug-build convenience for the emulator. Both enrol the Active slot. "Try the demo" switches to the
 * Demo slot (src/AppState.tsx switchSlot), opening src/nativeRoutes/demo.tsx to enrol on the public demo
 * server without a code when the phone has no demo enrolment yet. Manual server
 * and password enrolment opens the same Active account and unlock journey as a sign-in QR. "I have a sign-in code"
 * redeems a data manager's code (POST /sign-in-code/redeem), shows the generated password once ("Code accepted"),
 * then signs in with it through the same manual enrolment, so nobody retypes it (docs/policy/mobile-sign-in.md s.3).
 */
import Constants from "expo-constants";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { goHome } from "../goHome";
import { useEffect, useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { enrolDevice, passwordEnrolAndSignIn, redeemSignInCode, redeemSignInQr, setDeviceHomeProject, type EnrolledAccount } from "../auth";
import { DeviceLimitChoice, deviceLimitPhones, type LimitPhone } from "../DeviceLimitChoice";
import { defaultManualServer, EnrolmentError, manualServerAddress, parseScannedQr, type ScannedQr } from "../enrolment";
import { isPlusVariant } from "../appVariant";
import { deviceFamilyLabel, offlineEnginePlatform } from "../platformFamily";
import { t } from "../i18n";
import { useUiLanguages } from "../uiPacks";
import { MenuChoiceRow } from "../ui/controls";
import { MOBILE_MAX_CHARS, nextMobileDigits, formatSignInCode, looksLikeSignInCode, normalizeMobileIdentifier } from "../nativeAuthLinks";
import { CodeAccepted, SignInCodeForm, signInCodeErrorText } from "../SignInCodeSteps";
import { Icon, icons } from "../Icon";
import { radius, spacing, useTheme } from "../theme";
import { Button, Card, errorText, ListRow, Notice, PasswordInput, Screen, SegmentedControl, Separator, TextLink, useUiStyles } from "../ui";

const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";
/** Where an error shows: the QR code (scan, paste, confirm), the login form, the demo button, the code form, Code accepted. */
type ErrorAt = "code" | "login" | "demo" | "redeem" | "accepted";

function FirstLanguage({ value, hintStyle, onChoose }: { value: string; hintStyle: object; onChoose(code: string): void }) {
  const languages = useUiLanguages();
  return (
    <Screen title={t("chooseLanguageTitle")}>
      <Text style={hintStyle}>{t("chooseLanguageHint")}</Text>
      <View accessibilityRole="radiogroup" accessibilityLabel={t("chooseLanguageTitle")} testID="first-language">
        {languages.map((language) => (
          <MenuChoiceRow
            key={language.code}
            label={language.label}
            language={language.language}
            selected={language.code === value}
            onPress={() => onChoose(language.code)}
          />
        ))}
      </View>
    </Screen>
  );
}

export default function Enrol() {
  const styles = useUiStyles();
  const { ui, typography } = useTheme();
  const router = useRouter();
  const { reload, switchSlot, lockNow, slot, standaloneAvailable, uiLocale, uiLocaleChosen, chooseUiLocale } = useAppState();
  const [permission, requestPermission] = useCameraPermissions();
  const [pasted, setPasted] = useState("");
  /** Each error shows next to the action that produced it. */
  const [error, setErrorState] = useState<{ at: ErrorAt; text: string }>();
  const setError = (at: ErrorAt, text: string) => setErrorState(text ? { at, text } : undefined);
  const errorAt = (at: ErrorAt) =>
    error?.at === at ? <Notice tone="error">{error.text}</Notice> : null;
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<ScannedQr>();
  /** Welcome menu, QR scanner, the server-and-password form or the sign-in code form; a scanned code shows Confirm
   * server over any of them. */
  const [view, setView] = useState<"menu" | "scan" | "manual" | "code">("menu");
  const [server, setServer] = useState(defaultManualServer);
  const [mode, setMode] = useState<"email" | "mobile">("email");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [signInCode, setSignInCode] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);
  /** The code form was opened by a code typed into the Password box: it says so. */
  const [codeFromPassword, setCodeFromPassword] = useState(false);
  /** A redeemed code's generated password, in this state only: shown once until it signs the phone in, Cancel or
   * unmount; kept when that sign-in fails, so the person can retry without losing it. */
  const [accepted, setAccepted] = useState<{ server: string; identifier: string; password: string }>();
  const busyRef = useRef(false);
  /** Signed in with more than one eligible project: the owner's rule is to ask, never pick silently (mobile-sign-in.md). */
  const [choice, setChoice] = useState<EnrolledAccount>();
  /** After a `409 device_limit`: the account's phones, and the refused sign-in to retry with the one picked. */
  const [limit, setLimit] = useState<{ phones: LimitPhone[]; retry: (replaceDeviceId: string) => void; cancel: () => void }>();
  useEffect(() => () => {
    setPassword("");
    setSignInCode("");
    setAccepted(undefined);
  }, []);

  /** Go on to PIN setup, or first ask for the home project when there is more than one. */
  function afterSignIn(enrolled: EnrolledAccount) {
    if (enrolled.projects.length > 1) setChoice(enrolled);
    // Unlock sends a person without a PIN yet to PIN setup (then the unlock-options offer).
    else router.replace({ pathname: "/unlock", params: { userId: enrolled.account.user_id, refresh: "1" } });
  }

  async function pickProject(projectId: string) {
    if (!choice || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("code", "");
    try {
      await setDeviceHomeProject(choice.account.user_id, projectId);
      await reload();
      router.replace({ pathname: "/unlock", params: { userId: choice.account.user_id, refresh: "1" } });
    } catch (caught) {
      setError("code", errorText(caught));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const typedIdentifier = () => mode === "mobile" ? normalizeMobileIdentifier(identifier) : identifier.trim();
  const loginError = (caught: unknown) => caught instanceof EnrolmentError ? t(caught.key)
    : caught instanceof ApiError && caught.status === 404 ? t("errPasswordEnrolUnsupported") : errorText(caught);

  /** Lock every store, then enrol and sign in with a password (the manual form's or a redeemed code's). "limit": a
   * 409 device_limit opened the chooser, whose pick calls `retry` and Cancel `cancel`. Any other refusal throws. */
  async function enrolAndSignIn(serverAddress: string, submittedIdentifier: string, secret: string, replaceDeviceId: string | undefined,
    retry: (replaceDeviceId: string) => void, cancel: () => void): Promise<"signed_in" | "limit" | "not_locked"> {
    if (!(await lockNow())) return "not_locked";
    try {
      const enrolled = await passwordEnrolAndSignIn(serverAddress, submittedIdentifier, secret, Constants.deviceName ?? deviceFamilyLabel(), APP_VERSION, replaceDeviceId);
      setLimit(undefined);
      await reload();
      afterSignIn(enrolled);
      return "signed_in";
    } catch (caught) {
      const phones = deviceLimitPhones(caught);
      setLimit(phones && { phones, retry, cancel });
      if (phones) return "limit";
      throw caught;
    }
  }

  /** Credentials stay in this form only and are cleared after every attempt, except while the device-limit choice
   * is open for its retry (cleared on its Cancel or the retry's end). */
  async function submitPassword(replaceDeviceId?: string) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("login", "");
    let keepPassword = false;
    try {
      const submittedIdentifier = typedIdentifier();
      if (!submittedIdentifier) {
        setError("login", t("errMobile"));
        return;
      }
      const outcome = await enrolAndSignIn(manualServerAddress(server), submittedIdentifier, password, replaceDeviceId,
        (id) => void submitPassword(id), () => setPassword(""));
      keepPassword = outcome === "limit";
      if (outcome === "not_locked") setError("login", t("errGeneric"));
    } catch (caught) {
      // Field sign-in 2026-11-16: people typed their sign-in code here. A refused password with a code's shape
      // opens the code form with it. The password goes first: one set before generated passwords may look alike.
      if (caught instanceof ApiError && caught.code === "invalid_credentials" && looksLikeSignInCode(password)) {
        setSignInCode(formatSignInCode(password));
        setCodeFromPassword(true);
        setView("code");
        return;
      }
      setError("login", loginError(caught));
    } finally {
      if (!keepPassword) setPassword("");
      busyRef.current = false;
      setBusy(false);
    }
  }

  /** Redeem the code; nothing is stored, and the code is kept on a refusal so a typo can be fixed. */
  async function submitCode() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("redeem", "");
    try {
      const submittedIdentifier = typedIdentifier();
      if (!submittedIdentifier) {
        setError("redeem", t("errMobile"));
        return;
      }
      const serverAddress = manualServerAddress(server);
      const generated = await redeemSignInCode(serverAddress, submittedIdentifier, signInCode);
      setSignInCode("");
      setAcceptTerms(false);
      setCodeFromPassword(false);
      setAccepted({ server: serverAddress, identifier: submittedIdentifier, password: generated });
    } catch (caught) {
      setError("redeem", signInCodeErrorText(caught, loginError));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  /** "I have saved it": sign in with the generated password, exactly as the manual form does. */
  async function continueWithCode(replaceDeviceId?: string) {
    if (!accepted || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("accepted", "");
    try {
      const outcome = await enrolAndSignIn(accepted.server, accepted.identifier, accepted.password, replaceDeviceId,
        (id) => void continueWithCode(id), () => undefined);
      if (outcome === "signed_in") setAccepted(undefined);
      if (outcome === "not_locked") setError("accepted", t("errGeneric"));
    } catch (caught) {
      setError("accepted", loginError(caught));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  /** Validate a scanned or pasted QR; nothing is redeemed until the user confirms its server. */
  function review(raw: string) {
    if (busyRef.current) return;
    try {
      setPending(parseScannedQr(raw, __DEV__));
      setError("code", "");
    } catch (caught) {
      setError("code", caught instanceof EnrolmentError ? t(caught.key) : errorText(caught));
    }
  }

  async function submit(payload: ScannedQr, replaceDeviceId?: string) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("code", "");
    try {
      // Enrolling chooses the Active slot, so every store is saved and locked first (section 10.1).
      if (!(await lockNow())) {
        setPending(undefined);
        setError("code", t("errGeneric"));
        return;
      }
      const deviceName = Constants.deviceName ?? deviceFamilyLabel();
      if (payload.kind === "sign_in") {
        const enrolled = await redeemSignInQr(payload.server, payload.token, deviceName, APP_VERSION, replaceDeviceId);
        setPending(undefined);
        setLimit(undefined);
        await reload();
        afterSignIn(enrolled);
      } else {
        await enrolDevice(payload.server, payload.code, deviceName, APP_VERSION);
        await reload();
        goHome(router);
      }
    } catch (caught) {
      setPending(undefined);
      // The QR is not spent by a device_limit refusal: the retry redeems it again with the phone picked.
      const phones = payload.kind === "sign_in" ? deviceLimitPhones(caught) : undefined;
      setLimit(phones && { phones, retry: (id) => void submit(payload, id), cancel: () => undefined });
      if (phones) return;
      // One message for every refusal of a sign-in QR; the token and the server's detail are never shown or logged.
      // A 400 on a retry refuses the phone picked (signed out meanwhile), not the QR.
      const refused = payload.kind === "sign_in" && caught instanceof ApiError
        && (caught.status === 404 || (caught.status === 400 && replaceDeviceId === undefined));
      const limited = payload.kind === "sign_in" && caught instanceof ApiError && caught.status === 429;
      setError("code", refused ? t("errSignInQrInvalid") : limited ? t("errSignInQrRateLimited") : errorText(caught));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const styles2 = { section: { ...typography.caption, fontWeight: "600" as const, textTransform: "uppercase" as const, color: ui.mutedForeground, marginTop: spacing.xs, marginLeft: spacing.md } };
  const offerStandalone = slot !== "demo" && offlineEnginePlatform() && isPlusVariant();
  const tryDemo = () => void switchSlot?.("demo").catch((caught) => setError("demo", errorText(caught)));
  const cancel = <TextLink label={t("cancel")} disabled={busy} onPress={() => { setView("menu"); setError("code", ""); }} />;
  const working = busy ? <Text style={styles.muted}>{t("enrolWorking")}</Text> : null;

  // First install: ask the UI language before anything else; each name is shown in its own script.
  if (uiLocaleChosen === false) {
    return <FirstLanguage value={uiLocale} hintStyle={styles.muted} onChoose={(code) => void chooseUiLocale(code)} />;
  }

  if (limit) {
    return (
      <DeviceLimitChoice
        phones={limit.phones}
        busy={busy}
        onPick={limit.retry}
        onCancel={() => { limit.cancel(); setLimit(undefined); }}
      />
    );
  }

  // Home project (digitva-kspl): one grouped card of the projects, the welcome screen's own row vocabulary.
  if (choice) {
    return (
      <Screen title={t("chooseProject")}>
        <Text style={styles.muted}>{t("enrolChooseProjectHint")}</Text>
        <Card grouped>
          {choice.projects.map((project, index) => (
            <View key={project.project_id}>
              {index > 0 ? <Separator /> : null}
              <ListRow label={project.name} secondary={project.project_id} disabled={busy} onPress={() => void pickProject(project.project_id)} />
            </View>
          ))}
        </Card>
        {errorAt("code")}
        {working}
      </Screen>
    );
  }

  // Confirm server (design sheet 11): its own view, one primary action and a text Cancel, nothing else offered.
  if (pending) {
    return (
      <Screen title={t("enrolTitle")}>
        <View style={{ alignItems: "center", gap: spacing.xxs, paddingVertical: spacing.md }}>
          <View style={{ width: 56, height: 56, borderRadius: radius.full, backgroundColor: ui.primaryTint, alignItems: "center", justifyContent: "center" }}>
            <Icon name={icons.accepted} color={ui.primary} size={28} />
          </View>
          <Text accessibilityRole="header" style={[styles.headline, { textAlign: "center" }]}>{t("enrolCodeAccepted")}</Text>
          <Text style={[styles.muted, { textAlign: "center" }]}>{t("enrolCheckServer")}</Text>
        </View>
        <Card grouped>
          <ListRow label={t("enrolledServer")} value={new URL(pending.server).host} />
          {pending.kind === "enroll" ? (
            <>
              <Separator />
              <ListRow label={t("interviewProject")} value={pending.project} />
            </>
          ) : null}
        </Card>
        <Notice tone="warning">{pending.kind === "enroll" ? t("enrolConfirmHint") : t("enrolConfirmSignInHint")}</Notice>
        <Button label={t("enrolConfirm")} loading={busy} disabled={busy} onPress={() => void submit(pending)} />
        <TextLink label={t("cancel")} disabled={busy} onPress={() => setPending(undefined)} />
        {errorAt("code")}
      </Screen>
    );
  }

  if (view === "scan") {
    return (
      <Screen title={t("welcomeScanTitle")}>
        {permission?.granted ? (
          <View style={{ height: 240, borderRadius: radius.lg, overflow: "hidden" }}>
            <CameraView
              style={{ flex: 1 }}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
              onBarcodeScanned={({ data }) => review(data)}
            />
          </View>
        ) : (
          <Button label={t("enrolAllowCamera")} onPress={() => void requestPermission()} />
        )}
        {__DEV__ ? (
          <View style={{ gap: spacing.xs }}>
            <Text style={styles.muted}>{t("enrolPaste")}</Text>
            <TextInput
              accessibilityLabel={t("enrolPaste")}
              style={[styles.input, { minHeight: 80 }]}
              multiline
              autoCapitalize="none"
              autoCorrect={false}
              spellCheck={false}
              value={pasted}
              onChangeText={(value) => {
                setPasted(value);
                if (error?.at === "code") setError("code", "");
              }}
            />
            <Button kind="secondary" label={t("enrolSubmit")} disabled={busy || !pasted.trim()} onPress={() => review(pasted)} />
          </View>
        ) : null}
        {errorAt("code")}
        {cancel}
        {working}
      </Screen>
    );
  }

  // Server address and the Email/Mobile identifier: the manual form's and the code form's.
  const accountFields = (
    <>
      <Text style={styles.muted}>{t("enrolServerAddress")}</Text>
      <TextInput
        accessibilityLabel={t("enrolServerAddress")}
        style={styles.input}
        autoCapitalize="none"
        autoCorrect={false}
        spellCheck={false}
        keyboardType="url"
        editable={!busy}
        value={server}
        onChangeText={setServer}
      />
      <SegmentedControl
        accessibilityLabel={t("signInIdentifierType")}
        options={(["email", "mobile"] as const).map((option) => ({ value: option, label: t(option) }))}
        value={mode}
        disabled={busy}
        onChange={(option) => { setMode(option); setIdentifier(""); setErrorState(undefined); }}
      />
      <Text style={styles.muted}>{t(mode)}</Text>
      {mode === "mobile" ? (
        <View style={styles.phoneInputRow}>
          <Text style={styles.phonePrefix} accessibilityLabel={t("countryCodeIndia")}>+91</Text>
          <TextInput accessibilityLabel={t("mobile")} style={[styles.input, styles.phoneInput]} autoComplete="tel"
            keyboardType="phone-pad" maxLength={MOBILE_MAX_CHARS} editable={!busy} value={identifier}
            onChangeText={(value) => setIdentifier((previous) => nextMobileDigits(previous, value))} />
        </View>
      ) : (
        <TextInput accessibilityLabel={t("email")} style={styles.input} autoCapitalize="none" autoCorrect={false}
          autoComplete="username" editable={!busy} value={identifier} onChangeText={setIdentifier} />
      )}
    </>
  );
  const identifierReady = !!server.trim() && !!identifier.trim() && (mode !== "mobile" || !!normalizeMobileIdentifier(identifier));

  // Code accepted: the generated password once, then "I have saved it" signs in with it.
  if (accepted) {
    return (
      <CodeAccepted password={accepted.password} busy={busy} error={errorAt("accepted")} onContinue={() => void continueWithCode()}
        onCancel={() => { setAccepted(undefined); setView("menu"); setErrorState(undefined); }} />
    );
  }

  if (view === "code") {
    return (
      <SignInCodeForm fromPassword={codeFromPassword} identifierFields={accountFields} identifierReady={identifierReady}
        code={signInCode} onCodeChange={setSignInCode} acceptTerms={acceptTerms} onAcceptTermsChange={setAcceptTerms}
        busy={busy} error={errorAt("redeem")} onSubmit={() => void submitCode()} onCancel={() => {
          setView("menu"); setSignInCode(""); setAcceptTerms(false); setCodeFromPassword(false); setErrorState(undefined);
        }} />
    );
  }

  if (view === "manual") {
    return (
      <Screen title={t("welcomeManualTitle")}>
        {accountFields}
        <Text style={styles.muted}>{t("password")}</Text>
        <PasswordInput accessibilityLabel={t("password")} autoComplete="current-password" editable={!busy} value={password} onChangeText={setPassword} />
        <Button label={t("enrolManualSubmit")} loading={busy}
          disabled={busy || !identifierReady || !password}
          onPress={() => void submitPassword()} />
        {errorAt("login")}
        <TextLink label={t("cancel")} disabled={busy} onPress={() => { setView("menu"); setPassword(""); setError("login", ""); }} />
      </Screen>
    );
  }

  // Welcome (design sheet 11): one card of ways in, then the other ways; each row says what it is for in one line.
  return (
    <Screen title={t("enrolTitle")}>
      <Text style={styles.muted}>{t("welcomeTagline")}</Text>
      <Text accessibilityRole="header" style={styles2.section}>{t("welcomeGetStarted")}</Text>
      <Card grouped>
        <ListRow icon={icons.qr} label={t("welcomeScanTitle")} secondary={t("welcomeScanHint")} disabled={busy} onPress={() => setView("scan")} />
        {slot === "demo" ? null : (
          <>
            <Separator />
            <ListRow icon={icons.atSign} label={t("welcomeManualTitle")} secondary={t("welcomeManualHint")} disabled={busy} onPress={() => setView("manual")} />
            <Separator />
            <ListRow icon={icons.lock} label={t("redeemCode")} secondary={t("signInCodeHint")} disabled={busy}
              onPress={() => { setCodeFromPassword(false); setView("code"); }} />
          </>
        )}
      </Card>
      <Text accessibilityRole="header" style={styles2.section}>{t("welcomeOtherWays")}</Text>
      <Card grouped>
        {offerStandalone ? (
          <>
            <ListRow icon={icons.phoneOnly} label={t("welcomeStandaloneTitle")} secondary={t("welcomeStandaloneHint")}
              disabled={busy || standaloneAvailable !== true} onPress={() => router.push("/standalone-setup")} />
            <Separator />
          </>
        ) : null}
        <ListRow icon={icons.play} label={t("demoTryTitle")} secondary={t("welcomeDemoHint")} disabled={busy} onPress={tryDemo} />
      </Card>
      {offerStandalone && !standaloneAvailable ? <Notice tone="info">{t("standaloneLogoutRequired")}</Notice> : null}
      {errorAt("demo")}
      {working}
    </Screen>
  );
}
