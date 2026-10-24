/**
 * Collect Plus only: the hidden "Offline engine check" (Settings, or `digitvacollectplus://engine-check?run=1`).
 * Runs the offline ICD-11 engine's init, search, codeinfo, DORIS and CoDEdit once and shows each step's timings; the
 * profiling run drives it and samples `dumpsys meminfo` before and after.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { isPlusVariant } from "../appVariant";
import { offlineEngine } from "../offlineEngine";
import { runEngineCheck, type CheckStep } from "../offlineEngineCheck";
import { Button, Screen, useUiStyles } from "../ui";

export default function EngineCheck() {
  const router = useRouter();
  const styles = useUiStyles();
  const { run } = useLocalSearchParams<{ run?: string }>();
  const [steps, setSteps] = useState<CheckStep[]>([]);
  const [running, setRunning] = useState(false);
  const started = useRef(false);

  const start = useCallback(async () => {
    setRunning(true);
    setSteps([]);
    try {
      await runEngineCheck(offlineEngine(), (step) => {
        setSteps((previous) => [...previous, step]);
        // Timings and short codes only: no certificate or engine payload.
        console.log(`ICD11CHECK ${step.name} ok=${step.ok} note=${step.note} ms=${step.ms.toFixed(1)}${step.nativeMs === undefined ? "" : ` nativeMs=${step.nativeMs.toFixed(1)}`}`);
      });
    } finally {
      setRunning(false);
    }
  }, []);

  useEffect(() => {
    if (run === "1" && !started.current && isPlusVariant()) {
      started.current = true;
      void start();
    }
  }, [run, start]);

  if (!isPlusVariant()) return <Redirect href="/" />;
  return (
    <Screen title="Offline engine check">
      <Text style={styles.muted}>
        Experimental. Runs the on-phone ICD-11 / DORIS engine once. The first run copies and indexes the data (slow).
      </Text>
      <Button label="Run engine check" loading={running} disabled={running} onPress={() => void start()} />
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
