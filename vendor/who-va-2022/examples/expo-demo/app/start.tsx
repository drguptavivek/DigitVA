import { useLocalSearchParams } from "expo-router";

import { FormRouteScreen } from "../components/FormRouteScreen";
import { createWhoVaDataFromCaseEntry, useDemoState } from "../components/DemoState";

const editablePrefillQuestionNames = new Set(["Id10051"]);

export default function StartRoute() {
  const { caseUid, completedId } = useLocalSearchParams<{ caseUid?: string; completedId?: string }>();
  const { cases, completed, getDraft, newFormKey } = useDemoState();
  const requestedCaseUid = Array.isArray(caseUid) ? caseUid[0] : caseUid;
  const requestedCompletedId = Array.isArray(completedId) ? completedId[0] : completedId;
  const selectedCase = requestedCaseUid ? cases.find((entry) => entry.uid === requestedCaseUid) : undefined;
  const selectedCompleted = completed.find((submission) => {
    if (requestedCompletedId && submission.id === requestedCompletedId) return true;
    const completedCaseUid = submission.result.data.__caseUid;
    return (
      requestedCaseUid &&
      (completedCaseUid === requestedCaseUid || submission.caseEntry?.uid === requestedCaseUid)
    );
  });
  const recoveredCaseEntry = selectedCase?.caseEntry ?? selectedCompleted?.caseEntry;
  const recoveredPrefill = recoveredCaseEntry ? createWhoVaDataFromCaseEntry(recoveredCaseEntry) : undefined;
  const savedDraft = requestedCaseUid ? getDraft(requestedCaseUid) : undefined;
  const initialData = selectedCase?.whoVaData ?? selectedCompleted?.result.data;
  const formKey = recoveredCaseEntry
    ? `case-${requestedCaseUid ?? selectedCompleted?.id}-${selectedCompleted?.id ?? "new"}-${newFormKey}`
    : "start-empty";

  return (
    <FormRouteScreen
      caseEntry={recoveredCaseEntry}
      draft={savedDraft}
      draftId={requestedCaseUid ?? selectedCompleted?.id}
      emptyMessage={recoveredCaseEntry ? undefined : "Save case data before starting the WHO VA form."}
      formKey={formKey}
      initialData={initialData}
      lockedQuestionNames={
        recoveredPrefill
          ? Object.keys(recoveredPrefill).filter((name) => !editablePrefillQuestionNames.has(name))
          : undefined
      }
      title={recoveredCaseEntry ? `WHO VA: ${recoveredCaseEntry.deceasedFullName}` : "Start New"}
    />
  );
}
