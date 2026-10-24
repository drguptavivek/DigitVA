/**
 * Collect Plus only: the hidden "Offline engine check" (Settings, or `digitvacollectplus://engine-check?run=1`).
 * Runs the offline ICD-11 engine's init, search, codeinfo, DORIS and CoDEdit once and shows each step's timings; the
 * profiling run drives it and samples `dumpsys meminfo` before and after. "Update WHO files" (or `?update=1`) runs
 * the explicit WHO-file update (offlineEngine.updateWhoFiles) and shows its result.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { isPlusVariant } from "../appVariant";
import { offlineEngine } from "../offlineEngine";
import { describeProgress, describeUpdate, runEngineCheck, type CheckStep } from "../offlineEngineCheck";
import { Button, Screen, useUiStyles } from "../ui";

export default function EngineCheck() {
  const router = useRouter();
  const styles = useUiStyles();
  const { run, update } = useLocalSearchParams<{ run?: string; update?: string }>();
  const [steps, setSteps] = useState<CheckStep[]>([]);
  const [running, setRunning] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [updateResult, setUpdateResult] = useState("");
  const [progress, setProgress] = useState("");
  const started = useRef(false);
  const updateStarted = useRef(false);

  const start = useCallback(async () => {
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
  }, []);

  // Timings and short codes only: no certificate or engine payload.
  const startUpdate = useCallback(async () => {
    setUpdating(true);
    setUpdateResult("");
    const engine = offlineEngine();
    const unsubscribe = engine.onProgress((event) => {
      const line = describeProgress(event);
      setProgress(line);
      console.log(`ICD11CHECK progress ${line}`);
    });
    try {
      const result = await engine.updateWhoFiles();
      const line = describeUpdate(result);
      setUpdateResult(line);
      console.log(`ICD11CHECK update ok=${result.ok} note=${line} ms=${result.ms.toFixed(1)}`);
    } finally {
      unsubscribe();
      setProgress("");
      setUpdating(false);
    }
  }, []);

  useEffect(() => {
    if (run === "1" && !started.current && isPlusVariant()) {
      started.current = true;
      void start();
    }
  }, [run, start]);

  useEffect(() => {
    if (update === "1" && !updateStarted.current && isPlusVariant()) {
      updateStarted.current = true;
      void startUpdate();
    }
  }, [update, startUpdate]);

  if (!isPlusVariant()) return <Redirect href="/" />;
  return (
    <Screen title="Offline engine check">
      <Text style={styles.muted}>
        Experimental. Runs the on-phone ICD-11 / DORIS engine once. The first run copies and indexes the data (slow).
      </Text>
      <Button label="Run engine check" loading={running} disabled={running || updating} onPress={() => void start()} />
      <Button kind="secondary" label="Update WHO files" loading={updating} disabled={running || updating} onPress={() => void startUpdate()} />
      <Text style={styles.muted}>Fetches the WHO files when online; offline it keeps the current files. Coding waits for it.</Text>
      {updateResult ? <Text style={styles.text} testID="engine-update-result">{updateResult}</Text> : null}
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
      <Button kind="secondary" label="Back" onPress={() => router.back()} />
    </Screen>
  );
}
