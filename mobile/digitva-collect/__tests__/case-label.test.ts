import { cardAge, formatCardDate, shortCaseNumber } from "../src/workspace/caseLabel";

test("short case number from a masked id", () => {
  expect(shortCaseNumber("PHC01-000020_172313647")).toBe("000020");
  expect(shortCaseNumber("PHC01-000020")).toBeUndefined();
  expect(shortCaseNumber("CODER-MASKED-1")).toBeUndefined();
  expect(shortCaseNumber("odd id")).toBeUndefined();
  expect(shortCaseNumber(null)).toBeUndefined();
});

describe("formatCardDate", () => {
  test("a plain date is that day as written", () => {
    expect(formatCardDate("2026-10-03")).toBe("03-Oct-2026");
    expect(formatCardDate("2025-01-31")).toBe("31-Jan-2025");
  });
  test("a timestamp is its local day", () => {
    const at = new Date(2026, 11, 9, 12, 0, 0);
    expect(formatCardDate(at.toISOString())).toBe("09-Dec-2026");
  });
  test("a timestamp without an offset is read as UTC", () => {
    const at = new Date(Date.UTC(2026, 3, 24, 12, 0, 0));
    const local = `${String(at.getDate()).padStart(2, "0")}-Apr-2026`;
    expect(formatCardDate("2026-04-24T12:00:00")).toBe(local);
    expect(formatCardDate("2026-04-24T12:00:00.123456")).toBe(local);
  });
  test("nothing or anything unreadable is null", () => {
    for (const raw of [null, undefined, "", "  ", "not a date", "2026-13-01"]) expect(formatCardDate(raw)).toBeNull();
  });
});

describe("cardAge", () => {
  test("days under a month, whole months under a year, else whole years", () => {
    expect(cardAge(0, 0)).toEqual({ unit: "d", n: 0 });
    expect(cardAge(29, 0)).toEqual({ unit: "d", n: 29 });
    expect(cardAge(29.9, 0)).toEqual({ unit: "d", n: 29 });
    expect(cardAge(30, 0)).toEqual({ unit: "m", n: 1 });
    expect(cardAge(31, 0)).toEqual({ unit: "m", n: 1 });
    expect(cardAge(335, 0)).toEqual({ unit: "m", n: 11 });
    expect(cardAge(364, 0)).toEqual({ unit: "m", n: 11 });
    expect(cardAge(365, 1)).toEqual({ unit: "y", n: 1 });
    expect(cardAge(34 * 365.25 + 10, 34)).toEqual({ unit: "y", n: 34 });
  });
  test("without days the given years; missing or malformed is null", () => {
    expect(cardAge(undefined, 52)).toEqual({ unit: "y", n: 52 });
    expect(cardAge(null, "7")).toEqual({ unit: "y", n: 7 });
    expect(cardAge(null, null)).toBeNull();
    expect(cardAge(undefined, "")).toBeNull();
    expect(cardAge(-1, "x")).toBeNull();
  });
});
