/**
 * Enrol: scan the one-time QR from the project's Devices page, validate its
 * server against the compiled rule (src/enrolment.ts), show that server's host
 * and wait for the user to confirm, then POST /enroll. A sign-in QR (docs/policy/mobile-sign-in.md section 8)
 * is taken the same way but redeems its token, which enrols the phone and signs the person in; they go
 * on to PIN setup. Pasting the JSON is a
 * debug-build convenience for the emulator. Both enrol the Active slot. "Try the demo" switches to the
 * Demo slot (src/AppState.tsx switchSlot), opening src/nativeRoutes/demo.tsx to enrol on the public demo
 * server without a code when the phone has no demo enrolment yet. Manual server
 * and password enrolment opens the same Active account and unlock journey as a sign-in QR.
 */
import Constants from "expo-constants";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { enrolDevice, passwordEnrolAndSignIn, redeemSignInQr, setDeviceHomeProject, type EnrolledAccount } from "../auth";
import { EnrolmentError, parseScannedQr, type ScannedQr } from "../enrolment";
import { isPlusVariant } from "../appVariant";
import { deviceFamilyLabel, offlineEnginePlatform } from "../platformFamily";
import { t } from "../i18n";
import { mobileDigitsFromInput, normalizeMobileIdentifier } from "../nativeAuthLinks";
import { Icon, icons } from "../Icon";
import { radius, spacing, useTheme } from "../theme";
import { Button, Card, errorText, ListRow, Notice, PasswordInput, Screen, SegmentedControl, Separator, TextLink, useUiStyles } from "../ui";

const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";

export default function Enrol() {
  const styles = useUiStyles();
  const { ui, typography } = useTheme();
  const router = useRouter();
  const { reload, switchSlot, lockNow, slot, standaloneAvailable } = useAppState();
  const [permission, requestPermission] = useCameraPermissions();
  const [pasted, setPasted] = useState("");
  /** Each error shows next to the action that produced it: the code (scan, paste, confirm), the login form or the demo button. */
  const [error, setErrorState] = useState<{ at: "code" | "login" | "demo"; text: string }>();
  const setError = (at: "code" | "login" | "demo", text: string) => setErrorState(text ? { at, text } : undefined);
  const errorAt = (at: "code" | "login" | "demo") =>
    error?.at === at ? <Notice tone="error">{error.text}</Notice> : null;
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<ScannedQr>();
  /** Welcome menu, QR scanner or the server-and-password form; a scanned code shows Confirm server over any of them. */
  const [view, setView] = useState<"menu" | "scan" | "manual">("menu");
  const [server, setServer] = useState("");
  const [mode, setMode] = useState<"email" | "mobile">("email");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const busyRef = useRef(false);
  /** Signed in with more than one eligible project: the owner's rule is to ask, never pick silently (mobile-sign-in.md). */
  const [choice, setChoice] = useState<EnrolledAccount>();
  useEffect(() => () => setPassword(""), []);

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

  /** Lock local work before enrolling; credentials stay in this form only and are cleared after every attempt. */
  async function submitPassword() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("login", "");
    try {
      const submittedIdentifier = mode === "mobile" ? normalizeMobileIdentifier(identifier) : identifier.trim();
      if (!submittedIdentifier) {
        setError("login", t("errMobile"));
        return;
      }
      if (!(await lockNow())) {
        setError("login", t("errGeneric"));
        return;
      }
      const enrolled = await passwordEnrolAndSignIn(server, submittedIdentifier, password, Constants.deviceName ?? deviceFamilyLabel(), APP_VERSION);
      await reload();
      afterSignIn(enrolled);
    } catch (caught) {
      setError("login", caught instanceof EnrolmentError ? t(caught.key)
        : caught instanceof ApiError && caught.status === 404 ? t("errPasswordEnrolUnsupported") : errorText(caught));
    } finally {
      setPassword("");
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

  async function submit(payload: ScannedQr) {
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
        const enrolled = await redeemSignInQr(payload.server, payload.token, deviceName, APP_VERSION);
        setPending(undefined);
        await reload();
        afterSignIn(enrolled);
      } else {
        await enrolDevice(payload.server, payload.code, deviceName, APP_VERSION);
        await reload();
        router.replace("/");
      }
    } catch (caught) {
      setPending(undefined);
      // One message for every refusal of a sign-in QR; the token and the server's detail are never shown or logged.
      const refused = payload.kind === "sign_in" && caught instanceof ApiError && (caught.status === 404 || caught.status === 400);
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

  if (view === "manual") {
    return (
      <Screen title={t("welcomeManualTitle")}>
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
          onChange={(option) => { setMode(option); setIdentifier(""); setError("login", ""); }}
        />
        <Text style={styles.muted}>{t(mode)}</Text>
        {mode === "mobile" ? (
          <View style={styles.phoneInputRow}>
            <Text style={styles.phonePrefix} accessibilityLabel={t("countryCodeIndia")}>+91</Text>
            <TextInput accessibilityLabel={t("mobile")} style={[styles.input, styles.phoneInput]} autoComplete="tel"
              keyboardType="phone-pad" editable={!busy} value={identifier}
              onChangeText={(value) => setIdentifier(mobileDigitsFromInput(value))} />
          </View>
        ) : (
          <TextInput accessibilityLabel={t("email")} style={styles.input} autoCapitalize="none" autoCorrect={false}
            autoComplete="username" editable={!busy} value={identifier} onChangeText={setIdentifier} />
        )}
        <Text style={styles.muted}>{t("password")}</Text>
        <PasswordInput accessibilityLabel={t("password")} autoComplete="current-password" editable={!busy} value={password} onChangeText={setPassword} />
        <Button label={t("enrolManualSubmit")} loading={busy}
          disabled={busy || !server.trim() || !identifier.trim() || !password || (mode === "mobile" && !normalizeMobileIdentifier(identifier))}
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
