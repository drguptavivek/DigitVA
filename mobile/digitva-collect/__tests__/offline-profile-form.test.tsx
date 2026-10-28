import React from "react";
import { TextInput } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockStrings: Record<string, string> = {
  offlineProfileName: "Name",
  offlineProfileCountry: "Country",
  offlineProfileHideOptional: "Hide optional details",
  offlineProfileShowOptional: "Optional details",
  offlineProfileAge: "Age (years)",
  offlineProfileSex: "Sex",
  offlineProfileMale: "Male",
  offlineProfileFemale: "Female",
  offlineProfileOther: "Other",
  offlineProfileDesignation: "Designation",
  offlineProfileFacility: "Facility / organization",
  offlineProfileState: "State",
  offlineProfileOrgCode: "Organisation code",
  offlineProfileHiv: "HIV mortality level",
  offlineProfileMalaria: "Malaria endemicity",
  offlineProfileLevelUnset: "Not set",
  offlineProfileLevelNone: "None",
  offlineProfileLevelLow: "Low",
  offlineProfileLevelHigh: "High",
  offlineProfileSaved: "Saved {time}",
};

jest.mock("../src/i18n", () => ({ t: (key: string) => mockStrings[key] ?? key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, expanded }: { label: string; onPress?: () => void; expanded?: boolean }) => ReactActual.createElement("button", {
      accessibilityRole: "button", accessibilityLabel: label, onPress, expanded,
    }),
    useUiStyles: () => ({ input: {}, muted: {}, error: {} }),
  };
});

import type { OfflineProfile } from "../src/offlineProfile";
import { OfflineProfileForm } from "../src/offlineProfileForm";

const profile: OfflineProfile = {
  name: "Asha",
  age_years: 41,
  sex: "female" as const,
  designation: "Coder",
  facility_name: "District hospital",
  country: "India",
  state: "Delhi",
  org_code: "D01",
  hiv_mortality: "low" as const,
  malaria_mortality: "high" as const,
  updated_at: "2026-10-28T00:00:00.000Z",
};

async function render(onSubmit: (value: OfflineProfile) => void) {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <OfflineProfileForm
        initialProfile={profile}
        submitLabel="Save profile"
        onSubmit={onSubmit}
      />,
    );
  });
  return tree;
}

async function press(tree: ReactTestRenderer, label: string) {
  const button = tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
  expect(button).toBeDefined();
  await act(async () => { button.props.onPress(); });
}

it("collapsing optional details preserves prefilled values on save", async () => {
  const onSubmit = jest.fn();
  const tree = await render(onSubmit);

  expect(tree.root.findAllByType(TextInput).filter((node) => node.props.accessibilityLabel === "Age (years)")).toHaveLength(1);
  await press(tree, "Hide optional details");
  expect(tree.root.findAllByType(TextInput).filter((node) => node.props.accessibilityLabel === "Age (years)")).toHaveLength(0);
  await press(tree, "Save profile");

  expect(onSubmit).toHaveBeenCalledWith(profile);
});
