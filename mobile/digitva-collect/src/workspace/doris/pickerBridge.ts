import { ApiError } from "../../api";
import type { WorkspaceApi, JsonRequester } from "../api";
import type { JsonValue, WorkspaceIdentity } from "../contracts";
import { dorisGuidance } from "./guidance";

/**
 * Bridge between the shared ICD-11 picker page (app/static/doris_picker_host.html,
 * shown in an iframe on the browser build and a WebView on native) and the
 * authenticated workspace client. The page only sends `{path, body}` and gets
 * JSON or `{code, message, status}` back: it never receives a token, a cookie
 * or the case id, and only a code the server verified with selection-check can
 * be handed to the certificate.
 */

/** The shared picker page, served by the DigitVA server next to the web app's own assets. */
export const PICKER_PAGE_PATH = "/static/doris_picker_host.html";

/**
 * Page URL with the theme only. The search term travels in the init message, never
 * in the URL: it can describe the deceased and URLs land in server logs.
 */
export function pickerPageUrl(theme: PickerInit["theme"]): string {
  return `${PICKER_PAGE_PATH}?theme=${theme === "dark" ? "dark" : "light"}`;
}

/** What the page needs to show; ids, tokens and the case are never part of it. */
export interface PickerInit {
  title: string;
  /** `#rrggbb` shade of the certificate line being searched. */
  accent: string;
  allowUncoded: boolean;
  /** Pre-filled search text (e.g. the DORIS suggestion for the final cause). */
  query?: string;
  /** Confirming a final cause rather than adding a line condition. */
  finalMode?: boolean;
  /** App colour mode; the page is also told through `?theme=` so it renders right before init arrives. */
  theme?: "light" | "dark";
}

export interface PickerChoice {
  code: string;
  title: string;
  uri: string;
}

export interface PickerFailure {
  code: string;
  message: string;
  status: number;
}

export type PickerReply =
  | { t: "res"; id: number; ok: true; data: JsonValue }
  | { t: "res"; id: number; ok: false; error: PickerFailure };

export interface PickerBridgeOptions {
  api: WorkspaceApi;
  request: JsonRequester;
  identity: WorkspaceIdentity;
  /** The certificate revision now; a verified code is dropped if it moved on. */
  revision: () => number;
  /** A 403 means the allocation is lost: the owner must stop editing. */
  onForbidden: () => void;
  /** False in final-cause mode: a free-text `uncoded` message is then ignored. Defaults to true. */
  allowUncoded?: () => boolean;
  onSelect: (choice: PickerChoice) => void;
  onUncoded: (text: string) => void;
  onClose: () => void;
}

const GUIDANCE = {
  postcoordination: "postcoordination",
  "postcoordination-options": "postcoordination-options",
  hierarchy: "hierarchy",
  related: "related",
  details: "details",
} as const;

const MAX_TEXT = 300;
// Server limits (app/services/doris_certificate.py): LinearizationURI 2048, Code 128.
const MAX_URI = 2048;
const MAX_CODE = 128;
const MAX_URIS = 50;

function plain(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function str(body: Record<string, unknown>, key: string, max = MAX_TEXT): string {
  const value = body[key];
  if (typeof value !== "string" || !value || value.length > max) throw new ApiError(400, "invalid_picker_request");
  return value;
}

function failure(error: unknown): PickerFailure {
  if (error instanceof ApiError) return { code: error.code ?? "request_failed", message: error.message || "The request failed.", status: error.status };
  return { code: "request_failed", message: "The request could not be completed.", status: 0 };
}

/** Maps picker messages onto the existing client; one bridge per open picker. */
export function createPickerBridge(options: PickerBridgeOptions) {
  const { api, request, identity } = options;
  // Verified (code, uri) pairs and the revision they were verified at.
  const verified = new Map<string, { choice: PickerChoice; revision: number }>();

  async function call(path: string, raw: unknown): Promise<JsonValue> {
    const body = plain(raw);
    if (!body) throw new ApiError(400, "invalid_picker_request");
    switch (path) {
      case "terms": {
        const limit = typeof body.limit === "number" ? Math.min(20, Math.max(1, Math.trunc(body.limit))) : 20;
        const uris = body.subtree_uris;
        const subtreeUris = Array.isArray(uris) && uris.length <= MAX_URIS && uris.every((uri) => typeof uri === "string") ? uris as string[] : undefined;
        return await api.searchDorisTerms(identity.vaSid, str(body, "query"), { limit, ...(subtreeUris ? { subtreeUris } : {}) }) as unknown as JsonValue;
      }
      case "codeinfo":
        return await api.getDorisCodeInfo(identity.vaSid, str(body, "code", MAX_CODE)) as unknown as JsonValue;
      case "selection-check": {
        const code = str(body, "code", MAX_CODE);
        const sent = options.revision();
        const reply = await api.checkDorisSelection(identity.vaSid, code, str(body, "uri", MAX_URI));
        const choice = { code: reply.item.code, title: reply.item.title, uri: reply.item.uri };
        verified.set(`${choice.code}\n${choice.uri}`, { choice, revision: sent });
        return reply as unknown as JsonValue;
      }
      case "postcoordination":
      case "hierarchy":
      case "details":
        return await dorisGuidance<JsonValue>(request, identity, GUIDANCE[path], { code: str(body, "code", MAX_CODE) }, (value) => value as JsonValue);
      case "related": {
        const chapter = str(body, "chapter");
        if (chapter !== "maternal" && chapter !== "perinatal") throw new ApiError(400, "invalid_picker_request");
        return await dorisGuidance<JsonValue>(request, identity, "related", { code: str(body, "code", MAX_CODE), chapter }, (value) => value as JsonValue);
      }
      case "postcoordination-options":
        return await dorisGuidance<JsonValue>(request, identity, "postcoordination-options", { stem_code: str(body, "stem_code", MAX_CODE), axis_id: str(body, "axis_id"), parent_uri: str(body, "parent_uri", MAX_URI) }, (value) => value as JsonValue);
      default:
        throw new ApiError(400, "invalid_picker_request");
    }
  }

  /** Handle one page message; `reply` posts a response back to the page. */
  async function handle(message: unknown, reply: (reply: PickerReply) => void): Promise<void> {
    const source = plain(message);
    if (!source) return;
    if (source.t === "req" && typeof source.id === "number" && typeof source.path === "string") {
      const id = source.id;
      try {
        reply({ t: "res", id, ok: true, data: await call(source.path, source.body) });
      } catch (error) {
        if (error instanceof ApiError && error.status === 403) options.onForbidden();
        reply({ t: "res", id, ok: false, error: failure(error) });
      }
    } else if (source.t === "select") {
      const choice = plain(source.choice);
      const entry = choice && typeof choice.code === "string" && typeof choice.uri === "string" ? verified.get(`${choice.code}\n${choice.uri}`) : undefined;
      // Anything the server did not verify, or verified for an older certificate, is ignored.
      if (entry && entry.revision === options.revision()) options.onSelect(entry.choice);
    } else if (source.t === "uncoded" && (options.allowUncoded?.() ?? true) && typeof source.text === "string") {
      const value = source.text.trim();
      if (value && value.length <= MAX_TEXT) options.onUncoded(value);
    } else if (source.t === "close") {
      options.onClose();
    }
  }

  return { handle };
}
