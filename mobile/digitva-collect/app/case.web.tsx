import { Redirect, useLocalSearchParams } from "expo-router";

import { CaseDetailScreen } from "../src/web/LazyInterviewScreen";
import { hasLegacyTrainingParam } from "../src/training";

export default function BrowserCase() {
  const params = useLocalSearchParams();
  if (hasLegacyTrainingParam(params.training)) return <Redirect href={{ pathname: "/training/interview/case", params } as never} />;
  return <CaseDetailScreen />;
}
