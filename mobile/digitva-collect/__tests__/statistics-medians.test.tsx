import React from "react";
import { act, create } from "react-test-renderer";

/** Medians live on each project's Projects card; a multi-project Overview lists none, a single project keeps them. */

jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string | number> = {}) => [key, ...Object.values(values)].join(":"),
}));
jest.mock("../src/ui", () => ({
  Button: () => null,
}));

import { Medians, OverviewTab } from "../src/web/stats/OverviewTab";
import { ProjectsTab } from "../src/web/stats/ProjectsTab";

const summary = (id: string, medians: Record<string, number | null>) => ({
  project_id: id, project_name: `Name ${id}`, mode: "organization", period: "all", project_wide: true, unit: null, breadcrumb: [], rows: [],
  card: { counts: { deaths_reported: 10, submitted: 5, final_cod: 2, overdue_interview: 0, overdue_coding: 0 }, medians, causes: [], links: {} },
  thresholds: { interview_days: 7, coding_days: 7 }, freshness: null,
}) as never;
const text = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());
const full = { death_to_interview_days: 12, interview_to_final_cod_days: 3 };

const overview = (summaries: never[], sole: never | null) => (
  <OverviewTab
    summaries={summaries} sole={sole} unit={null} site={null} soleRoot={null} busy={false} pending={0} failedCount={0}
    onRetryFailed={jest.fn()} request={jest.fn()} onDrill={jest.fn()} onAttention={jest.fn()} onOpenLink={jest.fn()}
  />
);

test("a multi-project Overview has no medians list", async () => {
  const rows = [summary("P1", full), summary("P2", { death_to_interview_days: null, interview_to_final_cod_days: null })] as never[];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(overview(rows, null)); });
  expect(text(tree)).toContain("statsStageInterviewed");
  for (const key of ["statsMediansHeading", "statsMediansNone", "statsMedianInterview"]) expect(text(tree)).not.toContain(key);
  await act(async () => tree.unmount());
});

test("a Projects card shows the medians that exist and nothing when neither does", async () => {
  const projects = [{ project_id: "P1", project_name: "Name P1", mode: "organization" }, { project_id: "P2", project_name: "Name P2", mode: "organization" }, { project_id: "P3", project_name: "Name P3", mode: "organization" }] as never;
  const loads = {
    P1: { summary: summary("P1", full) },
    P2: { summary: summary("P2", { death_to_interview_days: 4, interview_to_final_cod_days: null }) },
    P3: { summary: summary("P3", { death_to_interview_days: null, interview_to_final_cod_days: null }) },
  } as never;
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<ProjectsTab projects={projects} loads={loads} onOpen={jest.fn()} onRetry={jest.fn()} />); });
  const cards = tree.root.findAll((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("statsProjectCardOpen") && typeof node.props.onPress === "function");
  const body = (i: number) => JSON.stringify(cards[i].findAll(() => true).map((n) => n.children).flat().filter((c) => typeof c === "string"));
  expect(cards).toHaveLength(3);
  expect(body(0)).toContain("statsMedianInterview:12");
  expect(body(0)).toContain("statsMedianCod:3");
  expect(body(1)).toContain("statsMedianInterview:4");
  expect(body(1)).not.toContain("statsMedianCod");
  expect(body(2)).not.toContain("statsMedian");
  await act(async () => tree.unmount());
});

test("one project's medians render as lines, with the none line when it has no medians", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Medians summary={summary("P1", full)} />); });
  expect(text(tree)).toContain("statsMedianInterview:12");
  await act(async () => { tree.update(<Medians summary={summary("P1", { death_to_interview_days: null, interview_to_final_cod_days: null })} />); });
  expect(text(tree)).toContain("statsMediansNone");
  await act(async () => tree.unmount());
});
