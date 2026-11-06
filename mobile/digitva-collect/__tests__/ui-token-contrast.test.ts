/** Every text/background pair the unified tokens put on screen keeps >= 4.5:1 (UI edges and the focus ring >= 3:1), light and dark. */
import { palette, roleTones, ui, uiHighContrast, type ColorMode } from "../src/theme";
import { webPalette } from "../src/workspace/webPalette";
import { whoWebThemeVars } from "../src/whoWebTheme";
import { disabledButtonTone, getTheme } from "../src/theme";

const channel = (hex: string, at: number) => {
  const value = parseInt(hex.slice(at, at + 2), 16) / 255;
  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex: string) => 0.2126 * channel(hex, 1) + 0.7152 * channel(hex, 3) + 0.0722 * channel(hex, 5);
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const modes: ColorMode[] = ["light", "dark"];

describe.each(modes)("%s token pairs", (mode) => {
  const t = ui[mode];
  const w = webPalette[mode];
  const p = palette[mode];

  const text: ReadonlyArray<[string, string, string]> = [
    ["foreground on page", t.foreground, t.page],
    ["foreground on card", t.foreground, t.card],
    ["foreground on input fill", t.foreground, t.background],
    ["foreground on muted", t.foreground, t.muted],
    ["foreground on selected row (accent)", t.accentForeground, t.accent],
    ["muted text on page", t.mutedForeground, t.page],
    ["muted text on card", t.mutedForeground, t.card],
    ["muted text on input fill", t.mutedForeground, t.background],
    ["muted text on muted", t.mutedForeground, t.muted],
    ["primary button label", t.primaryForeground, t.primary],
    ["secondary button label", t.secondaryForeground, t.secondary],
    ["destructive button label", t.destructiveForeground, t.destructive],
    ["petrol: tint-filled secondary button label", t.primary, t.primaryTint],
    ["petrol: amber badge ink text", t.onAttention, t.attention],
    ["petrol: text on the attention row", t.foreground, t.attentionTint],
    ["petrol: text on the selected tint", t.foreground, t.primaryTint],
    ["petrol: error message on the error tint", t.destructiveText, t.destructiveSoft],
    ["petrol: text on the error tint", t.foreground, t.destructiveSoft],
    ["petrol: text on the success tint", t.foreground, t.successTint],
    ["petrol: disabled button label", t.mutedForeground, t.muted],
    ["brand text on card", t.primary, t.card],
    ["brand text on page", t.primary, t.page],
    ["brand text on selected row", t.primary, t.accent],
    ["danger text on page", t.destructiveText, t.page],
    ["danger text on card", t.destructiveText, t.card],
    ["danger text on input fill", t.destructiveText, t.background],
    ["danger text on tinted fill", t.destructiveText, t.destructiveSoft],
    ["success text on card", t.success, t.card],
    ["warning text on card", t.warningText, t.card],
    ["warning alert text", t.warningForeground, t.warning],
    ["old palette: text on surface", p.text, p.surface],
    ["old palette: muted on surface", p.textMuted, p.surface],
    ["old palette: accent on surface", p.accent, p.surface],
    ["old palette: onAccent on accent", p.onAccent, p.accent],
    ["old palette: danger on dangerSoft", p.danger, p.dangerSoft],
    ["old palette: debug banner", p.onAccent, p.warning],
    ["web: text on card", w.text, w.card],
    ["web: muted on card", w.textMuted, w.card],
    ["web: muted on page", w.textMuted, w.page],
    ["web: brand on card", w.blue, w.card],
    ["web: header bar text", w.onBar, w.bar],
    ["web: selected category text", w.onBar, w.selected],
    ["web: demo badge", w.onBar, w.demo],
    ["web: blocked reason on card", w.blocked, w.card],
    ["web: yes answer", w.onBar, w.yes],
    ["web: no answer", w.onBar, w.no],
    ["web: yes panel", w.onBar, w.yesPanel],
    ["web: no panel", w.onBar, w.noPanel],
    ["web: warning note", w.warnText, w.warnBg],
    ["web: lightbox close", w.closeText, w.closeBg],
    ["web: disabled text", w.disabledText, w.disabledBg],
    ["web: text on header cell", w.text, w.header],
    ["web: brand on pill", w.blue, w.pillBg],
    ["WHO row text on its fill", whoWebThemeVars(getTheme(mode))["--who-2022-web-color-ink-subtle"], whoWebThemeVars(getTheme(mode))["--who-2022-web-color-surface"]],
    ["WHO row text on its selected fill", whoWebThemeVars(getTheme(mode))["--who-2022-web-color-ink-subtle"], whoWebThemeVars(getTheme(mode))["--who-2022-web-color-brand-soft"]]
  ];
  it.each(text)("%s keeps 4.5:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  // Case cards (src/web/DeathsList.tsx CaseCard) hold their text to AAA: facts and the case ID in
  // `foreground` on the card, badges in their foreground on their fill.
  const caseCard: ReadonlyArray<[string, string, string]> = [
    ["card fact on card", t.foreground, t.card],
    ["neutral status badge", t.foreground, t.muted],
    ["accent status badge", t.accentForeground, t.accent],
    ["warning status badge", t.warningForeground, t.warning],
    ["card notice on muted banner", t.foreground, t.muted],
    ["card notice on danger banner", t.foreground, t.destructiveSoft],
    ["card notice on accent banner", t.foreground, t.accent],
  ];
  it.each(caseCard)("%s keeps 7:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(7);
  });

  const edges: ReadonlyArray<[string, string, string]> = [
    ["control edge on input fill", t.input, t.background],
    ["control edge on card", t.input, t.card],
    ["petrol: success icon on the success tint (notice text is ink)", t.success, t.successTint],
    ["petrol: error icon on the error tint", t.destructiveText, t.destructiveSoft],
    ["focus ring on page", t.ring, t.page],
    ["focus ring on card", t.ring, t.card],
    ["selected row edge on selected fill", t.primary, t.accent],
    ["selected row edge on card", t.primary, t.card]
  ];
  it.each(edges)("%s keeps 3:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(3);
  });

  // Role chips (src/ui/RoleChip.tsx): text on the soft fill, edge against the card, one fill per tone.
  const tones = Object.entries(roleTones[mode]);
  it.each(tones)("role chip %s: text keeps 4.5:1 on its fill", (_name, tone) => {
    expect(contrast(tone.fg, tone.bg)).toBeGreaterThanOrEqual(4.5);
  });
  it.each(tones)("role chip %s: edge keeps 3:1 on the card", (_name, tone) => {
    expect(contrast(tone.border, t.card)).toBeGreaterThanOrEqual(3);
  });
  it("role chip tones have distinct fills", () => {
    expect(new Set(tones.map(([, tone]) => tone.bg)).size).toBe(tones.length);
  });
});

/**
 * High contrast (Settings > Display), light and dark: every text and primary pair at 7:1 (WCAG AAA 1.4.6), field
 * edges, separators, the focus ring and meaning-carrying icons at 3:1, and a stronger canvas/card step than the
 * normal palette, with no card borders added.
 */
describe.each(modes)("%s high-contrast token pairs", (mode) => {
  const t = uiHighContrast[mode];
  const text: ReadonlyArray<[string, string, string]> = [
    ["text on page", t.foreground, t.page],
    ["text on card", t.foreground, t.card],
    ["text on input fill", t.foreground, t.background],
    ["text on muted", t.foreground, t.muted],
    ["text on selected tint", t.foreground, t.primaryTint],
    ["text on attention row", t.foreground, t.attentionTint],
    ["text on error tint", t.foreground, t.destructiveSoft],
    ["text on success tint", t.foreground, t.successTint],
    ["secondary text on page", t.mutedForeground, t.page],
    ["secondary text on card", t.mutedForeground, t.card],
    ["secondary text on muted", t.mutedForeground, t.muted],
    ["secondary text on selected tint", t.mutedForeground, t.primaryTint],
    ["primary button label", t.primaryForeground, t.primary],
    ["primary (links, text buttons) on card", t.primary, t.card],
    ["primary on page", t.primary, t.page],
    ["tint-filled secondary button label", t.primary, t.primaryTint],
    ["amber badge ink text", t.onAttention, t.attention],
    ["destructive button label", t.destructiveForeground, t.destructive],
    ["error text on card", t.destructiveText, t.card],
    ["error text on page", t.destructiveText, t.page],
    ["error text on error tint", t.destructiveText, t.destructiveSoft],
    ["success text on card", t.success, t.card],
    ["guidance text on card", t.warningText, t.card],
    ["disabled button label", t.mutedForeground, t.muted]
  ];
  it.each(text)("%s keeps 7:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(7);
  });

  const edges: ReadonlyArray<[string, string, string]> = [
    ["field edge (hairline) on input fill", t.border, t.background],
    ["field edge (hairline) on page", t.border, t.page],
    ["separator on card", t.separator, t.card],
    ["control edge on card", t.input, t.card],
    ["focus ring on card", t.ring, t.card],
    ["focus ring on page", t.ring, t.page],
    ["success icon on success tint", t.success, t.successTint],
    ["error icon on error tint", t.destructiveText, t.destructiveSoft],
    ["selected edge on selected fill", t.primary, t.primaryTint]
  ];
  it.each(edges)("%s keeps 3:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(3);
  });

  it("steps the canvas further from the card than the normal palette", () => {
    expect(contrast(t.page, t.card)).toBeGreaterThan(contrast(ui[mode].page, ui[mode].card));
  });
});


describe.each([
  ["light", ui.light], ["dark", ui.dark], ["high-contrast light", uiHighContrast.light], ["high-contrast dark", uiHighContrast.dark],
] as const)("%s disabled button", (_name, t) => {
  it("keeps its label at 4.5:1 on the tint fill, and fainter than an enabled tint button", () => {
    const tone = disabledButtonTone(t);
    expect(tone.bg).toBe(t.primaryTint);
    expect(contrast(tone.fg, tone.bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(tone.fg, tone.bg)).toBeLessThanOrEqual(contrast(t.primary, t.primaryTint));
  });
});
