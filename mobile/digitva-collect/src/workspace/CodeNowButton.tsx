import { useEffect, useRef, useState } from "react";
import { Alert, Platform, Text } from "react-native";

import { ApiError } from "../api";
import { t } from "../i18n";
import { Button, errorText, useUiStyles } from "../ui";
import type { WorkspaceApi } from "./api";

const RETRY_DELAY_MS = 2_000;
const MAX_NOT_READY_RETRIES = 2;

/** Allocate only on the user's explicit action, then open the real coding workspace. */
export function CodeNowButton({
  api,
  vaSid,
  disabled = false,
  onOpen,
  onAccessLost,
}: {
  api: WorkspaceApi;
  vaSid: string;
  disabled?: boolean;
  onOpen: (vaSid: string) => void;
  onAccessLost: () => void;
}) {
  const styles = useUiStyles();
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [releaseRequired, setReleaseRequired] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [message, setMessage] = useState("");
  const busyRef = useRef(false);
  const contextRef = useRef({ api, vaSid });
  const retryRef = useRef<{ timer: ReturnType<typeof setTimeout>; resolve: (active: boolean) => void } | undefined>(undefined);
  if (contextRef.current.api !== api || contextRef.current.vaSid !== vaSid) {
    contextRef.current = { api, vaSid };
    busyRef.current = false;
  }

  function isCurrent(context: { api: WorkspaceApi; vaSid: string }) {
    return contextRef.current === context;
  }

  useEffect(() => {
    const retry = retryRef.current;
    if (retry) {
      clearTimeout(retry.timer);
      retryRef.current = undefined;
      retry.resolve(false);
    }
    busyRef.current = false;
    setUnavailable(false);
    setMessage("");
    setReleaseRequired(false);
    setBusy(false);
    setRetrying(false);
  }, [api, vaSid]);

  useEffect(() => () => {
    contextRef.current = { api: contextRef.current.api, vaSid: "" };
    busyRef.current = false;
    const retry = retryRef.current;
    if (retry) {
      clearTimeout(retry.timer);
      retry.resolve(false);
      retryRef.current = undefined;
    }
  }, []);

  function waitForRetry(context: { api: WorkspaceApi; vaSid: string }): Promise<boolean> {
    setRetrying(true);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        retryRef.current = undefined;
        setRetrying(false);
        resolve(isCurrent(context));
      }, RETRY_DELAY_MS);
      retryRef.current = { timer, resolve };
    });
  }

  function cancel() {
    const retry = retryRef.current;
    if (retry) {
      clearTimeout(retry.timer);
      retryRef.current = undefined;
      retry.resolve(false);
    }
    busyRef.current = false;
    setRetrying(false);
    setBusy(false);
    setMessage("");
  }

  async function allocate(context: { api: WorkspaceApi; vaSid: string }) {
    for (let retry = 0; retry <= MAX_NOT_READY_RETRIES; retry += 1) {
      try {
        const result = await context.api.codeOwnSubmission(context.vaSid);
        if (!isCurrent(context)) return;
        if (result.va_sid !== context.vaSid) throw new Error("allocation_case_mismatch");
        setReleaseRequired(false);
        busyRef.current = false;
        setBusy(false);
        onOpen(context.vaSid);
        return;
      } catch (error) {
        if (!isCurrent(context)) return;
        if (error instanceof ApiError && error.code === "not_ready" && retry < MAX_NOT_READY_RETRIES) {
          setMessage(t("codeNowPreparing"));
          if (!await waitForRetry(context)) return;
          continue;
        }
        busyRef.current = false;
        setBusy(false);
        if (error instanceof ApiError && error.code === "not_ready") {
          setMessage(t("codeNowStillPreparing"));
        } else if (error instanceof ApiError && error.code === "held_by_another") {
          setReleaseRequired(false);
          setUnavailable(true);
          setMessage(t("codeNowHeldByAnother"));
        } else if (error instanceof ApiError && error.code === "allocation_exists") {
          setReleaseRequired(true);
          setMessage(t("codeNowReleaseFirst"));
        } else {
          setReleaseRequired(false);
          setMessage(errorText(error));
          if (error instanceof ApiError && error.status === 403) onAccessLost();
        }
        return;
      }
    }
  }

  async function start() {
    const context = contextRef.current;
    if (busyRef.current || disabled || unavailable || !isCurrent(context)) return;
    busyRef.current = true;
    setBusy(true);
    setReleaseRequired(false);
    setMessage("");
    await allocate(context);
  }

  async function releaseAndAllocate(context: { api: WorkspaceApi; vaSid: string }) {
    if (!isCurrent(context) || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setReleaseRequired(false);
    setMessage("");
    try {
      await context.api.releaseCoding();
      if (!isCurrent(context)) return;
      await allocate(context);
    } catch (error) {
      if (!isCurrent(context)) return;
      busyRef.current = false;
      setBusy(false);
      setMessage(errorText(error));
      if (error instanceof ApiError && error.status === 403) onAccessLost();
    }
  }

  function confirmRelease(context: { api: WorkspaceApi; vaSid: string }) {
    if (!isCurrent(context) || busyRef.current) return;
    const proceed = () => void releaseAndAllocate(context);
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(t("codeNowReleaseConfirm"))) proceed();
      return;
    }
    Alert.alert(t("codeNowReleaseTitle"), t("codeNowReleaseConfirm"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("codeNowReleaseConfirmAction"), style: "destructive", onPress: proceed },
    ]);
  }

  return <>
    {!unavailable ? <Button label={t("codeNow")} loading={busy} disabled={busy || disabled} onPress={() => void start()} /> : null}
    {retrying ? <Button kind="secondary" label={t("cancel")} onPress={cancel} /> : null}
    {releaseRequired ? <Button kind="danger" label={t("codeNowReleaseAction")} onPress={() => confirmRelease(contextRef.current)} /> : null}
    {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
  </>;
}
