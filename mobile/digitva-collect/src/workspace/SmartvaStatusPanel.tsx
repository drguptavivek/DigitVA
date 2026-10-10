import { useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { Button, errorText, styles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { SmartvaStatus, WorkspaceIdentity } from "./contracts";

const STATUS_LABELS: Record<SmartvaStatus, string> = {
  not_requested: "Not requested",
  queued: "Queued",
  running: "Running",
  done: "Done",
  failed: "Failed",
};

export type SmartvaStatusPanelProps = {
  api: WorkspaceApi;
  identity: WorkspaceIdentity;
  status?: SmartvaStatus;
  canRun?: boolean;
  resultVisible?: boolean;
  visible?: boolean;
  onChanged?: () => void | Promise<void>;
};

/** Status-only SmartVA controls; result details remain in the assessment steps. */
export function SmartvaStatusPanel({
  api,
  identity,
  status,
  canRun,
  resultVisible = false,
  visible = true,
  onChanged,
}: SmartvaStatusPanelProps) {
  const contextKey = `${identity.vaSid}:${identity.mode}`;
  const contextRef = useRef({ api, contextKey });
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const foregroundRef = useRef(typeof document === "undefined" || document.visibilityState === "visible");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [localStatus, setLocalStatus] = useState<SmartvaStatus>();

  contextRef.current = { api, contextKey };

  useEffect(() => {
    mountedRef.current = true;
    const visibilityChanged = () => {
      foregroundRef.current = typeof document === "undefined" || document.visibilityState === "visible";
      if (foregroundRef.current) {
        setBusy(false);
        setError("");
      }
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      mountedRef.current = false;
      foregroundRef.current = false;
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  useEffect(() => {
    generationRef.current += 1;
    setBusy(false);
    setError("");
    setMessage("");
    setLocalStatus(undefined);
  }, [api, contextKey, status, canRun, visible]);

  if (!visible || status === undefined || canRun === undefined) return null;

  const currentStatus = localStatus ?? status;
  const action = identity.mode !== "view" && canRun && currentStatus === "done"
    ? { label: "Regenerate", regenerate: true }
    : identity.mode !== "view" && canRun && currentStatus === "failed"
      ? { label: "Run again", regenerate: false }
      : identity.mode !== "view" && canRun && currentStatus === "not_requested"
        ? { label: "Run SmartVA", regenerate: false }
        : null;

  const run = () => {
    if (!action || busy || !mountedRef.current || !foregroundRef.current) return;
    const generation = generationRef.current;
    const requestContext = contextRef.current;
    const isCurrent = () => mountedRef.current
      && foregroundRef.current
      && visible
      && generationRef.current === generation
      && contextRef.current.api === requestContext.api
      && contextRef.current.contextKey === requestContext.contextKey;
    setBusy(true);
    setError("");
    setMessage("");
    void requestContext.api.runSmartva(identity.vaSid, action.regenerate).then((reply) => {
      if (!isCurrent()) return;
      if (reply.va_sid !== identity.vaSid) {
        setError("SmartVA could not be queued.");
        return;
      }
      setLocalStatus(reply.status);
      setMessage("SmartVA has been queued. Reload this page in a minute to see the result.");
      void onChanged?.();
    }).catch((caught) => {
      if (isCurrent()) setError(errorText(caught));
    }).finally(() => {
      if (isCurrent()) setBusy(false);
    });
  };

  return (
    <View nativeID="smartva-status-panel" style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>SmartVA</Text>
      <Text nativeID="smartva-status-text" style={styles.text}>
        Status: <Text style={styles.headline}>{STATUS_LABELS[currentStatus]}</Text>
        {currentStatus === "done" ? <Text style={styles.muted}>{resultVisible ? " (result shown in the assessment steps)" : " (result not displayed in this assessment step)"}</Text> : null}
      </Text>
      {action ? <Button label={action.label} kind={currentStatus === "done" ? "secondary" : "primary"} onPress={run} disabled={busy} loading={busy} /> : null}
      {message ? <Text style={styles.muted}>{message}</Text> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  );
}
