/** Interviewer sign-in on this device. */
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Linking, Text, View } from "react-native";

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
import { Button, errorText, FieldLabel, Notice, PasswordInput, Screen, SegmentedControl, TextField, TextLink, useUiStyles } from "../ui";
import { spacing } from "../theme";
import { displayProjectName } from "../projectName";

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
      {/* Which server project this signs into, under the title (design sheet 11). */}
      {device?.project_id ? <Text style={styles.muted}>{[device.project_id, displayProjectName(device.project_name)].filter(Boolean).join(" · ")}</Text> : null}
      {returning ? <Text style={styles.text}>{t("signInAgainAs", { name: returning.name })}</Text> : null}
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
            value={identifier}
            onChangeText={(value) => setIdentifier(mobileDigitsFromInput(value))}
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
      <FieldLabel label={t("password")} />
      <PasswordInput accessibilityLabel={t("password")} autoComplete="current-password" value={password} onChangeText={setPassword} />
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Button
        label={t("signIn")}
        loading={busy}
        disabled={busy || !identifier.trim() || !password || (!demo && mode === "mobile" && !normalizeMobileIdentifier(identifier))}
        onPress={() => void submit()}
      />
      {/* Secondary ways in are text links, so Sign in stays the one button on the screen. No Cancel: it only went
          back, and Back (or the back swipe) returns to the screen this came from. */}
      {demo ? null : (
        <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.lg, marginTop: spacing.sm }}>
          <TextLink label={t("redeemCode")} disabled={busy} onPress={() => void openServerPage(NATIVE_AUTH_PATHS.redeemCode)} />
          <TextLink label={t("forgotPassword")} disabled={busy} onPress={() => void openServerPage(NATIVE_AUTH_PATHS.forgotPassword)} />
        </View>
      )}
    </Screen>
  );
}
