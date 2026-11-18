/**
 * True on a browser older than the web app is built for: iOS Safari before 15.4, Chrome before 108 (late 2022).
 * Feature-tested, not read from the user agent: `100dvh` (used by the workspace layout) shipped in those versions,
 * alongside APIs src/polyfills.ts cannot cover. ponytail: one CSS probe as the cut-off; raise it with the app's needs.
 */
export function outdatedBrowser(): boolean {
  if (typeof CSS === "undefined" || typeof CSS.supports !== "function") return false;
  return !CSS.supports("height", "100dvh");
}
