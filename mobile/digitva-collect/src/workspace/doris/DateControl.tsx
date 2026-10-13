import { Input } from "./ui";
import type { DateControlProps } from "./DateControl.web";

export type { DateControlProps };

/** Non-browser fallback: a typed ISO field; the browser build is DateControl.web. */
export function DateControl({ precision, value, onChange, label, readOnly, error }: DateControlProps) {
  const length = precision === "date" ? 10 : precision === "month" ? 7 : 4;
  return <Input accessibilityLabel={label} placeholder={"YYYY-MM-DD".slice(0, length)} maxLength={length} value={value} editable={!readOnly} invalid={error} onChangeText={onChange} style={{ flexGrow: 1, flexBasis: 150 }} />;
}
