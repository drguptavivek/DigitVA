import { useCallback, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { SubmissionData } from "@drguptavivek/who-2022-va";

import { ConfirmDialog } from "./ConfirmDialog";
import { t } from "./i18n";
import { isRefused } from "./refusalBoundary";

/** Structural slice of WhoVaSession the guard needs (keeps the web and native form types out of this file). */
type Session = { getSnapshot(): { data: SubmissionData }; replaceData(data: SubmissionData): void };

/**
 * One confirmation before a consent "No" (Id10013) mid-interview wipes the draft (owner, digitva-9xn9.22).
 * `onChange` returns true when the change may proceed; a "No" returns false and opens the dialog instead.
 * The caller holds the draft store's save of the No meanwhile (a saved No strips the draft). Confirm runs `onConfirmed` (the existing refusal path, outcome unchanged); cancel puts the last
 * non-refused answers back into the form and calls `onReverted` (save them over the autosaved "No").
 */
export function useWhoNoConfirm({ onConfirmed, onReverted }: { onConfirmed: () => void; onReverted: () => void }) {
  const session = useRef<Session | undefined>(undefined);
  const safe = useRef<SubmissionData | undefined>(undefined);
  const [asking, setAsking] = useState(false);

  const onReady = useCallback((next: Session) => {
    session.current = next;
    safe.current = next.getSnapshot().data;
  }, []);

  const onChange = useCallback((data: SubmissionData): boolean => {
    if (!isRefused(data)) {
      safe.current = data;
      return true;
    }
    setAsking(true);
    return false;
  }, []);

  const dialog: ReactElement | null = asking ? (
    <ConfirmDialog
      title={t("whoNoConfirmTitle")}
      message={t("whoNoConfirmMessage")}
      confirmLabel={t("whoNoConfirmAction")}
      destructive
      onConfirm={() => { setAsking(false); onConfirmed(); }}
      onCancel={() => {
        setAsking(false);
        const { Id10013: _no, ...rest } = (session.current?.getSnapshot().data ?? {}) as Record<string, unknown>;
        session.current?.replaceData((safe.current ?? rest) as SubmissionData);
        onReverted();
      }}
    />
  ) : null;

  return { onReady, onChange, dialog };
}
