/**
 * The Interviews list's online cases: the rows fetched page by page from the server for the picked project, the
 * cursor to the next page, and the busy flag. Moved out of worklist.tsx unchanged. The request generation is
 * bumped by the screen whenever the project changes, the screen blurs or a sync starts, so a late page is dropped.
 * refresh and send in worklist.tsx fill and clear this state through the setters and the generation returned here.
 */
import { useRef, useState, type MutableRefObject } from "react";

import type { CaseRow } from "../cases";
import { fetchCasePage } from "../sync";

export interface LoadMoreContext {
  account: { user_id: string } | undefined;
  selectedProjectId: string | undefined;
  selectedProjectRef: MutableRefObject<string | undefined>;
  isCurrent(): boolean;
  handleError(error: unknown): Promise<void>;
}

export function useOnlineCases(held: CaseRow[] | undefined) {
  const [onlineCases, setOnlineCases] = useState<CaseRow[]>(held ?? []);
  const [onlineCursor, setOnlineCursor] = useState<string | null>(null);
  const [onlineBusy, setOnlineBusy] = useState(false);
  const onlineRequestGenerationRef = useRef(0);

  /** The next page for the picked project, or its first when there is no cursor; a failed page leaves the rows and cursor as they were. */
  async function loadMore({ account, selectedProjectId, selectedProjectRef, isCurrent, handleError }: LoadMoreContext) {
    if (!account || !selectedProjectId || onlineBusy) return;
    const projectId = selectedProjectId;
    const requestGeneration = onlineRequestGenerationRef.current;
    const cursor = onlineCursor;
    setOnlineBusy(true);
    try {
      const page = await fetchCasePage(account.user_id, projectId, {
        limit: 50,
        ...(cursor ? { cursor } : {}),
      });
      if (
        isCurrent() &&
        requestGeneration === onlineRequestGenerationRef.current &&
        selectedProjectRef.current === projectId
      ) {
        setOnlineCases((current) =>
          cursor ? [...current, ...page.cases] : page.cases,
        );
        setOnlineCursor(page.next_cursor ?? null);
      }
    } catch (error) {
      if (isCurrent()) await handleError(error);
    } finally {
      setOnlineBusy(false);
    }
  }

  return { onlineCases, setOnlineCases, onlineCursor, setOnlineCursor, onlineBusy, onlineRequestGenerationRef, loadMore };
}
