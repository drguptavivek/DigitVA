/** Interviewer sign-in on this device; the code field appears when the account has factors. */
import { useRouter } from "expo-router";
import { useState } from "react";
import { Linking, Text, TextInput, View } from "react-native";

import { ApiError } from "../api";
import { useAppState } from "../AppState";
import { forgetDevice, loadDevice, signIn } from "../auth";
import { t } from "../i18n";
import {
  mobileDigitsFromInput,
  nativeAuthUrl,
  NATIVE_AUTH_PATHS,
  normalizeMobileIdentifier
} from "../nativeAuthLinks";
import { Button, errorText, Row, Screen, useUiStyles } from "../ui";

export default function SignIn() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload } = useAppState();
  const [mode, setMode] = useState<"email" | "mobile">("email");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needsOtp, setNeedsOtp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function openServerPage(path: (typeof NATIVE_AUTH_PATHS)[keyof typeof NATIVE_AUTH_PATHS]) {
    try {
      const device = await loadDevice();
      if (!device) throw new Error("not_enrolled");
      await Linking.openURL(nativeAuthUrl(device.server, path, __DEV__));
    } catch (caught) {
      setError(caught instanceof Error && caught.message === "server_not_allowed" ? t("errServerNotAllowed") : t("errNetwork"));
    }
  }

  async function submit() {
    const submittedIdentifier = mode === "mobile" ? normalizeMobileIdentifier(identifier) : identifier.trim();
    if (!submittedIdentifier) {
      setError(t("errMobile"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const account = await signIn(submittedIdentifier, password, needsOtp ? otp.trim() : undefined);
      await reload();
      // Unlock sends an interviewer without a PIN yet to PIN setup.
      router.replace({ pathname: "/unlock", params: { userId: account.user_id, refresh: "1" } });
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "second_factor_required") setNeedsOtp(true);
      if (caught instanceof ApiError && caught.code === "device_revoked") {
        await forgetDevice();
        await reload();
      }
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title={t("signInTitle")}>
      <Text style={styles.muted}>{t("signInIdentifierType")}</Text>
      <Row>
        <Button
          kind={mode === "email" ? "primary" : "secondary"}
          label={t("email")}
          accessibilityLabel={t("email")}
          onPress={() => {
            setMode("email");
            setIdentifier("");
            setError("");
          }}
        />
        <Button
          kind={mode === "mobile" ? "primary" : "secondary"}
          label={t("mobile")}
          accessibilityLabel={t("mobile")}
          onPress={() => {
            setMode("mobile");
            setIdentifier("");
            setError("");
          }}
        />
      </Row>
      <Text style={styles.muted}>{mode === "mobile" ? t("mobile") : t("email")}</Text>
      {mode === "mobile" ? (
        <View style={styles.phoneInputRow}>
          <Text style={styles.phonePrefix} accessibilityLabel={t("countryCodeIndia")}>
            +91
          </Text>
          <TextInput
            style={[styles.input, styles.phoneInput]}
            accessibilityLabel={t("mobile")}
            autoCapitalize="none"
            autoComplete="tel"
            keyboardType="phone-pad"
            value={identifier}
            onChangeText={(value) => setIdentifier(mobileDigitsFromInput(value))}
          />
        </View>
      ) : (
        <TextInput
          style={styles.input}
          accessibilityLabel={t("email")}
          autoCapitalize="none"
          autoComplete="username"
          keyboardType="default"
          value={identifier}
          onChangeText={setIdentifier}
        />
      )}
      <Text style={styles.muted}>{t("password")}</Text>
      <TextInput accessibilityLabel={t("password")} style={styles.input} secureTextEntry value={password} onChangeText={setPassword} />
      {needsOtp ? (
        <>
          <Text style={styles.muted}>{t("otp")}</Text>
          <TextInput
            style={styles.input}
            accessibilityLabel={t("otp")}
            autoCapitalize="none"
            autoComplete="one-time-code"
            value={otp}
            onChangeText={setOtp}
          />
        </>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button
        label={t("signIn")}
        loading={busy}
        disabled={busy || !identifier.trim() || !password || (mode === "mobile" && !normalizeMobileIdentifier(identifier))}
        onPress={() => void submit()}
      />
      <View style={styles.authLinks}>
        <Button
          kind="secondary"
          label={t("redeemCode")}
          disabled={busy}
          onPress={() => void openServerPage(NATIVE_AUTH_PATHS.redeemCode)}
        />
        <Button
          kind="secondary"
          label={t("forgotPassword")}
          disabled={busy}
          onPress={() => void openServerPage(NATIVE_AUTH_PATHS.forgotPassword)}
        />
      </View>
      <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
    </Screen>
  );
}
