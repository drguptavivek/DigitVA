/**
 * Collect Plus only: "Try DORIS", reached from Help without signing in. The offline DORIS editor (DorisPanel with the
 * React picker) over the on-phone ICD-11 engine, loaded with one of WHO's six synthetic certificates or a blank one.
 * Offline and unsaved by design: no server call, case, account, store or queue (src/workspace/dorisDemo.ts). Starting
 * the engine takes about 20 seconds; the device-wide ICD-11 / DORIS switch (Settings) is respected.
 */
import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { t } from "../i18n";
import { isIcd11DorisEnabled, useIcd11DorisPreference } from "../icd11DorisPreference";
import { offlineEngine } from "../offlineEngine";
import { describeProgress } from "../offlineEngineCheck";
import { Button, Screen, useUiStyles } from "../ui";
import { createGuidanceRequester } from "../workspace/offlineDoris";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import type { WorkspaceIdentity } from "../workspace/contracts";
import {
  createDorisDemoApi, createDorisDemoEditor, demoVaSid, demoWorkspace, DORIS_DEMO_BLANK, DORIS_DEMO_EXAMPLES,
} from "../workspace/dorisDemo";

const assertEnabled = async () => {
  if (!await isIcd11DorisEnabled()) throw new Error("icd11_doris_disabled");
};
const noop = async () => undefined;

/** The editor, picker and example chooser; mounted only while the switch is on and the user has continued. */
function Demo() {
  const styles = useUiStyles();
  const router = useRouter();
  const [engineReady, setEngineReady] = useState(false);
  const [failed, setFailed] = useState("");
  const [progress, setProgress] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState({ id: DORIS_DEMO_BLANK, load: 0 });

  const engine = offlineEngine();
  const editor = useMemo(() => createDorisDemoEditor(engine), [engine]);
  const api = useMemo(() => createDorisDemoApi(editor, assertEnabled), [editor]);
  // One requester per load: DorisPanel's in-memory drafts hang off it, so a reload starts from the example again.
  const session = useMemo(() => ({
    workspace: demoWorkspace(loaded.id, loaded.load),
    identity: { vaSid: demoVaSid(loaded.id, loaded.load), mode: "coding" } as WorkspaceIdentity,
    request: createGuidanceRequester(editor, demoVaSid(loaded.id, loaded.load), assertEnabled),
  }), [editor, loaded]);
  const example = DORIS_DEMO_EXAMPLES.find((item) => item.id === loaded.id);

  useEffect(() => {
    let live = true;
    setFailed("");
    setProgress("");
    setEngineReady(false);
    const stop = engine.onProgress((event) => { if (live) setProgress(describeProgress(event)); });
    engine.init().then((result) => {
      if (!live) return;
      if (result.ok) setEngineReady(true);
      else setFailed(result.error);
    }, () => { if (live) setFailed("native_error"); });
    return () => { live = false; stop(); };
  }, [engine, attempt]);

  const choose = (id: string) => setLoaded((current) => ({ id, load: current.load + 1 }));
  return (
    <Screen title={t("dorisDemoTitle")}>
      <Text style={styles.text}>{t("dorisDemoIntro")}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {[{ id: DORIS_DEMO_BLANK, label: t("dorisDemoBlank") }, ...DORIS_DEMO_EXAMPLES].map((item) => (
          <Button key={item.id} kind={item.id === loaded.id ? "primary" : "secondary"} label={item.label} onPress={() => choose(item.id)} />
        ))}
      </View>
      {example ? <Text style={styles.muted}>{example.purpose}</Text> : null}
      {failed ? <>
        <Text accessibilityRole="alert" style={styles.error}>{`${t("dorisDemoEngineFailed")} (${failed})`}</Text>
        <Button kind="secondary" label={t("dorisDemoRetry")} onPress={() => setAttempt((value) => value + 1)} />
      </> : !engineReady ? (
        <View accessibilityRole="progressbar" style={{ gap: 8 }}>
          <ActivityIndicator />
          <Text style={styles.muted}>{t("dorisDemoStarting")}</Text>
          {progress ? <Text style={styles.muted}>{progress}</Text> : null}
        </View>
      ) : (
        <DorisPanel key={session.identity.vaSid} workspace={session.workspace} identity={session.identity} api={api} request={session.request} onSaved={noop} onDone={() => undefined} demo />
      )}
      <Button kind="secondary" label={t("icd11DorisGoBack")} onPress={() => router.back()} />
    </Screen>
  );
}

export default function DorisDemo() {
  const router = useRouter();
  const styles = useUiStyles();
  const preference = useIcd11DorisPreference();
  // Turning the switch on in Settings must not start the engine as a side effect: if it was off on entry, wait for Continue.
  const [continued, setContinued] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    if (continued === undefined && preference.ready) setContinued(preference.enabled);
  }, [continued, preference.enabled, preference.ready]);

  if (!preference.ready || continued === undefined) {
    return <Screen title={t("dorisDemoTitle")}><ActivityIndicator accessibilityLabel={t("loading")} /></Screen>;
  }
  if (!preference.enabled) {
    return (
      <Screen title={t("icd11DorisDisabledTitle")}>
        <Text accessibilityRole="alert" style={styles.text}>{t("dorisDemoDisabledBody")}</Text>
        <Button label={t("icd11DorisOpenSettings")} onPress={() => router.push("/settings")} />
        <Button kind="secondary" label={t("icd11DorisGoBack")} onPress={() => router.back()} />
      </Screen>
    );
  }
  if (!continued) {
    return (
      <Screen title={t("dorisDemoTitle")}>
        <Text style={styles.text}>{t("icd11DorisContinueBody")}</Text>
        <Button label={t("icd11DorisContinue")} onPress={() => setContinued(true)} />
        <Button kind="secondary" label={t("icd11DorisGoBack")} onPress={() => router.back()} />
      </Screen>
    );
  }
  return <Demo />;
}
