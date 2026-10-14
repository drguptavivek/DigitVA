import { readFileSync } from "fs";
import { join } from "path";

import { dorisWarningPatterns } from "../src/workspace/doris/dorisMessages";
import { describeDorisWarning, dorisWarningCodes } from "../src/workspace/doris/dorisWarnings";
import { summaryChecks } from "../src/workspace/doris/resultSummary";
import { definitionPlainText } from "../src/workspace/doris/CodeDetailsSheet";

// The same cases the web check (tests/js/doris_warnings_check.mjs) runs against doris_warnings.js.
const fixture = JSON.parse(readFileSync(join(__dirname, "../../../tests/fixtures/doris_warning_cases.json"), "utf8")) as {
  cases: Array<{ name: string; warning: string; report: string; titles: Record<string, string>; expect: { text: string; original: string | null; code: string | null } }>;
};

describe("DORIS warning reader parity with the web", () => {
  it.each(fixture.cases.map((testCase) => [testCase.name, testCase] as const))("%s", (_name, testCase) => {
    const got = describeDorisWarning(testCase.warning, testCase.report, (code) => testCase.titles[code]);
    expect(got).toEqual({ text: testCase.expect.text, original: testCase.expect.original, code: testCase.expect.code });
  });

  it("names the codes of known warnings and no others", () => {
    expect(dorisWarningCodes("No injury found to postcoordinate with the TUC - PA78&XE9H6.\nM4 may have been applied.")).toEqual(["PA78&XE9H6"]);
    expect(dorisWarningCodes("M4 may have been applied.")).toEqual([]);
  });

  it("uses the same catalogue entries as the web table", () => {
    const web = readFileSync(join(__dirname, "../../../app/static/js/doris_messages.js"), "utf8");
    for (const entry of dorisWarningPatterns) expect(web).toContain(JSON.stringify(entry.pattern).slice(1, -1));
    expect(dorisWarningPatterns.map((entry) => entry.id)).toEqual(expect.arrayContaining(["injury_for_external_cause", "underlying_cause_inconsistent_with_manner"]));
  });

  it("keeps DORIS's text underneath a known warning in the Expo checks", () => {
    const checks = summaryChecks(
      { status: "completed", result: { warning: "No injury found to postcoordinate with the TUC - PA78&XE9H6.", report: "" } },
      { status: "completed", result: {} },
      (code) => (code === "PA78&XE9H6" ? "Fall on same level" : undefined),
    );
    expect(checks).toHaveLength(1);
    expect(checks[0].text).toContain("DORIS picked PA78&XE9H6 (Fall on same level), an external cause.");
    expect(checks[0].original).toBe("No injury found to postcoordinate with the TUC - PA78&XE9H6.");
  });
});

describe("VA definition shown in the cause details sheet", () => {
  it("is plain text: tags are dropped, common entities decoded, never HTML", () => {
    expect(definitionPlainText("<p>Death <em>from</em> a fall &amp; &quot;injury&quot;.</p>\n<p>Second&nbsp;line</p>")).toBe('Death from a fall & "injury". Second line');
    expect(definitionPlainText("<script>alert(1)</script>Text")).toBe("alert(1) Text");
    expect(definitionPlainText("")).toBe("");
  });
});
