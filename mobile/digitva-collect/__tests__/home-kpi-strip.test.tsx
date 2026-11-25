import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockRequest = jest.fn();

jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/ui", () => ({
  useUiStyles: () => ({ card: {}, text: {}, muted: {} }),
}));

import { KpiStrip } from "../src/web/KpiStrip";

const CSRF = { header: "X-CSRFToken", token: "csrf-token" };

function project(overrides: Record<string, unknown> = {}) {
  return {
    project_id: "P1", project_name: "Project One", deaths_reported: 12,
    interviews_done: 6, coded: 3, interviews_pct: 50, coded_pct: 25, ...overrides,
  };
}

/** All rendered strings joined in order, so a line split across nested Text nodes reads as one. */
function textOf(tree: ReactTestRenderer): string {
  const walk = (node: unknown): string => {
    if (typeof node === "string") return node;
    if (Array.isArray(node)) return node.map(walk).join("");
    if (node && typeof node === "object" && "children" in node) return walk((node as { children: unknown }).children ?? []);
    return "";
  };
  return walk(tree.toJSON());
}

/** Each project row's spoken sentence: the table's cells read as one line. */
function rowLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((node) => (node.type as unknown) === "View" && typeof node.props.accessibilityLabel === "string")
    .map((node) => node.props.accessibilityLabel as string);
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<KpiStrip csrf={CSRF} />);
  });
  await settle();
  return tree;
}

describe("KpiStrip", () => {
  beforeEach(() => {
    mockRequest.mockReset();
  });

  it("fetches the KPIs once and shows a named table row with counts and percentages", async () => {
    mockRequest.mockResolvedValue({ projects: [project()] });
    const tree = await render();

    expect(mockRequest).toHaveBeenCalledTimes(1);
    expect(mockRequest).toHaveBeenCalledWith("/api/v1/me/kpis");
    expect(rowLabels(tree)).toEqual(["Project One: Deaths reported 12 · Interviews done 6 (50%) · Coded 3 (25%)"]);
    const text = textOf(tree);
    for (const header of ["Deaths reported", "Interviews done", "Coded"]) expect(text).toContain(header);
    // Each count is its own cell and each percentage a separate muted Text below it.
    const texts = tree.root.findAll((node) => (node.type as unknown) === "Text").map((node) => node.props.children);
    expect(texts).toEqual(expect.arrayContaining(["Project One", 12, 6, "50%", 3, "25%"]));
  });

  it("shows the count alone for a null percentage", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({ deaths_reported: 0, interviews_done: 0, coded: 0, interviews_pct: null, coded_pct: null })],
    });
    const tree = await render();

    expect(rowLabels(tree)).toEqual(["Project One: Deaths reported 0 · Interviews done 0 · Coded 0"]);
    expect(textOf(tree)).not.toContain("%");
  });

  it("never sums projects into one line or one percentage, however many there are", async () => {
    mockRequest.mockResolvedValue({
      projects: [
        project({ deaths_reported: 2, interviews_done: 900, interviews_pct: null, coded: 1, coded_pct: null }),
        project({ project_id: "P2", project_name: "Project Two", deaths_reported: 40, interviews_done: 20, interviews_pct: 50, coded: 10, coded_pct: 25 }),
        project({ project_id: "P3", project_name: "Project Three", deaths_reported: 0, interviews_done: 0, interviews_pct: null, coded: 0, coded_pct: null }),
        project({ project_id: "P4", project_name: "Project Four", deaths_reported: 1, interviews_done: 1, interviews_pct: null, coded: 0, coded_pct: null }),
      ],
    });
    const tree = await render();

    const labels = rowLabels(tree);
    expect(labels).toHaveLength(4);
    expect(labels).toContain("Project Four: Deaths reported 1 · Interviews done 1 · Coded 0");
    expect(labels).toContain("Project Two: Deaths reported 40 · Interviews done 20 (50%) · Coded 10 (25%)");
    expect(labels.join()).not.toContain("Deaths reported 43");
    expect(textOf(tree)).not.toContain("All projects");
  });

  it("names each project when there are two", async () => {
    mockRequest.mockResolvedValue({
      projects: [project(), project({ project_id: "P2", project_name: "Project Two", deaths_reported: 4 })],
    });
    const tree = await render();

    const text = textOf(tree);
    expect(text).toContain("Project One");
    expect(text).toContain("Project Two");
    expect(rowLabels(tree)[1]).toContain("Deaths reported 4");
  });

  it("holds a reserved height while the call is pending, then shows the counts", async () => {
    let resolve!: (value: unknown) => void;
    mockRequest.mockReturnValue(new Promise((done) => { resolve = done; }));
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<KpiStrip csrf={CSRF} />);
    });

    expect(JSON.stringify(tree.toJSON())).toContain("minHeight");
    expect(JSON.stringify(tree.toJSON())).not.toContain("Deaths reported");
    await act(async () => {
      resolve({ projects: [project()] });
    });
    await settle();
    expect(rowLabels(tree)[0]).toContain("Deaths reported 12");
  });

  it("releases the reserved height when the call fails", async () => {
    mockRequest.mockRejectedValue(new TypeError("network down"));
    const tree = await render();

    expect(tree.toJSON()).toBeNull();
  });

  it("renders nothing for an empty project list", async () => {
    mockRequest.mockResolvedValue({ projects: [] });
    const tree = await render();

    expect(tree.toJSON()).toBeNull();
  });

  it("renders nothing when the call fails", async () => {
    mockRequest.mockRejectedValue(new TypeError("network down"));
    const tree = await render();

    expect(tree.toJSON()).toBeNull();
  });
});
