import { matchesSearch, normaliseSearch } from "../src/ui/caseSearch";
import { pickerModel, recentTarget, rowLabel, type PickerTarget } from "../src/ui/sitePicker";
import { isInternalPlaceholderUnit as fromCaseFilters } from "../src/web/caseFilters";
import { isInternalPlaceholderUnit } from "../src/ui/placeholderUnit";
import {
  buildInterviewItems, filterInterviews, interviewCounts, parseInterviewFilter,
  type InterviewSources,
} from "../src/ui/interviewRows";
import { homeSummary } from "../src/ui/homeSummary";

describe("search matching", () => {
  it("is case-insensitive and matches every word in any field", () => {
    expect(matchesSearch(["Ramesh Kumar", "AAM01-000002"], "ramesh 0002")).toBe(true);
    expect(matchesSearch(["Ramesh Kumar"], "suresh")).toBe(false);
    expect(matchesSearch(["x"], "   ")).toBe(true);
    expect(matchesSearch([null, undefined, "CHC Bhoranj"], "BHORANJ")).toBe(true);
  });

  it("matches Hindi and treats decomposed and composed forms alike", () => {
    expect(matchesSearch(["रमेश कुमार", "गाँव हमीरपुर"], "रमेश")).toBe(true);
    expect(matchesSearch(["रमेश कुमार"], "हमीर")).toBe(false);
    // A keyboard that sends a decomposed sequence still finds the composed text, and the reverse.
    expect(normaliseSearch("Zoe\u0308")).toBe(normaliseSearch("Zo\u00EB"));
    expect(matchesSearch(["Zo\u00EB"], "zoe\u0308")).toBe(true);
    expect(matchesSearch(["Zoe\u0308"], "zo\u00EB")).toBe(true);
    // Devanagari: the precomposed U+0929 equals U+0928 U+093C after NFC.
    expect(matchesSearch(["\u0929ाम"], "\u0928\u093Cाम")).toBe(true);
  });

  it("keeps matras: राम and रम are different words", () => {
    expect(matchesSearch(["राम"], "रम")).toBe(false);
  });
});

describe("site/unit picker model", () => {
  const unit = (siteId: string, siteName: string, unitName: string | undefined, id = unitName): PickerTarget => ({
    key: `P1:${siteId}:${id}`, label: unitName ? `${siteName} · ${unitName}` : siteName, projectId: "P1", siteId, orgUnitId: unitName ? `U-${id}` : undefined, siteName, unitName,
  });

  it("shows unit names only, with no site headers for a single site", () => {
    const model = pickerModel([unit("S1", "Bhoranj block", "CHC Bhoranj"), unit("S1", "Bhoranj block", "PHC Tauni Devi")]);
    expect(model.headers).toBe(false);
    expect(model.groups).toHaveLength(1);
    expect(model.groups[0].title).toBeUndefined();
    expect(model.groups[0].rows.map((row) => row.label)).toEqual(["CHC Bhoranj", "PHC Tauni Devi"]);
  });

  it("groups under a site header only when more than one real site is reachable", () => {
    const model = pickerModel([unit("S1", "Bhoranj block", "CHC Bhoranj"), unit("S2", "Nadaun block", "CHC Nadaun"), unit("S2", "Nadaun block", "AAM02")]);
    expect(model.headers).toBe(true);
    expect(model.groups.map((group) => [group.title, group.rows.map((row) => row.label)])).toEqual([
      ["Bhoranj block", ["CHC Bhoranj"]],
      ["Nadaun block", ["CHC Nadaun", "AAM02"]],
    ]);
  });

  it("drops placeholder units while a real one exists, and falls back to raw labels when none does", () => {
    const real = unit("S1", "Site A", "CHC A");
    const placeholder = unit("S1", "Site A", "sites_in_project_P1", "ph");
    expect(pickerModel([placeholder, real]).groups[0].rows.map((row) => row.label)).toEqual(["CHC A"]);
    const only = pickerModel([placeholder]);
    expect(only.groups[0].rows.map((row) => row.label)).toEqual(["Site A · sites_in_project_P1"]);
  });

  it("uses the site name when the project has no unit tree, and the raw label for the fixture without parts", () => {
    expect(rowLabel({ key: "k", label: "Site 1", projectId: "P1", siteId: "S1" })).toBe("Site 1");
    expect(rowLabel({ key: "k", label: "Site 1 label", projectId: "P1", siteId: "S1", siteName: "Site 1" })).toBe("Site 1");
  });

  it("searches unit and site names, case-insensitively", () => {
    const targets = [unit("S1", "Bhoranj block", "CHC Bhoranj"), unit("S2", "Nadaun block", "AAM02")];
    expect(pickerModel(targets, "aam").groups.flatMap((g) => g.rows.map((r) => r.label))).toEqual(["AAM02"]);
    expect(pickerModel(targets, "nadaun").groups.flatMap((g) => g.rows.map((r) => r.label))).toEqual(["AAM02"]);
    expect(pickerModel(targets, "zzz").groups).toEqual([]);
  });

  it("finds the remembered target by site and unit, and ignores one no longer offered", () => {
    const a = unit("S1", "A", "CHC A");
    const b = unit("S1", "A", "PHC B");
    expect(recentTarget([a, b], { siteId: "S1", orgUnitId: "U-PHC B" })).toBe(b);
    expect(recentTarget([a, b], { siteId: "S1", orgUnitId: "gone" })).toBeUndefined();
    expect(recentTarget([a, b], undefined)).toBeUndefined();
  });

  it("shares isInternalPlaceholderUnit with the browser filters", () => {
    expect(fromCaseFilters).toBe(isInternalPlaceholderUnit);
    expect(isInternalPlaceholderUnit("Sites_In_Project_X")).toBe(true);
    expect(isInternalPlaceholderUnit("CHC")).toBe(false);
    expect(isInternalPlaceholderUnit("")).toBe(true);
  });
});

describe("interview items", () => {
  const draft = (id: string, extra = {}) => ({ id, project_id: "P1", site_id: "S1", org_unit_id: null, completed: 0, updated_at: "2026-10-23T13:40:00.000Z", death_id: null, unique_id: null, client_death_id: null, ...extra }) as never;
  const caseRow = (id: string, extra = {}) => ({
    death_id: id, unique_id: `AAM01-${id}`, project_id: "P1", site_id: "S1", org_unit_id: null, unit_name: "CHC Bhoranj", state: "registered",
    source: "reported", my_draft_id: null, updated_at: "2026-10-01T00:00:00Z", next_visit_at: null, last_contact_at: null,
    deceased: { name: `Name ${id}`, sex: "male", age_years: 68, date_of_birth: null, date_of_birth_partial: null, date_of_death: "2026-09-12", place_of_death: null },
    household_address: { address: null, house_street: null, village_ward: "Hamirpur", landmark: null }, ...extra,
  }) as never;
  const sources = (extra: Partial<InterviewSources> = {}): InterviewSources => ({ drafts: [], registrations: [], cases: [], onlineCases: [], submitted: [], revisions: [], ...extra });

  it("gives every card a name title, a muted ID, a badge and at most one primary action", () => {
    const items = buildInterviewItems(sources({
      drafts: [draft("d1", { death_id: "C1", unique_id: "AAM01-C1" })],
      cases: [caseRow("C1"), caseRow("C2"), caseRow("C3", { state: "submitted" })],
      submitted: [{ draft_id: "s1", project_id: "P1", site_id: "S1", death_id: null, va_sid: "v", unique_id: "SENT-1", deceased_name: "Asha Rao", updated_at: "2026-10-02T00:00:00Z" }],
      revisions: [{ draft_id: "r1", project_id: "P1", site_id: "S1", death_id: null, va_sid: "v", unique_id: "REV-1", deceased_name: "Mohan Lal", state: "editing", refusal_code: null, updated_at: "2026-10-03T00:00:00Z" } as never],
    }));
    const byKey = Object.fromEntries(items.map((item) => [item.key, item]));
    // C1 appears once, as its draft, titled with the case's name and carrying the case facts.
    expect(items.filter((item) => item.title === "Name C1")).toHaveLength(1);
    expect(byKey["draft-d1"]).toMatchObject({ kind: "drafts", title: "Name C1", caseId: "AAM01-C1", ageYears: 68, unit: "CHC Bhoranj", action: { type: "resume", label: "Resume" } });
    expect(byKey["case-C2"]).toMatchObject({ kind: "todo", title: "Name C2", caseId: "AAM01-C2", action: { type: "case", label: "Start" } });
    expect(byKey["case-C3"]).toMatchObject({ kind: "sent" });
    expect(byKey["sent-s1"]).toMatchObject({ kind: "sent", title: "Asha Rao", caseId: "SENT-1", action: { type: "revise" } });
    expect(byKey["revision-r1"]).toMatchObject({ kind: "revisions", title: "Mohan Lal", caseId: "REV-1", action: { type: "revise" } });
    for (const item of items) expect([0, 1]).toContain(item.action ? 1 : 0);
    expect(items.map((item) => item.kind)).toEqual(["drafts", "revisions", "todo", "sent", "sent"]);
  });

  it("offers no action on a draft already marked ready to send, and the ID alone when no name is known", () => {
    const [ready] = buildInterviewItems(sources({ drafts: [draft("d2", { completed: 1, unique_id: "VA-9" })] }));
    expect(ready.action).toBeUndefined();
    expect(ready.title).toBe("VA-9");
    expect(ready.caseId).toBeUndefined();
  });

  it("shows why the server refused a draft: 'Not accepted: <reason>', and a held 409 with its retry", () => {
    const refusals = new Map([
      ["d1", { ref: "HTTP 422", message: "Record the name, date of death and sex of the deceased before submitting.", at: "" }],
      ["d2", { ref: "HTTP 409", message: "This case is closed.", at: "" }],
    ]);
    const items = buildInterviewItems(sources({
      drafts: [draft("d1"), draft("d2", { completed: 1, upload_issue: "case_conflict" }), draft("d3")],
      refusals,
    }));
    const byKey = Object.fromEntries(items.map((item) => [item.key, item]));
    expect(byKey["draft-d1"].lines).toEqual([{ text: "Not accepted: Record the name, date of death and sex of the deceased before submitting.", tone: "error" }]);
    expect(byKey["draft-d1"].action).toMatchObject({ type: "resume" });
    expect(byKey["draft-d2"].lines.map((line) => line.text)).toEqual([
      "Not accepted: This case is closed.",
      expect.stringContaining("Held:"),
    ]);
    expect(byKey["draft-d2"].retryDemo).toBeTruthy();
    expect(byKey["draft-d2"].retryLabel).toBe("Send again");
    expect(byKey["draft-d3"].lines).toEqual([]);
  });

  it("counts per chip and filters by chip and search together", () => {
    const items = buildInterviewItems(sources({
      drafts: [draft("d1"), draft("d2")],
      cases: [caseRow("C1"), caseRow("C2"), caseRow("C3")],
      registrations: [{ client_death_id: "R1", project_id: "P1", site_id: "S1", org_unit_id: null, fields: { deceased_name: "Unsent Person", deceased_sex: "female", date_of_death: "2026-10-01" }, state: "queued", created_at: "2026-10-04T00:00:00Z" } as never],
    }));
    expect(interviewCounts(items)).toEqual({ all: 6, drafts: 3, todo: 3, sent: 0, revisions: 0 });
    expect(filterInterviews(items, "todo", "")).toHaveLength(3);
    expect(filterInterviews(items, "all", "name c2").map((item) => item.title)).toEqual(["Name C2"]);
    expect(filterInterviews(items, "todo", "hamirpur")).toHaveLength(3); // village is searchable
    expect(filterInterviews(items, "drafts", "name c2")).toEqual([]);
    expect(filterInterviews(items, "all", "AAM01-C3").map((item) => item.title)).toEqual(["Name C3"]);
  });

  it("searches Hindi names", () => {
    const items = buildInterviewItems(sources({ cases: [caseRow("C1", { deceased: { name: "रमेश कुमार", sex: "male", age_years: 60, date_of_death: null } })] }));
    expect(filterInterviews(items, "all", "रमेश")).toHaveLength(1);
    expect(filterInterviews(items, "all", "सुरेश")).toHaveLength(0);
  });

  it("parses the chip from the route and falls back to All", () => {
    expect(parseInterviewFilter("todo")).toBe("todo");
    expect(parseInterviewFilter(["sent"])).toBe("sent");
    expect(parseInterviewFilter("nope")).toBe("all");
    expect(parseInterviewFilter(undefined)).toBe("all");
  });

  it("summarises Home from the same items: drafts in progress and cases needing a visit (unsent is shared, see unsent-work.test)", () => {
    const items = buildInterviewItems(sources({ drafts: [draft("d1"), draft("d2", { completed: 1 })], cases: [caseRow("C1"), caseRow("C2")] }));
    const summary = homeSummary(items, interviewCounts(items));
    expect(summary.inProgress).toHaveLength(1);
    expect(summary.needVisit).toBe(2);
  });
});
