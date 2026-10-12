import { ApiError } from "../src/api";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import { palette } from "../src/theme";
import { lineShade } from "../src/workspace/doris/compact";
import { createPickerBridge, type PickerReply } from "../src/workspace/doris/pickerBridge";

const identity = { vaSid: "sid-1", mode: "coding" as const };
const item = { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40", release: "2025-01", postcoordination: false };

function setup(overrides: Partial<WorkspaceApi> = {}, request: JsonRequester = jest.fn(async () => ({ schema_version: 1 })), allowUncoded = true) {
  let revision = 3;
  const api = {
    searchDorisTerms: jest.fn(async () => ({ schema_version: 1, items: [], truncated: false, next_cursor: null })),
    getDorisCodeInfo: jest.fn(async () => ({ schema_version: 1, item })),
    checkDorisSelection: jest.fn(async () => ({ schema_version: 1, item })),
    ...overrides,
  } as unknown as WorkspaceApi;
  const handlers = { onForbidden: jest.fn(), onSelect: jest.fn(), onUncoded: jest.fn(), onClose: jest.fn() };
  const bridge = createPickerBridge({ api, request, identity, revision: () => revision, allowUncoded: () => allowUncoded, ...handlers });
  const replies: PickerReply[] = [];
  const send = async (message: unknown) => { await bridge.handle(message, (reply) => replies.push(reply)); };
  return { api, request, handlers, send, replies, bump: () => { revision += 1; } };
}

describe("picker transport bridge", () => {
  it("accepts a 1500-character postcoordinated uri and a 128-character code, but not longer", async () => {
    const { api, send, replies } = setup();
    const uri = `https://id.who.int/icd/entity/${"1".repeat(1470)}`;
    expect(uri.length).toBeGreaterThan(1400);
    await send({ t: "req", id: 1, path: "selection-check", body: { code: "C".repeat(128), uri } });
    expect(api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "C".repeat(128), uri);
    expect(replies[0].ok).toBe(true);
    await send({ t: "req", id: 2, path: "selection-check", body: { code: "C".repeat(129), uri } });
    await send({ t: "req", id: 3, path: "selection-check", body: { code: "CA40", uri: "u".repeat(2049) } });
    expect(api.checkDorisSelection).toHaveBeenCalledTimes(1);
    expect(replies.slice(1).every((reply) => !reply.ok)).toBe(true);
  });

  it("ignores uncoded text when the picker is in final-cause mode", async () => {
    const open = setup();
    await open.send({ t: "uncoded", text: "Fever" });
    expect(open.handlers.onUncoded).toHaveBeenCalledWith("Fever");
    const final = setup({}, undefined, false);
    await final.send({ t: "uncoded", text: "Fever" });
    expect(final.handlers.onUncoded).not.toHaveBeenCalled();
  });

  it("maps every picker path to the authenticated client", async () => {
    const { api, request, send, replies } = setup();
    const calls: Array<[string, unknown]> = [
      ["terms", { query: "pneu", limit: 99, subtree_uris: ["u1"] }],
      ["codeinfo", { code: "CA40" }],
      ["selection-check", { code: "CA40", uri: "https://who.int/CA40" }],
      ["postcoordination", { code: "CA40" }],
      ["postcoordination-options", { stem_code: "CA40", axis_id: "a", parent_uri: "p" }],
      ["hierarchy", { code: "CA40" }],
      ["related", { code: "CA40", chapter: "maternal" }],
      ["details", { code: "CA40" }],
    ];
    for (const [index, [path, body]] of calls.entries()) await send({ t: "req", id: index, path, body: { schema_version: 1, ...(body as object) } });
    expect(api.searchDorisTerms).toHaveBeenCalledWith("sid-1", "pneu", { limit: 20, subtreeUris: ["u1"] });
    expect(api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "CA40");
    expect(api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "CA40", "https://who.int/CA40");
    const paths = (request as jest.Mock).mock.calls.map(([path]) => path);
    expect(paths).toEqual([
      "/api/v1/doris-clinical/postcoordination/sid-1",
      "/api/v1/doris-clinical/postcoordination-options/sid-1",
      "/api/v1/doris-clinical/hierarchy/sid-1",
      "/api/v1/doris-clinical/related/sid-1",
      "/api/v1/doris-clinical/details/sid-1",
    ]);
    expect(replies).toHaveLength(8);
    expect(replies.every((reply) => reply.ok)).toBe(true);
  });

  it("rejects unknown paths and malformed bodies without calling the server", async () => {
    const { api, request, send, replies } = setup();
    await send({ t: "req", id: 1, path: "process", body: {} });
    await send({ t: "req", id: 2, path: "terms", body: { query: 5 } });
    await send({ t: "req", id: 3, path: "related", body: { code: "CA40", chapter: "../x" } });
    expect(api.searchDorisTerms).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
    expect(replies.map((reply) => reply.ok)).toEqual([false, false, false]);
  });

  it("surfaces a 403 as onForbidden and returns only code, message and status", async () => {
    const forbidden = new ApiError(403, "FORBIDDEN");
    const { handlers, send, replies } = setup({ searchDorisTerms: jest.fn(async () => { throw forbidden; }) as never });
    await send({ t: "req", id: 7, path: "terms", body: { query: "pneu" } });
    expect(handlers.onForbidden).toHaveBeenCalledTimes(1);
    expect(replies[0]).toEqual({ t: "res", id: 7, ok: false, error: { code: "FORBIDDEN", message: "HTTP 403 FORBIDDEN", status: 403 } });
  });

  it("hides unexpected error detail from the page", async () => {
    const { send, replies } = setup({ getDorisCodeInfo: jest.fn(async () => { throw new TypeError("token abc leaked"); }) as never });
    await send({ t: "req", id: 1, path: "codeinfo", body: { code: "CA40" } });
    expect(JSON.stringify(replies)).not.toContain("token");
  });

  it("selects only after selection-check verified the code and uri, for the same revision", async () => {
    const { handlers, send, bump } = setup();
    await send({ t: "select", choice: { code: "CA40", uri: "https://who.int/CA40" } });
    expect(handlers.onSelect).not.toHaveBeenCalled();
    await send({ t: "req", id: 1, path: "selection-check", body: { code: "CA40", uri: "https://who.int/CA40" } });
    await send({ t: "select", choice: { code: "CA40", uri: "https://evil.example/x" } });
    expect(handlers.onSelect).not.toHaveBeenCalled();
    bump();
    await send({ t: "select", choice: { code: "CA40", uri: "https://who.int/CA40" } });
    expect(handlers.onSelect).not.toHaveBeenCalled();
  });

  it("hands the server's verified title and uri to the certificate", async () => {
    const { handlers, send } = setup();
    await send({ t: "req", id: 1, path: "selection-check", body: { code: "CA40", uri: "https://who.int/CA40" } });
    await send({ t: "select", choice: { code: "CA40", uri: "https://who.int/CA40", title: "forged title" } });
    expect(handlers.onSelect).toHaveBeenCalledWith({ code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40" });
  });

  it("passes uncoded text and close through, trimmed and bounded", async () => {
    const { handlers, send } = setup();
    await send({ t: "uncoded", text: "  Fever " });
    await send({ t: "uncoded", text: "   " });
    await send({ t: "uncoded", text: "x".repeat(400) });
    await send({ t: "close" });
    expect(handlers.onUncoded).toHaveBeenCalledTimes(1);
    expect(handlers.onUncoded).toHaveBeenCalledWith("Fever");
    expect(handlers.onClose).toHaveBeenCalledTimes(1);
  });
});

function luminance(hex: string): number {
  const channel = (offset: number) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("line colour shades", () => {
  it("gives each of five Part I lines and Part II a distinct bar colour in both modes", () => {
    for (const mode of ["light", "dark"] as const) {
      const bars = [0, 1, 2, 3, 4].map((index) => lineShade(mode, index, false).bar);
      bars.push(lineShade(mode, 0, true).bar);
      expect(new Set(bars).size).toBe(6);
    }
  });

  it("keeps chip text readable and cycles beyond five lines", () => {
    for (const mode of ["light", "dark"] as const) {
      for (const index of [0, 1, 2, 3, 4]) {
        const shade = lineShade(mode, index, false);
        expect(contrast(shade.chipText, shade.chipBg)).toBeGreaterThanOrEqual(4.5);
      }
      const part2 = lineShade(mode, 0, true);
      expect(contrast(part2.chipText, part2.chipBg)).toBeGreaterThanOrEqual(4.5);
    }
    expect(lineShade("light", 5, false)).toEqual(lineShade("light", 0, false));
  });
});

describe("editor colours in both modes", () => {
  it("keeps warnings, placeholders, errors and the picker text readable (4.5:1), borders visible (3:1)", () => {
    for (const mode of ["light", "dark"] as const) {
      const c = palette[mode];
      expect(contrast(c.warning, c.surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c.textMuted, c.surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c.text, c.surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c.danger, c.dangerSoft)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c.danger, c.surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c.text, c.accentSoft)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c.borderStrong, c.surface)).toBeGreaterThanOrEqual(3);
    }
  });
});
