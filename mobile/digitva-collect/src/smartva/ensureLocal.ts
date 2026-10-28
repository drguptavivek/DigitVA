import { accountStoreIdentityIsInSelectedMode } from "../accountStoreIdentity";
import { loadAccounts, loadActiveSlot } from "../auth";
import { isPlusVariant } from "../appVariant";
import { canUseOfflineCoding } from "../codingCapabilities";
import { getMeta, type Db } from "../drafts";
import { isIcd11DorisEnabled } from "../icd11DorisPreference";
import { acquireLocalCodingEditor } from "../localCodingLeases";
import { draftAnswersSha256 } from "../sync";
import { assertSmartVaEligible, runLocalSmartVa } from "./localApi";
import { getLocalSmartVa, isLocalSmartVaCurrent, type LocalSmartVaRow } from "./localStore";
import { offlineSmartvaEngine } from "./nativeEngine";
import { isSmartVaOptionsSnapshot } from "./options";

type Result = { status: "current" | "ran" | "skipped" | "config_needed" | "failed"; row?: LocalSmartVaRow; reason?: string };
const flights = new Map<string, Promise<Result>>();

/** Reserve the draft synchronously so an upload cannot overtake completion scoring. */
export function ensureLocalSmartVa(input: { db: Db; userId: string; draftId: string }): Promise<Result> {
  const key = `${input.userId}\u0000${input.draftId}`;
  const pending = flights.get(key);
  if (pending) return pending;
  const release = acquireLocalCodingEditor(input.userId, input.draftId);
  if (!release) return Promise.resolve({ status: "skipped", reason: "busy" });
  const flight = ensure(input).catch((): Result => ({ status: "failed" })).finally(() => {
    release();
    flights.delete(key);
  });
  flights.set(key, flight);
  return flight;
}

async function ensure({ db, userId, draftId }: { db: Db; userId: string; draftId: string }): Promise<Result> {
  if (!isPlusVariant()) return { status: "skipped" };
  const slot = await loadActiveSlot();
  const assertAllowed = async () => {
    if (await loadActiveSlot() !== slot || !await accountStoreIdentityIsInSelectedMode(userId) || !await isIcd11DorisEnabled()) throw new Error("offline_case_access_revoked");
    const account = (await loadAccounts(slot)).find((item) => item.user_id === userId);
    const draft = await db.getFirstAsync<{ project_id: string | null }>("SELECT project_id FROM drafts WHERE id = ?", [draftId]);
    if (!account || !draft?.project_id || !canUseOfflineCoding(account, draft.project_id) || await loadActiveSlot() !== slot) throw new Error("offline_case_access_revoked");
  };
  try { await assertAllowed(); } catch { return { status: "skipped" }; }
  const config = await getMeta<{ smartva?: unknown }>(db, `draft-config:${draftId}`);
  if (!isSmartVaOptionsSnapshot(config?.smartva)) return { status: "config_needed" };
  const options = config.smartva;
  let envelope: string;
  try { envelope = await assertSmartVaEligible(db, draftId, options); } catch { return { status: "skipped" }; }
  const engine = offlineSmartvaEngine();
  const initialized = await engine.init();
  await assertAllowed();
  await assertSmartVaEligible(db, draftId, options);
  const hash = await draftAnswersSha256(db, draftId);
  const row = await getLocalSmartVa(db, draftId);
  await assertAllowed();
  await assertSmartVaEligible(db, draftId, options);
  if (initialized.ok && row?.status === "ready" && isLocalSmartVaCurrent(row, hash, options.optionsDigest, initialized.version) && await draftAnswersSha256(db, draftId) === hash) return { status: "current", row };
  const saved = await runLocalSmartVa({ db, draftId, envelope, options, answersHash: () => draftAnswersSha256(db, draftId), engine, assertAllowed });
  return { status: "ran", row: saved };
}
