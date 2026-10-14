import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { collapseBlankLines, certificateTitle, icd11Alternatives, summaryChecks } from "../src/workspace/doris/resultSummary";
import { SearchBox } from "../src/workspace/doris/compact";
import { wholeNumberText } from "../src/workspace/SmartVaReference";
import type { JsonObject } from "../src/workspace/contracts";

describe("collapseBlankLines", () => {
  it("collapses a run of two or more blank lines to one and drops trailing spaces", () => {
    expect(collapseBlankLines("a\n\n\n\nb")).toBe("a\n\nb");
    expect(collapseBlankLines("a\n \t\n\nb")).toBe("a\n\nb");
    expect(collapseBlankLines("a\r\n\r\n\r\nb")).toBe("a\n\nb");
    expect(collapseBlankLines("a\n\nb")).toBe("a\n\nb");
  });
  it("is empty for empty, blank or missing text", () => {
    expect(collapseBlankLines("")).toBe("");
    expect(collapseBlankLines("  \n\n  ")).toBe("");
    expect(collapseBlankLines(undefined)).toBe("");
    expect(collapseBlankLines(null)).toBe("");
  });
});

describe("summaryChecks", () => {
  it("explains a bare DORIS rule id from its report and spells out TUC and TSP", () => {
    const checks = summaryChecks(
      { status: "completed", result: { warning: "M4 may have been applied.\nM1: Manual check is needed.", report: "M4: Adding the main injury - NC72.Z - as postcoordination for the current TUC - PA60." } },
      { status: "completed", result: {} },
    );
    expect(checks.map((check) => check.text)).toEqual([
      "M4 may have been applied: Adding the main injury - NC72.Z - as postcoordination for the current tentative underlying cause - PA60.",
      "M1: Manual check is needed.",
    ]);
  });
  it("turns a bare CoDEdit key into WHO's sentence with its parameters", () => {
    const checks = summaryChecks(
      { status: "completed", result: {} },
      { status: "completed", result: { issueIds: "BER-CE-9", report: "RE_W_IV_CodeURIMismatch", tabularReport: "0,RE_W_IV_CodeURIMismatch,BER-CE-9;5A11/GB61.Z;;;" } },
    );
    expect(checks.map((check) => check.text)).toEqual(["The selected code - 5A11/GB61.Z - and URI correspond to different ICD entities for the same condition. Please verify that the code and the associated URI refer to the same ICD category."]);
  });
  it("adds nothing for an empty CoDEdit issue list, and says when CoDEdit did not run", () => {
    expect(summaryChecks({ status: "completed", result: {} }, { status: "completed", result: { issueIds: [], report: "", tabularReport: "" } })).toEqual([]);
    expect(summaryChecks({ status: "completed", result: {} }, { status: "unavailable", result: null }).map((check) => check.text)).toEqual(["The certificate check (CoDEdit) did not run."]);
  });
});

describe("certificateTitle and icd11Alternatives", () => {
  const certificate = { Part1: [{ Conditions: [{ Code: "CA40", Text: "Pneumonia" }] }], Part2: { Conditions: [] } } as unknown as JsonObject;
  it("finds the typed text for a code on the certificate, else empty", () => {
    expect(certificateTitle(certificate, ["CA40"])).toBe("Pneumonia");
    expect(certificateTitle(certificate, ["ZZ99"])).toBe("");
  });
  it("splits the WHO ICD-11 target on / and uppercases it, as the server does", () => {
    expect(icd11Alternatives("ca40 / ca41")).toEqual(["CA40", "CA41"]);
    expect(icd11Alternatives(null)).toEqual([]);
    expect(icd11Alternatives("")).toEqual([]);
  });
});

describe("wholeNumberText", () => {
  it("shows an integral age without its decimal point and leaves other values as served", () => {
    expect(wholeNumberText("28.0")).toBe("28");
    expect(wholeNumberText("28.5")).toBe("28.5");
    expect(wholeNumberText("")).toBe("");
    expect(wholeNumberText("unknown")).toBe("unknown");
  });
});

describe("SearchBox height", () => {
  it("is one control high with no flex basis, so it cannot stretch to 200 points in a column card", () => {
    let tree!: ReactTestRenderer;
    act(() => { tree = create(<SearchBox label="Search" iconLabel="Open search" onOpen={() => undefined} />); });
    let node: ReactTestRenderer["root"] | null = tree.root.findByProps({ accessibilityLabel: "Search" });
    while (node && !(node.props.style && Object.assign({}, ...[node.props.style].flat(3).filter(Boolean)).borderWidth === 1)) node = node.parent;
    expect(node).not.toBeNull();
    const style = Object.assign({}, ...[node!.props.style].flat(3).filter(Boolean));
    expect(style.height).toBeGreaterThan(0);
    expect(style.flexBasis).toBeUndefined();
    act(() => tree.unmount());
  });
});
