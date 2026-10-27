/** Interviewer sign-in on this device. */
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Linking, Text, TextInput, View } from "react-native";

import { ApiError } from "../api";
import { useAppState } from "../AppState";
import { forgetDevice, loadActiveSlot, loadDevice, signIn, type Slot } from "../auth";
import { normalizeUsername } from "../demoRules";
import { isDemoServer } from "../enrolment";
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
  // "Sign in again" names the account it came from; signIn never wipes a store.
  const { userId } = useLocalSearchParams<{ userId?: string }>();
  const { reload, accounts, device, lockNow } = useAppState();
  // The public demo signs in by username and has no code or password-reset links.
  const demo = isDemoServer(device?.server, __DEV__, process.env.EXPO_PUBLIC_DEMO_SERVER);
  const returning = accounts.find((account) => account.user_id === userId);
  const [mode, setMode] = useState<"email" | "mobile">("email");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
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
    const submittedIdentifier = demo
      ? normalizeUsername(identifier)
      : mode === "mobile" ? normalizeMobileIdentifier(identifier) : identifier.trim();
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
      const account = await signIn(submittedIdentifier, password, slot);
      await reload();
      // Unlock sends an interviewer without a PIN yet to PIN setup.
      router.replace({ pathname: "/unlock", params: { userId: account.user_id, refresh: "1" } });
    } catch (caught) {
      // Forgetting the Demo device hands the phone back to Active, a slot change: lock first, or keep it.
      if (caught instanceof ApiError && caught.code === "device_revoked" && slot !== undefined
        && (slot === "active" || await lockNow())) {
        await forgetDevice(slot);
        await reload();
      }
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title={t("signInTitle")}>
      {returning ? <Text style={styles.text}>{t("signInAgainAs", { name: returning.name })}</Text> : null}
      {demo ? null : <Text style={styles.muted}>{t("signInIdentifierType")}</Text>}
      {demo ? null : <Row>
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
      </Row>}
      <Text style={styles.muted}>{demo ? t("demoSignInUsername") : mode === "mobile" ? t("mobile") : t("email")}</Text>
      {demo ? (
        <TextInput
          style={styles.input}
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
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button
        label={t("signIn")}
        loading={busy}
        disabled={busy || !identifier.trim() || !password || (!demo && mode === "mobile" && !normalizeMobileIdentifier(identifier))}
        onPress={() => void submit()}
      />
      {demo ? null : <View style={styles.authLinks}>
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
      </View>}
      <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
    </Screen>
  );
}
