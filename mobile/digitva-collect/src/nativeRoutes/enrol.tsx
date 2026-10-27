/**
 * Enrol: scan the one-time QR from the project's Devices page, validate its
 * server against the compiled rule (src/enrolment.ts), show that server's host
 * and wait for the user to confirm, then POST /enroll. A sign-in QR (docs/policy/mobile-sign-in.md section 8)
 * is taken the same way but redeems its token, which enrols the phone and signs the person in; they go
 * on to PIN setup. Pasting the JSON is a
 * debug-build convenience for the emulator. Both enrol the Active slot. "Try the demo" switches to the
 * Demo slot (src/AppState.tsx switchSlot), opening src/nativeRoutes/demo.tsx to enrol on the public demo
 * server without a code when the phone has no demo enrolment yet.
 */
import Constants from "expo-constants";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Platform, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { enrolDevice, redeemSignInQr } from "../auth";
import { EnrolmentError, parseScannedQr, type ScannedQr } from "../enrolment";
import { isPlusVariant } from "../appVariant";
import { t } from "../i18n";
import { Button, errorText, Screen, useUiStyles } from "../ui";

const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";

export default function Enrol() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload, switchSlot, lockNow, slot } = useAppState();
  const [permission, requestPermission] = useCameraPermissions();
  const [pasted, setPasted] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<ScannedQr>();
  const busyRef = useRef(false);

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
      <Text style={styles.text}>{t("enrolHint")}</Text>
      {pending ? (
        <View style={{ gap: 8 }}>
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
        </View>
      ) : permission?.granted ? (
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
      {__DEV__ && !pending ? (
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
      {pending ? null : (
        <View style={{ gap: 8 }}>
          <Text style={styles.muted}>{t("demoTryHint")}</Text>
          <Button kind="secondary" label={t("demoTryTitle")} disabled={busy} onPress={() => void switchSlot?.("demo").catch((caught) => setError(errorText(caught)))} />
        </View>
      )}
      {/* Standalone (Path C) accounts belong to Active only. */}
      {pending || slot === "demo" || Platform.OS !== "android" || !isPlusVariant() ? null : (
        <View style={{ gap: 8 }}>
          <Text style={styles.muted}>{t("standaloneWarning")}</Text>
          <Button kind="secondary" label={t("standaloneEntry")} disabled={busy} onPress={() => router.push("/standalone-setup")} />
        </View>
      )}
      {busy ? <Text style={styles.muted}>{t("enrolWorking")}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </Screen>
  );
}
