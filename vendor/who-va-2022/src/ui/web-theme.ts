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

/** The colour entries of a `FormTheme` (not its `fontScale`). */
type FormThemeColour = Exclude<keyof FormTheme, "fontScale">;
type FormThemeBindings = Record<string, FormThemeColour>;
const formThemeBindings = new WeakMap<object, FormThemeBindings>();

/** The `FormTheme` colour a colour token stands for when the host passes a theme. */
const tokenThemeKey: Partial<Record<WebThemeToken, FormThemeColour>> = {
  canvas: "canvas",
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

const petrolStyles = new WeakMap<object, object>();

/**
 * The Petrol look (DigitVA Collect): `petrol` is merged over `style` whenever the host passes a `FormTheme`; without
 * one (the Flask web component, any default consumer) `style` renders alone. `petrol` is itself annotated with
 * `withWebTheme` when it carries theme colours. Returns `style`.
 */
export function withPetrol<T extends object>(style: T, petrol: object): T {
  petrolStyles.set(style, petrol);
  return style;
}

/** A theme colour; the optional `canvas` falls back to `surfaceAlt`, any other unset one is left to the style. */
function themeColour(theme: FormTheme, key: FormThemeColour): string | undefined {
  return key === "canvas" ? (theme.canvas ?? theme.surfaceAlt) : theme[key];
}

/** The colour properties of an annotated style, resolved against a host theme. */
function themeColours(style: object, theme: FormTheme): Record<string, string> {
  const colours: Record<string, string> = {};
  for (const [property, token] of Object.entries(webThemeBindings.get(style) ?? {})) {
    const key = tokenThemeKey[token];
    const colour = key && themeColour(theme, key);
    if (colour) colours[property] = colour;
  }
  for (const [property, key] of Object.entries(formThemeBindings.get(style) ?? {})) {
    const colour = themeColour(theme, key);
    if (colour) colours[property] = colour;
  }
  return colours;
}

/** `fontSize` and `lineHeight` of a style times `scale`, to the half point; other styles are returned as they are. */
function scaledText(style: object, scale: number): Record<string, number> {
  const sizes: Record<string, number> = {};
  for (const property of ["fontSize", "lineHeight"] as const) {
    const value = (style as Record<string, unknown>)[property];
    if (typeof value === "number") sizes[property] = Math.round(value * scale * 2) / 2;
  }
  return sizes;
}

/**
 * Native styles: the annotated colours become the host theme's, text sizes take its `fontScale` and a `withPetrol`
 * override is merged on top; without a theme the style is untouched.
 */
export function applyNativeTheme(style: unknown, theme: FormTheme | undefined): unknown {
  if (!theme) return style;
  if (Array.isArray(style)) return style.map((entry) => applyNativeTheme(entry, theme));
  if (style == null || typeof style !== "object") return style;
  const themed = nativeThemed(style, theme);
  const petrol = petrolStyles.get(style);
  return petrol ? { ...(themed as object), ...nativeThemed(petrol, theme) } : themed;
}

function nativeThemed(style: object, theme: FormTheme): object {
  const scale = theme.fontScale ?? 1;
  const themed = { ...themeColours(style, theme), ...(scale === 1 ? {} : scaledText(style, scale)) };
  return Object.keys(themed).length ? { ...style, ...themed } : style;
}

/** Web styles: tokens become CSS variables, or the host theme's colours plus any `withPetrol` override. */
export function applyWebTheme(style: unknown, theme?: FormTheme): unknown {
  if (Array.isArray(style)) return style.map((entry) => applyWebTheme(entry, theme));
  if (style == null || typeof style !== "object") return style;
  const themed = webThemed(style, theme);
  const petrol = theme && petrolStyles.get(style);
  return petrol ? { ...themed, ...webThemed(petrol, theme) } : themed;
}

function webThemed(style: object, theme: FormTheme | undefined): object {
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
