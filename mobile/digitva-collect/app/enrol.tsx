/**
 * Enrol: scan the one-time QR from the project's Devices page, validate it
 * against the compiled server allowlist, POST /enroll. Pasting the JSON is a
 * debug-build convenience for the emulator.
 */
import Constants from "expo-constants";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../src/AppState";
import { enrolDevice } from "../src/auth";
import { EnrolmentError, parseEnrolmentQr } from "../src/enrolment";
import { t } from "../src/i18n";
import { Button, errorText, Screen, styles } from "../src/ui";

const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";

export default function Enrol() {
  const router = useRouter();
  const { reload } = useAppState();
  const [permission, requestPermission] = useCameraPermissions();
  const [pasted, setPasted] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  async function submit(raw: string) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const payload = parseEnrolmentQr(raw, __DEV__);
      await enrolDevice(payload.server, payload.code, Constants.deviceName ?? "Android", APP_VERSION);
      await reload();
      router.replace("/");
    } catch (caught) {
      setError(caught instanceof EnrolmentError ? t(caught.key) : errorText(caught));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <Screen title={t("enrolTitle")}>
      <Text style={styles.text}>{t("enrolHint")}</Text>
      {permission?.granted ? (
        <View style={{ height: 280, borderRadius: 8, overflow: "hidden" }}>
          <CameraView
            style={{ flex: 1 }}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            onBarcodeScanned={busy ? undefined : ({ data }) => void submit(data)}
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
          <Button label={t("enrolSubmit")} disabled={busy || !pasted.trim()} onPress={() => void submit(pasted)} />
        </View>
      ) : null}
      {busy ? <Text style={styles.muted}>{t("enrolWorking")}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </Screen>
  );
}
