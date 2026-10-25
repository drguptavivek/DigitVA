import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { validateRegistration as validateNative } from "../src/cases";
import { validateRegistration as validateWeb } from "../src/cases.web";

test("browser case entrypoint does not pull the native draft store or WHO package", () => {
  const source = readFileSync(resolve(__dirname, "../src/cases.web.ts"), "utf8");
  expect(source).not.toMatch(/(?:drafts|@drguptavivek\/who-2022-va)/);
});

test("browser and native registration validation use the same rules", () => {
  const fields = {
    deceased_name: "Asha",
    deceased_sex: "female",
    date_of_death: "2026-10-02",
    date_of_birth_partial: "1987-04",
    informant_phone: "987 654 3210",
  };
  expect(validateWeb(fields, "2026-10-25")).toEqual(validateNative(fields, "2026-10-25"));
});
