/** Native adapter that delegates bearer storage and refresh to existing auth. */
import { authedRequest } from "../auth";
import { trainingScopedPath } from "../training";
import type { JsonRequester } from "./api";

/**
 * Bind a workspace client to one signed-in account without reading tokens here. *training*: the training workspace's
 * route, so every request (queue, case, DORIS) asks for `training=1`; the scope comes from the route, not stored state.
 */
export function createNativeWorkspaceTransport(userId: string, training = false): JsonRequester {
  return async (path, init = {}) => {
    const response = await authedRequest<unknown>(userId, trainingScopedPath(path, training), {
      method: init.method,
      body: init.json,
      allowList: init.allowList,
    });
    return response.body;
  };
}
