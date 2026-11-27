/** LocalCasesRow is disabled while the ICD-11/DORIS preference is off. */
import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
let mockEnabled = false;
jest.mock("../src/icd11DorisPreference", () => ({ useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: mockEnabled }) }));

import { LocalCasesRow } from "../src/ui/CodingCaseChips";
import { t } from "../src/i18n";

const row = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props.label === t("localCases") && typeof n.props.onPress === "function")[0];

it("is disabled while the preference is off and enabled when on", async () => {
  let tree!: ReturnType<typeof create>;
  mockEnabled = false;
  await act(async () => { tree = create(<LocalCasesRow userId="u1" />); });
  expect(row(tree).props.disabled).toBe(true);
  mockEnabled = true;
  await act(async () => { tree.update(<LocalCasesRow userId="u1" />); });
  expect(row(tree).props.disabled).toBe(false);
});
