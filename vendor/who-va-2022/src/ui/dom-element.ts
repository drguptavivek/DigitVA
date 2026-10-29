/**
 * Tells a real DOM element from a native view ref. `instanceof HTMLElement`
 * is not enough: React Native 0.86 polyfills a global `HTMLElement` as its
 * own `ReactNativeElement`, so a native ref passes that check yet has no
 * `querySelector`, `scrollTo` or the other DOM members. Test for the members
 * the caller is about to use instead.
 */
export function domElement(node: unknown, ...members: string[]): HTMLElement | undefined {
  if (typeof node !== "object" || node === null) return undefined;
  const candidate = node as Record<string, unknown>;
  if (typeof candidate.querySelector !== "function") return undefined;
  return members.every((member) => candidate[member] !== undefined) ? (node as HTMLElement) : undefined;
}

/** Moves focus into a web question's first control; false when `node` is not a DOM element. */
export function focusDomQuestion(node: unknown): boolean {
  const element = domElement(node);
  if (!element) return false;
  element.querySelector<HTMLElement>("input, textarea, select, button, [tabindex]")?.focus?.({ preventScroll: true });
  return true;
}
