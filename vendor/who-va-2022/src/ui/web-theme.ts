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
  | "formPadding";

type ThemeableStyle = Record<string, unknown>;
type WebThemeBindings = Record<string, WebThemeToken>;

const webThemeBindings = new WeakMap<object, WebThemeBindings>();

const webThemeValues: Record<Exclude<WebThemeToken, "formPadding">, string> = {
  canvas: "var(--who-2022-web-color-canvas, #f5f7fa)",
  surface: "var(--who-2022-web-color-surface, #ffffff)",
  ink: "var(--who-2022-web-color-ink, #1f2937)",
  inkSubtle: "var(--who-2022-web-color-ink-subtle, #374151)",
  muted: "var(--who-2022-web-color-muted, #667085)",
  brandDeep: "var(--who-2022-web-color-brand-deep, #1e3a5f)",
  brand: "var(--who-2022-web-color-brand, #2563eb)",
  brandSoft: "var(--who-2022-web-color-brand-soft, #eff6ff)",
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
  formMaxWidth: "var(--who-2022-web-form-max-width, 48rem)"
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
    if (token === "formPadding") {
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
