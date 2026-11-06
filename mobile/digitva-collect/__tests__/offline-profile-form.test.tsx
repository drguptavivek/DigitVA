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
  offlineProfileSectionProfile: "Profile",
  offlineProfileSectionOptional: "Optional",
  offlineProfileSectionPresets: "Presets",
};

jest.mock("../src/i18n", () => ({ t: (key: string) => mockStrings[key] ?? key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const { TextInput } = jest.requireActual("react-native");
  const el = (name: string) => ({ children, ...props }: { children?: React.ReactNode }) => ReactActual.createElement(name, props, children);
  const press = (label: string, onPress?: () => void) => ReactActual.createElement("button", { accessibilityRole: "button", accessibilityLabel: label, onPress });
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => press(label, onPress),
    TextLink: ({ label, onPress }: { label: string; onPress?: () => void }) => press(label, onPress),
    Card: ({ label, children }: { label?: string; children?: React.ReactNode }) => ReactActual.createElement("card", { label }, children),
    FieldLabel: ({ label }: { label: string }) => ReactActual.createElement("fieldlabel", { label }),
    TextField: (props: object) => ReactActual.createElement(TextInput, props),
    ChoiceRow: ({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) => ReactActual.createElement("choice", { label, selected, onPress }),
    Separator: el("separator"),
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

it("groups the fields in Profile, Optional and Presets cards, with Not set first in each choice group", async () => {
  const tree = await render(jest.fn());
  const cards = tree.root.findAll((n) => (n.type as string) === "card").map((n) => n.props.label);
  expect(cards).toEqual(["Profile", "Optional", "Presets"]);
  const sex = tree.root.findAll((n) => n.props.accessibilityRole === "radiogroup" && n.props.accessibilityLabel === "Sex")[0];
  const choices = sex.findAll((n) => (n.type as string) === "choice");
  expect(choices.map((n) => n.props.label)).toEqual(["Not set", "Male", "Female", "Other"]);
  expect(choices.map((n) => n.props.selected)).toEqual([false, false, true, false]);
});

it("a choice changes the stored value, Not set clears it, and no Settings button is added", async () => {
  const onSubmit = jest.fn();
  const tree = await render(onSubmit);
  const hiv = tree.root.findAll((n) => n.props.accessibilityRole === "radiogroup" && n.props.accessibilityLabel === "HIV mortality level")[0];
  await act(async () => { hiv.findAll((n) => (n.type as string) === "choice" && n.props.label === "Not set")[0].props.onPress(); });
  await press(tree, "Save profile");
  expect(onSubmit).toHaveBeenCalledWith({ ...profile, hiv_mortality: null });
  expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Settings")).toHaveLength(0);
});
