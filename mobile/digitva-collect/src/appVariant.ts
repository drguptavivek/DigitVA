import Constants from "expo-constants";
import { requireOptionalNativeModule } from "expo";

/**
 * Whether this is the experimental "DigitVA Collect Plus" build. Both variants support online coding; Plus adds
 * offline ICD-11 coding and its native engine. app.config.js sets extra.appVariant when APP_VARIANT=plus, but the
 * release JS bundle reads the config at Gradle time, so a Gradle run without APP_VARIANT embeds a plain config into a plus APK.
 * The DigitvaIcd11 native module is excluded from plain builds, so its presence also identifies Plus.
 */
export function isPlusVariant(
  extra: Record<string, unknown> | undefined = Constants.expoConfig?.extra,
  hasEngineModule: () => boolean = () => requireOptionalNativeModule("DigitvaIcd11") !== null,
): boolean {
  return extra?.appVariant === "plus" || hasEngineModule();
}

/**
 * Whether this is the Google Play build (DIGITVA_DISTRIBUTION=play, app.config.js). Play forbids an app updating
 * itself outside Play, so this build never checks for or links to the hosted APK; Google Play updates it. The Play
 * workflow sets the flag for the Gradle run too, so the embedded config carries it (see isPlusVariant above).
 */
export function isPlayDistribution(extra: Record<string, unknown> | undefined = Constants.expoConfig?.extra): boolean {
  return extra?.digitvaDistribution === "play";
}
