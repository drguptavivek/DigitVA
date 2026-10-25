import React, { act } from "react";
import { ScrollView, StyleSheet, Text } from "react-native";
import { create, type ReactTestRenderer } from "react-test-renderer";

import { caseStripParts, formatLiveCaseSummary, InterviewCaseStrip } from "../src/web/InterviewCaseStrip";
import { Screen } from "../src/ui";
import { setUiLocale } from "../src/i18n";

beforeEach(() => setUiLocale("en"));

const deceased = { givenNames: "Asha", surname: "Devi", sex: "female", dateOfDeath: "2026-09-22" };

it("joins name, age, sex and date of death as plain text without field labels", () => {
  const parts = caseStripParts({ deceased: { ...deceased, ageInYears: 51 } } as never);
  expect(parts).toEqual(["Asha Devi", "51 y", "Female", "Died 2026-09-22"]);
  expect(parts.join(" · ")).not.toMatch(/Age:|Sex:/);
});

it("derives age from the exact date of birth, ahead of the stored age", () => {
  expect(caseStripParts({ deceased: { ...deceased, dateOfBirth: "1975-09-23" } } as never)[1]).toBe("50 y");
  expect(caseStripParts({ deceased: { ...deceased, dateOfBirth: "1975-09-22" } } as never)[1]).toBe("51 y");
});

it("derives age from a partial date of birth and shows infants in months and days", () => {
  expect(caseStripParts({ deceased, answers: { dob_month_year: "1975-10-01" } } as never)[1]).toBe("50 y");
  expect(caseStripParts({ deceased, answers: { dob_year: "1975-01-01" } } as never)[1]).toBe("51 y");
  expect(caseStripParts({ deceased: { ...deceased, dateOfBirth: "2026-02-10" } } as never)[1]).toBe("7 m");
  expect(caseStripParts({ deceased: { ...deceased, dateOfBirth: "2026-09-10" } } as never)[1]).toBe("12 d");
});

it("falls back to the registered child age and omits unknown parts", () => {
  const parts = caseStripParts({ deceased: { sex: "undetermined", dateOfDeath: "2026-09-22" }, answers: { age_child_unit: "years", age_child_years: 4 } } as never);
  expect(parts).toEqual(["4 y", "Undetermined", "Died 2026-09-22"]);
});

it("is empty without a deceased block", () => {
  expect(caseStripParts({ answers: {} } as never)).toEqual([]);
  expect(caseStripParts(undefined)).toEqual([]);
});

it("pins to the very top of the scroller, opaque and above the form's own sticky progress", () => {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<InterviewCaseStrip prefill={{ deceased } as never} />); });
  const strip = tree.root.find((node) => node.props.nativeID === "digitva-interview-case-strip");
  const style = StyleSheet.flatten(strip.props.style) as Record<string, unknown>;
  expect(style).toMatchObject({ position: "sticky", top: 0 });
  expect(style.zIndex).toBeGreaterThan(0);
  expect(style.zIndex).toBeLessThan(35); // under the phone bottom bar (35) and the leave dialog (60)
  expect(style.backgroundColor).toBeTruthy();
});

it("with a lead, Screen scrolls the lead and the title row with the content, so only the strip stays pinned", () => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <Screen title="WHO verbal autopsy" sidebar={<Text>menu</Text>} lead={<Text>header bar</Text>}>
        <InterviewCaseStrip prefill={{ deceased } as never} />
      </Screen>
    );
  });
  const scroller = tree.root.findByType(ScrollView);
  const inside = (text: string) => scroller.findAll((node) => node.type === Text && node.props.children === text).length > 0;
  expect(inside("header bar")).toBe(true);
  expect(inside("WHO verbal autopsy")).toBe(true);
  expect(scroller.findAll((node) => node.props.nativeID === "digitva-interview-case-strip").length).toBeGreaterThan(0);
  // Without a lead the title row stays above the scroller, as on every other screen.
  act(() => { tree.update(<Screen title="Collection" sidebar={<Text>menu</Text>}><Text>body</Text></Screen>); });
  const plain = tree.root.findByType(ScrollView);
  expect(plain.findAll((node) => node.type === Text && node.props.children === "body").length).toBe(1);
  expect(plain.findAll((node) => node.type === Text && node.props.children === "Collection")).toHaveLength(0);
  expect(tree.root.findAll((node) => node.type === Text && node.props.children === "Collection").length).toBe(1);
});

it("formats live case summary placeholders for an empty direct interview and updates as answers arrive", () => {
  expect(formatLiveCaseSummary(undefined, {}).join(" · ")).toBe("— · DOD: — · Age: — · Sex: —");

  expect(
    formatLiveCaseSummary(undefined, {
      Id10017: "Ramesh",
      Id10018: "Kumar",
      Id10023: "2026-10-01",
      ageInYears: 64,
      Id10019: "male",
    }).join(" · "),
  ).toBe("Ramesh Kumar · DOD: 2026-10-01 · Age: 64 yr · Sex: Male");

  expect(
    formatLiveCaseSummary(undefined, {
      Id10023: "2026-10-01",
      dob_known: "yes",
      dob_type: "month_year",
      dob_month_year: "1980-05",
    }).join(" · "),
  ).toBe("— · DOD: 2026-10-01 · Age: ~46 yr · Sex: —");
});

it("renders the case id, location, save status and live summary row when showLiveSummary is enabled", () => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <InterviewCaseStrip
        prefill={undefined}
        showLiveSummary
        uniqueId="PHC01-000146"
        locationLabel="PHC-AAM PHC 1"
        saveStatus="Saved 23:19:18 (8 sections)"
        answers={{}}
      />,
    );
  });
  const meta = tree.root.findByProps({ testID: "interview-case-meta" });
  const save = tree.root.findByProps({ testID: "interview-save-status" });
  const summary = tree.root.findByProps({ testID: "interview-case-summary" });
  expect(meta.props.children).toBe("Case id PHC01-000146 · PHC-AAM PHC 1");
  expect(save.props.children).toBe("Saved 23:19:18 (8 sections)");
  expect(summary.props.children).toBe("— · DOD: — · Age: — · Sex: —");

  act(() => {
    tree.update(
      <InterviewCaseStrip
        prefill={undefined}
        showLiveSummary
        uniqueId="PHC01-000146"
        locationLabel="PHC-AAM PHC 1"
        saveStatus="Saved 23:19:18 (8 sections)"
        answers={{ Id10017: "Asha", Id10018: "Devi", Id10023: "2026-09-22", ageInYears: 51, Id10019: "female" }}
      />,
    );
  });
  expect(tree.root.findByProps({ testID: "interview-case-summary" }).props.children).toBe(
    "Asha Devi · DOD: 2026-09-22 · Age: 51 yr · Sex: Female",
  );
});
