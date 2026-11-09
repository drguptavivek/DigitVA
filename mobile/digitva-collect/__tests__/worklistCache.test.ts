import { dropWorklist, heldWorklist, holdWorklist, type WorklistSnapshot } from "../src/worklistCache";
import { unlockedDb } from "../src/interviewerDb";

jest.mock("../src/interviewerDb", () => ({ unlockedDb: jest.fn() }));

const snapshot = { drafts: [], selectedProjectId: "P1" } as unknown as WorklistSnapshot;
const db = {} as never;
const unlocked = unlockedDb as jest.Mock;

beforeEach(() => { dropWorklist(); unlocked.mockReset(); });

test("held data is served for the same account and the same open store", () => {
  unlocked.mockReturnValue(db);
  holdWorklist("u1", db, snapshot);
  expect(heldWorklist("u1")).toBe(snapshot);
  expect(heldWorklist("u1")?.selectedProjectId).toBe("P1");
});

test("another account, a lock (no handle), a re-unlock (new handle) or a drop serves nothing", () => {
  unlocked.mockReturnValue(db);
  holdWorklist("u1", db, snapshot);
  expect(heldWorklist("u2")).toBeUndefined();
  unlocked.mockReturnValue(undefined);
  expect(heldWorklist("u1")).toBeUndefined();
  unlocked.mockReturnValue({});
  expect(heldWorklist("u1")).toBeUndefined();
  unlocked.mockReturnValue(db);
  expect(heldWorklist("u1")).toBe(snapshot);
  dropWorklist();
  expect(heldWorklist("u1")).toBeUndefined();
});
