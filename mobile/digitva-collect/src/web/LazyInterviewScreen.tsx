import { Component, Suspense, lazy, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { Text, View } from "react-native";

import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";
import { WebShell } from "./common";
import LoadingScreen from "./LoadingScreen";

/** A failed chunk download can be retried without reloading or touching saved interviews. */
class DownloadBoundary extends Component<{ children: ReactNode; onRetry(): void; onFailed(): void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onFailed(); }
  render() {
    return this.state.failed ? <DownloadRetry onRetry={this.props.onRetry} /> : this.props.children;
  }
}

function DownloadRetry({ onRetry }: { onRetry(): void }) {
  const styles = useUiStyles();
  return <WebShell title={t("appName")}><View style={styles.card} accessibilityRole="alert">
    <Text style={styles.text}>{t("errNetwork")}</Text>
    <Button label={t("retry")} onPress={onRetry} />
  </View></WebShell>;
}

type Loader = () => Promise<{ default: ComponentType }>;
// One lazy component per loader for the page's life: a fresh lazy() per mount suspended every visit (a full-screen
// "Loading…" flash) though the chunk was already downloaded. A retry replaces the failed one.
const lazyScreens = new Map<Loader, ComponentType>();

/** Keep the interviewer and WHO form renderer out of login and coding downloads. */
export function DeferredScreen({ load }: { load: Loader }) {
  const [attempt, setAttempt] = useState(0);
  const Screen = useMemo(() => {
    if (attempt > 0 || !lazyScreens.has(load)) lazyScreens.set(load, lazy(load));
    return lazyScreens.get(load)!;
  }, [load, attempt]);
  // A failed download is forgotten, so a later visit tries again by itself (as before the shared lazy component).
  return <DownloadBoundary key={attempt} onRetry={() => setAttempt((value) => value + 1)} onFailed={() => lazyScreens.delete(load)}>
    <Suspense fallback={<LoadingScreen />}><Screen /></Suspense>
  </DownloadBoundary>;
}

const loadInterview = () => import("./InterviewScreen");
const loadRegistration = () => import("./DeathRegistrationScreen");
const loadCaseDetail = () => import("./newCaseDetailScreen");
export function InterviewScreen() { return <DeferredScreen load={loadInterview} />; }
export function DeathRegistrationScreen() { return <DeferredScreen load={loadRegistration} />; }
export function CaseDetailScreen() { return <DeferredScreen load={loadCaseDetail} />; }
