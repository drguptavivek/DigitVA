import Constants from "expo-constants";

/**
 * Whether this is the experimental "DigitVA Collect Plus" build (APP_VARIANT=plus at prebuild, app.config.js sets
 * extra.appVariant). It adds the coding screens and the offline ICD-11 engine; the plain build has neither.
 */
export function isPlusVariant(extra: Record<string, unknown> | undefined = Constants.expoConfig?.extra): boolean {
  return extra?.appVariant === "plus";
}
