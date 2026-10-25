import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api";
import { errorText } from "../ui";
import type { WorkspaceApi } from "./api";
import type { SmartvaStatus, WorkspaceIdentity } from "./contracts";

const POLL_MS = 3_000;

export type SmartvaLifecycleState = {
  status?: SmartvaStatus;
  canRun?: boolean;
  busy: boolean;
  error: string;
  message: string;
  run: (regenerate?: boolean) => Promise<void>;
};

type SmartvaLifecycleOptions = {
  api: WorkspaceApi;
  identity: WorkspaceIdentity;
  status?: SmartvaStatus;
  canRun?: boolean;
  /** Screen visibility/foreground state; polling is suspended when false. */
  active?: boolean;
  onChanged?: () => void | Promise<void>;
};

/** Keep SmartVA status current without coupling polling to the optional drawer. */
export function useSmartvaLifecycle({
  api,
  identity,
  status: sourceStatus,
  canRun: sourceCanRun,
  active = true,
  onChanged,
}: SmartvaLifecycleOptions): SmartvaLifecycleState {
  const contextKey = `${identity.vaSid}:${identity.mode}`;
  const contextRef = useRef({ api, contextKey });
  const lifecycleContextRef = useRef({ api, contextKey });
  const activeRef = useRef(active);
  const generationRef = useRef(0);
  const statusRef = useRef<SmartvaStatus | undefined>(sourceStatus);
  const canRunRef = useRef(sourceCanRun);
  const sourceStatusRef = useRef(sourceStatus);
  const inFlightRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoStartedRef = useRef(false);
  const terminalNotifiedRef = useRef(false);
  const callbackRef = useRef(onChanged);
  const refreshRef = useRef<(() => Promise<void>) | undefined>(undefined);
  const [state, setState] = useState<SmartvaLifecycleState>({
    status: sourceStatus,
    canRun: sourceCanRun,
    busy: false,
    error: "",
    message: "",
    run: async () => undefined,
  });

  contextRef.current = { api, contextKey };
  activeRef.current = active;
  callbackRef.current = onChanged;

  const current = useCallback((generation: number) => (
    activeRef.current
      && generationRef.current === generation
      && contextRef.current.api === api
      && contextRef.current.contextKey === contextKey
  ), [api, contextKey]);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const notifyChanged = useCallback(() => {
    if (terminalNotifiedRef.current) return;
    terminalNotifiedRef.current = true;
    void callbackRef.current?.();
  }, []);

  const run = useCallback(async (regenerate?: boolean) => {
    if (!activeRef.current || inFlightRef.current || identity.mode !== "coding") return;
    const generation = generationRef.current;
    const currentStatus = statusRef.current;
    if (currentStatus === "queued" || currentStatus === "running") return;
    if (!canRunRef.current) return;
    const replace = regenerate ?? currentStatus === "done";
    inFlightRef.current = true;
    setState(previous => ({ ...previous, busy: true, error: "", message: "" }));
    try {
      const reply = await api.runSmartva(identity.vaSid, replace);
      if (!current(generation)) return;
      statusRef.current = reply.status;
      setState(previous => ({ ...previous, status: reply.status, busy: false, message: "SmartVA has been queued." }));
      if (reply.status === "queued" || reply.status === "running") {
        terminalNotifiedRef.current = false;
        clearTimer();
        timerRef.current = setTimeout(() => { timerRef.current = null; void refreshRef.current?.(); }, POLL_MS);
      } else if (reply.status === "done" || reply.status === "failed") {
        notifyChanged();
      }
    } catch (caught) {
      if (!current(generation)) return;
      // A race with another browser tab is authoritative, not a user-facing failure.
      if (caught instanceof ApiError && caught.status === 409 && caught.code === "already_done") {
        setState(previous => ({ ...previous, busy: false }));
        inFlightRef.current = false;
        await refreshRef.current?.();
      } else {
        setState(previous => ({ ...previous, busy: false, error: errorText(caught) }));
      }
    } finally {
      if (current(generation)) inFlightRef.current = false;
    }
  }, [api, clearTimer, contextKey, current, identity.mode, identity.vaSid, notifyChanged]);

  const refresh = useCallback(async () => {
    if (!activeRef.current || inFlightRef.current) return;
    const generation = generationRef.current;
    inFlightRef.current = true;
    try {
      const reply = await api.getSmartvaStatus(identity.vaSid);
      if (!current(generation)) return;
      const previous = statusRef.current;
      statusRef.current = reply.status;
      canRunRef.current = reply.can_run;
      setState(stateValue => ({ ...stateValue, status: reply.status, canRun: reply.can_run, error: "" }));
      if ((reply.status === "queued" || reply.status === "running")) {
        terminalNotifiedRef.current = false;
      } else {
        clearTimer();
        if ((previous === "queued" || previous === "running") && (reply.status === "done" || reply.status === "failed")) notifyChanged();
        if (reply.status === "not_requested" && identity.mode === "coding" && reply.can_run && !autoStartedRef.current) {
          autoStartedRef.current = true;
          inFlightRef.current = false;
          await run(false);
          return;
        }
      }
      if (current(generation) && (reply.status === "queued" || reply.status === "running")) {
        clearTimer();
        timerRef.current = setTimeout(() => { timerRef.current = null; void refresh(); }, POLL_MS);
      }
    } catch (caught) {
      if (current(generation)) setState(stateValue => ({ ...stateValue, error: errorText(caught) }));
    } finally {
      if (current(generation)) inFlightRef.current = false;
    }
  }, [api, clearTimer, contextKey, current, identity.mode, identity.vaSid, notifyChanged, run]);

  refreshRef.current = refresh;

  useEffect(() => {
    if (sourceStatus !== sourceStatusRef.current) {
      sourceStatusRef.current = sourceStatus;
      statusRef.current = sourceStatus;
      setState(previous => ({ ...previous, status: sourceStatus }));
    }
    if (sourceCanRun !== undefined) {
      canRunRef.current = sourceCanRun;
      setState(previous => ({ ...previous, canRun: sourceCanRun }));
    }
  }, [sourceCanRun, sourceStatus]);

  useEffect(() => {
    const contextChanged = lifecycleContextRef.current.api !== api || lifecycleContextRef.current.contextKey !== contextKey;
    lifecycleContextRef.current = { api, contextKey };
    generationRef.current += 1;
    clearTimer();
    inFlightRef.current = false;
    if (contextChanged) {
      autoStartedRef.current = false;
      terminalNotifiedRef.current = false;
    }
    statusRef.current = sourceStatus;
    canRunRef.current = sourceCanRun;
    setState({ status: sourceStatus, canRun: sourceCanRun, busy: false, error: "", message: "", run });
    if (!active || identity.mode !== "coding") return undefined;
    void refresh();
    return () => {
      generationRef.current += 1;
      clearTimer();
    };
  // Context/foreground changes define a new lifecycle; status changes are synced above.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, api, contextKey, identity.mode, identity.vaSid]);

  useEffect(() => () => {
    generationRef.current += 1;
    clearTimer();
  }, [clearTimer]);

  return { ...state, run };
}
