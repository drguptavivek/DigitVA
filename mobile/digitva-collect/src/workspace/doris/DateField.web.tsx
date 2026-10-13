import { DateControl } from "./DateControl.web";
import { DateFieldShell, type DateFieldProps } from "./dateFieldShared";

export type { DateFieldProps };

/**
 * Browser build: the shared DateControl (real <input type=date|month> or a year dropdown). The value is the ISO day itself, so there is no time part and
 * no timezone shift; the shown format follows the browser locale. No min or max: odd dates warn, never block.
 */
export function DateField(props: DateFieldProps) {
  const control = (precision: "date" | "month" | "year") => (value: string, onChange: (value: string) => void) =>
    <DateControl precision={precision} label={props.label} value={value} onChange={onChange} now={props.now} />;
  return <DateFieldShell {...props} date={control("date")} month={control("month")} year={control("year")} />;
}
