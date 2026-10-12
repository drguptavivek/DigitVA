import { Input } from "./ui";
import { DateFieldShell, type DateFieldProps } from "./dateFieldShared";

export type { DateFieldProps };

/** Fallback without a calendar; the browser and native builds use DateField.web / DateField.native. */
export function DateField(props: DateFieldProps) {
  return <DateFieldShell {...props} date={(value, onChange) => <Input accessibilityLabel={props.label} placeholder="YYYY-MM-DD" maxLength={10} value={value} onChangeText={onChange} style={{ flexGrow: 1, flexBasis: 150 }} />} />;
}
