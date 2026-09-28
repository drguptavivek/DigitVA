export type WebThemeToken =
  | "canvas"
  | "surface"
  | "ink"
  | "inkSubtle"
  | "muted"
  | "brandDeep"
  | "brand"
  | "brandSoft"
  | "border"
  | "controlBorder"
  | "guidance"
  | "danger"
  | "dangerBorder"
  | "dangerStrong"
  | "dangerSoft"
  | "imageBackground"
  | "controlRadius"
  | "cardRadius"
  | "formMaxWidth"
  | "formPadding"
  | "overlayPosition"
  | "stickyPosition"
  | "entryTransition"
  | "stickyRail"
  | "scrollMargin";

type ThemeableStyle = Record<string, unknown>;
type WebThemeBindings = Record<string, WebThemeToken>;

const webThemeBindings = new WeakMap<object, WebThemeBindings>();

/**
 * True when the viewer asked for reduced motion. Shared with native, where
 * `window` does not exist, so every browser global is guarded.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The height of whatever the host fixes to the top of the page (DigitVA's
 * navbar is 56px): the section rail sticks below it and a section scrolled to
 * the top stops beneath it. Hosts set `--who-2022-web-sticky-top`.
 */
const STICKY_TOP = "var(--who-2022-web-sticky-top, 64px)";

const webThemeValues: Record<
  Exclude<WebThemeToken, "formPadding" | "entryTransition" | "stickyRail" | "scrollMargin">,
  string
> = {
  canvas: "var(--who-2022-web-color-canvas, #f5f7fa)",
  surface: "var(--who-2022-web-color-surface, #ffffff)",
  ink: "var(--who-2022-web-color-ink, #1f2937)",
  inkSubtle: "var(--who-2022-web-color-ink-subtle, #374151)",
  muted: "var(--who-2022-web-color-muted, #667085)",
  brandDeep: "var(--who-2022-web-color-brand-deep, #004687)",
  brand: "var(--who-2022-web-color-brand, #1b4f9c)",
  brandSoft: "var(--who-2022-web-color-brand-soft, #eaf1fa)",
  border: "var(--who-2022-web-color-border, #e2e8f0)",
  controlBorder: "var(--who-2022-web-color-control-border, #b8c2d1)",
  guidance: "var(--who-2022-web-color-guidance, #475569)",
  danger: "var(--who-2022-web-color-danger, #b42318)",
  dangerBorder: "var(--who-2022-web-color-danger-border, #d92d20)",
  dangerStrong: "var(--who-2022-web-color-danger-strong, #912018)",
  dangerSoft: "var(--who-2022-web-color-danger-soft, #fff1f0)",
  imageBackground: "var(--who-2022-web-color-image-background, #111827)",
  controlRadius: "var(--who-2022-web-radius-control, 8px)",
  cardRadius: "var(--who-2022-web-radius-card, 12px)",
  formMaxWidth: "var(--who-2022-web-form-max-width, 64rem)",
  // Browser-only positioning the native style system has no word for: the
  // section drawer is fixed to the viewport, the section rail sticks while
  // a long section scrolls. Native keeps the plain values.
  overlayPosition: "fixed",
  stickyPosition: "sticky"
};

/** Associates shared/native style properties with their semantic web tokens. */
export function withWebTheme<T extends ThemeableStyle>(style: T, bindings: WebThemeBindings): T {
  webThemeBindings.set(style, bindings);
  return style;
}

export function applyWebTheme(style: unknown): unknown {
  if (Array.isArray(style)) return style.map(applyWebTheme);
  if (style == null || typeof style !== "object") return style;
  const bindings = webThemeBindings.get(style);
  if (!bindings) return style;

  const themedStyle: ThemeableStyle = { ...(style as ThemeableStyle) };
  for (const [property, token] of Object.entries(bindings)) {
    if (token === "stickyRail") {
      // Sticks below the host's fixed bar and scrolls on its own when taller
      // than the viewport, without dragging the page along at its ends.
      themedStyle.position = "sticky";
      themedStyle.top = STICKY_TOP;
      themedStyle.maxHeight = `calc(100vh - ${STICKY_TOP} - 8px)`;
      themedStyle.overflowY = "auto";
      themedStyle.overscrollBehavior = "contain";
      themedStyle.scrollbarWidth = "thin";
    } else if (token === "scrollMargin") {
      themedStyle.scrollMarginTop = STICKY_TOP;
    } else if (token === "entryTransition") {
      // A section that has just appeared fades in; no fade under reduced motion.
      themedStyle.transitionProperty = "opacity";
      themedStyle.transitionDuration = prefersReducedMotion() ? "0ms" : "400ms";
    } else if (token === "formPadding") {
      delete themedStyle[property];
      const sharedFallback = "var(--who-2022-web-form-padding, clamp(1rem, 2.5vw, 1.5rem))";
      themedStyle.paddingBlock = `var(--who-2022-web-form-padding-block, ${sharedFallback})`;
      themedStyle.paddingInline = `var(--who-2022-web-form-padding-inline, ${sharedFallback})`;
    } else {
      themedStyle[property] = webThemeValues[token];
    }
  }
  return themedStyle;
}
