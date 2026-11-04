/**
 * Platform services for WhoVaForm: the date picker. Android opens the system dialog (DateTimePickerAndroid);
 * iOS has no such dialog, so the request goes to IosDatePickerHost through src/iosDatePicker.ts. Attachment
 * capture comes from src/attachmentServices. Adapted from the vendored Expo demo.
 */
import { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import { Platform } from "react-native";
import type { WhoVaPlatformServices } from "@drguptavivek/who-2022-va/native";

import { dateFromIso, isoFromDate, requestIosDate } from "./iosDatePicker";

export const platformServices: WhoVaPlatformServices = {
  pickDate: (_question, _data, currentValue) => {
    if (Platform.OS === "ios") return requestIosDate(currentValue);
    return new Promise((resolve) => {
      DateTimePickerAndroid.open({
        mode: "date",
        value: dateFromIso(currentValue),
        onValueChange: (_event, selected) => resolve(selected ? isoFromDate(selected) : undefined),
        onDismiss: () => resolve(undefined),
        onNeutralButtonPress: () => resolve(undefined)
      });
    });
  }
};
