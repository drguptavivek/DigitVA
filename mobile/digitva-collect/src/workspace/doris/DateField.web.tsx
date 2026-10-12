import { createElement } from "react";
import { useTheme } from "../../theme";
import { CONTROL_HEIGHT, font, gap, uiRadius, useUi } from "./ui";
import { DateFieldShell, isFullIso, type DateFieldProps } from "./dateFieldShared";

export type { DateFieldProps };

/**
 * Browser build: a real <input type="date"> or <input type="month"> (react-native-web's TextInput has
 * no such types). The value is the ISO day itself, so there is no time part and
 * no timezone shift; the shown format follows the browser locale. No min or max: odd dates warn, never block.
 */
export function DateField(props: DateFieldProps) {
  const { mode } = useTheme();
  const { t, phone } = useUi();
  const input = (type: "date" | "month", value: string, accept: (next: string) => boolean, onChange: (value: string) => void) => createElement("input", {
    type,
    "aria-label": props.label,
    value: accept(value) ? value : "",
    onChange: (event: { target: { value: string } }) => { const next = event.target.value; if (next === "" || accept(next)) onChange(next); },
    style: { boxSizing: "border-box", height: phone ? 44 : CONTROL_HEIGHT, flexGrow: 1, minWidth: 150, padding: `4px ${gap.md - 2}px`, fontSize: font.body, borderRadius: uiRadius.md, border: `1px solid ${t.input}`, background: t.background, color: t.foreground, colorScheme: mode },
  });
  return (
    <DateFieldShell {...props}
      date={(value, onChange) => input("date", value, isFullIso, onChange)}
      month={(value, onChange) => input("month", value, (next) => /^\d{4}-(0[1-9]|1[0-2])$/.test(next), onChange)} />
  );
}
