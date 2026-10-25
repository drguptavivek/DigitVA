import { Redirect, useLocalSearchParams } from "expo-router";

import { hasLegacyTrainingParam, TRAINING_CODING_CASE_ROUTE, TRAINING_REVIEWING_CASE_ROUTE } from "../src/training";
import { WorkspaceScreen } from "../src/browserScreens";

export default function WorkspaceRoute() {
  const params = useLocalSearchParams<{ mode?: string | string[]; training?: string | string[] }>();
  const mode = Array.isArray(params.mode) ? params.mode[0] : params.mode;
  if (hasLegacyTrainingParam(params.training)) {
    const pathname = mode === "reviewing" ? TRAINING_REVIEWING_CASE_ROUTE : TRAINING_CODING_CASE_ROUTE;
    return <Redirect href={{ pathname, params } as never} />;
  }
  return <WorkspaceScreen />;
}
