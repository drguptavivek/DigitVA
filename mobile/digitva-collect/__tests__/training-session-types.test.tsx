/**
 * Training session types on the clients (docs/policy/training-session-types.md): the per-project training scope,
 * training mode's collection access, the languages lines, the training queues and their error texts.
 */
import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ApiError, type AccessProject, type AccessSummary } from "../src/api";
import { hasTypedTrainingSession, scopeFor, trainingScopedPath, withTrainingCollection } from "../src/training";
import { errorText } from "../src/ui";
import { codingLanguageLines, trainingQueueCounts } from "../src/workspace/codingLanguages";
import { QueueScreen } from "../src/workspace/QueueScreen";
import type { WorkspaceApi } from "../src/workspace/api";
import { createWorkspaceApi } from "../src/workspace/api";

const project = (id: string) => ({ project_id: id, project_name: id }) as unknown as AccessProject;
const access = (training: AccessSummary["training"]) => ({ projects: [project("P1")], training });

describe("scopeFor and trainingScopedPath", () => {
  it("scopes exactly the training project", () => {
    expect(scopeFor("TRN01", "TRN01")).toBe(true);
    expect(scopeFor("TRN01", "P1")).toBe(false);
    expect(scopeFor("TRN01", "TRN011")).toBe(false);
    expect(scopeFor(undefined, "TRN01")).toBe(false);
    expect(scopeFor("TRN01", undefined)).toBe(false);
    expect(scopeFor(null, null)).toBe(false);
  });

  it("adds training=1 once", () => {
    expect(trainingScopedPath("/x", true)).toBe("/x?training=1");
    expect(trainingScopedPath("/x?a=1", true)).toBe("/x?a=1&training=1");
    expect(trainingScopedPath("/x?training=1", true)).toBe("/x?training=1");
    expect(trainingScopedPath("/x", false)).toBe("/x");
  });
});

describe("withTrainingCollection", () => {
  it("appends the training project last, once", () => {
    const next = withTrainingCollection(access({ project_id: "TRN01", areas: ["interview"], pending: false, session_types: ["self_coding"], project: project("TRN01") }));
    expect(next.projects.map((entry) => entry.project_id)).toEqual(["P1", "TRN01"]);
    expect(withTrainingCollection(next).projects).toHaveLength(2);
  });

  it("keeps today's access without a participation, after close, or from an older server", () => {
    for (const training of [undefined, null, { project_id: "TRN01", areas: [], pending: false, project: null }, { project_id: "TRN01", areas: [], pending: false },
      // A server before session types sends `project` for a legacy (S001) participation: no training mode.
      { project_id: "TRN01", areas: ["interview"], pending: false, project: project("TRN01") }]) {
      const before = access(training as AccessSummary["training"]);
      expect(withTrainingCollection(before)).toBe(before);
    }
  });
});

describe("hasTypedTrainingSession", () => {
  it("is true only with a typed session", () => {
    expect(hasTypedTrainingSession({ training: { project_id: "TRN01", areas: ["coding"], pending: false, session_types: ["coder"] } })).toBe(true);
    expect(hasTypedTrainingSession({ training: { project_id: "TRN01", areas: ["coding"], pending: false, session_types: [null] } })).toBe(false);
    expect(hasTypedTrainingSession({ training: { project_id: "TRN01", areas: ["coding"], pending: false } })).toBe(false);
    expect(hasTypedTrainingSession(undefined)).toBe(false);
  });
});

describe("codingLanguageLines", () => {
  it("answers nothing from an older server", () => {
    expect(codingLanguageLines(undefined)).toBeUndefined();
    expect(codingLanguageLines({ random_ready: 2 })).toBeUndefined();
  });

  it("says none set for an empty list and shows only languages with forms", () => {
    expect(codingLanguageLines({ languages: { mine: [], pending: [] } })).toEqual({ mine: "Your languages: none set" });
    expect(codingLanguageLines({
      languages: { mine: ["english", "hindi"], pending: [{ language: "hindi", count: 42 }, { language: "tamil", count: 5 }, { language: "telugu", count: 0 }, { language: "unrecorded", count: 1 }] },
    })).toEqual({ mine: "Your languages: English, Hindi", pending: "Forms pending coding: Hindi 42 · Tamil 5 · Unrecorded 1" });
  });
});

describe("trainingQueueCounts", () => {
  it("is undefined off the training side", () => {
    expect(trainingQueueCounts({})).toBeUndefined();
    expect(trainingQueueCounts({ training_queues: { own: null, standard: null } })).toBeUndefined();
  });

  it("has own only in a self-coding session", () => {
    expect(trainingQueueCounts({ training_queues: { own: null, standard: { coded: 1, total: 10 } } })).toEqual({ standard: { coded: 1, total: 10 } });
    expect(trainingQueueCounts({ training_queues: { own: { coded: 0, total: 2 }, standard: { coded: 1, total: 10 } } }))
      .toEqual({ standard: { coded: 1, total: 10 }, own: { coded: 0, total: 2 } });
  });
});

describe("error texts", () => {
  it("maps the training codes to plain messages", () => {
    expect(errorText(new ApiError(403, "not_in_your_training_set"))).toBe("This case is not in your training set.");
    expect(errorText(new ApiError(409, "role_not_in_session_type"))).toBe("That role is not allowed in this session type.");
    expect(errorText(new ApiError(409, "corpus_missing"))).toBe("The training case list is not ready yet. Ask your trainer.");
    expect(errorText(new ApiError(409, "corpus_cases_ineligible"))).toBe("The training case list is not ready yet. Ask your trainer.");
    expect(errorText(new ApiError(403, "app_update_required"))).toBe("Update the app to take part in training.");
  });
});

describe("createWorkspaceApi queue", () => {
  it("sends the queue with the training scope only", async () => {
    const request = jest.fn(async () => ({}));
    await createWorkspaceApi(request, { training: true, queue: "own" }).getCodingStats();
    expect(request).toHaveBeenLastCalledWith("/api/v1/coding/stats?training=1&queue=own");
    await createWorkspaceApi(request, { training: true }).getCodingStats("P1");
    expect(request).toHaveBeenLastCalledWith("/api/v1/coding/stats?project_id=P1&training=1");
    await createWorkspaceApi(request).getCodingStats();
    expect(request).toHaveBeenLastCalledWith("/api/v1/coding/stats");
  });
});

function makeApi(stats: Record<string, unknown>): WorkspaceApi {
  return {
    getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: false, ...stats }),
    getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1"], project_options: [{ project_id: "P1", project_name: "One" }], last_project_id: null }),
    getCodingAllocation: jest.fn().mockResolvedValue(null),
    getCodingAvailable: jest.fn().mockResolvedValue({ forms: [], count: 0, limit: 50, offset: 0, has_more: false }),
    getCodingHistory: jest.fn().mockResolvedValue({ history: [], count: 0, limit: 50, offset: 0, has_more: false }),
  } as unknown as WorkspaceApi;
}

async function render(element: React.ReactElement) {
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(element); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  return renderer;
}

const texts = (root: ReactTestInstance) => root.findAll((node) => (node.type as unknown) === "Text")
  .flatMap((node) => node.children.filter((child): child is string => typeof child === "string"));
const byId = (root: ReactTestInstance, id: string) => root.findAll((node) => node.props.testID === id);

describe("QueueScreen languages and training queues", () => {
  it("shows the languages lines and the edit link", async () => {
    const onEdit = jest.fn();
    const renderer = await render(<QueueScreen api={makeApi({ languages: { mine: ["hindi"], pending: [{ language: "hindi", count: 42 }] } })} mode="coding" onOpen={jest.fn()} onEditLanguages={onEdit} />);
    const all = texts(renderer.root).join("|");
    expect(all).toContain("Your languages: Hindi");
    expect(all).toContain("Forms pending coding: Hindi 42");
    await act(async () => byId(renderer.root, "coding-languages-edit")[0].props.onPress());
    expect(onEdit).toHaveBeenCalled();
    expect(byId(renderer.root, "training-queues")).toHaveLength(0);
  });

  it("shows nothing new for an older server", async () => {
    const renderer = await render(<QueueScreen api={makeApi({})} mode="coding" onOpen={jest.fn()} onTrainingQueue={jest.fn()} />);
    expect(byId(renderer.root, "coding-languages")).toHaveLength(0);
    expect(byId(renderer.root, "training-queues")).toHaveLength(0);
  });

  it("coder session: the standard set button and count only", async () => {
    const renderer = await render(<QueueScreen api={makeApi({ training_queues: { own: null, standard: { coded: 3, total: 10 } } })} mode="coding" onOpen={jest.fn()} trainingQueue="standard" onTrainingQueue={jest.fn()} />);
    expect(byId(renderer.root, "training-queue-standard").length).toBeGreaterThan(0);
    expect(byId(renderer.root, "training-queue-own")).toHaveLength(0);
    expect(texts(renderer.root).join("|")).toContain("Standard training set coded: 3 of 10");
  });

  it("self-coding session: both queues with counts, and a press switches the queue", async () => {
    const onQueue = jest.fn();
    const renderer = await render(<QueueScreen api={makeApi({ training_queues: { own: { coded: 1, total: 2 }, standard: { coded: 0, total: 10 } } })} mode="coding" onOpen={jest.fn()} trainingQueue="standard" onTrainingQueue={onQueue} />);
    const all = texts(renderer.root).join("|");
    expect(all).toContain("My interviews coded: 1 of 2");
    expect(all).toContain("Standard training set coded: 0 of 10");
    await act(async () => byId(renderer.root, "training-queue-own")[0].props.onPress());
    expect(onQueue).toHaveBeenCalledWith("own");
    onQueue.mockClear();
    await act(async () => byId(renderer.root, "training-queue-standard")[0].props.onPress());
    expect(onQueue).not.toHaveBeenCalled();
  });

  it("keeps the generic text for a refusal on the standard queue", async () => {
    const api = makeApi({});
    (api.getCodingStats as jest.Mock).mockRejectedValue(new ApiError(403, "forbidden"));
    const renderer = await render(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} trainingQueue="standard" onTrainingQueue={jest.fn()} />);
    expect(texts(renderer.root).join("|")).toContain("You do not have permission to do that.");
  });

  it("names a refused queue plainly", async () => {
    const api = makeApi({});
    (api.getCodingStats as jest.Mock).mockRejectedValue(new ApiError(403, "forbidden"));
    const renderer = await render(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} trainingQueue="own" onTrainingQueue={jest.fn()} />);
    expect(texts(renderer.root).join("|")).toContain("This training queue is not open to you.");
  });
});
