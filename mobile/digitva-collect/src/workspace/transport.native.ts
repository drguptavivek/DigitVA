/** Native adapter that delegates bearer storage and refresh to existing auth. */
import { authedRequest } from "../auth";
import type { JsonRequester } from "./api";

/** Bind a workspace client to one signed-in account without reading tokens here. */
export function createNativeWorkspaceTransport(userId: string): JsonRequester {
  return async (path, init = {}) => {
    const response = await authedRequest<unknown>(userId, path, {
      method: init.method,
      body: init.json,
    });
    return response.body;
  };
}
