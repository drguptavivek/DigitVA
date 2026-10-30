import { Platform } from "react-native";

import { isPlusVariant } from "./appVariant";

/** The "Try DORIS" demo exists only in the Collect Plus Android build; plain Collect and the web never show it. */
export function canTryDorisDemo(): boolean {
  return Platform.OS === "android" && isPlusVariant();
}
