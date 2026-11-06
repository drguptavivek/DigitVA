import { setUiLocale } from "../src/i18n";
import { syncedText } from "../src/nativeShell/shellContext";
import { displayProjectName } from "../src/projectName";

afterEach(() => setUiLocale("en"));

describe("displayProjectName", () => {
  it("title-cases an all-capitals name, keeping short words, codes and small words right", () => {
    expect(displayProjectName("GUJARAT HEALTH SYSTEM")).toBe("Gujarat Health System");
    expect(displayProjectName("PHC OF THE HILLS")).toBe("PHC of the Hills");
    expect(displayProjectName("UNSW01 KERALA")).toBe("UNSW01 Kerala");
  });

  it("leaves a mixed-case name, a caseless script and an empty name as stored", () => {
    expect(displayProjectName("Gujarat HEALTH")).toBe("Gujarat HEALTH");
    expect(displayProjectName("गुजरात स्वास्थ्य")).toBe("गुजरात स्वास्थ्य");
    expect(displayProjectName(undefined)).toBe("");
    expect(displayProjectName("")).toBe("");
  });
});

describe("syncedText", () => {
  const at = new Date(2026, 10, 3, 13, 19).getTime();

  it("says Not synced yet before the first sync", () => {
    expect(syncedText(undefined, at)).toBe("Not synced yet");
  });

  it("says today with the time on the same day, and the date otherwise", () => {
    expect(syncedText(at, new Date(2026, 10, 3, 18, 0).getTime())).toMatch(/^Synced today, 1:19\s?pm$/i);
    expect(syncedText(at, new Date(2026, 10, 4, 9, 0).getTime())).toMatch(/^Synced 3 Nov, 1:19\s?pm$/i);
  });

  it("uses the Hindi strings in Hindi", () => {
    setUiLocale("hi");
    expect(syncedText(at, new Date(2026, 10, 3, 18, 0).getTime())).toContain("आज");
  });
});
