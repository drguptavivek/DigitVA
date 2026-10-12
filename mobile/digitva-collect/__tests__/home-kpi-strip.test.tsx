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
    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain("Deaths reported 12 · Interviews done 6 (50%) · Coded 3 (25%)");
    expect(text).not.toContain("Project One");
  });

  it("shows a dash for a null percentage", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({ deaths_reported: 0, interviews_done: 0, coded: 0, interviews_pct: null, coded_pct: null })],
    });
    const tree = await render();

    expect(JSON.stringify(tree.toJSON())).toContain("Interviews done 0 (—) · Coded 0 (—)");
  });

  it("names each project when there are two", async () => {
    mockRequest.mockResolvedValue({
      projects: [project(), project({ project_id: "P2", project_name: "Project Two", deaths_reported: 4 })],
    });
    const tree = await render();

    const text = JSON.stringify(tree.toJSON());
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
    expect(JSON.stringify(tree.toJSON())).toContain("Deaths reported 12");
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
