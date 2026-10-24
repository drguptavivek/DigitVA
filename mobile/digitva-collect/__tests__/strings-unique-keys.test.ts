/** Two workers adding the same key silently overrode one meaning (2026-10-24); JSON.parse keeps only the last one. */
import { readFileSync } from "fs";
import { join } from "path";

test.each(["en", "hi"])("%s.json has no duplicate keys", (locale) => {
  const text = readFileSync(join(__dirname, "..", "src", "strings", `${locale}.json`), "utf8");
  const keys = [...text.matchAll(/^\s*"([^"]+)":/gm)].map((match) => match[1]);
  expect(keys.length).toBeGreaterThan(100);
  expect(keys.filter((key, index) => keys.indexOf(key) !== index)).toEqual([]);
});
