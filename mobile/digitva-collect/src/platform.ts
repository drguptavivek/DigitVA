/**
 * Platform services for WhoVaForm. Phase 2a supplies the Android date picker
 * only; attachment capture is deliberately absent (attachments arrive as
 * encrypted BLOBs in phase 3). Adapted from the vendored Expo demo.
 */
import { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import type { WhoVaPlatformServices } from "@drguptavivek/who-2022-va/native";

function dateFromIso(value: string | undefined): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return new Date();
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function isoFromDate(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${value.getFullYear()}-${month}-${day}`;
}

export const platformServices: WhoVaPlatformServices = {
  pickDate: (_question, _data, currentValue) =>
    new Promise((resolve) => {
      DateTimePickerAndroid.open({
        mode: "date",
        value: dateFromIso(currentValue),
        onValueChange: (_event, selected) => resolve(selected ? isoFromDate(selected) : undefined),
        onDismiss: () => resolve(undefined),
        onNeutralButtonPress: () => resolve(undefined)
      });
    })
};
