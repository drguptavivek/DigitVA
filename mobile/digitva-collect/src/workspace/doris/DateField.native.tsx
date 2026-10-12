import { useState } from "react";
import { Platform, View } from "react-native";

import { ControlText, FieldButton, useLayout } from "./ui";
import { DateFieldShell, isFullIso, isoFromLocal, localDate, todayIso, type DateFieldProps } from "./dateFieldShared";

export type { DateFieldProps };

/**
 * Native build: the system date picker behind a field-style button. It emits the
 * picked local calendar day as ISO with no min or max (odd dates warn, never block).
 * Year-Month and Year use the shell's month list and year field.
 */
export function DateField(props: DateFieldProps) {
  const layout = useLayout();
  const [open, setOpen] = useState(false);
  const today = localDate(todayIso(props.now, props.timeZone));

  return (
    <DateFieldShell {...props} date={(value, onChange) => {
      const current = isFullIso(value) ? localDate(value) : today;
      const pick = (date: Date) => onChange(isoFromLocal(date));
      const show = () => {
        // Loaded on first use: the native module is absent in unit tests that only import the editor.
        const picker = require("@react-native-community/datetimepicker") as typeof import("@react-native-community/datetimepicker");
        if (Platform.OS === "android") {
          picker.DateTimePickerAndroid.open({ value: current, mode: "date", onChange: (event, date) => { if (event.type === "set" && date) pick(date); } });
        } else setOpen(!open);
      };
      const Picker = open ? (require("@react-native-community/datetimepicker") as typeof import("@react-native-community/datetimepicker")).default : null;
      return (
        <View style={{ gap: 4, flexGrow: 1, flexBasis: 150 }}>
          <FieldButton accessibilityLabel={props.label} accessibilityValue={{ text: value || "Not set" }} onPress={show}>
            <ControlText>{value ? value : "Select date 📅"}</ControlText>
          </FieldButton>
          {Picker ? <Picker value={current} mode="date" display="inline" onChange={(_event, date) => { setOpen(false); if (date) pick(date); }} /> : null}
        </View>
      );
    }} />
  );
}
