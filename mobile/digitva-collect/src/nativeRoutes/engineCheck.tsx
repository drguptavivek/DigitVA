/**
 * Collect Plus only: the hidden "Offline engine check" (Settings, or `digitvacollectplus://engine-check?run=1`).
 * Runs the offline ICD-11 engine's init, search, codeinfo, DORIS and CoDEdit once and shows each step's timings; the
 * profiling run drives it and samples `dumpsys meminfo` before and after.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { isPlusVariant } from "../appVariant";
import { canUseOfflineCoding } from "../codingCapabilities";
import { offlineEngine } from "../offlineEngine";
import { describeProgress, runEngineCheck, type CheckStep } from "../offlineEngineCheck";
import { isIcd11DorisEnabled, useIcd11DorisPreference } from "../icd11DorisPreference";
import { t } from "../i18n";
import { offlineSmartvaEngine } from "../smartva/nativeEngine";
import { engineCheckAutoRun, runSmartVaEngineCheck, type SmartVaEngineCheckResult } from "../smartva/engineCheck";
import { Button, Screen, useUiStyles } from "../ui";

export default function EngineCheck() {
  const router = useRouter();
  const styles = useUiStyles();
  const { run, smartva, userId } = useLocalSearchParams<{ run?: string; smartva?: string; userId?: string | string[] }>();
  const appState = useAppState();
  const requestedUserId = Array.isArray(userId) ? userId[0] : userId;
  const account = requestedUserId
    ? appState.accounts.find((item) => item.user_id === requestedUserId)
    : appState.accounts.length === 1 ? appState.accounts[0] : undefined;
  const accountAllowed = !!account && canUseOfflineCoding(account);
  const preference = useIcd11DorisPreference();
  const [enabledOnEntry, setEnabledOnEntry] = useState<boolean | undefined>(undefined);
  const [steps, setSteps] = useState<CheckStep[]>([]);
  const [running, setRunning] = useState(false);
  const [smartvaRunning, setSmartvaRunning] = useState(false);
  const [smartvaResult, setSmartvaResult] = useState<SmartVaEngineCheckResult>();
  const [progress, setProgress] = useState("");
  const started = useRef(false);
  const smartvaStarted = useRef(false);

  useEffect(() => {
    if (enabledOnEntry === undefined && preference.ready) setEnabledOnEntry(preference.enabled);
  }, [enabledOnEntry, preference.enabled, preference.ready]);

  const start = useCallback(async () => {
    if (!accountAllowed || !await isIcd11DorisEnabled()) return;
    setRunning(true);
    setSteps([]);
    const engine = offlineEngine();
    const unsubscribe = engine.onProgress((event) => {
      const line = describeProgress(event);
      setProgress(line);
      console.log(`ICD11CHECK progress ${line}`);
    });
    try {
      await runEngineCheck(engine, (step) => {
        setSteps((previous) => [...previous, step]);
        // Timings and short codes only: no certificate or engine payload.
        console.log(`ICD11CHECK ${step.name} ok=${step.ok} note=${step.note} ms=${step.ms.toFixed(1)}${step.nativeMs === undefined ? "" : ` nativeMs=${step.nativeMs.toFixed(1)}`}`);
      });
    } finally {
      unsubscribe();
      setProgress("");
      setRunning(false);
    }
  }, [accountAllowed]);

  const startSmartva = useCallback(async () => {
    if (!accountAllowed || !await isIcd11DorisEnabled()) return;
    setSmartvaRunning(true);
    setSmartvaResult(undefined);
    try {
      const result = await runSmartVaEngineCheck(offlineSmartvaEngine(), setSmartvaResult);
      setSmartvaResult(result);
    } finally {
      setSmartvaRunning(false);
    }
  }, [accountAllowed]);

  useEffect(() => {
    const mayRun = appState.ready && accountAllowed && isPlusVariant()
      && enabledOnEntry === true && preference.enabled;
    const autoRun = engineCheckAutoRun(run, smartva);
    if (autoRun === "smartva") {
      if (!smartvaStarted.current && mayRun) {
        smartvaStarted.current = true;
        void startSmartva();
      }
      return;
    }
    if (autoRun === "icd11" && !started.current && mayRun) {
      started.current = true;
      void start();
    }
  }, [accountAllowed, appState.ready, enabledOnEntry, preference.enabled, run, smartva, start, startSmartva]);

  if (!isPlusVariant()) return <Redirect href="/" />;
  if (!appState.ready) return <Screen title="Offline engine check"><Text style={styles.muted}>Checking account access…</Text></Screen>;
  if (!accountAllowed) return <Screen title="Offline engine check">
    <Text accessibilityRole="alert" style={styles.text}>This account does not have offline coding access.</Text>
    <Button label="Settings" onPress={() => router.push({ pathname: "/settings", params: { userId: account?.user_id ?? requestedUserId } })} />
    <Button kind="secondary" label="Back" onPress={() => router.back()} />
  </Screen>;
  if (!preference.enabled) return <Screen title={t("icd11DorisDisabledTitle")}>
    <Text accessibilityRole="alert" style={styles.text}>{t("icd11DorisDisabledBody")}</Text>
    <Button label={t("icd11DorisOpenSettings")} onPress={() => router.push({ pathname: "/settings", params: { userId: account?.user_id ?? requestedUserId } })} />
    <Button kind="secondary" label={t("icd11DorisGoBack")} onPress={() => router.back()} />
  </Screen>;
  return (
    <Screen title="Offline engine check">
      <Text style={styles.muted}>
        Experimental. Runs the on-phone ICD-11 / DORIS engine once. The first run copies and indexes the data (slow).
      </Text>
      <Button label="Run engine check" loading={running} disabled={running || smartvaRunning} onPress={() => void start()} />
      <Button kind="secondary" label="Run SmartVA check" loading={smartvaRunning} disabled={running || smartvaRunning} onPress={() => void startSmartva()} />
      <Text style={styles.muted}>WHO ICD-11 and DORIS data are included with app updates.</Text>
      {progress ? <Text style={styles.muted} testID="engine-progress">{`Starting the engine: ${progress}`}</Text> : null}
      {steps.map((step) => (
        <View key={step.name} style={styles.card} testID={`engine-step-${step.name}`}>
          <Text accessibilityRole="header" style={styles.headline}>{`${step.name}: ${step.ok ? "ok" : "FAILED"}`}</Text>
          <Text style={styles.text}>
            {`${step.ms.toFixed(1)} ms${step.nativeMs === undefined ? "" : ` (engine ${step.nativeMs.toFixed(1)} ms)`}`}
          </Text>
          <Text style={styles.muted}>{step.note}</Text>
        </View>
      ))}
      {smartvaRunning && !smartvaResult ? <Text style={styles.muted}>Scoring synthetic adult, child, and neonate cases…</Text> : null}
      {smartvaResult ? (
        <View style={styles.card} testID="smartva-engine-check">
          <Text accessibilityRole="header" style={styles.headline}>{`SmartVA check: ${smartvaResult.ok ? "passed" : "FAILED"}`}</Text>
          {smartvaResult.version ? <Text style={styles.muted}>{smartvaResult.version}</Text> : null}
          <Text style={styles.text}>{`Process init: ${smartvaResult.initMs.toFixed(0)} ms`}</Text>
          {smartvaResult.error ? <Text style={styles.muted}>{`Code: ${smartvaResult.error}`}</Text> : null}
          {smartvaResult.cases.map((item) => (
            <Text key={item.id} style={styles.text}>
              {`${item.id}: ${item.ok && item.matched ? "ok" : "FAILED"} · ${item.ms.toFixed(0)} ms${item.nativeMs === undefined ? "" : ` (engine ${item.nativeMs.toFixed(0)} ms)`}${item.module ? ` · ${item.module}` : ""}${item.cause34 ? ` · ${item.cause34}` : ""}${item.icd10 ? ` · ICD-10 ${item.icd10}` : ""}${item.topIcd10?.some(Boolean) ? ` · top ${item.topIcd10.filter(Boolean).join(", ")}` : ""}${item.error ? ` · ${item.error}` : ""}`}
            </Text>
          ))}
          {smartvaResult.warmRepeat ? <Text style={styles.text}>{`adult warm repeat: ${smartvaResult.warmRepeat.ok && smartvaResult.warmRepeat.matched ? "ok" : "FAILED"} · ${smartvaResult.warmRepeat.ms.toFixed(0)} ms${smartvaResult.warmRepeat.nativeMs === undefined ? "" : ` (engine ${smartvaResult.warmRepeat.nativeMs.toFixed(0)} ms)`}`}</Text> : null}
        </View>
      ) : null}
      <Button kind="secondary" label="Back" onPress={() => router.back()} />
    </Screen>
  );
}
