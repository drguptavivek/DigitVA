/**
 * Characterization (digitva-r8nh.24): the methods each WorkspaceApi implementation answers. The offline
 * implementation's list is pinned in offline-case-sql-characterization.test.tsx, where its route is mounted.
 */
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

import { createWorkspaceApi } from "../src/workspace/api";
import { createDorisDemoApi } from "../src/workspace/dorisDemo";
import type { OfflineDorisEditor } from "../src/workspace/offlineDoris";

const ONLINE = [
  "allocateCoding", "allocateReviewer", "checkDorisSelection", "codeOwnSubmission", "getCategory", "getCertificate",
  "getCodingAllocation", "getCodingAvailable", "getCodingHistory", "getCodingProjects", "getCodingStats", "getDorisCodeInfo",
  "getNote", "getReviewerAllocation", "getReviewerAvailable", "getReviewerHistory", "getReviewerProjects", "getReviewerStats",
  "getSmartvaStatus", "getVaDefinitionForIcd", "getWorkflowEvents", "getWorkspace", "listVaDefinitions", "processDoris",
  "recode", "releaseCoding", "releaseReviewer", "runSmartva", "saveFinal", "saveInitial", "saveNarrativeQuality",
  "saveNotCodeable", "saveNote", "saveSocialAutopsy", "searchDorisTerms", "searchIcd",
];

/** The online methods less the two optional ones a server-less implementation leaves out. */
const WITHOUT_SERVER = ONLINE.filter((name) => name !== "getCertificate" && name !== "listVaDefinitions");

it("the online api answers every method, the two optional ones included", () => {
  expect(Object.keys(createWorkspaceApi(jest.fn())).sort()).toEqual(ONLINE);
  expect(Object.keys(createWorkspaceApi(jest.fn(), { training: true, queue: "own" })).sort()).toEqual(ONLINE);
});

it("the DORIS demo api answers every required method and neither optional one", () => {
  expect(Object.keys(createDorisDemoApi({} as OfflineDorisEditor, async () => undefined)).sort()).toEqual(WITHOUT_SERVER);
});
