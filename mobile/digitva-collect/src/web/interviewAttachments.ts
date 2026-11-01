/**
 * The browser interview's attachment services: the Flask questionnaire page's encrypted buffer, uploader and
 * platform (app/static/js/intake/attachment_buffer.js and attachment_platform.js, imported as they are, so there
 * is one implementation of the crypto and the sending), set up the way that page's setupAttachments() does.
 * Policy: docs/policy/web-intake.md, "Attachments" (the Expo web interview paragraph).
 */
import type { WhoVaPlatformServices } from "@drguptavivek/who-2022-va";
import { useCallback, useEffect, useRef, useState } from "react";

import { createBuffer, createIdbBacking, createUploader } from "../../../../app/static/js/intake/attachment_buffer.js";
import { createAttachmentPlatform } from "../../../../app/static/js/intake/attachment_platform.js";
import { ApiError, getLocalStationLaunchToken, requestJson, type ClientCsrf } from "../api";
import { t } from "../i18n";
import type { WhoWebRuntime } from "./whoRuntimeLoader";

const SWEEP_EVERY_MS = 60 * 60 * 1000;
// The same allowance the phone gives one attachment upload (src/attachmentUpload.ts).
const UPLOAD_TIMEOUT_MS = 180_000;

interface BufferEntry { id: string; draftId: string; type: string; size: number; createdAt: number }
interface UploaderEvent { type: "confirmed" | "rejected" | "held"; id: string; fileType: string; createdAt: number; status?: number }

export interface HeldAttachment { id: string; text: string }

export interface InterviewAttachments {
  /** Absent until the buffer is ready, for a revision, or when the browser cannot encrypt (see `unavailable`). */
  platform?: WhoVaPlatformServices;
  unavailable: boolean;
  /** "Files waiting to be sent" while the buffer holds any, else "". */
  status: string;
  /** Refused files and the seven-day warnings, shown until dismissed. */
  notices: string[];
  /** Files the server would not take because the draft is gone or closed: kept until deleted here. */
  held: HeldAttachment[];
  dismissNotices(): void;
  deleteHeld(id: string): Promise<void>;
  /** Sends what the buffer holds now; resolves to how many files of this draft are still waiting. */
  send(): Promise<number>;
}

export interface InterviewAttachmentsOptions {
  web: WhoWebRuntime | undefined;
  userId: string | undefined;
  /** The open server draft; undefined turns the services off (a revision, or no draft yet). */
  draftId: string | undefined;
  /** `bootstrap.links.intakeDrafts`. */
  draftsEndpoint: string | undefined;
  csrf: ClientCsrf | undefined;
  /** The question a file answers, to name it without its file name. */
  labelFor(id: string): string | undefined;
}

const kindOf = (type: string) =>
  t(type.startsWith("audio/") ? "webAttachmentKindRecording" : type === "application/pdf" ? "webAttachmentKindPdf" : "webAttachmentKindImage");
const kindAndDay = (type: string, createdAt: number) =>
  t("webAttachmentOfDay", { kind: kindOf(type), day: new Date(createdAt).toLocaleDateString() });

/**
 * The uploader's PUT, sent by the app's cookie request helper so it carries the current CSRF token (it rotates),
 * the training scope and the desktop station's launch token like every other request. The helper's ApiError is
 * handed back as the response the uploader reads; a network failure stays a throw, which the uploader retries.
 */
export function clientUploadFetch(csrf: ClientCsrf): typeof fetch {
  const reply = (status: number, body: unknown) =>
    new Response(JSON.stringify(body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  return async (input, init) => {
    const file = init?.body;
    if (!(file instanceof Blob)) throw new TypeError("upload_body_not_blob");
    const sha256 = new Headers(init?.headers).get("X-Content-SHA256") ?? undefined;
    try {
      const { status, body } = await requestJson<unknown>("", String(input), {
        method: "PUT",
        csrf,
        rawBody: { bytes: new Uint8Array(await file.arrayBuffer()), sha256 },
        timeoutMs: UPLOAD_TIMEOUT_MS,
      });
      return reply(status, body);
    } catch (error) {
      // Only a refusal (4xx/5xx) is handed back. A 2xx/3xx ApiError is a redirect or a reply that was not the
      // server's JSON (a captive portal, a proxy): read as a 200 it would delete a file the server never stored.
      if (!(error instanceof ApiError) || error.status < 400) throw error;
      return reply(error.status, { code: error.code, error: error.payload?.error });
    }
  };
}

/** The platform's GET of a file the device no longer holds, with the station's launch token when present. */
const clientAttachmentFetch: typeof fetch = (input, init) => {
  const launchToken = getLocalStationLaunchToken();
  return fetch(input, { ...init, cache: "no-store", ...(launchToken ? { headers: { "X-DigitVA-Launch-Token": launchToken } } : {}) });
};

export function useInterviewAttachments({ web, userId, draftId, draftsEndpoint, csrf, labelFor }: InterviewAttachmentsOptions): InterviewAttachments {
  const [platform, setPlatform] = useState<WhoVaPlatformServices>();
  const [unavailable, setUnavailable] = useState(false);
  const [status, setStatus] = useState("");
  const [notices, setNotices] = useState<string[]>([]);
  const [held, setHeld] = useState<HeldAttachment[]>([]);
  const session = useRef<{
    buffer: ReturnType<typeof createBuffer>;
    uploader: ReturnType<typeof createUploader>;
    draftId: string;
    refresh(): Promise<void>;
  }>(undefined);
  const labelRef = useRef(labelFor);
  labelRef.current = labelFor;

  useEffect(() => {
    setPlatform(undefined);
    setUnavailable(false);
    setStatus("");
    setNotices([]);
    setHeld([]);
    session.current = undefined;
    if (!web || !userId || !draftId || !draftsEndpoint || !csrf) return undefined;
    // WebCrypto and IndexedDB exist only in a secure context; without them the form stays without attachment
    // controls rather than store anything in the clear.
    if (typeof window === "undefined" || !window.indexedDB || !globalThis.crypto?.subtle) {
      setUnavailable(true);
      return undefined;
    }
    let live = true;
    const apiBase = (id: string) => `${draftsEndpoint}/${encodeURIComponent(id)}`;
    const describe = (id: string, type: string, createdAt: number) => labelRef.current(id) || kindAndDay(type, createdAt);
    const buffer = createBuffer({ userId, draftId, backing: createIdbBacking(window.indexedDB) });
    const refresh = async () => {
      const count = (await buffer.entries()).length;
      if (!live) return;
      const offline = typeof navigator !== "undefined" && navigator.onLine === false;
      setStatus(count ? t(offline ? "webAttachmentsWaitingOffline" : "webAttachmentsWaiting", { count }) : "");
    };
    const uploader = createUploader({
      buffer,
      apiBase,
      // Unused by clientUploadFetch, which sends the helper's current token.
      csrf: () => csrf.token,
      fetchImpl: clientUploadFetch(csrf),
      onEvent: (event: UploaderEvent) => {
        if (!live) return;
        const file = describe(event.id, event.fileType, event.createdAt);
        if (event.type === "held") {
          const text = t(event.status === 404 ? "webAttachmentHeldMissing" : "webAttachmentHeldClosed", { file });
          setHeld((current) => [...current.filter((entry) => entry.id !== event.id), { id: event.id, text }]);
        } else {
          setHeld((current) => current.filter((entry) => entry.id !== event.id));
          if (event.type === "rejected") setNotices((current) => [...current, t("webAttachmentRejected", { file })]);
        }
        refresh().catch(() => undefined);
      },
    });
    // Warn first, then delete: the warning names the kind and the day captured.
    const sweep = async () => {
      const { expired, expiring } = (await buffer.sweep()) as { expired: BufferEntry[]; expiring: BufferEntry[] };
      const name = (entries: BufferEntry[]) => entries.map((entry) => kindAndDay(entry.type, entry.createdAt)).join(", ");
      const lines = [
        ...(expired.length ? [t("webAttachmentsExpired", { files: name(expired) })] : []),
        ...(expiring.length ? [t("webAttachmentsExpiring", { files: name(expiring) })] : []),
      ];
      // The hourly sweep repeats a warning still true; it is listed once.
      if (live && lines.length) setNotices((current) => [...new Set([...current, ...lines])]);
      for (const entry of expired) await buffer.remove(entry.id);
      await refresh();
    };
    const sendNow = () => { uploader.flush().then(refresh).catch(() => undefined); };
    const showOffline = () => { refresh().catch(() => undefined); };
    let timer: ReturnType<typeof setInterval> | undefined;
    void (async () => {
      // What another user left in this browser goes before anything else.
      await buffer.wipeOthers();
      await sweep();
      if (!live) return;
      session.current = { buffer, uploader, draftId, refresh };
      setPlatform(createAttachmentPlatform({
        WhoVa: web,
        buffer,
        uploader,
        attachmentUrl: (id: string) => `${apiBase(draftId)}/attachments/${encodeURIComponent(id)}${csrf.training ? "?training=1" : ""}`,
        fetchImpl: clientAttachmentFetch,
      }));
      window.addEventListener("online", sendNow);
      window.addEventListener("offline", showOffline);
      timer = setInterval(() => { sweep().catch(() => undefined); }, SWEEP_EVERY_MS);
      sendNow();
    })().catch(() => { if (live) setUnavailable(true); });
    return () => {
      live = false;
      uploader.stop();
      if (timer !== undefined) clearInterval(timer);
      window.removeEventListener("online", sendNow);
      window.removeEventListener("offline", showOffline);
    };
  }, [web, userId, draftId, draftsEndpoint, csrf]);

  const dismissNotices = useCallback(() => setNotices([]), []);
  const deleteHeld = useCallback(async (id: string) => {
    const current = session.current;
    if (!current) return;
    await current.buffer.remove(id);
    setHeld((entries) => entries.filter((entry) => entry.id !== id));
    await current.refresh();
  }, []);
  const send = useCallback(async () => {
    const current = session.current;
    if (!current) return 0;
    await current.uploader.flush().catch(() => undefined);
    return current.uploader.pending(current.draftId);
  }, []);

  return { platform, unavailable, status, notices, held, dismissNotices, deleteHeld, send };
}
