/** Presentation gates mirror the case workflow; server authorization remains authoritative. */
export function canStartDeathInterview(state: string): boolean {
  return ["registered", "scheduled", "paused", "not_reachable", "refused"].includes(state);
}

export function canFollowUpDeath(state: string): boolean {
  return ["registered", "scheduled", "not_reachable", "paused"].includes(state);
}

/** Masked contacts must never be passed to a dialler. */
export function deathPhoneUrl(phone: string | null | undefined): string | undefined {
  const normalized = phone?.trim().replace(/[\s()-]/g, "");
  return normalized && /^\+?\d{10,15}$/.test(normalized) ? `tel:${normalized}` : undefined;
}
