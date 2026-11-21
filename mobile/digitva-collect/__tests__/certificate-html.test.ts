jest.mock("expo-print", () => ({ printToFileAsync: jest.fn(async () => ({ uri: "file:///cache/Print/x.pdf" })) }));
const mockRename = jest.fn();
jest.mock("expo-file-system", () => ({ File: jest.fn().mockImplementation((uri: string) => ({ uri, rename: mockRename })) }));
jest.mock("../src/standalone/shareFile", () => ({ shareAndDelete: jest.fn(async () => undefined) }));

import { printToFileAsync } from "expo-print";

import { certificateHtml, parseCertificate } from "../src/workspace/certificate";
import { sharePdf } from "../src/workspace/certificatePdf.native";
import { shareAndDelete } from "../src/standalone/shareFile";

const reply = {
  project_name: "Proj <b>", case_id: "MASK-1", age: 50, sex: "female", date_of_death: "",
  part1: [{ conditions: [{ text: "<script>alert(1)</script>", code: "1G41" }], interval: "3 days" }],
  part2: [{ text: "Diabetes", code: "5A14" }],
  underlying_cause: "1B10 Tuberculosis", outcome: "not reviewed", coded_at: "2026-11-20T10:00:00+00:00",
  generated_at: null, coded_by: null, reviewed_by: null, deceased_name: null, address: null,
  place_of_death: null, respondent: null, real_id: null, redacted: true,
};

describe("certificateHtml", () => {
  const html = certificateHtml(parseCertificate(reply));

  it("has Part I lines (padded to four), Part II and the underlying cause", () => {
    expect(html).toContain("(a)");
    expect(html).toContain("(d)");
    expect(html).toContain("3 days");
    expect(html).toContain("Other significant conditions");
    expect(html).toContain("Diabetes");
    expect(html).toContain("Underlying cause of death");
    expect(html).toContain("1B10 Tuberculosis");
  });

  it("escapes every text and prints a dash for redacted fields", () => {
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).toContain("Proj &lt;b&gt;");
    expect(html).toContain("<th>Deceased</th><td colspan=\"2\">—</td>");
  });

  it("refuses a reply that is not a certificate", () => {
    expect(() => parseCertificate({ error: "x" })).toThrow();
  });
});

it("sharePdf prints the HTML to an A4 PDF named after the case and shares it as application/pdf", async () => {
  await sharePdf("<html></html>", "COD-form-AAM125/000030 x");
  expect(mockRename).toHaveBeenCalledWith("COD-form-AAM125_000030_x.pdf");
  expect(printToFileAsync).toHaveBeenCalledWith({ html: "<html></html>", width: 595, height: 842 });
  expect(shareAndDelete).toHaveBeenCalledWith(expect.objectContaining({ uri: "file:///cache/Print/x.pdf" }), "application/pdf");
});


test("dates print as DD-MMM-YYYY HH:MM:SS and DD-MMM-YYYY", () => {
  const { formatWhen, formatDate } = require("../src/workspace/certificate");
  const local = new Date(2026, 9, 21, 20, 7, 1).toISOString();
  expect(formatWhen(local)).toBe("21-Oct-2026 20:07:01");
  expect(formatDate("2026-10-12")).toBe("12-Oct-2026");
});
