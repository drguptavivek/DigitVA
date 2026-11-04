/**
 * Small platform facts shared by native screens (docs/policy/ios-client.md). Kept out of src/appVariant.ts so
 * tests that mock the variant do not also have to mock these.
 */
import Constants from "expo-constants";
import { Platform } from "react-native";

/**
 * Whether this platform can host the offline Plus engines (ICD-11, DORIS, profile, identity): Android and iOS, never the
 * web. Combine with isPlusVariant(), which also requires the native engine module on the device.
 */
export function offlineEnginePlatform(os: string = Platform.OS): boolean {
  return os === "android" || os === "ios";
}

/** "Android", "iPhone", "iPad" or "Web": display and export text only, never a stored identifier. */
export function deviceFamilyLabel(os: string = Platform.OS, isPad: boolean = (Platform as { isPad?: boolean }).isPad === true): string {
  if (os === "ios") return isPad ? "iPad" : "iPhone";
  if (os === "web") return "Web";
  return "Android";
}

/** The App Store id app.config.js embeds from DIGITVA_IOS_APP_STORE_ID, or undefined when it is not set. */
export function iosAppStoreId(extra: Record<string, unknown> | undefined = Constants.expoConfig?.extra): string | undefined {
  const id = extra?.digitvaIosAppStoreId;
  return typeof id === "string" && /^\d+$/.test(id) ? id : undefined;
}
