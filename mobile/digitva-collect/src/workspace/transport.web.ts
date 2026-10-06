/** Browser adapter that delegates cookie and CSRF handling to the shared API transport. */
import { requestClientJson, type ClientCsrf } from "../api";
import type { JsonRequester } from "./api";

/** Use the cookie session for workspace calls; mutations carry the server-issued CSRF token. */
export function createWebWorkspaceTransport(csrf?: ClientCsrf): JsonRequester {
  return (path, init = {}) => requestClientJson<unknown>(path, {
    method: init.method,
    json: init.json,
    csrf,
  });
}
