import { fetchClientBootstrap, type BootstrapResult, type ClientBootstrap, type ClientCsrf } from "./api";

export interface BrowserSession {
  bootstrap: ClientBootstrap;
  csrf: ClientCsrf;
  loadedAt: number;
}

export async function loadBrowserSession(): Promise<BootstrapResult> {
  return fetchClientBootstrap();
}

export function sessionFromBootstrap(bootstrap: ClientBootstrap): BrowserSession {
  return { bootstrap, csrf: bootstrap.csrf, loadedAt: Date.now() };
}
