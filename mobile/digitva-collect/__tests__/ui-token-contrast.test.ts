/** Every text/background pair the unified tokens put on screen keeps >= 4.5:1 (UI edges and the focus ring >= 3:1), light and dark. */
import { palette, ui, type ColorMode } from "../src/theme";
import { webPalette } from "../src/workspace/webPalette";
import { whoWebThemeVars } from "../src/whoWebTheme";
import { getTheme } from "../src/theme";

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
    ["focus ring on page", t.ring, t.page],
    ["focus ring on card", t.ring, t.card],
    ["selected row edge on selected fill", t.primary, t.accent],
    ["selected row edge on card", t.primary, t.card]
  ];
  it.each(edges)("%s keeps 3:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(3);
  });
});
