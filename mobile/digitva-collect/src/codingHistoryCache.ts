import type { CoderHistory } from "./workspace/contracts";

export interface CodingHistoryIdentity {
  mode: "enrolled" | "demo";
  serverOrigin: string;
  userId: string;
}

export interface CachedCodingHistoryPage {
  page: CoderHistory;
  fetchedAt: string;
  accessFingerprint: string;
}

/** Optional port keeps the shared queue independent of native SQLite. */
export interface CodingHistoryCache {
  cachedProjects(identity: CodingHistoryIdentity): Promise<string[]>;
  fingerprintForProject(projectId: string): string | undefined;
  readPage(identity: CodingHistoryIdentity, projectId: string, offset: number): Promise<CachedCodingHistoryPage | null>;
  writePage(identity: CodingHistoryIdentity, projectId: string, page: CoderHistory, fingerprint: string): Promise<void>;
  invalidateCase(identity: CodingHistoryIdentity, vaSid: string): Promise<void>;
  invalidateProject(identity: CodingHistoryIdentity, projectId?: string): Promise<void>;
}
