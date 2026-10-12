/** Pure routing rules of the shared browser header: which tab is current, when the phone bottom bar shows, how many tabs fit. */

/** Pre-login and device screens: nobody is signed in to see navigation there. */
export const HEADERLESS_ROUTES = ["/sign-in", "/enrol", "/unlock", "/pin-setup", "/register"];

/** Top-level destinations that carry the phone bottom bar; case, form and interview screens do not. */
const TOP_LEVEL = ["/", "/coding", "/reviewing", "/collection", "/worklist", "/death-registration", "/supervision", "/organization", "/settings", "/workspace"];

export type NavParams = { vaSid?: string | string[]; mode?: string | string[] };

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value)?.trim();

/** The tab route a path belongs to, or undefined (home, a view-only workspace, unknown routes). /workspace belongs to Coding or Review by its `mode`. */
export function activeTab(pathname: string, params: NavParams = {}): string | undefined {
  if (pathname === "/workspace") {
    const mode = first(params.mode);
    return mode === "coding" ? "/coding" : mode === "reviewing" ? "/reviewing" : undefined;
  }
  if (pathname === "/worklist") return "/collection";
  return ["/coding", "/reviewing", "/collection", "/death-registration", "/supervision", "/organization", "/settings"]
    .find((route) => pathname === route || pathname.startsWith(`${route}/`));
}

/** The phone bottom bar: top-level screens only, never inside a case (/workspace with a vaSid) or before sign-in. */
export function showBottomTabs(pathname: string, params: NavParams = {}): boolean {
  if (HEADERLESS_ROUTES.includes(pathname)) return false;
  if (pathname === "/workspace" && first(params.vaSid)) return false;
  return TOP_LEVEL.includes(pathname);
}

/**
 * How many of the tabs fit before the rest go to "More". Widths are estimated from label length (14px Roboto
 * 500 is about 7.6px a glyph) instead of measured: no layout pass, and the same answer in tests.
 * ponytail: an estimate, so a very long translated label may overflow by a few px; measure with ResizeObserver if that shows.
 */
export function tabsThatFit(labels: string[], available: number, reserved: number): number {
  const widths = labels.map((label) => 28 + 18 + 8 + Math.ceil(label.length * 7.6));
  const total = widths.reduce((sum, width) => sum + width, 0);
  if (total + reserved <= available) return labels.length;
  const room = available - reserved - MORE_WIDTH;
  let used = 0;
  let count = 0;
  for (const width of widths) {
    if (used + width > room) break;
    used += width;
    count += 1;
  }
  return count;
}

export const MORE_WIDTH = 96;
