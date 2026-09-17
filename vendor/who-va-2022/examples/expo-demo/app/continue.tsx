import { useLocalSearchParams } from "expo-router";
import { useEffect } from "react";

import { FormRouteScreen } from "../components/FormRouteScreen";
import { countAnswers, useDemoState } from "../components/DemoState";

export default function ContinueRoute() {
  const { draftId } = useLocalSearchParams<{ draftId?: string }>();
  const { getDraft, latestDraft, setLastUpdate } = useDemoState();
  const requestedDraftId = Array.isArray(draftId) ? draftId[0] : draftId;
  const draft = getDraft(requestedDraftId) ?? latestDraft;

  useEffect(() => {
    if (draft) setLastUpdate(`Continuing draft: ${countAnswers(draft)} answers`);
  }, [draft, setLastUpdate]);

  return (
    <FormRouteScreen
      draft={draft}
      emptyMessage={draft ? undefined : "No saved draft is available. Start a new interview first."}
      formKey={draft ? `draft-${draft.id}` : "continue-empty"}
      title="Continue Last"
    />
  );
}
