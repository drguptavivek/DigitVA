/**
 * Try the demo (docs/policy/public-demo.md sections 2 and 10): create a demo
 * account, or use one, then enrol this phone on the demo server without a QR
 * code and sign in. The server is the compiled demo origin (src/demo.ts), kept
 * in the phone's Demo slot beside any live enrolment, and the Demo slot is
 * then the one in use (docs/policy/public-demo.md section 10.1); changing it
 * later is by re-enrolling. A refused call is shown and stops there: limits
 * are never retried on their own, and a failed security check gets a fresh
 * challenge only when the user presses the button again.
 */
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { ApiError } from "../api";
import { useAppState } from "../AppState";
import {
  demoErrorText,
  enrolAndSignInDemo,
  signUpDemoAccount,
  type DemoProgress,
} from "../demo";
import { normalizeUsername, validateSignUp } from "../demoRules";
import { t } from "../i18n";
import { PowCancelled } from "../pow";
import { Button, Screen, useUiStyles } from "../ui";

type Mode = "choose" | "create" | "existing";

/** The status line for a stage of the flow. */
export function progressText(progress: DemoProgress): string {
  switch (progress.stage) {
    case "challenge":
      return t("demoStageChallenge");
    case "solving":
      return t("demoStageSolving", { percent: Math.round((progress.fraction ?? 0) * 100) });
    case "signup":
      return t("demoStageSignup");
    case "enrol":
      return t("demoStageEnrol");
    case "signin":
      return t("demoStageSignin");
  }
}

export default function Demo() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload, lockNow } = useAppState();
  const [mode, setMode] = useState<Mode>("choose");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<DemoProgress>();
  // A demo limit is final for this attempt: nothing offers or runs a retry.
  const [limited, setLimited] = useState(false);
  const busyRef = useRef(false);
  const cancel = useRef({ aborted: false });
  // The account created by a previous press whose later step failed: pressing
  // again continues with enrolment instead of signing up a taken name.
  const createdRef = useRef<string | undefined>(undefined);
  useEffect(() => () => {
    cancel.current.aborted = true;
  }, []);

  const busy = progress !== undefined;
  const name = normalizeUsername(username);
  const canSubmit = !busy && !limited && !!name && !!password && (mode === "existing" || (!!confirm && accepted));

  function choose(next: Mode) {
    setMode(next);
    setError("");
    setLimited(false);
    setPassword("");
    setConfirm("");
    createdRef.current = undefined;
  }

  async function submit() {
    if (busyRef.current) return;
    if (mode === "create") {
      const problem = validateSignUp(username, password, confirm);
      if (problem) {
        setError(t(problem));
        return;
      }
      if (!accepted) return;
    }
    busyRef.current = true;
    setError("");
    setLimited(false);
    try {
      // Enrolling chooses the Demo slot, so every store is saved and locked first (section 10.1).
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      if (mode === "create" && createdRef.current !== name) {
        await signUpDemoAccount(name, password, { onProgress: setProgress, signal: cancel.current });
        createdRef.current = name;
      }
      const account = await enrolAndSignInDemo(name, password, setProgress);
      await reload();
      // Unlock sends a new account to PIN setup, as after a QR enrolment's sign-in.
      router.replace({ pathname: "/unlock", params: { userId: account.user_id, refresh: "1" } });
    } catch (caught) {
      if (caught instanceof PowCancelled) return;
      setLimited(caught instanceof ApiError && caught.code === "demo_limit");
      setError(demoErrorText(caught));
    } finally {
      busyRef.current = false;
      setProgress(undefined);
    }
  }

  return (
    <Screen title={t("demoTitle")}>
      <Text style={styles.text}>{t("demoIntro")}</Text>
      <View accessibilityRole="alert" style={styles.card}>
        <Text style={styles.text}>{t("demoNotice")}</Text>
      </View>
      {mode === "choose" ? (
        <View style={{ gap: 8 }}>
          <Button label={t("demoCreateAccount")} onPress={() => choose("create")} />
          <Button kind="secondary" label={t("demoHaveAccount")} onPress={() => choose("existing")} />
          <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
        </View>
      ) : (
        <View style={{ gap: 8 }}>
          <Text style={styles.muted}>{t("demoUsername")}</Text>
          <TextInput
            style={styles.input}
            accessibilityLabel={t("demoUsername")}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="username"
            editable={!busy}
            value={username}
            onChangeText={setUsername}
          />
          {mode === "create" ? <Text style={styles.muted}>{t("demoUsernameHint")}</Text> : null}
          <Text style={styles.muted}>{t("password")}</Text>
          <TextInput
            style={styles.input}
            accessibilityLabel={t("password")}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete={mode === "create" ? "new-password" : "current-password"}
            editable={!busy}
            value={password}
            onChangeText={setPassword}
          />
          {mode === "create" ? (
            <>
              <Text style={styles.muted}>{t("demoPasswordHint")}</Text>
              <Text style={styles.muted}>{t("demoConfirmPassword")}</Text>
              <TextInput
                style={styles.input}
                accessibilityLabel={t("demoConfirmPassword")}
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
                autoComplete="new-password"
                editable={!busy}
                value={confirm}
                onChangeText={setConfirm}
              />
              <Text style={styles.muted}>{t("demoNoReset")}</Text>
              <Pressable
                accessibilityRole="checkbox"
                accessibilityState={{ checked: accepted, disabled: busy }}
                disabled={busy}
                style={styles.card}
                onPress={() => setAccepted(!accepted)}
              >
                <Text style={styles.text}>{`${accepted ? "☑" : "☐"} ${t("demoAccept")}`}</Text>
              </Pressable>
            </>
          ) : null}
          {progress ? <Text style={styles.muted} accessibilityRole="progressbar">{progressText(progress)}</Text> : null}
          {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
          <Button
            label={error ? t("demoTryAgain") : t(mode === "create" ? "demoSubmitCreate" : "demoSubmitExisting")}
            loading={busy}
            disabled={!canSubmit}
            onPress={() => void submit()}
          />
          <Button kind="secondary" label={t("demoBack")} disabled={busy} onPress={() => choose("choose")} />
        </View>
      )}
    </Screen>
  );
}
