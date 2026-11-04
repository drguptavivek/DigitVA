import { isPlusVariant } from "./appVariant";
import { offlineEnginePlatform } from "./platformFamily";

/** The "Try DORIS" demo exists only in the Collect Plus build (Android or iOS); plain Collect and the web never show it. */
export function canTryDorisDemo(): boolean {
  return offlineEnginePlatform() && isPlusVariant();
}
