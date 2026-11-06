import { Platform } from "react-native";

import { formatDisplayTimestamp } from "../src/ui/CaseCard";

const original = Platform.OS;
afterEach(() => { Platform.OS = original; });

it("writes the phone's timestamp like formatWhen and keeps the web's ISO form", () => {
  const iso = new Date(2026, 10, 6, 4, 50).toISOString();
  Platform.OS = "android";
  expect(formatDisplayTimestamp(iso)).toMatch(/^6 Nov 2026, 4:50\s?am$/i);
  expect(formatDisplayTimestamp("2026-11-03")).toBe("3 Nov 2026");
  expect(formatDisplayTimestamp("not a date")).toBe("not a date");
  expect(formatDisplayTimestamp(null)).toBe("");
  Platform.OS = "web";
  expect(formatDisplayTimestamp(iso)).toBe("2026-11-06 04:50");
  expect(formatDisplayTimestamp("2026-11-03")).toBe("2026-11-03");
});
