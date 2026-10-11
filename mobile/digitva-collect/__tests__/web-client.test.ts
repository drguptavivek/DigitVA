import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

import {
  ClientApiError,
  fetchClientBootstrap,
  getCaseDetail,
  getInstrumentTranslations,
  getProjectFormOptions,
  requestClientJson,
} from "../src/client/api";
import { ServerDraftStore } from "../src/client/serverDraftStore";

type MockResponseOptions = {
  status: number;
  body?: unknown;
  contentType?: string;
  redirected?: boolean;
  url?: string;
  jsonError?: Error;
};

function response({
  status,
  body,
  contentType = "application/json",
  redirected = false,
  url = "",
  jsonError,
}: MockResponseOptions): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected,
    url,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? contentType : null,
    } as Headers,
    json: async () => {
      if (jsonError) throw jsonError;
      return body;
    },
    text: async () => (typeof body === "string" ? body : ""),
  } as Response;
}

const csrf = { header: "X-CSRFToken", token: "csrf" };

afterEach(() => {
  jest.restoreAllMocks();
});

describe("browser client", () => {
  it("rejects a successful HTML redirect instead of treating it as saved JSON", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      response({
        status: 200,
        contentType: "text/html",
        redirected: true,
        url: "https://example.test/vaauth/valogin",
      }),
    );

    await expect(
      requestClientJson("/api/v1/intake/drafts/d1", { csrf }),
    ).rejects.toMatchObject({
      status: 200,
      code: "redirected_response",
    });
  });

  it("accepts the POST logout redirect without parsing its HTML landing page", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        response({ status: 0, contentType: "", redirected: false, url: "/" }),
      );
    await expect(
      requestClientJson("/vaauth/valogout", {
        method: "POST",
        csrf,
        allowRedirect: true,
      }),
    ).resolves.toEqual({});
  });

  it("rejects a successful malformed JSON response explicitly", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        response({ status: 200, jsonError: new SyntaxError("invalid json") }),
      );

    await expect(
      requestClientJson("/api/v1/intake/cases", { csrf }),
    ).rejects.toMatchObject({
      status: 200,
      code: "malformed_response",
    });
  });

  it("uses the documented sign-in path on unauthorized access without response URLs", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ status: 401,
      body: { error: "Authentication required", code: "unauthorized" } }));
    await expect(fetchClientBootstrap()).resolves.toEqual({
      authenticated: false, loginUrl: "/vaauth/valogin?next=%2Fapp%2F"
    });
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/me/access", expect.anything());
  });

  it("routes pending terms to the existing browser acceptance workflow", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ status: 403,
      body: { error: "Accept terms", code: "terms_required" } }));
    await expect(fetchClientBootstrap()).resolves.toEqual({
      authenticated: false, loginUrl: "/profile/force-password-change", actionCode: "terms_required"
    });
  });

  it("loads project form options through the authorized project endpoint", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      response({
        status: 200,
        body: {
          project_id: "P1",
          enabled_extensions: ["digitva_core"],
          form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
          available_locales: [{ code: "en", label: "English" }],
          translation_versions: { en: 0 },
        },
      }),
    );

    await expect(getProjectFormOptions("P1", csrf)).resolves.toMatchObject({
      form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/organization/P1/form-options",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });

  it("surfaces a translation failure so the caller can keep the previous language", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        response({ status: 404, body: { code: "not_found" } }),
      );
    await expect(
      getInstrumentTranslations("WHO_2022_VA", "hi", csrf),
    ).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
  });

  it("loads a case detail by id from the server-provided cases link", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      response({
        status: 200,
        body: {
          case: {
            death_id: "death/1",
            informant: { name: "Ravi", phone: "+91 98765 43210" },
          },
        },
      }),
    );

    await expect(
      getCaseDetail("/prefix/api/v1/intake/cases/", "death/1", csrf),
    ).resolves.toMatchObject({
      case: { death_id: "death/1" },
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/prefix/api/v1/intake/cases/death%2F1",
      expect.objectContaining({
        credentials: "include",
        cache: "no-store",
        headers: expect.objectContaining({ "X-CSRFToken": "csrf" }),
      }),
    );
  });

  it("polls the signed-in user's bounded notification metadata with cookie credentials", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response({
      status: 200,
      body: { notifications: [], next_cursor: 12 },
    }));

    await expect(requestClientJson("/api/v1/me/notifications?after=12")).resolves.toEqual({
      notifications: [], next_cursor: 12,
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/me/notifications?after=12",
      expect.objectContaining({ method: "GET", credentials: "include", cache: "no-store" }),
    );
  });
});

describe("server draft store", () => {
  const draft: WhoVaDraft = {
    schemaVersion: 1,
    formVersion: "f1",
    id: "d1",
    instrumentId: "who-2022-va",
    instrumentVersion: "1",
    currentSection: "s1",
    createdAt: "2026-10-03T00:00:00Z",
    updatedAt: "2026-10-03T00:01:00Z",
    data: { Id10007: "updated" },
  };

  it("retains a failed write so an unchanged draft can be retried", async () => {
    const calls: Array<{ url: string; body?: Record<string, unknown> }> = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({
        url,
        body: init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : undefined,
      });
      if (calls.length === 1) {
        return response({
          status: 200,
          body: {
            draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "2026-10-03T00:01:00Z" },
            envelope: { ...draft, data: {} },
            prefill: {},
          },
        });
      }
      if (calls.length === 2)
        return response({
          status: 503,
          body: { code: "temporarily_unavailable" },
        });
      return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "2026-10-03T00:02:00Z" } } });
    });
    const store = new ServerDraftStore({
      endpoint: "/api/v1/intake/drafts",
      csrf,
      sectionOf: new Map([["Id10007", "s1"]]),
      locale: "hi",
      translationVersion: 7,
    });
    await store.load("d1");
    const savePromise = store.save(draft);
    await expect(store.flush()).rejects.toBeInstanceOf(ClientApiError);
    await expect(savePromise).rejects.toBeInstanceOf(ClientApiError);
    await expect(store.flush()).resolves.toBeUndefined();
    expect(calls.map((call) => call.url)).toEqual([
      "/api/v1/intake/drafts/d1",
      "/api/v1/intake/drafts/d1",
      "/api/v1/intake/drafts/d1",
    ]);
    expect(calls[2].body).toMatchObject({
      meta: { locale: "hi", translation_version: 7 },
    });
  });

  it("serializes queued saves using each acknowledged server revision", async () => {
    const requests: Array<{ method: string; body?: Record<string, unknown> }> = [];
    let releaseFirst!: (reply: Response) => void;
    const firstPatch = new Promise<Response>((resolve) => { releaseFirst = resolve; });
    let markPatchStarted!: () => void;
    const patchStarted = new Promise<void>((resolve) => { markPatchStarted = resolve; });
    jest.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ method, body });
      if (method === "GET") return response({ status: 200, body: {
        draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "revision-0" },
        envelope: { ...draft, data: {} }, prefill: {}
      } });
      if (requests.filter((request) => request.method === "PATCH").length === 1) {
        markPatchStarted();
        return firstPatch;
      }
      return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "revision-2" } } });
    });
    const store = new ServerDraftStore({ endpoint: "/api/v1/intake/drafts", csrf, sectionOf: new Map([["Id10007", "s1"]]) });
    await store.load("d1");
    const first = store.save(draft);
    const firstFlush = store.flush();
    await patchStarted;
    const second = store.save({ ...draft, data: { Id10007: "newer" } });
    const secondFlush = store.flush();
    expect(requests.filter((request) => request.method === "PATCH")).toHaveLength(1);
    releaseFirst(response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "revision-1" } } }));
    await Promise.all([first, firstFlush, second, secondFlush]);
    const patches = requests.filter((request) => request.method === "PATCH");
    expect(patches.map((request) => request.body?.if_updated_at)).toEqual(["revision-0", "revision-1"]);
    expect(store.getServerUpdatedAt()).toBe("revision-2");
  });

  it("refuses a stale save and retains it for an explicit retry", async () => {
    const patches: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PATCH") {
        patches.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return response({ status: 409, body: { error: "This interview was also edited on another device.", code: "draft_stale" } });
      }
      return response({ status: 200, body: {
        draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "revision-0" },
        envelope: { ...draft, data: {} }, prefill: {}
      } });
    });
    const store = new ServerDraftStore({ endpoint: "/api/v1/intake/drafts", csrf, sectionOf: new Map([["Id10007", "s1"]]) });
    await store.load("d1");
    const pending = store.save(draft);
    await expect(store.flush()).rejects.toMatchObject({ status: 409, code: "draft_stale" });
    await expect(pending).rejects.toMatchObject({ status: 409, code: "draft_stale" });
    await expect(store.flush()).rejects.toMatchObject({ status: 409, code: "draft_stale" });
    expect(patches).toHaveLength(2);
    expect(patches.map((body) => body.if_updated_at)).toEqual(["revision-0", "revision-0"]);
    expect(store.getServerUpdatedAt()).toBe("revision-0");
  });

  it("does not advance the server revision from an acknowledgement for another draft", async () => {
    const patches: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PATCH") {
        patches.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "other", updated_at: "revision-1" } } });
      }
      return response({ status: 200, body: {
        draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "revision-0" },
        envelope: { ...draft, data: {} }, prefill: {}
      } });
    });
    const store = new ServerDraftStore({ endpoint: "/api/v1/intake/drafts", csrf, sectionOf: new Map([["Id10007", "s1"]]) });
    await store.load("d1");
    const pending = store.save(draft);
    await expect(store.flush()).rejects.toMatchObject({ status: 200, code: "malformed_response" });
    await expect(pending).rejects.toMatchObject({ status: 200, code: "malformed_response" });
    expect(store.getServerUpdatedAt()).toBe("revision-0");
    expect(patches[0].if_updated_at).toBe("revision-0");
  });

  it("writes a locale change even when no answer section changed", async () => {
    const requests: Array<{ url: string; body?: Record<string, unknown> }> = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      requests.push({
        url: String(input),
        body: init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : undefined,
      });
      if (requests.length === 1) {
        return response({
          status: 200,
          body: {
            draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "2026-10-03T00:01:00Z" },
            envelope: {
              ...draft,
              data: {},
              locale: "en",
              translation_version: 0,
            },
            prefill: {},
          },
        });
      }
      if (requests.length === 3) {
        return response({
          status: 200,
          body: {
            draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "2026-10-03T00:03:00Z" },
            envelope: {
              ...draft,
              data: {},
              locale: "hi",
              translation_version: 7,
            },
            prefill: {},
          },
        });
      }
      return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "2026-10-03T00:02:00Z" } } });
    });
    const store = new ServerDraftStore({
      endpoint: "/api/v1/intake/drafts",
      csrf,
      sectionOf: new Map([["Id10007", "s1"]]),
      locale: "en",
      translationVersion: 0,
    });
    await store.load("d1");
    store.setLocaleMetadata("hi", 7);
    const unchanged = { ...draft, data: {}, currentSection: "s1" };
    const savePromise = store.save(unchanged);
    await store.flush();
    await savePromise;
    expect(requests).toHaveLength(2);
    expect(requests[1].body).toMatchObject({
      meta: { locale: "hi", translation_version: 7 },
    });
    expect(requests[1].body?.sections).toEqual({});
    await store.load("d1");
    const reloaded = store.save(unchanged);
    await store.flush();
    await reloaded;
    expect(requests).toHaveLength(3);
  });

  it("does not retry a failed locale write with the new metadata", async () => {
    const requests: Array<{ url: string; body?: Record<string, unknown> }> = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      requests.push({
        url: String(input),
        body: init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : undefined,
      });
      if (requests.length === 1) {
        return response({
          status: 200,
          body: {
            draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "2026-10-03T00:01:00Z" },
            envelope: {
              ...draft,
              data: {},
              locale: "en",
              translation_version: 0,
            },
            prefill: {},
          },
        });
      }
      if (requests.length === 2)
        return response({
          status: 503,
          body: { code: "temporarily_unavailable" },
        });
      return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "2026-10-03T00:02:00Z" } } });
    });
    const store = new ServerDraftStore({
      endpoint: "/api/v1/intake/drafts",
      csrf,
      sectionOf: new Map([["Id10007", "s1"]]),
      locale: "en",
      translationVersion: 0,
    });
    await store.load("d1");
    const previous = store.getLocaleMetadata();
    store.setLocaleMetadata("hi", 7);
    const localeSave = store.save({ ...draft, data: {} });
    await expect(store.flush()).rejects.toBeInstanceOf(ClientApiError);
    await expect(localeSave).rejects.toBeInstanceOf(ClientApiError);
    store.restoreLocaleMetadata(previous);

    const ordinarySave = store.save(draft);
    await store.flush();
    await ordinarySave;
    expect(requests).toHaveLength(3);
    expect(requests[1].body).toMatchObject({
      meta: { locale: "hi", translation_version: 7 },
    });
    expect(requests[2].body).toMatchObject({
      meta: { locale: "en", translation_version: 0 },
    });
    expect(store.getLocaleMetadata()).toEqual(previous);
  });

  it("merges new prefill defaults under saved answers and sends only the defaults as changes", async () => {
    const requests: Array<{ body?: Record<string, unknown> }> = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      requests.push({
        body: init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : undefined,
      });
      if (requests.length === 1) {
        return response({
          status: 200,
          body: {
            draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "2026-10-03T00:01:00Z" },
            envelope: { ...draft, data: { Id10010: "Saved interviewer" } },
            prefill: {},
          },
        });
      }
      return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "2026-10-03T00:02:00Z" } } });
    });
    const store = new ServerDraftStore({
      endpoint: "/api/v1/intake/drafts",
      csrf,
      sectionOf: new Map([
        ["Id10010", "interviewer"],
        ["Id10017", "deceased"],
      ]),
      initialData: { Id10010: "New interviewer", Id10017: "Ramesh" },
    });
    const loaded = await store.load("d1");
    expect(loaded?.data).toMatchObject({
      Id10010: "Saved interviewer",
      Id10017: "Ramesh",
    });
    const savePromise = store.save({ ...draft, data: loaded?.data ?? {} });
    await store.flush();
    await savePromise;
    expect(requests[1].body?.sections).toEqual({
      deceased: { Id10017: "Ramesh" },
    });
  });
  it("persists clearing the last answer in a section across reload", async () => {
    let savedData: Record<string, unknown> = { Id10007: "old" };
    const patches: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        patches.push(body.sections);
        if (Object.hasOwn(body.sections, "s1"))
          savedData = { ...body.sections.s1 };
        return response({ status: 200, body: { saved_sections: 1, draft: { draft_id: "d1", updated_at: "2026-10-03T00:02:00Z" } } });
      }
      return response({
        status: 200,
        body: {
          draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "2026-10-03T00:01:00Z" },
          envelope: { ...draft, data: savedData },
          prefill: {},
        },
      });
    });
    const store = new ServerDraftStore({
      endpoint: "/api/v1/intake/drafts",
      csrf,
      sectionOf: new Map([["Id10007", "s1"]]),
    });
    const loaded = await store.load("d1");
    expect(loaded?.data).toEqual({ Id10007: "old" });
    const cleared = { ...loaded!, data: {} };
    const pending = store.save(cleared);
    await store.flush();
    await pending;
    expect(patches).toEqual([{ s1: {} }]);
    expect((await store.load("d1"))?.data).toEqual({});
    const repeated = store.save(cleared);
    await store.flush();
    await repeated;
    expect(patches).toHaveLength(1);
  });

  it("pins a served definition before the first answer save and preserves it on later writes", async () => {
    const requests: Array<{ method: string; body?: Record<string, unknown> }> = [];
    const pin = {
      instrumentVersion: "served-2",
      definitionSha256: "a".repeat(64),
      definitionExtensions: ["digitva_core"],
    };
    jest.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ method, body });
      if (method === "PATCH") {
        return response({ status: 200, body: { saved_sections: 0, draft: { draft_id: "d1", updated_at: `revision-${requests.length}` } } });
      }
      return response({ status: 200, body: {
        draft: { draft_id: "d1", project_id: "p1", site_id: "s1", updated_at: "revision-0" },
        envelope: { ...draft, instrumentVersion: "served-2", data: { Id10007: "server answer" } },
        prefill: {},
      } });
    });
    const store = new ServerDraftStore({
      endpoint: "/api/v1/intake/drafts", csrf, sectionOf: new Map([["Id10007", "s1"]]),
      definitionPin: pin,
    });
    const loaded = await store.load("d1");
    expect(loaded).toMatchObject({
      instrumentVersion: pin.instrumentVersion,
      definitionSha256: pin.definitionSha256,
      definitionExtensions: pin.definitionExtensions,
      data: { Id10007: "server answer" },
    });
    expect(requests[1].body?.meta).toMatchObject({
      instrumentVersion: pin.instrumentVersion,
      definitionSha256: pin.definitionSha256,
      definitionExtensions: pin.definitionExtensions,
    });

    const pending = store.save({
      ...loaded!, instrumentVersion: "changed", definitionSha256: "b".repeat(64),
      definitionExtensions: [], data: { Id10007: "edited answer" },
    } as WhoVaDraft);
    await store.flush();
    await pending;
    expect(requests[2].body?.meta).toMatchObject({
      instrumentVersion: pin.instrumentVersion,
      definitionSha256: pin.definitionSha256,
      definitionExtensions: pin.definitionExtensions,
    });
    expect(requests[2].body?.sections).toEqual({ s1: { Id10007: "edited answer" } });
  });
});
