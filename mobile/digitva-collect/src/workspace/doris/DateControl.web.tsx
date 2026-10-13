import { createElement, useRef, useState, type CSSProperties } from "react";
import { useTheme } from "../../theme";
import { CONTROL_HEIGHT, font, gap, uiRadius, useUi } from "./ui";
import { isFullIso, type Precision } from "./dateFieldShared";

export interface DateControlProps {
  precision: Precision;
  /** ISO "YYYY-MM-DD", "YYYY-MM" or "YYYY" to match `precision`; anything else shows empty. */
  value: string;
  onChange: (value: string) => void;
  /** Accessible name; the visible label is drawn by the caller. */
  label: string;
  /** Same ISO shape as `value`; year precision limits the dropdown to min..max years. */
  min?: string;
  max?: string;
  readOnly?: boolean;
  error?: boolean;
  /** Empty option of the year dropdown. */
  placeholder?: string;
  /** Injected clock so the year range can be tested. */
  now?: Date;
}

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const YEAR = /^\d{4}$/;
const ACCEPT: Record<Precision, (value: string) => boolean> = { date: isFullIso, month: (v) => MONTH.test(v), year: (v) => YEAR.test(v) };
/** Years offered by the dropdown: the current year back this many. */
export const YEAR_SPAN = 120;

/** The browser's own date picker indicator is hidden: the themed calendar button is the one icon. */
const HIDE_NATIVE_INDICATOR = ".dv-date-input::-webkit-calendar-picker-indicator{display:none;-webkit-appearance:none}.dv-date-input::-webkit-inner-spin-button{display:none}";

const icon = (paths: string[]) => createElement("svg", { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, focusable: false },
  ...paths.map((d) => createElement("path", { key: d, d })));
/** Tabler "calendar" outline, the line-icon family of the app header. */
const CALENDAR = icon(["M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12z", "M16 3v4", "M8 3v4", "M4 11h16"]);
/** Tabler "chevron-down". */
const CHEVRON = icon(["M6 9l6 6l6 -6"]);

/**
 * The app's one date control (web): the real <input type=date|month> (keyboard and the browser's picker work)
 * with a themed calendar button, or for year precision a themed dropdown. Height 44 on phones. Emits only
 * valid values or "". Native builds use DateControl.tsx.
 */
export function DateControl({ precision, value, onChange, label, min, max, readOnly, error, placeholder = "Year", now = new Date() }: DateControlProps) {
  const { mode } = useTheme();
  const { t, phone } = useUi();
  const input = useRef<{ showPicker?: () => void; focus?: () => void } | null>(null);
  const [focused, setFocused] = useState(false);
  const accept = ACCEPT[precision];
  const shown = accept(value) ? value : "";
  const height = phone ? 44 : CONTROL_HEIGHT;
  const field: CSSProperties = {
    boxSizing: "border-box", height, flexGrow: 1, minWidth: 150, padding: `4px ${gap.md - 2}px`, fontSize: font.body, borderRadius: uiRadius.md,
    border: `1px solid ${error ? t.destructive : t.input}`, background: t.background, color: t.foreground, colorScheme: mode,
    outline: focused ? `2px solid ${t.ring}` : "none", outlineOffset: 2, opacity: readOnly ? 0.5 : 1,
  };
  const handlers = { onFocus: () => setFocused(true), onBlur: () => setFocused(false) };

  if (precision === "year") {
    const top = now.getFullYear();
    const lo = min && YEAR.test(min.slice(0, 4)) ? Number(min.slice(0, 4)) : top - YEAR_SPAN;
    const hi = max && YEAR.test(max.slice(0, 4)) ? Number(max.slice(0, 4)) : top;
    const years = Array.from({ length: Math.max(0, hi - lo + 1) }, (_, index) => String(hi - index));
    if (shown && !years.includes(shown)) years.push(shown);
    return createElement("div", { style: { position: "relative", display: "flex", flexGrow: 1, minWidth: 150, color: t.mutedForeground } },
      createElement("select", { "aria-label": label, "aria-invalid": error || undefined, disabled: readOnly, value: shown, ...handlers, style: { ...field, appearance: "none", WebkitAppearance: "none", paddingRight: 36, width: "100%" }, onChange: (event: { target: { value: string } }) => onChange(event.target.value) },
        createElement("option", { value: "" }, placeholder), ...years.map((year) => createElement("option", { key: year, value: year }, year))),
      createElement("span", { style: { position: "absolute", right: gap.sm, top: 0, bottom: 0, display: "flex", alignItems: "center", pointerEvents: "none" } }, CHEVRON));
  }

  return createElement("div", { style: { display: "flex", alignItems: "center", gap: gap.xs, flexGrow: 1 } },
    createElement("style", null, HIDE_NATIVE_INDICATOR),
    createElement("input", { ref: input, className: "dv-date-input", type: precision === "month" ? "month" : "date", "aria-label": label, "aria-invalid": error || undefined, readOnly, value: shown, ...(min ? { min } : {}), ...(max ? { max } : {}), ...handlers, style: field,
      onChange: (event: { target: { value: string } }) => { const next = event.target.value; if (next === "" || accept(next)) onChange(next); } }),
    createElement("button", { type: "button", "aria-label": `${label} calendar`, disabled: readOnly, style: { boxSizing: "border-box", width: 44, height, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 0, borderRadius: uiRadius.md, border: `1px solid ${t.input}`, background: t.background, color: t.foreground, cursor: readOnly ? "not-allowed" : "pointer", opacity: readOnly ? 0.5 : 1 },
      onClick: () => { try { input.current?.showPicker?.(); } catch { input.current?.focus?.(); } } }, CALENDAR));
}
