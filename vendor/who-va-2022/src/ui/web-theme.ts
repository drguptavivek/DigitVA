import { type FormTheme, webDefaults as W } from "./theme.js";

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
  canvas: `var(--who-2022-web-color-canvas, ${W.canvas})`,
  surface: `var(--who-2022-web-color-surface, ${W.surface})`,
  ink: `var(--who-2022-web-color-ink, ${W.ink})`,
  inkSubtle: `var(--who-2022-web-color-ink-subtle, ${W.inkSubtle})`,
  muted: `var(--who-2022-web-color-muted, ${W.muted})`,
  brandDeep: `var(--who-2022-web-color-brand-deep, ${W.brandDeep})`,
  brand: `var(--who-2022-web-color-brand, ${W.brand})`,
  brandSoft: `var(--who-2022-web-color-brand-soft, ${W.brandSoft})`,
  border: `var(--who-2022-web-color-border, ${W.border})`,
  controlBorder: `var(--who-2022-web-color-control-border, ${W.controlBorder})`,
  guidance: `var(--who-2022-web-color-guidance, ${W.guidance})`,
  danger: `var(--who-2022-web-color-danger, ${W.danger})`,
  dangerBorder: `var(--who-2022-web-color-danger-border, ${W.dangerBorder})`,
  dangerStrong: `var(--who-2022-web-color-danger-strong, ${W.dangerStrong})`,
  dangerSoft: `var(--who-2022-web-color-danger-soft, ${W.dangerSoft})`,
  imageBackground: `var(--who-2022-web-color-image-background, ${W.imageBackground})`,
  controlRadius: "var(--who-2022-web-radius-control, 8px)",
  cardRadius: "var(--who-2022-web-radius-card, 12px)",
  formMaxWidth: "var(--who-2022-web-form-max-width, 64rem)",
  // Browser-only positioning the native style system has no word for: the
  // section drawer is fixed to the viewport, the section rail sticks while
  // a long section scrolls. Native keeps the plain values.
  overlayPosition: "fixed",
  stickyPosition: "sticky"
};

type FormThemeBindings = Record<string, keyof FormTheme>;
const formThemeBindings = new WeakMap<object, FormThemeBindings>();

/** The `FormTheme` colour a colour token stands for when the host passes a theme. */
const tokenThemeKey: Partial<Record<WebThemeToken, keyof FormTheme>> = {
  canvas: "surfaceAlt",
  surface: "surface",
  ink: "text",
  inkSubtle: "text",
  muted: "textMuted",
  brandDeep: "primary",
  brand: "primary",
  brandSoft: "primarySoft",
  border: "border",
  controlBorder: "borderStrong",
  guidance: "accent",
  danger: "danger",
  dangerBorder: "danger",
  dangerStrong: "danger",
  dangerSoft: "dangerSoft",
  imageBackground: "surfaceAlt"
};

/**
 * Associates shared/native style properties with their semantic web tokens.
 * `themeColours` names the `FormTheme` colour of a property the tokens do not
 * cover or cover differently (text on a primary fill, the answered badge).
 */
export function withWebTheme<T extends ThemeableStyle>(
  style: T,
  bindings: WebThemeBindings,
  themeColours?: FormThemeBindings
): T {
  webThemeBindings.set(style, bindings);
  if (themeColours) formThemeBindings.set(style, themeColours);
  return style;
}

/** The colour properties of an annotated style, resolved against a host theme. */
function themeColours(style: object, theme: FormTheme): Record<string, string> {
  const colours: Record<string, string> = {};
  for (const [property, token] of Object.entries(webThemeBindings.get(style) ?? {})) {
    const key = tokenThemeKey[token];
    if (key) colours[property] = theme[key];
  }
  for (const [property, key] of Object.entries(formThemeBindings.get(style) ?? {}))
    colours[property] = theme[key];
  return colours;
}

/** Native styles: the annotated colours become the host theme's; without a theme the style is untouched. */
export function applyNativeTheme(style: unknown, theme: FormTheme | undefined): unknown {
  if (!theme) return style;
  if (Array.isArray(style)) return style.map((entry) => applyNativeTheme(entry, theme));
  if (style == null || typeof style !== "object") return style;
  const colours = themeColours(style, theme);
  return Object.keys(colours).length ? { ...style, ...colours } : style;
}

export function applyWebTheme(style: unknown, theme?: FormTheme): unknown {
  if (Array.isArray(style)) return style.map((entry) => applyWebTheme(entry, theme));
  if (style == null || typeof style !== "object") return style;
  const bindings = webThemeBindings.get(style);
  if (!bindings) return style;

  const themedStyle: ThemeableStyle = { ...(style as ThemeableStyle) };
  for (const [property, token] of Object.entries(bindings)) {
    if (theme && tokenThemeKey[token]) continue;
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
  if (theme) Object.assign(themedStyle, themeColours(style, theme));
  return themedStyle;
}
