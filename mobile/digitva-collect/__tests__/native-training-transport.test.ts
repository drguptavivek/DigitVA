jest.mock("../src/auth", () => ({ authedRequest: jest.fn(async () => ({ status: 200, body: {} })) }));

import { authedRequest } from "../src/auth";
import { createWorkspaceApi } from "../src/workspace/api";
import { createNativeWorkspaceTransport } from "../src/workspace/transport.native";

const paths = () => (authedRequest as jest.Mock).mock.calls.map((call) => String(call[1]));

beforeEach(() => (authedRequest as jest.Mock).mockClear());

test("the training workspace asks for training=1 on every request, once; the normal one never", async () => {
  const training = createWorkspaceApi(createNativeWorkspaceTransport("u1", true), { training: true, queue: "own" });
  await training.getWorkspace("sid-1", "coding").catch(() => undefined);
  await training.getCodingAvailable().catch(() => undefined);
  expect(paths()).toHaveLength(2);
  expect(paths()[0]).toMatch(/\/va\/sid-1\/workspace\?mode=coding&training=1$/);
  expect(paths()[1]).toContain("training=1&queue=own");
  expect(paths()[1].match(/training=1/g)).toHaveLength(1);

  (authedRequest as jest.Mock).mockClear();
  const normal = createWorkspaceApi(createNativeWorkspaceTransport("u1"));
  await normal.getWorkspace("sid-1", "coding").catch(() => undefined);
  expect(paths()).toHaveLength(1);
  expect(paths()[0]).not.toContain("training=");
});
