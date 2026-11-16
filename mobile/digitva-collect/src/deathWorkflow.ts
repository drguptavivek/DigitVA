/** Presentation gates mirror the case workflow; server authorization remains authoritative. */
export function canStartDeathInterview(state: string): boolean {
  return [
    "registered",
    "scheduled",
    "in_progress",
    "paused",
    "not_reachable",
    "refused",
  ].includes(state);
}

export function canFollowUpDeath(state: string): boolean {
  return ["registered", "scheduled", "not_reachable", "paused"].includes(state);
}

/** Masked contacts must never be passed to a dialler. */
export function deathPhoneUrl(phone: string | null | undefined): string | undefined {
  const normalized = phone?.trim().replace(/[\s()-]/g, "");
  return normalized && /^\+?\d{10,15}$/.test(normalized) ? `tel:${normalized}` : undefined;
}

export interface DeathFix {
  latitude: number;
  longitude: number;
  accuracy_m: number | null;
}

/** The registration's GPS fix, or null unless both coordinates are real numbers on Earth. */
export function deathFix(
  address: { latitude?: unknown; longitude?: unknown; accuracy_m?: unknown } | null | undefined,
): DeathFix | null {
  const lat = address?.latitude;
  const lng = address?.longitude;
  if (typeof lat !== "number" || typeof lng !== "number") return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  const acc = address?.accuracy_m;
  return { latitude: lat, longitude: lng, accuracy_m: typeof acc === "number" && Number.isFinite(acc) && acc >= 0 ? acc : null };
}

/** Navigation URLs to the fix, tried in order: Android falls back from Google Maps to any geo: app. */
export function deathDirectionsUrls(fix: DeathFix, os: string, iosApp: "apple" | "google" = "apple"): string[] {
  const ll = `${fix.latitude},${fix.longitude}`;
  if (os !== "ios") return [`google.navigation:q=${ll}`, `geo:${ll}?q=${ll}`];
  // iOS offers both: Google Maps app if installed, else its web directions; Apple Maps otherwise.
  return iosApp === "google"
    ? [`comgooglemaps://?daddr=${ll}&directionsmode=driving`, deathShareUrl(fix)]
    : [`http://maps.apple.com/?daddr=${ll}`];
}

/** The link the Share sheet sends; opens in Google Maps or any browser. */
export function deathShareUrl(fix: DeathFix): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${fix.latitude},${fix.longitude}`;
}
