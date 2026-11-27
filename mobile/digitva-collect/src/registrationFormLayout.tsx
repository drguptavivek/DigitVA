/**
 * The Register a death layout shared by the phone (src/nativeRoutes/register.tsx) and the web Add a Death form
 * (src/web/DeathRegistrationScreen.tsx): the text fields, their section groups and the single-choice list.
 * Web-safe: imports nothing native-only, so the web bundle can take it (__tests__/web-bundle-boundary.test.ts).
 */
import { View } from "react-native";

import type { RegistrationFields } from "./cases";
import type { SEX_VALUES } from "./registrationRules";
import type { StringKey, ThemeStringKey } from "./i18n";
import { radius } from "./theme";
import { ChoiceRow, SegmentedControl, Separator } from "./ui";

export type Field = Exclude<keyof RegistrationFields, "identifiers">;

/** Text fields in the web form's order, with their label and the helper line under the field (format, example). */
export const TEXT_FIELDS: Array<{
  name: Field;
  label: StringKey;
  help?: StringKey | ThemeStringKey;
  required?: boolean;
}> = [
  { name: "deceased_name", label: "fieldDeceasedName", required: true },
  { name: "date_of_death", label: "fieldDateOfDeath", required: true },
  { name: "address", label: "fieldAddress" },
  { name: "informant_name", label: "fieldInformantName" },
  // Rendered with informant_phone_2 by PhoneNumbers.
  { name: "informant_phone", label: "fieldPhoneNumber" },
  { name: "abha_number", label: "fieldAbhaNumber", help: "abhaNumberHint" },
  { name: "abha_address", label: "fieldAbhaAddress", help: "abhaAddressHint" },
  { name: "place_of_death", label: "fieldPlaceOfDeath" },
  { name: "address_house_street", label: "fieldHouseStreet" },
  { name: "address_village_ward", label: "fieldVillageWard" },
  { name: "address_landmark", label: "fieldLandmark" },
  { name: "father_name", label: "fieldFatherName" },
  { name: "mother_name", label: "fieldMotherName" },
  { name: "remarks", label: "fieldRemarks", help: "remarksHelp" },
];

/**
 * The form's groups under their section labels (design sheet 01): who died, where, the identifiers, then notes.
 * Fields the consent notice covers are drawn in the Informant group instead, wherever they are listed here.
 */
export const DECEASED_FIELDS: Field[] = ["father_name", "mother_name"];
export const PLACE_FIELDS: Field[] = ["place_of_death", "address", "address_house_street", "address_village_ward", "address_landmark"];
export const IDENTIFIER_FIELDS: Field[] = ["abha_number", "abha_address"];
export const NOTE_FIELDS: Field[] = ["remarks"];

export const SEX_LABELS: Record<(typeof SEX_VALUES)[number], StringKey> = {
  male: "sexMale",
  female: "sexFemale",
  undetermined: "sexUndetermined",
  unknown: "sexUnknown",
};

/**
 * A single choice: a SegmentedControl for up to three short options, else a ChoiceRow per option, so a long label
 * ("Undetermined") never wraps inside a segment. The rows sit inside the section card's padding, in line with the
 * fields, as one rounded group (the selected tint and the hairlines stop where the fields do; no card inside a card).
 */
export function ChoiceList<T extends string>({ options, value, onChange, disabled, accessibilityLabel }: {
  options: ReadonlyArray<{ value: T; label: string }>;
  value: T | undefined;
  onChange: (value: T) => void;
  disabled: boolean;
  accessibilityLabel: string;
}) {
  if (options.length <= 3) return <SegmentedControl options={options} value={value} onChange={onChange} disabled={disabled} accessibilityLabel={accessibilityLabel} />;
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={accessibilityLabel} style={{ borderRadius: radius.lg, overflow: "hidden" }}>
      {options.map((option, index) => (
        <View key={option.value}>
          {index ? <Separator choice /> : null}
          <ChoiceRow label={option.label} selected={option.value === value} disabled={disabled} onPress={() => onChange(option.value)} />
        </View>
      ))}
    </View>
  );
}
