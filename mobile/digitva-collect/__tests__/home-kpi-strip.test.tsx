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

  it("fetches the KPIs once and shows counts and percentages for one project without its name", async () => {
    mockRequest.mockResolvedValue({ projects: [project()] });
    const tree = await render();

    expect(mockRequest).toHaveBeenCalledTimes(1);
    expect(mockRequest).toHaveBeenCalledWith("/api/v1/me/kpis");
    const text = textOf(tree);
    expect(text).toContain("Deaths reported 12 · Interviews done 6 (50%) · Coded 3 (25%)");
    expect(text).not.toContain("Project One");
    // Each percentage is its own secondary Text beside the count, never part of the count text.
    expect(tree.root.findAll((node) => (node.type as unknown) === "Text" && node.props.children === " (50%)")).toHaveLength(1);
  });

  it("shows the count alone for a null percentage", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({ deaths_reported: 0, interviews_done: 0, coded: 0, interviews_pct: null, coded_pct: null })],
    });
    const tree = await render();

    expect(textOf(tree)).toContain("Deaths reported 0 · Interviews done 0 · Coded 0");
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

    const text = textOf(tree);
    expect(text).toContain("Project Four");
    expect(text).toContain("Deaths reported 40 · Interviews done 20 (50%) · Coded 10 (25%)");
    expect(text).not.toContain("Deaths reported 43");
    expect(text).not.toContain("All projects");
  });

  it("names each project when there are two", async () => {
    mockRequest.mockResolvedValue({
      projects: [project(), project({ project_id: "P2", project_name: "Project Two", deaths_reported: 4 })],
    });
    const tree = await render();

    const text = textOf(tree);
    expect(text).toContain("Project One");
    expect(text).toContain("Project Two");
    expect(text).toContain("Deaths reported 4");
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
    expect(textOf(tree)).toContain("Deaths reported 12");
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
