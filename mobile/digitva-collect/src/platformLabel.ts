/** Display name for a stored device platform ("ios" -> "iOS"); unknown values pass through. Never sent to the server. */
export function platformLabel(platform: string | null | undefined): string {
  const known: Record<string, string> = { ios: "iOS", android: "Android" };
  return platform ? known[platform.toLowerCase()] ?? platform : "";
}
