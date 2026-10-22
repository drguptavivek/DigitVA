/**
 * Enrol: scan the one-time QR from the project's Devices page, validate its
 * server against the compiled rule (src/enrolment.ts), show that server's host
 * and wait for the user to confirm, then POST /enroll. Pasting the JSON is a
 * debug-build convenience for the emulator. "Try the demo" (src/nativeRoutes/demo.tsx)
 * enrols on the public demo server without a code.
 */
import Constants from "expo-constants";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { enrolDevice } from "../auth";
import { EnrolmentError, parseEnrolmentQr, type EnrolmentPayload } from "../enrolment";
import { t } from "../i18n";
import { Button, errorText, Screen, useUiStyles } from "../ui";

const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";

export default function Enrol() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload } = useAppState();
  const [permission, requestPermission] = useCameraPermissions();
  const [pasted, setPasted] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<EnrolmentPayload>();
  const busyRef = useRef(false);

  /** Validate a scanned or pasted QR; nothing is redeemed until the user confirms its server. */
  function review(raw: string) {
    if (busyRef.current) return;
    try {
      setPending(parseEnrolmentQr(raw, __DEV__));
      setError("");
    } catch (caught) {
      setError(caught instanceof EnrolmentError ? t(caught.key) : errorText(caught));
    }
  }

  async function submit(payload: EnrolmentPayload) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await enrolDevice(payload.server, payload.code, Constants.deviceName ?? "Android", APP_VERSION);
      await reload();
      router.replace("/");
    } catch (caught) {
      setPending(undefined);
      setError(errorText(caught));
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
          <Text style={styles.text}>{t("enrolConfirmProject", { project: pending.project })}</Text>
          <Text style={styles.muted}>{t("enrolConfirmHint")}</Text>
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
          <Button kind="secondary" label={t("demoTryTitle")} disabled={busy} onPress={() => router.push("/demo")} />
        </View>
      )}
      {busy ? <Text style={styles.muted}>{t("enrolWorking")}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </Screen>
  );
}
