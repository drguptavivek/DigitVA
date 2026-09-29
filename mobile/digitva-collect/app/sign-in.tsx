/** Interviewer sign-in on this device; the code field appears when the account has factors. */
import { useRouter } from "expo-router";
import { useState } from "react";
import { Text, TextInput } from "react-native";

import { ApiError } from "../src/api";
import { useAppState } from "../src/AppState";
import { forgetDevice, signIn } from "../src/auth";
import { t } from "../src/i18n";
import { Button, errorText, Screen, styles } from "../src/ui";

export default function SignIn() {
  const router = useRouter();
  const { reload } = useAppState();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needsOtp, setNeedsOtp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const account = await signIn(email.trim(), password, needsOtp ? otp.trim() : undefined);
      await reload();
      // Unlock sends an interviewer without a PIN yet to PIN setup.
      router.replace({ pathname: "/unlock", params: { userId: account.user_id } });
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
      <Text style={styles.muted}>{t("email")}</Text>
      <TextInput
        style={styles.input}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
      />
      <Text style={styles.muted}>{t("password")}</Text>
      <TextInput style={styles.input} secureTextEntry value={password} onChangeText={setPassword} />
      {needsOtp ? (
        <>
          <Text style={styles.muted}>{t("otp")}</Text>
          <TextInput
            style={styles.input}
            autoCapitalize="none"
            autoComplete="one-time-code"
            value={otp}
            onChangeText={setOtp}
          />
        </>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button label={t("signIn")} disabled={busy || !email.trim() || !password} onPress={() => void submit()} />
      <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
    </Screen>
  );
}
