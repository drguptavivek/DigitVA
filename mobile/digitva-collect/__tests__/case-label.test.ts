import { shortCaseNumber } from "../src/workspace/caseLabel";

test("short case number from a masked id", () => {
  expect(shortCaseNumber("PHC01-000020_172313647")).toBe("000020");
  expect(shortCaseNumber("PHC01-000020")).toBeUndefined();
  expect(shortCaseNumber("CODER-MASKED-1")).toBeUndefined();
  expect(shortCaseNumber("odd id")).toBeUndefined();
  expect(shortCaseNumber(null)).toBeUndefined();
});
