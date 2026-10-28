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
import { Platform, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { enrolDevice, passwordEnrolAndSignIn, redeemSignInQr } from "../auth";
import { EnrolmentError, parseScannedQr, type ScannedQr } from "../enrolment";
import { isPlusVariant } from "../appVariant";
import { t } from "../i18n";
import { mobileDigitsFromInput, normalizeMobileIdentifier } from "../nativeAuthLinks";
import { Button, errorText, Screen, useUiStyles } from "../ui";

const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";

export default function Enrol() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload, switchSlot, lockNow, slot, standaloneAvailable } = useAppState();
  const [permission, requestPermission] = useCameraPermissions();
  const [pasted, setPasted] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<ScannedQr>();
  const [showServerSetup, setShowServerSetup] = useState(false);
  const [server, setServer] = useState("");
  const [mode, setMode] = useState<"email" | "mobile">("email");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const busyRef = useRef(false);
  useEffect(() => () => setPassword(""), []);

  /** Lock local work before enrolling; credentials stay in this form only and are cleared after every attempt. */
  async function submitPassword() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const submittedIdentifier = mode === "mobile" ? normalizeMobileIdentifier(identifier) : identifier.trim();
      if (!submittedIdentifier) {
        setError(t("errMobile"));
        return;
      }
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      const account = await passwordEnrolAndSignIn(server, submittedIdentifier, password, Constants.deviceName ?? "Android", APP_VERSION);
      await reload();
      router.replace({ pathname: "/unlock", params: { userId: account.user_id, refresh: "1" } });
    } catch (caught) {
      setError(caught instanceof EnrolmentError ? t(caught.key)
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
      setError("");
    } catch (caught) {
      setError(caught instanceof EnrolmentError ? t(caught.key) : errorText(caught));
    }
  }

  async function submit(payload: ScannedQr) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      // Enrolling chooses the Active slot, so every store is saved and locked first (section 10.1).
      if (!(await lockNow())) {
        setPending(undefined);
        setError(t("errGeneric"));
        return;
      }
      const deviceName = Constants.deviceName ?? "Android";
      if (payload.kind === "sign_in") {
        const account = await redeemSignInQr(payload.server, payload.token, deviceName, APP_VERSION);
        await reload();
        // Unlock sends a person without a PIN yet to PIN setup (then the unlock-options offer).
        router.replace({ pathname: "/unlock", params: { userId: account.user_id, refresh: "1" } });
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
      setError(refused ? t("errSignInQrInvalid") : limited ? t("errSignInQrRateLimited") : errorText(caught));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <Screen title={t("enrolTitle")}>
      <Text accessibilityRole="header" style={styles.headline}>{t("enrolServerTitle")}</Text>
      <Text style={styles.text}>{t("enrolServerHint")}</Text>
      <Button label={t("enrolTitle")} disabled={busy} onPress={() => setShowServerSetup(true)} />
      {pending || slot === "demo" || Platform.OS !== "android" || !isPlusVariant() ? null : (
        <View style={{ gap: 8 }}>
          <Text accessibilityRole="header" style={styles.headline}>{t("enrolStandaloneTitle")}</Text>
          <Text style={styles.muted}>{t("enrolStandaloneHint")}</Text>
          {!standaloneAvailable ? <Text style={styles.muted}>{t("standaloneLogoutRequired")}</Text> : null}
          <Button kind="secondary" label={t("standaloneEntry")} disabled={busy || standaloneAvailable !== true} onPress={() => router.push("/standalone-setup")} />
        </View>
      )}
      {pending ? null : (
        <View style={{ gap: 8 }}>
          <Text accessibilityRole="header" style={styles.headline}>{t("enrolDemoTitle")}</Text>
          <Text style={styles.muted}>{t("enrolDemoHint")}</Text>
          <Text style={styles.muted}>{t("demoTryHint")}</Text>
          <Button kind="secondary" label={t("demoTryTitle")} disabled={busy} onPress={() => void switchSlot?.("demo").catch((caught) => setError(errorText(caught)))} />
        </View>
      )}
      {showServerSetup ? (
        <View style={{ gap: 8 }}>
          {pending ? (
            <>
              <Text style={[styles.text, { fontSize: 20, fontWeight: "700" }]} selectable>
                {t("enrolConfirmServer", { host: new URL(pending.server).host })}
              </Text>
              {pending.kind === "enroll" ? (
                <>
                  <Text style={styles.text}>{t("enrolConfirmProject", { project: pending.project })}</Text>
                  <Text style={styles.muted}>{t("enrolConfirmHint")}</Text>
                </>
              ) : (
                <Text style={styles.muted}>{t("enrolConfirmSignInHint")}</Text>
              )}
              <Button label={t("enrolConfirm")} loading={busy} disabled={busy} onPress={() => void submit(pending)} />
              <Button kind="secondary" label={t("cancel")} disabled={busy} onPress={() => setPending(undefined)} />
            </>
          ) : (
            <>
              {permission?.granted ? (
                <View style={{ height: 280, borderRadius: 8, overflow: "hidden" }}>
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
                <View style={{ gap: 8 }}>
                  <Text style={styles.muted}>{t("enrolPaste")}</Text>
                  <TextInput
                    style={[styles.input, { minHeight: 80 }]}
                    multiline
                    autoCapitalize="none"
                    autoCorrect={false}
                    value={pasted}
                    onChangeText={setPasted}
                  />
                  <Button label={t("enrolSubmit")} disabled={busy || !pasted.trim()} onPress={() => review(pasted)} />
                </View>
              ) : null}
              {slot === "demo" ? null : (
                <View style={{ gap: 8 }}>
                  <Text accessibilityRole="header" style={styles.headline}>{t("enrolManualTitle")}</Text>
                  <Text style={styles.muted}>{t("enrolServerAddress")}</Text>
                  <TextInput
                    accessibilityLabel={t("enrolServerAddress")}
                    style={styles.input}
                    autoCapitalize="none"
                    autoCorrect={false}
                    keyboardType="url"
                    editable={!busy}
                    value={server}
                    onChangeText={setServer}
                  />
                  <Text style={styles.muted}>{t("signInIdentifierType")}</Text>
                  <View style={styles.row}>
                    {(["email", "mobile"] as const).map((option) => (
                      <Button key={option} kind={mode === option ? "primary" : "secondary"} label={t(option)} disabled={busy}
                        onPress={() => { setMode(option); setIdentifier(""); setError(""); }} />
                    ))}
                  </View>
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
                  <TextInput accessibilityLabel={t("password")} style={styles.input} secureTextEntry autoCapitalize="none"
                    autoCorrect={false} editable={!busy} value={password} onChangeText={setPassword} />
                  <Button label={t("enrolManualSubmit")} loading={busy}
                    disabled={busy || !server.trim() || !identifier.trim() || !password || (mode === "mobile" && !normalizeMobileIdentifier(identifier))}
                    onPress={() => void submitPassword()} />
                </View>
              )}
              <Button kind="secondary" label={t("cancel")} disabled={busy} onPress={() => setShowServerSetup(false)} />
            </>
          )}
        </View>
      ) : null}
      {busy ? <Text style={styles.muted}>{t("enrolWorking")}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </Screen>
  );
}
