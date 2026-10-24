import Constants from "expo-constants";
import { requireOptionalNativeModule } from "expo";

/**
 * Whether this is the experimental "DigitVA Collect Plus" build. It adds the coding screens and the offline ICD-11
 * engine; the plain build has neither. app.config.js sets extra.appVariant when APP_VARIANT=plus, but the release JS
 * bundle reads the config at Gradle time, so a Gradle run without APP_VARIANT embeds a plain config into a plus APK.
 * The DigitvaIcd11 native module is excluded from plain builds, so its presence also identifies Plus.
 */
export function isPlusVariant(
  extra: Record<string, unknown> | undefined = Constants.expoConfig?.extra,
  hasEngineModule: () => boolean = () => requireOptionalNativeModule("DigitvaIcd11") !== null,
): boolean {
  return extra?.appVariant === "plus" || hasEngineModule();
}
