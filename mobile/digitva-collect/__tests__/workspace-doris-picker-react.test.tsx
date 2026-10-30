import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { Platform } from "react-native";

import { ApiError } from "../src/api";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import { ui, __setThemePreferenceForTest } from "../src/theme";
import { IcdPicker } from "../src/workspace/doris/picker/IcdPicker";
import { createPickerBridge, type PickerInit } from "../src/workspace/doris/pickerBridge";

// A test may set `mockWindow` to lay the picker out at another size or font scale; null keeps the renderer's own 750 x 1334.
let mockWindow: { width: number; height: number; fontScale: number } | null = null;
jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const own = actual.useWindowDimensions;
  Object.defineProperty(actual, "useWindowDimensions", { value: () => (mockWindow ? { ...mockWindow, scale: 1 } : own()), configurable: true });
  return actual;
});
// A test may set `mockInsets` for a device with a side cutout (a tablet in landscape).
const NO_SIDE_INSETS = { top: 10, bottom: 20, left: 0, right: 0 };
let mockInsets = NO_SIDE_INSETS;
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => mockInsets }));

const identity = { vaSid: "sid-1", mode: "coding" as const };

/* ---------------------------------------------------------------- server fakes */

const term = (code: string, title: string, extra: Record<string, unknown> = {}) => ({
  code, title, uri: `https://who.int/${code}`, release: "2025-01", matching_text: title, postcoordination: false, postcoordination_availability: 0,
  related_maternal: false, related_perinatal: false, has_coding_note: false, ...extra,
});
const opt = (code: string, extra: Record<string, unknown> = {}) => ({ code, title: `Title ${code}`, uri: `https://who.int/${code}`, has_children: false, ...extra });
const failure = (status: number, code: string, message: string) => Object.assign(new ApiError(status, code), { message });

const axes = () => [
  { id: "hasManifestation", label: "Has manifestation", instruction: "use additional code, if desired", required: false, allow_multiple_values: "AllowAlways", options: [opt("MC85"), opt("MC86", { has_children: true })], subtree_uris: ["https://who.int/s-man"], truncated: false },
  { id: "hasCausingCondition", label: "Has causing condition", instruction: "code also", required: true, allow_multiple_values: "AllowedExceptFromSameBlock", options: [opt("5A11", { block_uri: "b1" }), opt("5A12", { block_uri: "b1" }), opt("6B00", { block_uri: "b2" }), { code: "", title: "Endocrine group", uri: "https://who.int/g", has_children: true }], subtree_uris: ["https://who.int/s-cause"], truncated: false },
  { id: "severity", label: "Has severity", required: false, allow_multiple_values: "NotAllowed", options: [opt("XS1"), opt("XS2")], subtree_uris: [], truncated: false },
];
const postcoordination = (over: Record<string, unknown> = {}) => ({
  schema_version: 1, stem: opt("BD54", { title: "Acute MI" }), axes: axes(), other_postcoordination: { subtree_uris: ["https://who.int/x-chapter"] }, truncated: false, ...over,
});

interface Env {
  terms?: (query: string, options?: { limit?: number; subtreeUris?: string[] }) => unknown;
  codeinfo?: (code: string) => unknown;
  check?: (code: string, uri: string) => unknown;
  guidance?: Record<string, (body: Record<string, unknown>) => unknown>;
}

function makeEnv(env: Env = {}) {
  const info = (code: string) => ({ schema_version: 1, item: { code, title: `Title ${code}`, uri: `https://who.int/${code}`, release: "2025-01", postcoordination: false, primary_stem: null } });
  const api = {
    searchDorisTerms: jest.fn(async (_sid: string, query: string, options?: { limit?: number; subtreeUris?: string[] }) => (env.terms ? env.terms(query, options) : { schema_version: 1, items: [term("CA40", "Pneumonia")], truncated: false, next_cursor: null })),
    getDorisCodeInfo: jest.fn(async (_sid: string, code: string) => (env.codeinfo ? env.codeinfo(code) : info(code))),
    checkDorisSelection: jest.fn(async (_sid: string, code: string, uri: string) => (env.check ? env.check(code, uri) : { schema_version: 1, item: { ...info(code).item, uri, title: `Verified ${code}` } })),
  } as unknown as WorkspaceApi;
  const guidance = env.guidance ?? {};
  const request = jest.fn(async (path: string, options?: { json?: Record<string, unknown> }) => {
    const handler = guidance[path.split("/")[4]];
    // The offline requester's own failure: the picker must not show this raw text.
    if (!handler) throw new Error("offline_server_unavailable");
    return handler(options?.json ?? {});
  }) as unknown as JsonRequester;
  return { api, request };
}

/* ------------------------------------------------------------------- harness */

const mounted: Array<() => void> = [];
const baseInit: PickerInit = { title: "Immediate cause", accent: "#C2185B", allowUncoded: true, theme: "light" };

function mount(options: { init?: Partial<PickerInit>; revision?: number; env?: Env } = {}) {
  const { api, request } = makeEnv(options.env);
  const init = { ...baseInit, ...options.init };
  const state = { revision: options.revision ?? 1 };
  const handlers = { onSelect: jest.fn(), onUncoded: jest.fn(), onForbidden: jest.fn(), onClose: jest.fn() };
  const makeBridge = () => createPickerBridge({ api, request, identity, revision: () => state.revision, allowUncoded: () => init.allowUncoded, ...handlers });
  let bridge = makeBridge();
  let generation = 0;
  const element = () => <IcdPicker init={init} revision={state.revision} generation={generation} onMessage={(message, reply) => void bridge.handle(message, reply)} onClose={handlers.onClose} />;
  let tree!: ReactTestRenderer;
  act(() => { tree = create(element()); });
  mounted.push(() => act(() => tree.unmount()));
  return {
    api, request, handlers, get tree() { return tree; },
    /** Lays the picker out again, as after the window turned. */
    rerender: () => act(() => tree.update(element())),
    setRevision: (revision: number) => { state.revision = revision; act(() => tree.update(element())); },
    /** What IcdPickerModal does when the parent's request generation moves: a new bridge, the old one never answers. */
    replaceBridge: () => { bridge.dispose(); bridge = makeBridge(); generation += 1; act(() => tree.update(element())); },
  };
}
type Harness = ReturnType<typeof mount>;

async function settle() {
  for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}
const flat = (node: unknown): string => (node == null ? "" : typeof node === "string" ? node : Array.isArray(node) ? node.map(flat).join("") : flat((node as { children?: unknown }).children));
const text = (h: Harness) => flat(h.tree.toJSON());
const control = (h: Harness, label: string): ReactTestInstance => {
  const found = h.tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
  if (!found) throw new Error(`No control labelled "${label}"`);
  return found;
};
const has = (h: Harness, label: string) => h.tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function").length > 0;
const field = (h: Harness, label: string): ReactTestInstance => {
  const found = h.tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onChangeText === "function")[0];
  if (!found) throw new Error(`No field labelled "${label}"`);
  return found;
};
/** A tap on an enabled control; a disabled one does nothing, as on a phone. */
async function press(h: Harness, label: string) {
  const node = control(h, label);
  if (node.props.disabled || node.props.accessibilityState?.disabled) return;
  act(() => node.props.onPress());
  await settle();
}
/** Optional build axes are folded on a phone; this opens one by its name. */
async function openAxis(h: Harness, label: string) {
  const node = h.tree.root.findAll((n) => typeof n.props.accessibilityLabel === "string" && n.props.accessibilityLabel.startsWith(`${label}, optional`) && typeof n.props.onPress === "function")[0];
  act(() => node.props.onPress());
  await settle();
}
/** What assistive tech reads from an option row: the state of its host element. */
const optionState = (h: Harness, label: string) => h.tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityLabel === label)[0].props.accessibilityState;
/** The keyboard's search key; the picker has no Search button. */
async function submit(h: Harness) {
  act(() => field(h, SEARCH).props.onSubmitEditing());
  await settle();
}
async function typeInto(h: Harness, label: string, value: string) {
  act(() => field(h, label).props.onChangeText(value));
  await settle();
}
const SEARCH = "Search a condition or ICD-11 code";
/** Our own wording for WHO_API_UNAVAILABLE; the server's text is never shown. */
const WHO_DOWN = "The WHO ICD-11 service is unavailable. Try again shortly.";
const GENERIC = "The request could not be completed.";
const WHO_DOWN_FAILURE = () => failure(503, "WHO_API_UNAVAILABLE", "raw server words");
const previewCode = (h: Harness) => h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children;
/** Hierarchy is reached from a code's Details card, not from the result row. */
async function openHierarchy(h: Harness, code: string) {
  await press(h, `Details of ${code}`);
  await press(h, `Hierarchy of ${code}`);
}
async function search(h: Harness, value: string) {
  await typeInto(h, SEARCH, value);
  await submit(h);
}
const advance = async (ms: number) => { await act(async () => { jest.advanceTimersByTime(ms); }); await settle(); };
const calls = (h: Harness, endpoint: string) => (h.request as jest.Mock).mock.calls.filter(([path]) => String(path).includes(`/${endpoint}/`)).map(([, options]) => options.json);

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => {
  mockWindow = null;
  mockInsets = NO_SIDE_INSETS;
  mounted.splice(0).forEach((unmount) => unmount());
  act(() => __setThemePreferenceForTest("light"));
  jest.useRealTimers();
});

/* ------------------------------------------------------------------- search */

describe("search", () => {
  it("opens with the suggested text, searches at once and lists code, title, matched wording and the bound of 20", async () => {
    const env: Env = { terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia", { matching_text: "Lung infection" }), term("CA41", "Bronchitis")], truncated: false, next_cursor: null }) };
    const h = mount({ init: { query: "pneu" }, env });
    await settle();
    expect(h.api.searchDorisTerms).toHaveBeenCalledWith("sid-1", "pneu", { limit: 20 });
    const out = text(h);
    expect(out).toContain("Immediate cause");
    expect(out).toContain("CA40 — Pneumonia");
    expect(out).toContain("Matched: Lung infection");
    expect(out).not.toContain("Matched: Bronchitis");
    expect(out).toContain("Choose a result.");
    expect(out).toContain("No code selected");
  });

  it("follows the app's search rule: from 3 characters, 500 ms after the last keystroke, and a term only once", async () => {
    const h = mount();
    await settle();
    await typeInto(h, SEARCH, "p");
    await typeInto(h, SEARCH, "pn");
    await advance(1000);
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    await typeInto(h, SEARCH, "pneu");
    await advance(499);
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    await typeInto(h, SEARCH, "pneum");
    await advance(499);
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    await advance(1);
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(1);
    expect(h.api.searchDorisTerms).toHaveBeenCalledWith("sid-1", "pneum", { limit: 20 });
    // The same term again (also after surrounding blanks) does not search again ...
    await typeInto(h, SEARCH, "pneum ");
    await advance(1000);
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(1);
    // ... until the box dropped under 3 characters; two characters keep the old results, one clears them.
    await typeInto(h, SEARCH, "pn");
    expect(text(h)).toContain("CA40 — Pneumonia");
    await typeInto(h, SEARCH, "pneum");
    await advance(500);
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(2);
    await typeInto(h, SEARCH, "p");
    expect(text(h)).not.toContain("Choose a result.");
    expect(text(h)).not.toContain("CA40");
  });

  it("does not search again for a term an explicit Search already ran", async () => {
    const h = mount();
    await search(h, "pneu");
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(1);
    await typeInto(h, SEARCH, "pneu");
    await advance(1000);
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(1);
  });

  it("searches on the keyboard's search key, which has no button beside it, and asks for two characters", async () => {
    const h = mount();
    await typeInto(h, SEARCH, "x");
    await submit(h);
    expect(text(h)).toContain("Type at least 2 characters.");
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    await typeInto(h, SEARCH, "fever");
    await submit(h);
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(1);
    await submit(h);
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(2);
  });

  it("looks a code up with codeinfo and anything else with a text search", async () => {
    const h = mount({ env: { codeinfo: (code) => ({ schema_version: 1, item: { code, title: "Pneumonia", uri: "https://who.int/CA40", release: "r", postcoordination: true, postcoordination_availability: 1, primary_stem: null } }) } });
    await search(h, "CA40");
    expect(h.api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "CA40");
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    expect(text(h)).toContain("CA40 — Pneumonia");
    expect(has(h, "Postcoordination available")).toBe(true);
    await search(h, "type 2 diabetes");
    expect(h.api.searchDorisTerms).toHaveBeenCalledWith("sid-1", "type 2 diabetes", { limit: 20 });
    await search(h, "pneumonia");
    expect(h.api.searchDorisTerms).toHaveBeenCalledTimes(2);
  });

  it("says when nothing matched and when WHO cut the list", async () => {
    let reply: { items: unknown[]; truncated: boolean } = { items: [], truncated: false };
    const h = mount({ env: { terms: () => ({ schema_version: 1, ...reply, next_cursor: null }) } });
    await search(h, "zzzz");
    expect(text(h)).toContain("No matching conditions.");
    reply = { items: [term("CA40", "Pneumonia")], truncated: true };
    await search(h, "pneu");
    expect(text(h)).toContain("Showing the first 20 matches. Refine the search to see others.");
    expect(text(h)).toContain("CA40 — Pneumonia");
  });

  it("shows a failed search or code lookup as an alert in our own words for a known DORIS code", async () => {
    const h = mount({ env: { terms: () => { throw WHO_DOWN_FAILURE(); }, codeinfo: () => { throw failure(404, "CODE_NOT_FOUND", "raw server words"); } } });
    await search(h, "pneu");
    expect(h.tree.root.findAll((node) => node.props.accessibilityRole === "alert" && flat(node.children).includes(WHO_DOWN)).length).toBeGreaterThan(0);
    await search(h, "ZZ99");
    expect(text(h)).toContain("Select a valid ICD-11 code.");
    expect(text(h)).not.toContain("raw server words");
  });

  it("shows only a generic line for a failure without a known DORIS code, never the raw text", async () => {
    const h = mount({ env: { terms: () => { throw failure(502, "request_failed", "HTTP 502 code"); }, codeinfo: () => { throw Object.assign(new Error(""), {}); } } });
    await search(h, "pneu");
    expect(text(h)).toContain(GENERIC);
    expect(text(h)).not.toContain("HTTP 502");
    await search(h, "ZZ99");
    expect(text(h)).toContain(GENERIC);
  });

  it("drops a slow reply that a newer search has replaced", async () => {
    let release!: (value: unknown) => void;
    let first = true;
    const h = mount({ env: { terms: (query) => {
      if (first) { first = false; return new Promise((resolve) => { release = resolve; }); }
      return { schema_version: 1, items: [term("NEW1", `Newer ${query}`)], truncated: false, next_cursor: null };
    } } });
    await search(h, "older");
    await search(h, "newer");
    expect(text(h)).toContain("NEW1 — Newer newer");
    await act(async () => { release({ schema_version: 1, items: [term("OLD1", "Older")], truncated: false, next_cursor: null }); });
    await settle();
    expect(text(h)).not.toContain("OLD1");
    expect(text(h)).toContain("NEW1");
  });

  it("drops a slow failure that a newer search has replaced", async () => {
    let fail!: (error: Error) => void;
    let first = true;
    const h = mount({ env: { terms: () => {
      if (first) { first = false; return new Promise((_resolve, reject) => { fail = reject; }); }
      return { schema_version: 1, items: [term("NEW1", "Newer")], truncated: false, next_cursor: null };
    } } });
    await search(h, "older");
    await search(h, "newer");
    await act(async () => { fail(new Error("late failure")); });
    await settle();
    expect(text(h)).not.toContain("late failure");
  });

  it("Reset clears the text, results and selection; Close leaves through the modal", async () => {
    const h = mount();
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    expect(text(h)).toContain("SELECTED");
    await press(h, "Reset search and current selection");
    expect(text(h)).not.toContain("CA40");
    expect(text(h)).toContain("No code selected");
    expect(field(h, SEARCH).props.value).toBe("");
    await press(h, "Close search");
    expect(h.handlers.onClose).toHaveBeenCalledTimes(1);
  });

  it("starts the pending debounce over on Reset", async () => {
    const h = mount();
    await typeInto(h, SEARCH, "pneu");
    await press(h, "Reset search and current selection");
    await advance(500);
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
  });

  it("clears pending results when the text goes below two characters", async () => {
    const h = mount();
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    expect(text(h)).toContain("See in hierarchy");
    await typeInto(h, SEARCH, "p");
    expect(text(h)).not.toContain("CA40");
    expect(text(h)).not.toContain("See in hierarchy");
  });

  it("clears a staged choice and its details as soon as the text changes", async () => {
    const h = mount({ env: { guidance: { details: () => ({ schema_version: 1, definition: "A lung infection." }) } } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await settle();
    expect(text(h)).toContain("A lung infection.");
    await typeInto(h, SEARCH, "pneum");
    expect(text(h)).not.toContain("SELECTED");
    expect(text(h)).not.toContain("A lung infection.");
  });
});

/* -------------------------------------------------------- uncoded text, theme */

describe("uncoded text, theme and chrome", () => {
  it("offers uncoded text only for a line, and sends it trimmed to the bridge", async () => {
    const h = mount();
    await press(h, "Add uncoded text");
    expect(text(h)).toContain("Enter the condition text first.");
    expect(h.handlers.onUncoded).not.toHaveBeenCalled();
    await typeInto(h, SEARCH, "  Fever of unknown cause ");
    await press(h, "Add uncoded text");
    expect(h.handlers.onUncoded).toHaveBeenCalledWith("Fever of unknown cause");
    const final = mount({ init: { allowUncoded: false, finalMode: true } });
    expect(has(final, "Add uncoded text")).toBe(false);
  });

  it("renders in light and dark with the theme tokens, and the accent bar of the line", () => {
    const style = (h: Harness, testID: string) => h.tree.root.findAll((node) => node.props.testID === testID).map((node) => node.props.style).flat(Infinity);
    const light = mount({ init: { query: "" } });
    expect(JSON.stringify(light.tree.toJSON())).toContain(ui.light.accent);
    expect(JSON.stringify(light.tree.toJSON())).toContain("#C2185B");
    expect(JSON.stringify(light.tree.toJSON())).not.toContain(ui.dark.accent);
    act(() => __setThemePreferenceForTest("dark"));
    const dark = mount();
    expect(JSON.stringify(dark.tree.toJSON())).toContain(ui.dark.accent);
    expect(JSON.stringify(dark.tree.toJSON())).not.toContain(ui.light.accent);
    expect(style(dark, "none")).toEqual([]);
  });

  it("uses the brand colour when the accent is not a hex shade", () => {
    const h = mount({ init: { accent: "red; background:url(x)" } });
    const json = JSON.stringify(h.tree.toJSON());
    expect(json).toContain(ui.light.primary);
    expect(json).not.toContain("url(x)");
  });

  it("pads for the keyboard on iOS only", async () => {
    const original = Platform.OS;
    try {
      (Platform as { OS: string }).OS = "android";
      const android = mount();
      expect(android.tree.root.findAll((node) => node.props.behavior !== undefined).length).toBe(0);
      await search(android, "pneu");
      await press(android, "CA40 Pneumonia");
      expect(text(android)).toContain("SELECTED");
      (Platform as { OS: string }).OS = "ios";
      const ios = mount();
      expect(ios.tree.root.findAll((node) => node.props.behavior === "padding").length).toBeGreaterThan(0);
      await search(ios, "pneu");
      await press(ios, "CA40 Pneumonia");
      expect(text(ios)).toContain("SELECTED");
    } finally { (Platform as { OS: string }).OS = original; }
  });
});

/* ------------------------------------------------------------ rows and badges */

describe("result rows and badges", () => {
  const rows = [
    term("CA40", "Pneumonia"),
    term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2, has_coding_note: true }),
    term("NC72.7", "Injury", { postcoordination: true, postcoordination_availability: 1 }),
    term("BD54/MC85", "Complete", { postcoordination: true, postcoordination_availability: 2 }),
    term("JA00", "Pregnancy", { related_maternal: true, related_perinatal: true }),
  ];
  const env: Env = { terms: () => ({ schema_version: 1, items: rows, truncated: false, next_cursor: null }) };

  it("has no Use or Details button on a phone: line 1 is the Use, Details is the trailing 'ⓘ'", async () => {
    mockWindow = { width: 360, height: 800, fontScale: 1 };
    const h = mount({ env });
    await search(h, "heart");
    for (const code of ["CA40", "BD54", "NC72.7", "BD54/MC85", "JA00"]) {
      expect(has(h, `Use ${code}`)).toBe(false);
      expect(has(h, `Details of ${code}`)).toBe(true);
    }
    expect(has(h, "Hierarchy of BD54")).toBe(false);
    expect(h.tree.root.findAll((node) => node.props.children === "Details" && typeof node.type === "string")).toHaveLength(0);
  });

  it("shows small Use and Details buttons at the right on a tablet, and withholds Use while postcoordination is mandatory unless the code is a complete expression", async () => {
    mockWindow = { width: 1180, height: 820, fontScale: 1 };
    const h = mount({ env });
    await search(h, "heart");
    expect(has(h, "Use CA40")).toBe(true);
    expect(has(h, "Use BD54")).toBe(false);
    expect(has(h, "Use NC72.7")).toBe(true);
    expect(has(h, "Use BD54/MC85")).toBe(true);
    expect(has(h, "Details of BD54")).toBe(true);
    expect(has(h, "Hierarchy of BD54")).toBe(false);
  });

  it("line 1 stages an ordinary code and routes a mandatory stem to its builder, never to OK", async () => {
    const h = mount({ env: { ...env, guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }) } } });
    await search(h, "heart");
    await press(h, "CA40 Pneumonia");
    expect(text(h)).toContain("SELECTED");
    expect(calls(h, "postcoordination")).toEqual([]);
    await press(h, "BD54 Acute MI");
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "BD54" }]);
    expect(control(h, "BD54 Acute MI").props.accessibilityHint).toMatch(/builder/);
    expect(control(h, "CA40 Pneumonia").props.accessibilityHint).toBe("Selects this code");
  });

  it("labels the badges for assistive technology", async () => {
    const h = mount({ env });
    await search(h, "heart");
    expect(has(h, "Mandatory postcoordination")).toBe(true);
    expect(has(h, "Postcoordination available")).toBe(true);
    expect(has(h, "Open coding note")).toBe(true);
    expect(has(h, "Open pregnancy related terms")).toBe(true);
    expect(has(h, "Open perinatal related terms")).toBe(true);
  });

  it("a plain result without badges draws none", async () => {
    const h = mount();
    await search(h, "pneu");
    expect(has(h, "Open coding note")).toBe(false);
    expect(has(h, "Mandatory postcoordination")).toBe(false);
  });
});

/* ------------------------------------------------- staging, OK and verification */

describe("staging and verification", () => {
  it("OK hands on only the pair the server verified, with the server's own title", async () => {
    const h = mount();
    await search(h, "pneu");
    expect(control(h, "Use the selected code").props.disabled).toBe(true);
    await press(h, "CA40 Pneumonia");
    expect(text(h)).toContain("SELECTED");
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    await press(h, "Use the selected code");
    expect(h.api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "CA40", "https://who.int/CA40");
    expect(h.handlers.onSelect).toHaveBeenCalledWith({ code: "CA40", title: "Verified CA40", uri: "https://who.int/CA40" });
  });

  it("tapping the title of an ordinary result stages it", async () => {
    const h = mount();
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    expect(text(h)).toContain("SELECTED");
  });

  it("shows why a code was refused and hands nothing on", async () => {
    const h = mount({ env: { check: () => { throw failure(422, "INVALID_SELECTION", "raw server words") } } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(text(h)).toContain("The selected code does not match its WHO URI.");
    expect(text(h)).not.toContain("raw server words");
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    expect(control(h, "Use the selected code").props.disabled).toBe(false);
  });

  it("refuses a verification reply that lacks a code or uri", async () => {
    const h = mount({ env: { check: () => ({ schema_version: 1, item: { code: "", title: "t", uri: "", release: "r", postcoordination: false, primary_stem: null } }) } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(text(h)).toContain("The server did not return a verified code and URI.");
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
  });

  it("shows the generic line when verification fails without a known code", async () => {
    const h = mount({ env: { check: () => { throw new Error(""); } } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(text(h)).toContain("The request could not be completed.");
  });

  it("ends the edit when the server says the allocation is gone", async () => {
    const h = mount({ env: { check: () => { throw failure(403, "FORBIDDEN", "Not allowed."); } } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(h.handlers.onForbidden).toHaveBeenCalledTimes(1);
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
  });

  it("drops a verification that arrives after the certificate moved on", async () => {
    let release!: (value: unknown) => void;
    const h = mount({ env: { check: () => new Promise((resolve) => { release = resolve; }) } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(text(h)).toContain("Verifying CA40…");
    h.setRevision(2);
    await settle();
    await act(async () => { release({ schema_version: 1, item: { code: "CA40", title: "t", uri: "https://who.int/CA40", release: "r", postcoordination: false, primary_stem: null } }); });
    await settle();
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    expect(text(h)).toContain("No code selected");
    expect(text(h)).not.toContain("Verifying");
    expect(control(h, "Use the selected code").props.disabled).toBe(true);
  });

  it("a stale failure after the certificate moved is not shown", async () => {
    let fail!: (error: Error) => void;
    const h = mount({ env: { check: () => new Promise((_resolve, reject) => { fail = reject; }) } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    h.setRevision(2);
    await settle();
    await act(async () => { fail(new Error("late refusal")); });
    await settle();
    expect(text(h)).not.toContain("late refusal");
  });

  it("starts over when the certificate moves: searches again and closes every panel", async () => {
    const h = mount({ env: { guidance: { details: () => ({ schema_version: 1, definition: "A lung infection." }) } } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    expect(text(h)).toContain("A lung infection.");
    const before = (h.api.searchDorisTerms as jest.Mock).mock.calls.length;
    h.setRevision(2);
    await settle();
    expect((h.api.searchDorisTerms as jest.Mock).mock.calls.length).toBe(before + 1);
    expect(text(h)).not.toContain("SELECTED");
    expect(text(h)).not.toContain("A lung infection.");
  });

  it("OK does nothing without a staged code", async () => {
    const h = mount();
    act(() => control(h, "Use the selected code").props.onPress());
    await settle();
    expect(h.api.checkDorisSelection).not.toHaveBeenCalled();
  });

  it("a revision change with nothing typed leaves the picker empty", async () => {
    const h = mount();
    h.setRevision(2);
    await settle();
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    expect(text(h)).toContain("No code selected");
  });
});

/* ------------------------------------------------------------------- details */

describe("details", () => {
  const detailsReply = { schema_version: 1, coding_note: "Code also the cause.", definition: "A lung infection.", fully_specified_name: "Pneumonia, unspecified", inclusions: ["Chest infection"], exclusions: [{ code: "CA07", title: "Bronchiolitis" }, { code: "", title: "Aspiration" }], truncated: true };

  it("shows the coding note first, then definition, name, inclusions and exclusions", async () => {
    const h = mount({ env: { guidance: { details: () => detailsReply } } });
    await search(h, "pneu");
    await press(h, "Details of CA40");
    expect(calls(h, "details")).toEqual([{ schema_version: 1, code: "CA40" }]);
    const out = text(h);
    expect(out).toContain("CA40 — Pneumonia");
    expect(out.indexOf("☰ Coding note: Code also the cause.")).toBeGreaterThan(-1);
    expect(out.indexOf("Coding note")).toBeLessThan(out.indexOf("Definition"));
    for (const part of ["A lung infection.", "Fully specified name", "Pneumonia, unspecified", "Includes", "• Chest infection", "Exclusions", "• Bronchiolitis (CA07)", "• Aspiration", "More WHO details exist than are shown here."]) expect(out).toContain(part);
    expect(out).not.toContain("No additional WHO details");
    await press(h, "Close CA40 — Pneumonia");
    expect(text(h)).not.toContain("A lung infection.");
  });

  it("says when WHO returned nothing, and shows a failure", async () => {
    const h = mount({ env: { guidance: { details: () => ({ schema_version: 1 }) } } });
    await search(h, "pneu");
    await press(h, "Details of CA40");
    expect(text(h)).toContain("No additional WHO details were returned.");
    const offline = mount();
    await search(offline, "pneu");
    await press(offline, "Details of CA40");
    expect(text(offline)).toContain("The request could not be completed.");
    expect(text(offline)).not.toContain("offline_server_unavailable");
  });

  it("the coding-note badge opens the details", async () => {
    const env: Env = { terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia", { has_coding_note: true })], truncated: false, next_cursor: null }), guidance: { details: () => detailsReply } };
    const h = mount({ env });
    await search(h, "pneu");
    await press(h, "Open coding note");
    expect(text(h)).toContain("A lung infection.");
  });
});

/* --------------------------------------------------------------------- builder */

describe("builder", () => {
  const mandatory = term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 });
  const optionalStem = term("NC72.7", "Injury", { postcoordination: true, postcoordination_availability: 1 });
  const env = (extra: Partial<Env> = {}): Env => ({
    terms: (query, options) => options?.subtreeUris
      ? { schema_version: 1, items: [term("5A11", "Diabetes"), term("MC85", "Angina"), term("NOURI", "Orphan", { uri: "" })], truncated: true, next_cursor: null }
      : { schema_version: 1, items: [mandatory, term("CA40", "Pneumonia")], truncated: false, next_cursor: null },
    ...extra,
    guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1, definition: "Heart attack." }), ...(extra.guidance ?? {}) },
  });

  it("opens by itself for a first result with mandatory postcoordination, with its details, required axes first", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "BD54" }]);
    const out = text(h);
    expect(out).toContain("Build expression");
    expect(out).toContain("Stem: BD54 — Acute MI");
    expect(out).toContain("Heart attack.");
    // Required axes are open; the optional ones are folded on a phone and say how many are chosen.
    expect(out.indexOf("Has causing condition (code also.)")).toBeLessThan(out.indexOf("Has manifestation (optional)"));
    expect(out).toContain("Has severity (optional)");
    expect(out).toContain("(choose across different blocks)");
    expect(out).not.toContain("(choose one or more)");
    expect(out).not.toContain("MC85 — Title MC85");
    await openAxis(h, "Has manifestation");
    await openAxis(h, "Has severity");
    const open = text(h);
    expect(open).toContain("Has manifestation (use additional code, if desired.)");
    expect(open).toContain("Has severity (optional.)");
    expect(open).toContain("(choose one or more)");
    expect(open).toContain("(choose one)");
    expect(out).toContain("A required axis is missing. Choose one option to complete the expression.");
    expect(out).toContain("▷ Endocrine group");
    expect(has(h, "Use stem without extensions")).toBe(false);
    expect(control(h, "Use complete expression").props.disabled).toBe(true);
  });

  it("in final mode the builder opens without the details card", async () => {
    const h = mount({ init: { finalMode: true }, env: env() });
    await search(h, "heart");
    expect(text(h)).toContain("Build expression");
    expect(calls(h, "details")).toEqual([]);
    await press(h, "BD54 Acute MI");
    expect(calls(h, "details")).toEqual([]);
  });

  it("an axis without a WHO instruction reads required or optional", async () => {
    const bare = axes().map(({ instruction: _instruction, ...axis }) => axis);
    const h = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: bare }) } }) });
    await search(h, "heart");
    expect(text(h)).toContain("Has causing condition (required.)");
    await openAxis(h, "Has manifestation");
    expect(text(h)).toContain("Has manifestation (optional.)");
  });

  it("the + Build badge in final mode opens the builder without details", async () => {
    const h = mount({ init: { finalMode: true }, env: env({ terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia"), term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 })], truncated: false, next_cursor: null }) }) });
    await search(h, "heart");
    await press(h, "Mandatory postcoordination");
    expect(calls(h, "postcoordination")).toHaveLength(1);
    expect(calls(h, "details")).toEqual([]);
  });

  it("does not open by itself when the mandatory stem is not the first result", async () => {
    const h = mount({ env: env({ terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia"), mandatory], truncated: false, next_cursor: null }) }) });
    await search(h, "heart");
    expect(calls(h, "postcoordination")).toEqual([]);
    await press(h, "BD54 Acute MI");
    expect(calls(h, "postcoordination")).toHaveLength(1);
    expect(calls(h, "details")).toHaveLength(1);
  });

  it("builds the expression with X extensions first and stages it for OK", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await openAxis(h, "Has severity");
    await press(h, "Has manifestation MC85 Title MC85");
    await press(h, "Has severity XS1 Title XS1");
    expect(text(h)).toContain("A required axis is missing.");
    await press(h, "Has causing condition 5A11 Title 5A11");
    expect(text(h)).not.toContain("A required axis is missing.");
    expect(optionState(h, "Has causing condition 5A11 Title 5A11")).toMatchObject({ selected: true });
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54&XS1/MC85/5A11");
    // A second value in the same WHO block replaces the first; another block adds.
    await press(h, "Has causing condition 5A12 Title 5A12");
    await press(h, "Has causing condition 6B00 Title 6B00");
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54&XS1/MC85/5A12/6B00");
    await press(h, "Has severity XS2 Title XS2");
    await press(h, "Use complete expression");
    expect(text(h)).not.toContain("Build expression");
    expect(text(h)).toContain("BD54&XS2/MC85/5A12/6B00");
    await press(h, "Use the selected code");
    expect(h.api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "BD54&XS2/MC85/5A12/6B00", "https://who.int/BD54 & https://who.int/XS2 / https://who.int/MC85 / https://who.int/5A12 / https://who.int/6B00");
    expect(h.handlers.onSelect).toHaveBeenCalledWith(expect.objectContaining({ code: "BD54&XS2/MC85/5A12/6B00" }));
  });

  it("'Causing condition not known' stands in for the required axis and travels with the choice", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await press(h, "Has causing condition 5A11 Title 5A11");
    await press(h, "Causing condition not known");
    expect(optionState(h, "Causing condition not known")).toMatchObject({ selected: true });
    expect(optionState(h, "Has causing condition 5A11 Title 5A11")).toMatchObject({ selected: false });
    expect(control(h, "Use complete expression").props.disabled).toBe(false);
    await press(h, "Use complete expression");
    await press(h, "Use the selected code");
    expect(h.handlers.onSelect).toHaveBeenCalledWith(expect.objectContaining({ code: "BD54", causingConditionUnknown: true }));
    // Picking a causing condition afterwards switches "not known" off; pressing it again toggles it off.
    const g = mount({ env: env() });
    await search(g, "heart");
    await press(g, "Causing condition not known");
    await press(g, "Causing condition not known");
    expect(text(g)).toContain("A required axis is missing.");
    await press(g, "Causing condition not known");
    await press(g, "Has causing condition 5A11 Title 5A11");
    expect(optionState(g, "Causing condition not known")).toMatchObject({ selected: false });
  });

  it("offers the stem alone only when no axis is required", async () => {
    const optionalAxes = axes().filter((axis) => !axis.required);
    const h = mount({ env: env({ terms: () => ({ schema_version: 1, items: [optionalStem], truncated: false, next_cursor: null }), guidance: { postcoordination: () => postcoordination({ stem: opt("NC72.7", { title: "Injury" }), axes: optionalAxes }) } }) });
    await search(h, "injury");
    await press(h, "Postcoordination available");
    expect(text(h)).not.toContain("A required axis is missing.");
    await press(h, "Use stem without extensions");
    expect(text(h)).toContain("NC72.7 — Injury");
    expect(h.tree.root.findAll((node) => node.props.testID === "picker-build")).toHaveLength(0);
  });

  it("Cancel closes the builder", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await press(h, "Cancel Build expression");
    expect(text(h)).not.toContain("Stem: BD54");
  });

  it("More choices loads the children of an option once, bounded, and says when WHO cut them", async () => {
    const h = mount({ env: env({ guidance: { "postcoordination-options": () => ({ schema_version: 1, items: [opt("MC86.1"), opt("MC86.2")], truncated: true }) } }) });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    expect(h.tree.root.findAll((node) => node.props.accessibilityLabel === "More choices" && typeof node.props.onPress === "function").length).toBeGreaterThanOrEqual(2);
    await press(h, "More choices");
    expect(calls(h, "postcoordination-options")[0]).toEqual({ schema_version: 1, stem_code: "BD54", axis_id: "hasCausingCondition", parent_uri: "https://who.int/g" });
  });

  it("More choices shows children under their parent, which can be chosen and removed", async () => {
    const onlyManifestation = [{ ...axes()[0] }];
    const h = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: onlyManifestation }), "postcoordination-options": () => ({ schema_version: 1, items: [opt("MC86.1")], truncated: true }) } }) });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await press(h, "More choices");
    expect(calls(h, "postcoordination-options")[0]).toMatchObject({ axis_id: "hasManifestation", parent_uri: "https://who.int/MC86" });
    expect(has(h, "More choices")).toBe(false);
    expect(text(h)).toContain("MC86.1 — Title MC86.1");
    expect(text(h)).toContain("More WHO options exist. Refine the search if the needed choice is not shown.");
    await press(h, "Has manifestation MC86.1 Title MC86.1");
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54/MC86.1");
    await press(h, "Has manifestation MC86.1 Title MC86.1");
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54");
  });

  it("More choices that fails says so and can be tried again", async () => {
    let fail = true;
    const onlyManifestation = [{ ...axes()[0] }];
    const h = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: onlyManifestation }), "postcoordination-options": () => { if (fail) throw WHO_DOWN_FAILURE(); return { schema_version: 1, items: [opt("MC86.1")], truncated: false }; } } }) });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await press(h, "More choices");
    expect(text(h)).toContain(WHO_DOWN);
    fail = false;
    await press(h, "More choices");
    expect(text(h)).toContain("MC86.1");
    expect(text(h)).not.toContain(WHO_DOWN);
  });

  it("More choices that fails without a message shows the generic line", async () => {
    const onlyManifestation = [{ ...axes()[0] }];
    const h = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: onlyManifestation }), "postcoordination-options": () => { throw new Error(""); } } }) });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await press(h, "More choices");
    expect(text(h)).toContain("The request could not be completed.");
  });

  it("a chosen value that is not a root option stays visible and can be unchosen", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await typeInto(h, "search in axis: Has manifestation", "angina");
    await advance(250);
    expect(calls(h, "postcoordination")).toHaveLength(1);
    expect((h.api.searchDorisTerms as jest.Mock).mock.calls.at(-1)).toEqual(["sid-1", "angina", { limit: 20, subtreeUris: ["https://who.int/s-man"] }]);
    // The options hide while matches are shown; "NOURI" has no uri and is not offered.
    expect(has(h, "Has manifestation MC86 Title MC86")).toBe(false);
    expect(has(h, "NOURI Orphan")).toBe(false);
    expect(text(h)).toContain("Showing the first 20 matches. Refine the search to narrow them.");
    await press(h, "5A11 Diabetes");
    expect(field(h, "search in axis: Has manifestation").props.value).toBe("");
    expect(has(h, "Has manifestation MC86 Title MC86")).toBe(true);
    expect(has(h, "Has manifestation 5A11 Diabetes")).toBe(true);
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54/5A11");
    await press(h, "Has manifestation 5A11 Diabetes");
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54");
  });

  it("per-axis search marks a value already chosen and reports no matches, a failure and a short query", async () => {
    let mode: "none" | "fail" | "ok" = "ok";
    const base = env();
    const h = mount({ env: { ...base, terms: (query, options) => {
      if (!options?.subtreeUris) return (base.terms as NonNullable<Env["terms"]>)(query, options);
      if (mode === "fail") throw WHO_DOWN_FAILURE();
      return { schema_version: 1, items: mode === "none" ? [] : [term("MC85", "Angina")], truncated: false, next_cursor: null };
    } } });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await press(h, "Has manifestation MC85 Title MC85");
    await typeInto(h, "search in axis: Has manifestation", "ang");
    await advance(250);
    expect(optionState(h, "MC85 Angina")).toMatchObject({ selected: true });
    mode = "none";
    await typeInto(h, "search in axis: Has manifestation", "angi");
    await advance(250);
    expect(text(h)).toContain("No matches in this axis.");
    mode = "fail";
    await typeInto(h, "search in axis: Has manifestation", "angin");
    await advance(250);
    expect(text(h)).toContain(WHO_DOWN);
    await typeInto(h, "search in axis: Has manifestation", "a");
    expect(text(h)).not.toContain(WHO_DOWN);
    expect(text(h)).not.toContain("No matches in this axis.");
  });

  it("a per-axis search that fails without a message shows the generic line, and a late reply is dropped", async () => {
    let release!: (value: unknown) => void;
    let mode: "fail" | "slow" = "fail";
    const base = env();
    const h = mount({ env: { ...base, terms: (query, options) => {
      if (!options?.subtreeUris) return (base.terms as NonNullable<Env["terms"]>)(query, options);
      if (mode === "fail") throw new Error("");
      return new Promise((resolve) => { release = resolve; });
    } } });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await typeInto(h, "search in axis: Has manifestation", "angina");
    await advance(250);
    expect(text(h)).toContain("The request could not be completed.");
    mode = "slow";
    await typeInto(h, "search in axis: Has manifestation", "angio");
    await advance(250);
    await typeInto(h, "search in axis: Has manifestation", "");
    await act(async () => { release({ schema_version: 1, items: [term("MC85", "Angina")], truncated: false, next_cursor: null }); });
    await settle();
    expect(has(h, "MC85 Angina")).toBe(false);
  });

  it("a late per-axis failure after the text was cleared is dropped", async () => {
    let fail!: (error: Error) => void;
    const base = env();
    const h = mount({ env: { ...base, terms: (query, options) => options?.subtreeUris ? new Promise((_resolve, reject) => { fail = reject; }) : (base.terms as NonNullable<Env["terms"]>)(query, options) } });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    await typeInto(h, "search in axis: Has manifestation", "angina");
    await advance(250);
    await typeInto(h, "search in axis: Has manifestation", "");
    await act(async () => { fail(new Error("too late")); });
    await settle();
    expect(text(h)).not.toContain("too late");
  });

  it("Other postcoordination? takes an extension only when WHO resolves stem&code, and puts it in the expression", async () => {
    const h = mount({ env: env({ codeinfo: (code: string) => {
      if (code === "BD54&XK9J") return { schema_version: 1, item: { code, title: "ext", uri: "https://who.int/ext", release: "r", postcoordination: false, primary_stem: null } };
      if (code === "BD54&XS5W") throw failure(404, "CODE_NOT_FOUND", "not found");
      throw WHO_DOWN_FAILURE();
    }, terms: (query, options) => options?.subtreeUris?.[0]?.includes("x-chapter")
      ? { schema_version: 1, items: [term("XK9J", "Cavity"), term("XS5W", "Other"), term("XQ00", "Third")], truncated: false, next_cursor: null }
      : { schema_version: 1, items: [mandatory], truncated: false, next_cursor: null } }) });
    await search(h, "heart");
    expect(text(h)).toContain("Other postcoordination? (use additional code, if desired.)");
    await typeInto(h, "search in axis: Other postcoordination", "cavity");
    await advance(250);
    await press(h, "XS5W Other");
    expect(text(h)).toContain("WHO does not accept XS5W as an extension of BD54.");
    await press(h, "XQ00 Third");
    expect(text(h)).toContain(WHO_DOWN);
    expect(text(h)).not.toContain("WHO does not accept XS5W");
    await press(h, "XK9J Cavity");
    expect(calls(h, "codeinfo")).toEqual([]);
    expect(h.api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "BD54&XK9J");
    expect(has(h, "Remove XK9J")).toBe(true);
    await press(h, "Has causing condition 5A11 Title 5A11");
    expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54&XK9J/5A11");
    await press(h, "Remove XK9J");
    expect(has(h, "Remove XK9J")).toBe(false);
  });

  it("an extension that cannot be verified, without a message, shows the generic line", async () => {
    const base = env({ codeinfo: () => { throw new Error(""); } });
    const h = mount({ env: { ...base, terms: (query, options) => options?.subtreeUris?.[0]?.includes("x-chapter") ? { schema_version: 1, items: [term("XK9J", "Cavity")], truncated: false, next_cursor: null } : { schema_version: 1, items: [mandatory], truncated: false, next_cursor: null } } });
    await search(h, "heart");
    await typeInto(h, "search in axis: Other postcoordination", "cavity");
    await advance(250);
    await press(h, "XK9J Cavity");
    expect(text(h)).toContain("The request could not be completed.");
  });

  it("warns when WHO cut the choices, and shows a stem without an Other section", async () => {
    const cutAxes = axes().map((axis) => ({ ...axis, truncated: axis.id === "severity" }));
    const h = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: cutAxes, other_postcoordination: null }) } }) });
    await search(h, "heart");
    expect(text(h)).toContain("More WHO options exist. Refine the search if the needed choice is not shown.");
    expect(text(h)).not.toContain("Other postcoordination?");
    const stemCut = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ truncated: true }) } }) });
    await search(stemCut, "heart");
    expect(text(stemCut)).toContain("More WHO options exist.");
  });

  it("shows a builder that cannot load, including the offline message", async () => {
    const failing = mount({ env: env({ guidance: { postcoordination: () => { throw WHO_DOWN_FAILURE(); } } }) });
    await search(failing, "heart");
    expect(text(failing)).toContain(WHO_DOWN);
    expect(text(failing)).not.toContain("raw server words");
    const offline = mount({ env: { terms: () => ({ schema_version: 1, items: [mandatory], truncated: false, next_cursor: null }) } });
    await search(offline, "heart");
    expect(text(offline)).toContain("The request could not be completed.");
    expect(text(offline)).not.toContain("offline_server_unavailable");
    expect(offline.handlers.onClose).not.toHaveBeenCalled();
  });

  it("an unreadable builder reply is shown as the generic line, not as the parser's text or a crash", async () => {
    const h = mount({ env: env({ guidance: { postcoordination: () => ({ schema_version: 1, axes: "no" }) } }) });
    await search(h, "heart");
    expect(text(h)).toContain(GENERIC);
    expect(text(h)).not.toContain("Invalid DORIS");
    const badAxis = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: [{ label: "x" }] }) } }) });
    await search(badAxis, "heart");
    expect(text(badAxis)).toContain(GENERIC);
    expect(text(badAxis)).not.toContain("axes[0]");
  });

  describe("composite codes", () => {
    const composite = term("BD54/MC85", "Complete", { postcoordination: true, postcoordination_availability: 2 });
    const compositeEnv = (extra: Partial<Env> = {}): Env => ({
      terms: () => ({ schema_version: 1, items: [composite], truncated: false, next_cursor: null }),
      ...extra,
      guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }), ...(extra.guidance ?? {}) },
    });

    it("'+ Build' on a complete expression opens its stem with the other parts already chosen", async () => {
      const h = mount({ env: compositeEnv() });
      await search(h, "heart");
      expect(calls(h, "postcoordination")).toEqual([]);
      await press(h, "Mandatory postcoordination");
      expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "BD54" }]);
      expect(optionState(h, "Has manifestation MC85 Title MC85")).toMatchObject({ selected: true });
      expect(calls(h, "details")).toHaveLength(1);
    });

    it("resolves a part that is not a root option through codeinfo: X codes become the other pick, others take the first stem axis", async () => {
      const wide = { ...composite, code: "BD54&XK9J/9Z99/9Z98/NOURI" };
      const h = mount({ env: compositeEnv({
        terms: () => ({ schema_version: 1, items: [wide], truncated: false, next_cursor: null }),
        codeinfo: (code: string) => {
          if (code === "9Z98") return { schema_version: 1, item: { code, title: "No uri", uri: "", release: "r", postcoordination: false, primary_stem: null } };
          if (code === "NOURI") throw failure(404, "CODE_NOT_FOUND", "gone");
          return { schema_version: 1, item: { code, title: `Part ${code}`, uri: `https://who.int/${code}`, release: "r", postcoordination: false, primary_stem: null } };
        },
      }) });
      await search(h, "heart");
      await press(h, "Mandatory postcoordination");
      expect(has(h, "Remove XK9J")).toBe(true);
      expect(has(h, "Has manifestation 9Z99 Part 9Z99")).toBe(true);
      expect(optionState(h, "Has manifestation 9Z99 Part 9Z99")).toMatchObject({ selected: true });
      expect(has(h, "Has manifestation 9Z98 Part 9Z98")).toBe(false);
      expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54&XK9J/9Z99");
    });

    it("a part is not added twice when the same code resolves again", async () => {
      const dup = { ...composite, code: "BD54/9Z99/9Z99" };
      const h = mount({ env: compositeEnv({ terms: () => ({ schema_version: 1, items: [dup], truncated: false, next_cursor: null }) }) });
      await search(h, "heart");
      await press(h, "Mandatory postcoordination");
      expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54/9Z99");
    });

    it("keeps an unresolvable part out when no axis takes stem codes", async () => {
      const onlyExtensions = [{ ...axes()[2], required: false }];
      const odd = { ...composite, code: "BD54/9Z99" };
      const h = mount({ env: compositeEnv({ terms: () => ({ schema_version: 1, items: [odd], truncated: false, next_cursor: null }), guidance: { postcoordination: () => postcoordination({ axes: onlyExtensions }), details: () => ({ schema_version: 1 }) } }) });
      await search(h, "heart");
      await press(h, "Mandatory postcoordination");
      expect(h.tree.root.findAll((node) => node.props.testID === "build-preview")[0].props.children).toBe("BD54");
    });
  });
});

/* ------------------------------------------------------------------ hierarchy */

describe("build layout", () => {
  const mandatory = term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 });
  const env = (axesList = axes()): Env => ({
    terms: () => ({ schema_version: 1, items: [mandatory], truncated: false, next_cursor: null }),
    guidance: { postcoordination: () => postcoordination({ axes: axesList }), details: () => ({ schema_version: 1 }) },
  });
  const many = (count: number) => Array.from({ length: count }, (_, index) => opt(`MC${String(index).padStart(2, "0")}`));
  const flatStyle = (node: ReactTestInstance) => Object.assign({}, ...[node.props.style].flat(Infinity).filter(Boolean));
  const host = (h: Harness, label: string) => h.tree.root.findAll((node) => typeof node.type === "string" && node.props.accessibilityLabel === label)[0];

  it("folds the optional axes on a phone and says how many are chosen; the required axis stays open", async () => {
    mockWindow = { width: 360, height: 800, fontScale: 1 };
    const h = mount({ env: env() });
    await search(h, "heart");
    expect(has(h, "Has causing condition 5A11 Title 5A11")).toBe(true);
    expect(has(h, "Has manifestation MC85 Title MC85")).toBe(false);
    expect(host(h, "Has manifestation, optional").props.accessibilityState).toMatchObject({ expanded: false });
    expect(text(h)).toContain("Has manifestation (optional)▸");
    await openAxis(h, "Has manifestation");
    expect(host(h, "Has manifestation, optional").props.accessibilityState).toMatchObject({ expanded: true });
    await press(h, "Has manifestation MC85 Title MC85");
    await openAxis(h, "Has manifestation");
    expect(has(h, "Has manifestation MC85 Title MC85")).toBe(false);
    expect(text(h)).toContain("Has manifestation (optional) · 1 chosen▸");
    expect(has(h, "Has manifestation, optional, 1 chosen")).toBe(true);
    expect(previewCode(h)).toBe("BD54/MC85");
  });

  it("opens an optional axis that already holds a choice, such as a composite's part", async () => {
    mockWindow = { width: 360, height: 800, fontScale: 1 };
    const h = mount({ env: { ...env(), terms: () => ({ schema_version: 1, items: [term("BD54/MC85", "Complete", { postcoordination: true, postcoordination_availability: 2 })], truncated: false, next_cursor: null }) } });
    await search(h, "heart");
    await press(h, "Mandatory postcoordination");
    expect(optionState(h, "Has manifestation MC85 Title MC85")).toMatchObject({ selected: true });
    expect(text(h)).toContain("Has manifestation (use additional code, if desired.)");
  });

  it("shows every axis open on a tablet and still lets the coder fold none", async () => {
    mockWindow = { width: 1180, height: 820, fontScale: 1 };
    const h = mount({ env: env() });
    await search(h, "heart");
    expect(has(h, "Has manifestation MC85 Title MC85")).toBe(true);
    expect(has(h, "Has severity XS1 Title XS1")).toBe(true);
    expect(has(h, "Has manifestation, optional")).toBe(false);
  });

  it("an axis that was folded on a phone shows its options once the window is wide", async () => {
    mockWindow = { width: 360, height: 800, fontScale: 1 };
    const h = mount({ env: env() });
    await search(h, "heart");
    expect(has(h, "Has manifestation MC85 Title MC85")).toBe(false);
    mockWindow = { width: 1180, height: 820, fontScale: 1 };
    h.rerender();
    await settle();
    expect(has(h, "Has manifestation MC85 Title MC85")).toBe(true);
  });

  it("draws each option as a 40-point row with a check circle that fills when chosen", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    const row = host(h, "Has causing condition 5A11 Title 5A11");
    expect(flatStyle(row).minHeight).toBe(40);
    expect(row.props.hitSlop).toMatchObject({ top: 2, bottom: 2 });
    expect(flat(row.children)).toBe("5A11 — Title 5A11");
    await press(h, "Has causing condition 5A11 Title 5A11");
    expect(flat(host(h, "Has causing condition 5A11 Title 5A11").children)).toBe("✓5A11 — Title 5A11");
    expect(flatStyle(host(h, "Has causing condition 5A11 Title 5A11")).backgroundColor).toBe(ui.light.accent);
  });

  it("caps a long option list at 8 with 'Show all N', and keeps a chosen option visible past the cap", async () => {
    const long = [{ ...axes()[1], options: many(12) }];
    const h = mount({ env: env(long) });
    await search(h, "heart");
    expect(has(h, "Has causing condition MC07 Title MC07")).toBe(true);
    expect(has(h, "Has causing condition MC08 Title MC08")).toBe(false);
    expect(has(h, "Show all 12 options")).toBe(true);
    expect(text(h)).toContain("Show all 12");
    await press(h, "Show all 12 options");
    expect(has(h, "Has causing condition MC11 Title MC11")).toBe(true);
    expect(has(h, "Show all 12 options")).toBe(false);
    // A choice beyond the cap stays on screen: a second build of the same list from a search pick.
    const g = mount({ env: { ...env(long), terms: (query, options) => options?.subtreeUris ? { schema_version: 1, items: [term("MC10", "Late")], truncated: false, next_cursor: null } : { schema_version: 1, items: [mandatory], truncated: false, next_cursor: null } } });
    await search(g, "heart");
    await typeInto(g, "search in axis: Has causing condition", "late");
    await advance(250);
    await press(g, "MC10 Late");
    expect(has(g, "Has causing condition MC10 Title MC10")).toBe(true);
    expect(has(g, "Show all 12 options")).toBe(true);
  });

  it("does not offer 'Show all' for a list of 8 or fewer", async () => {
    const h = mount({ env: env([{ ...axes()[1], options: many(8) }]) });
    await search(h, "heart");
    expect(h.tree.root.findAll((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("Show all"))).toHaveLength(0);
  });
});

describe("hierarchy", () => {
  const tree = (over: Record<string, unknown> = {}) => ({
    schema_version: 1, selected: opt("CA40", { title: "Pneumonia" }), ancestors: [opt("CA00", { title: "Chest" }), { code: "", title: "Respiratory", uri: "https://who.int/r", has_children: true }],
    siblings: [opt("CA41", { title: "Bronchitis" })], children: [opt("CA40.1", { title: "Viral" })], related_maternal: [opt("JB00", { title: "Maternal one" })], related_perinatal: [opt("KB00", { title: "Perinatal one" })], truncated: true, ...over,
  });
  const stemInfo = (code: string) => ({ schema_version: 1, item: { code, title: `Title ${code}`, uri: `https://who.int/${code}`, release: "r", postcoordination: true, postcoordination_availability: code === "BD54" ? 2 : 1, primary_stem: null } });

  it("opens from the Details card of a code, never from the result row", async () => {
    const h = mount({ env: { guidance: { hierarchy: () => tree() } } });
    await search(h, "pneu");
    expect(has(h, "Hierarchy of CA40")).toBe(false);
    await press(h, "Details of CA40");
    expect(has(h, "Hierarchy of CA40")).toBe(true);
    await press(h, "Hierarchy of CA40");
    expect(text(h)).toContain("See in hierarchy");
  });

  it("lists ancestors, siblings, children and context, and a node opens its own hierarchy", async () => {
    const h = mount({ env: { guidance: { hierarchy: (body) => (body.code === "CA41" ? tree({ selected: opt("CA41", { title: "Bronchitis" }), siblings: [], children: [], ancestors: [], related_maternal: [], related_perinatal: [], truncated: false }) : tree()) } } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    expect(calls(h, "hierarchy")).toEqual([{ schema_version: 1, code: "CA40" }]);
    const out = text(h);
    for (const part of ["See in hierarchy", "Selected: CA40 — Pneumonia", "Ancestor path", "▷ Respiratory", "Siblings", "Children", "Maternal context: Maternal one", "Perinatal context: Perinatal one", "Some hierarchy choices were omitted"]) expect(out).toContain(part);
    expect(has(h, "Build expression for this stem")).toBe(true);
    await press(h, "CA41 Bronchitis");
    expect(text(h)).toContain("Selected: CA41 — Bronchitis");
    expect(text(h)).not.toContain("Ancestor path");
    expect(text(h)).not.toContain("Some hierarchy choices were omitted");
  });

  it("'Use this code' checks the node with codeinfo, stages it and closes the card", async () => {
    const h = mount({ env: { guidance: { hierarchy: () => tree(), details: () => ({ schema_version: 1 }) } } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    await press(h, "Use this code");
    expect(h.api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "CA40");
    expect(text(h)).not.toContain("See in hierarchy");
    expect(text(h)).toContain("SELECTED");
  });

  it("a mandatory-postcoordination stem reached through the hierarchy opens its builder and is never staged", async () => {
    const h = mount({ env: {
      codeinfo: stemInfo,
      guidance: { hierarchy: () => tree({ selected: opt("BD54", { title: "Acute MI" }) }), postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }) },
    } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    await press(h, "Use this code");
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "BD54" }]);
    expect(text(h)).toContain("Build expression");
    expect(text(h)).toContain("BUILDING");
    expect(text(h)).not.toContain("SELECTED");
    expect(control(h, "Use complete expression").props.disabled).toBe(true);
    // While the footer is building there is no OK to press, and nothing was verified or handed on.
    expect(has(h, "Use the selected code")).toBe(false);
    expect(h.api.checkDorisSelection).not.toHaveBeenCalled();
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
  });

  it("a stem with optional postcoordination reached through the hierarchy can still be used", async () => {
    const h = mount({ env: { codeinfo: stemInfo, guidance: { hierarchy: () => tree({ selected: opt("NC72.7", { title: "Injury" }) }), details: () => ({ schema_version: 1 }) } } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    await press(h, "Use this code");
    expect(text(h)).toContain("SELECTED");
    expect(calls(h, "postcoordination")).toEqual([]);
  });

  it("a hierarchy node WHO cannot resolve is refused in the footer", async () => {
    const h = mount({ env: { codeinfo: () => { throw failure(404, "CODE_NOT_FOUND", "raw server words"); }, guidance: { hierarchy: () => tree(), details: () => ({ schema_version: 1 }) } } });
    await search(h, "CA40x y");
    await openHierarchy(h, "CA40");
    await press(h, "Use this code");
    expect(text(h)).toContain("Select a valid ICD-11 code.");
    expect(text(h)).not.toContain("SELECTED");
  });

  it("'Build expression for this stem' opens the builder and replaces the hierarchy", async () => {
    const h = mount({ env: { guidance: { hierarchy: () => tree(), postcoordination: () => postcoordination() } } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    await press(h, "Build expression for this stem");
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "CA40" }]);
    expect(text(h)).toContain("Build expression");
    expect(text(h)).not.toContain("See in hierarchy");
    await press(h, "Hierarchy of CA40");
    expect(text(h)).not.toContain("Stem: BD54");
  });

  it("an uncoded selection cannot be used or built; a closed card goes away; a failure is shown", async () => {
    const h = mount({ env: { guidance: { hierarchy: () => tree({ selected: { code: "", title: "Group", uri: "", has_children: true }, ancestors: [], siblings: [], children: [], related_maternal: [], related_perinatal: [], truncated: false }) } } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    expect(control(h, "Use this code").props.disabled).toBe(true);
    expect(has(h, "Build expression for this stem")).toBe(false);
    await press(h, "Close See in hierarchy");
    expect(text(h)).not.toContain("See in hierarchy");
    const offline = mount();
    await search(offline, "pneu");
    await openHierarchy(offline, "CA40");
    expect(text(offline)).toContain(GENERIC);
  });

  it("a selection without a title still reads", async () => {
    const h = mount({ env: { guidance: { hierarchy: () => tree({ selected: { code: "CA40", title: "", uri: "https://who.int/CA40", has_children: false } }) } } });
    await search(h, "pneu");
    await openHierarchy(h, "CA40");
    expect(text(h)).toContain("Selected: CA40");
  });
});

/* -------------------------------------------------------------------- related */

describe("related terms", () => {
  const maternal = term("JA00", "Pregnancy", { related_maternal: true, related_perinatal: true });
  const related = (over: Record<string, unknown> = {}) => ({
    schema_version: 1, composite: { code: "JB64.4/BD54", title: "Composite", uri: "", has_children: false },
    terms: [{ ...opt("JB64", { title: "Maternal cat" }), requires_postcoordination: false }, { ...opt("JB65", { title: "Needs build" }), requires_postcoordination: true }, { code: "JB66", title: "No uri", uri: "", has_children: false, requires_postcoordination: false }, { code: "JB66/BD54", title: "Joined", uri: "", has_children: false, requires_postcoordination: false }],
    truncated: true, ...over,
  });
  const env = (extra: Partial<Env> = {}): Env => ({
    terms: (query) => ({ schema_version: 1, items: query === "JB65" ? [term("JB65", "Needs build")] : [maternal], truncated: false, next_cursor: null }),
    ...extra,
    guidance: { related: (body) => related({ chapter: body.chapter }), details: () => ({ schema_version: 1 }), postcoordination: () => postcoordination(), ...(extra.guidance ?? {}) },
  });

  it("opens the pregnancy window with the composite first, and the K badge switches chapter", async () => {
    const h = mount({ env: env() });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    expect(calls(h, "related")).toEqual([{ schema_version: 1, code: "JA00", chapter: "maternal" }]);
    const out = text(h);
    for (const part of ["Pregnancy related terms", "JA00 — Pregnancy", "JB64.4/BD54 — Composite", "JB64 — Maternal cat", "WHO returned a shortened list."]) expect(out).toContain(part);
    expect(out.indexOf("JB64.4/BD54")).toBeLessThan(out.indexOf("JB64 — Maternal cat"));
    // Inside the window the J and K badges switch chapter (there are two of each: the row and the window).
    const inWindow = h.tree.root.findAll((node) => node.props.testID === "picker-related")[0];
    act(() => inWindow.findAll((node) => node.props.accessibilityLabel === "Open perinatal related terms" && typeof node.props.onPress === "function")[0].props.onPress());
    await settle();
    expect(text(h)).toContain("Perinatal related terms");
    expect(calls(h, "related")[1]).toEqual({ schema_version: 1, code: "JA00", chapter: "perinatal" });
    await press(h, "Close Perinatal related terms");
    expect(text(h)).not.toContain("Perinatal related terms");
  });

  it("switching J and K inside the window scrolls the new list into view again", async () => {
    const h = mount({ env: env() });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    const results = h.tree.root.findAll((node) => node.props.testID === "picker-results" && node.instance)[0];
    const spy = jest.fn();
    (results.instance as { scrollTo: unknown }).scrollTo = spy;
    // The card's wrapper (Reveal) reports its place once laid out, and the list scrolls there once.
    const layOut = () => {
      let wrapper: ReactTestInstance | null = h.tree.root.findAll((node) => node.props.testID === "picker-related")[0];
      while (wrapper && !wrapper.props.onLayout) wrapper = wrapper.parent;
      expect(wrapper).not.toBeNull();
      act(() => { wrapper!.props.onLayout({ nativeEvent: { layout: { y: 640 } } }); });
    };
    layOut();
    expect(spy).toHaveBeenCalledTimes(1);
    const inWindow = h.tree.root.findAll((node) => node.props.testID === "picker-related")[0];
    act(() => inWindow.findAll((node) => node.props.accessibilityLabel === "Open perinatal related terms" && typeof node.props.onPress === "function")[0].props.onPress());
    await settle();
    expect(text(h)).toContain("Perinatal related terms");
    layOut();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("inside the window the + and coding-note badges are plain markers, not buttons", async () => {
    const rich = { ...maternal, postcoordination: true, postcoordination_availability: 1, has_coding_note: true };
    const h = mount({ env: env({ terms: () => ({ schema_version: 1, items: [rich], truncated: false, next_cursor: null }) }) });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    const inWindow = h.tree.root.findAll((node) => node.props.testID === "picker-related")[0];
    const labelled = (label: string) => inWindow.findAll((node) => node.props.accessibilityLabel === label);
    expect(labelled("Postcoordination available").length).toBeGreaterThan(0);
    expect(labelled("Postcoordination available").every((node) => node.props.onPress === undefined)).toBe(true);
    expect(labelled("Coding note available").length).toBeGreaterThan(0);
    expect(labelled("Open coding note")).toEqual([]);
  });

  it("a term that needs postcoordination searches for its code again", async () => {
    const h = mount({ env: env() });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB65 Needs build");
    expect(field(h, SEARCH).props.value).toBe("JB65");
    expect(h.api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "JB65");
    expect(text(h)).not.toContain("Pregnancy related terms");
  });

  it("in final mode every related pick searches again", async () => {
    const h = mount({ init: { finalMode: true }, env: env() });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB64 Maternal cat");
    expect(field(h, SEARCH).props.value).toBe("JB64");
    expect(h.api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "JB64");
    expect(calls(h, "postcoordination")).toEqual([]);
  });

  it("a term with a uri is staged for OK", async () => {
    const h = mount({ env: env() });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB64 Maternal cat");
    expect(text(h)).toContain("JB64 — Maternal cat");
    expect(text(h)).toContain("SELECTED");
    await press(h, "Use the selected code");
    expect(h.api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "JB64", "https://who.int/JB64");
  });

  it("a composite without a uri opens the builder for its stem with the other parts chosen", async () => {
    const h = mount({ env: env() });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB64.4/BD54 Composite");
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "JB64.4" }]);
    expect(text(h)).not.toContain("Pregnancy related terms");
    expect(calls(h, "details")).toEqual([]);
  });

  it("a term without a uri is resolved through codeinfo first; a failure is shown in the footer", async () => {
    const h = mount({ env: env({ codeinfo: (code) => {
      if (code === "JB66") return { schema_version: 1, item: { code, title: "Resolved", uri: "https://who.int/JB66", release: "r", postcoordination: false, primary_stem: null } };
      if (code === "JB67") return { schema_version: 1, item: { code, title: "No uri", uri: "", release: "r", postcoordination: false, primary_stem: null } };
      throw failure(404, "CODE_NOT_FOUND", "raw server words");
    }, guidance: { related: () => related({ terms: [{ code: "JB66", title: "No uri", uri: "", has_children: false, requires_postcoordination: false }, { code: "JB67", title: "Empty", uri: "", has_children: false, requires_postcoordination: false }, { code: "JB68", title: "Gone", uri: "", has_children: false, requires_postcoordination: false }], composite: null, truncated: false }), details: () => ({ schema_version: 1 }) } }) });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB68 Gone");
    expect(text(h)).toContain("Select a valid ICD-11 code.");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB67 Empty");
    expect(text(h)).toContain("WHO did not return JB67.");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB66 No uri");
    expect(text(h)).toContain("SELECTED");
    expect(text(h)).toContain("JB66 — Resolved");
    expect(text(h)).not.toContain("Select a valid ICD-11 code.");
  });

  it("a related code lookup that fails without a message shows the generic line", async () => {
    const h = mount({ env: env({ codeinfo: () => { throw new Error(""); }, guidance: { related: () => related({ terms: [{ code: "JB66", title: "No uri", uri: "", has_children: false, requires_postcoordination: false }], composite: null }) } }) });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "JB66 No uri");
    expect(text(h)).toContain("The request could not be completed.");
  });

  it("says when WHO returned nothing, without a composite or a shortened list", async () => {
    const h = mount({ env: env({ guidance: { related: () => related({ terms: [], composite: null, truncated: false }) } }) });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    expect(text(h)).toContain("No related terms were returned for this code.");
    expect(text(h)).not.toContain("WHO returned a shortened list.");
  });

  it("shows a failure, including the offline one, without the raw text", async () => {
    const h = mount({ env: { terms: () => ({ schema_version: 1, items: [maternal], truncated: false, next_cursor: null }) } });
    await search(h, "pregnant");
    await press(h, "Open perinatal related terms");
    expect(text(h)).toContain("The request could not be completed.");
    expect(text(h)).not.toContain("offline_server_unavailable");
  });

  it("a composite alone is enough, and its title may be missing", async () => {
    const h = mount({ env: env({ guidance: { related: () => related({ terms: [], composite: { code: "JB64.4/BD54", title: "C", uri: "", has_children: false }, truncated: false }) } }) });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    expect(text(h)).toContain("JB64.4/BD54 — C");
    const untitled = mount({ env: { terms: () => ({ schema_version: 1, items: [{ ...maternal, title: "" }], truncated: false, next_cursor: null }), guidance: { related: () => related({ terms: [], composite: null, truncated: false }) } } });
    await search(untitled, "pregnant");
    await press(untitled, "Open pregnancy related terms");
    expect(text(untitled)).toContain("No related terms");
  });
});

/* ------------------------------------------------- mandatory stems never reach OK */

describe("mandatory postcoordination stems", () => {
  const stem = (code: string, availability: number) => ({ schema_version: 1, item: { code, title: `Title ${code}`, uri: `https://who.int/${code}`, release: "r", postcoordination: true, postcoordination_availability: availability, primary_stem: null } });
  const mandatoryTerm = term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 });
  const noOk = (h: Harness) => {
    expect(has(h, "Use the selected code")).toBe(false);
    expect(text(h)).not.toContain("SELECTED");
    expect(h.api.checkDorisSelection).not.toHaveBeenCalled();
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
  };

  it("a typed code is looked up, withholds Use, and its title opens the builder instead of staging", async () => {
    const h = mount({ env: { codeinfo: (code) => stem(code, 2), guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }) } } });
    await search(h, "BD54");
    expect(h.api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "BD54");
    expect(has(h, "Use BD54")).toBe(false);
    expect(text(h)).toContain("Build expression");
    await press(h, "Cancel Build expression");
    await press(h, "BD54 Title BD54");
    expect(calls(h, "postcoordination")).toHaveLength(2);
    expect(text(h)).toContain("Build expression");
    noOk(h);
  });

  it("a related term with a uri that WHO's own check shows to be a mandatory stem opens the builder at OK, and nothing is sent", async () => {
    const h = mount({ env: {
      terms: () => ({ schema_version: 1, items: [term("JA00", "Pregnancy", { related_maternal: true })], truncated: false, next_cursor: null }),
      check: (code) => stem(code, 2),
      guidance: {
        related: () => ({ schema_version: 1, composite: null, terms: [{ code: "BD54", title: "Looks plain", uri: "https://who.int/BD54", has_children: false, requires_postcoordination: false }], truncated: false }),
        postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }),
      },
    } });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "BD54 Looks plain");
    expect(text(h)).toContain("SELECTED");
    await press(h, "Use the selected code");
    expect(h.api.checkDorisSelection).toHaveBeenCalledTimes(1);
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "BD54" }]);
    expect(text(h)).toContain("BD54 needs postcoordination. Complete it in the builder.");
    expect(text(h)).toContain("BUILDING");
    expect(text(h)).not.toContain("SELECTED");
    expect(has(h, "Use the selected code")).toBe(false);
  });

  it("the builder's own output is not sent back to the builder, though the server flags the bare stem as mandatory", async () => {
    // Mirrors the server: _codeinfo_item gives any bare code its availability, so BD54 is 2 even when "Causing condition not known" completed it.
    const onlyCausing = [{ ...axes()[1] }];
    const h = mount({ env: {
      terms: () => ({ schema_version: 1, items: [mandatoryTerm], truncated: false, next_cursor: null }),
      check: (code) => stem(code, 2),
      guidance: { postcoordination: () => postcoordination({ axes: onlyCausing }), details: () => ({ schema_version: 1 }) },
    } });
    await search(h, "heart");
    await press(h, "Causing condition not known");
    await press(h, "Use complete expression");
    await press(h, "Use the selected code");
    expect(h.api.checkDorisSelection).toHaveBeenCalledTimes(1);
    expect(h.handlers.onSelect).toHaveBeenCalledWith(expect.objectContaining({ code: "BD54", causingConditionUnknown: true }));
    expect(calls(h, "postcoordination")).toHaveLength(1);
    // The stem alone, offered by the builder only when no axis is required, goes through the same way.
    const g = mount({ env: {
      terms: () => ({ schema_version: 1, items: [mandatoryTerm], truncated: false, next_cursor: null }),
      check: (code) => stem(code, 2),
      guidance: { postcoordination: () => postcoordination({ axes: axes().filter((axis) => !axis.required) }), details: () => ({ schema_version: 1 }) },
    } });
    await search(g, "heart");
    await press(g, "Use stem without extensions");
    await press(g, "Use the selected code");
    expect(g.handlers.onSelect).toHaveBeenCalledWith({ code: "BD54", title: "Title BD54", uri: "https://who.int/BD54" });
  });

  it("the same stem, verified by OK in final mode, opens the builder without the details card", async () => {
    const h = mount({ init: { finalMode: true }, env: { check: (code) => stem(code, 2), guidance: { postcoordination: () => postcoordination() } } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "CA40" }]);
    // The builder adds no details card of its own in final mode (the Use before it showed the staged code's).
    expect(calls(h, "details")).toHaveLength(1);
  });

  it("a related term that needs postcoordination goes through a search and its builder, not to OK", async () => {
    const h = mount({ env: {
      terms: (query) => ({ schema_version: 1, items: query === "BD54" ? [mandatoryTerm] : [term("JA00", "Pregnancy", { related_maternal: true })], truncated: false, next_cursor: null }),
      codeinfo: (code) => stem(code, 2),
      guidance: {
        related: () => ({ schema_version: 1, composite: null, terms: [{ code: "BD54", title: "Needs build", uri: "https://who.int/BD54", has_children: false, requires_postcoordination: true }], truncated: false }),
        postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }),
      },
    } });
    await search(h, "pregnant");
    await press(h, "Open pregnancy related terms");
    await press(h, "BD54 Needs build");
    expect(calls(h, "postcoordination")).toEqual([{ schema_version: 1, code: "BD54" }]);
    noOk(h);
  });

  it("a built expression of a mandatory stem is complete and can be used", async () => {
    const h = mount({ env: { terms: () => ({ schema_version: 1, items: [mandatoryTerm], truncated: false, next_cursor: null }), guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }) } } });
    await search(h, "heart");
    await press(h, "Has causing condition 5A11 Title 5A11");
    await press(h, "Use complete expression");
    expect(text(h)).toContain("SELECTED");
    expect(text(h)).toContain("BD54/5A11");
    expect(h.tree.root.findAll((node) => node.props.testID === "picker-build")).toHaveLength(0);
  });
});

/* ------------------------------------------------------------ density and layout */

describe("layout", () => {
  const findHost = (h: Harness, testID: string) => h.tree.root.findAll((node) => node.props.testID === testID && typeof node.type === "string");
  const rich = term("JA00", "Pregnancy", { matching_text: "Gestation", postcoordination: true, postcoordination_availability: 2, has_coding_note: true, related_maternal: true, related_perinatal: true });
  // The plain row comes first: a mandatory first result would open its builder and take OK out of the footer.
  const env: Env = { terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia"), rich], truncated: false, next_cursor: null }), guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }) } };
  const withIn = (container: ReactTestInstance, predicate: (node: ReactTestInstance) => boolean) => container.findAll(predicate).length > 0;
  const labelled = (label: string) => (node: ReactTestInstance) => node.props.accessibilityLabel === label;
  const flatStyle = (node: ReactTestInstance) => Object.assign({}, ...[node.props.style].flat(Infinity).filter(Boolean));
  const scrollerOf = (h: Harness, testID = "picker-results") => h.tree.root.findAll((node) => node.props.testID === testID && node.instance)[0];
  const PHONE = { width: 360, height: 800, fontScale: 1 };
  const TABLET = { width: 1180, height: 820, fontScale: 1 };

  it("keeps the title, the search box and the status above the scrolling area, the footer below it, with no Search button", async () => {
    const h = mount({ env });
    await search(h, "pregnant");
    const scroller = scrollerOf(h);
    expect(scroller).toBeDefined();
    for (const label of [SEARCH, "Add uncoded text", "Reset search and current selection"]) {
      expect(h.tree.root.findAll(labelled(label)).length).toBeGreaterThan(0);
      expect(withIn(scroller, labelled(label))).toBe(false);
    }
    expect(h.tree.root.findAll(labelled("Search"))).toHaveLength(0);
    expect(field(h, SEARCH).props.returnKeyType).toBe("search");
    expect(withIn(findHost(h, "picker-search")[0], (node) => node.props.children === "Choose a result.")).toBe(true);
    expect(withIn(scroller, (node) => node.props.children === "Choose a result.")).toBe(false);
    expect(withIn(scroller, labelled("Details of CA40"))).toBe(true);
    expect(withIn(scroller, (node) => node.props.testID === "picker-footer")).toBe(false);
    expect(withIn(findHost(h, "picker-footer")[0], labelled("Use the selected code"))).toBe(true);
  });

  it("shows the status alone when the line takes no uncoded text, and no status row at all before a search", async () => {
    const h = mount({ init: { allowUncoded: false }, env });
    expect(h.tree.root.findAll(labelled("Add uncoded text"))).toHaveLength(0);
    expect(findHost(h, "picker-search")[0].children).toHaveLength(1);
    await search(h, "pregnant");
    expect(withIn(findHost(h, "picker-search")[0], (node) => node.props.children === "Choose a result.")).toBe(true);
    expect(h.tree.root.findAll(labelled("Add uncoded text"))).toHaveLength(0);
  });

  it("offers 'Add uncoded text' as a link on the status line, not as a button row of its own", async () => {
    const h = mount({ env });
    await search(h, "pregnant");
    const link = control(h, "Add uncoded text");
    expect(link.props.hitSlop).toMatchObject({ top: 8, bottom: 8 });
    const line = findHost(h, "picker-search")[0].children.map((child) => (typeof child === "string" ? null : child)).filter(Boolean) as ReactTestInstance[];
    // The search box and the one status line: nothing else takes height.
    expect(line.filter((child) => child.props.accessibilityLabel === SEARCH || withIn(child, labelled("Add uncoded text")))).toHaveLength(2);
    expect(withIn(link, (node) => flatStyle(node).textDecorationLine === "underline")).toBe(true);
  });

  describe("result row anatomy", () => {
    const rowOf = (h: Harness, code: string) => h.tree.root.findAll((node) => typeof node.type === "string" && typeof node.props.onLayout === "function" && withIn(node, labelled(`Details of ${code}`)) && node.props.testID === undefined).at(-1) as ReactTestInstance;

    it("is flat: a hairline below, no card border, no fill, no gap between rows", async () => {
      mockWindow = PHONE;
      const h = mount({ env });
      await search(h, "pregnant");
      const style = flatStyle(rowOf(h, "CA40"));
      expect(style.borderBottomWidth).toBeGreaterThan(0);
      expect(style.borderBottomWidth).toBeLessThan(1);
      expect(style).not.toHaveProperty("borderWidth");
      expect(style).not.toHaveProperty("borderRadius");
      expect(style).not.toHaveProperty("backgroundColor");
      expect(scrollerOf(h).props.contentContainerStyle).not.toHaveProperty("gap");
    });

    it("has one line for a plain result: a 44-point whole-line target and a 32-point ⓘ that reaches 44", async () => {
      mockWindow = PHONE;
      const h = mount({ env });
      await search(h, "pregnant");
      const row = rowOf(h, "CA40");
      expect(withIn(row, (node) => node.props.testID === "result-meta")).toBe(false);
      const line = row.findAll((node) => node.props.testID === "result-line" && typeof node.type === "string")[0];
      expect(flatStyle(line).flexDirection).toBe("row");
      const title = row.findAll((node) => node.props.accessibilityLabel === "CA40 Pneumonia" && typeof node.type === "string")[0];
      expect(flatStyle(title)).toMatchObject({ minHeight: 44, flex: 1 });
      const info = row.findAll((node) => node.props.accessibilityLabel === "Details of CA40" && typeof node.type === "string")[0];
      expect(flatStyle(info)).toMatchObject({ minWidth: 32, minHeight: 32 });
      expect(info.props.hitSlop).toBe(6);
      expect(flat(info.children)).toBe("ⓘ");
      expect(flatStyle(info.children[0] as ReactTestInstance).lineHeight).toBeGreaterThanOrEqual(20 * 1.4);
      // Title and ⓘ are siblings in line 1; pressing either acts on the same row.
      expect(withIn(line, (node) => node === title)).toBe(true);
      expect(withIn(line, (node) => node === info)).toBe(true);
    });

    it("adds line 2 only when something is there: pills, the matched caption on one line, the age tag", async () => {
      mockWindow = PHONE;
      const h = mount({ env: { ...env, terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia"), rich, term("CA41", "Cough", { age_restricted: true })], truncated: false, next_cursor: null }) } });
      await search(h, "pregnant");
      expect(withIn(rowOf(h, "CA40"), (node) => node.props.testID === "result-meta")).toBe(false);
      const meta = rowOf(h, "JA00").findAll((node) => node.props.testID === "result-meta" && typeof node.type === "string")[0];
      expect(flatStyle(meta)).toMatchObject({ flexDirection: "row", flexWrap: "nowrap" });
      for (const badge of ["Mandatory postcoordination", "Open coding note", "Open pregnancy related terms", "Open perinatal related terms"]) expect(withIn(meta, labelled(badge))).toBe(true);
      const matched = meta.findAll((node) => typeof node.type === "string" && flat(node.children) === "Matched: Gestation")[0];
      expect(matched.props.numberOfLines).toBe(1);
      expect(flatStyle(matched).flexShrink).toBe(1);
      expect(withIn(rowOf(h, "CA41"), labelled("Age-restricted: Usually used only for certain age groups."))).toBe(true);
      expect(withIn(rowOf(h, "CA41"), (node) => node.props.testID === "result-meta")).toBe(true);
    });

    it("draws 28-point pills with capped text, and a '+ Build' pill for postcoordination", async () => {
      mockWindow = PHONE;
      const h = mount({ env: { ...env, terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia"), rich, term("CA41", "Cough", { age_restricted: true, matching_text: "Tussis" })], truncated: false, next_cursor: null }) } });
      await search(h, "pregnant");
      const hosts = (label: string) => h.tree.root.findAll((node) => typeof node.type === "string" && node.props.accessibilityLabel === label)[0];
      for (const label of ["Mandatory postcoordination", "Open coding note", "Open pregnancy related terms", "Open perinatal related terms", "Age-restricted: Usually used only for certain age groups."]) {
        expect(flatStyle(hosts(label)).minHeight).toBe(28);
      }
      expect(flat(hosts("Mandatory postcoordination").children)).toBe("+ Build");
      const capped = h.tree.root.findAll((node) => typeof node.type === "string" && node.props.maxFontSizeMultiplier !== undefined);
      expect(capped.length).toBeGreaterThan(0);
      // Titles are never capped: they grow with the system font.
      const title = h.tree.root.findAll((node) => typeof node.type === "string" && node.props.accessibilityLabel === "JA00 Pregnancy")[0];
      expect(withIn(title, (node) => node.props.maxFontSizeMultiplier !== undefined)).toBe(false);
      // No text container has a fixed height.
      const fixed = h.tree.root.findAll((node) => typeof node.type === "string" && flatStyle(node).height !== undefined && typeof flatStyle(node).height === "number" && withIn(node, (inner) => typeof inner.type === "string" && typeof inner.props.children === "string" && inner.props.children.length > 2));
      expect(fixed).toHaveLength(0);
    });

    it("gives Devanagari and other tall scripts room: every row text has a line height of at least 1.4 times its size", async () => {
      mockWindow = PHONE;
      const h = mount({ env: { ...env, terms: () => ({ schema_version: 1, items: [rich], truncated: false, next_cursor: null }) } });
      await search(h, "pregnant");
      const texts = rowOf(h, "JA00").findAll((node) => String(node.type) === "Text");
      const sized = texts.map(flatStyle).filter((style) => style.fontSize);
      expect(sized.length).toBeGreaterThan(3);
      for (const style of sized) if (style.lineHeight !== undefined) expect(style.lineHeight).toBeGreaterThanOrEqual(style.fontSize * 1.4 - 0.5);
    });

    it("stacks Details under line 1 at font scale 1.5 and keeps it a 44-point target", async () => {
      mockWindow = { ...PHONE, fontScale: 1.5 };
      const h = mount({ env });
      await search(h, "pregnant");
      const row = rowOf(h, "JA00");
      expect(flatStyle(row.findAll((node) => node.props.testID === "result-line" && typeof node.type === "string")[0]).flexDirection).toBe("column");
      const info = row.findAll((node) => node.props.accessibilityLabel === "Details of JA00" && typeof node.type === "string")[0];
      expect(flatStyle(info).minHeight).toBe(44);
      expect(flat(info.children)).toBe("ⓘDetails");
      const title = row.findAll((node) => node.props.accessibilityLabel === "JA00 Pregnancy" && typeof node.type === "string")[0];
      expect(flatStyle(title)).not.toHaveProperty("flex");
      expect(flatStyle(row.findAll((node) => node.props.testID === "result-meta" && typeof node.type === "string")[0]).flexWrap).toBe("wrap");
      await press(h, "Details of JA00");
      expect(calls(h, "details")).toHaveLength(1);
    });

    it("keeps one row at fontScale 1.49 and stacks it at 1.5", async () => {
      mockWindow = { ...PHONE, fontScale: 1.49 };
      const h = mount({ env });
      await search(h, "pregnant");
      expect(flatStyle(findHost(h, "result-line")[0]).flexDirection).toBe("row");
    });

    it("estimates how many rows a 411 x 917 phone shows: about 14 plain and 8 annotated rows, 8 and 5 with the keyboard up", () => {
      // Layout constants of a row: line 1 is a 44 target plus 2 + 2 padding and the hairline; line 2 is a 28 pill plus 4 + 4.
      const plain = 44 + 4 + 1;
      const annotated = plain + 28 + 4 + 4;
      const chrome = 24 + 52 + 68 + 70; // status bar, title row, search + status line, footer without a selection
      const free = (keyboard: number) => 917 - chrome - keyboard;
      expect(Math.floor(free(0) / plain)).toBeGreaterThanOrEqual(13);
      expect(Math.floor(free(0) / annotated)).toBeGreaterThanOrEqual(7);
      expect(Math.floor(free(300) / plain)).toBeGreaterThanOrEqual(7);
      expect(Math.floor(free(300) / annotated)).toBeGreaterThanOrEqual(4);
    });
  });

  describe("tablet", () => {
    const open = async (h: Harness) => { await search(h, "pregnant"); await press(h, "Details of CA40"); };

    it("is a single pane until a card is open, with the inline Use and Details buttons", async () => {
      mockWindow = TABLET;
      const h = mount({ env });
      await search(h, "pregnant");
      expect(flatStyle(findHost(h, "picker-body")[0]).flexDirection).toBe("column");
      expect(findHost(h, "picker-detail")).toHaveLength(0);
      expect(has(h, "Use CA40")).toBe(true);
      await press(h, "Use CA40");
      expect(flat(findHost(h, "picker-footer")[0].children)).toContain("CA40 — Pneumonia");
      expect(calls(h, "details")).toHaveLength(1);
    });

    it("opens a card to the right of the results: a row of two scrolling panes, results about 40 % and at least 320", async () => {
      mockWindow = TABLET;
      const h = mount({ env });
      await open(h);
      expect(flatStyle(findHost(h, "picker-body")[0]).flexDirection).toBe("row");
      const list = flatStyle(scrollerOf(h));
      expect(list.width).toBe(Math.round(1180 * 0.4));
      expect(list).toMatchObject({ flexGrow: 0, flexShrink: 0 });
      const detail = scrollerOf(h, "picker-detail");
      expect(detail).toBeDefined();
      expect(flatStyle(detail).flex).toBe(1);
      expect(withIn(detail, (node) => node.props.testID === "picker-details")).toBe(true);
      expect(withIn(scrollerOf(h), (node) => node.props.testID === "picker-details")).toBe(false);
      expect(withIn(scrollerOf(h), labelled("Details of CA40"))).toBe(true);
      // Rows in the narrow pane drop the inline buttons for the ⓘ.
      expect(has(h, "Use CA40")).toBe(false);
    });

    it("never narrows the results below 320", async () => {
      mockWindow = { width: 768, height: 1024, fontScale: 1 };
      const h = mount({ env });
      await open(h);
      expect(flatStyle(scrollerOf(h)).width).toBe(320);
    });

    it("has no scroll-jump and no Back to results: a card is just there", async () => {
      mockWindow = TABLET;
      const h = mount({ env });
      await open(h);
      expect(has(h, "Back to results")).toBe(false);
      const spy = jest.fn();
      const results = scrollerOf(h);
      (results.instance as { scrollTo: unknown }).scrollTo = spy;
      const card = findHost(h, "picker-details")[0];
      act(() => { (card.parent as ReactTestInstance).props.onLayout?.({ nativeEvent: { layout: { y: 900 } } }); });
      expect(spy).not.toHaveBeenCalled();
    });

    it("keeps the footer across the full width, below both panes", async () => {
      mockWindow = TABLET;
      const h = mount({ env });
      await open(h);
      const footer = findHost(h, "picker-footer")[0];
      expect(withIn(findHost(h, "picker-body")[0], (node) => node === footer)).toBe(false);
      expect(flatStyle(footer).maxHeight).toBeCloseTo(820 * 0.28);
    });

    it("puts the footer on one row: its text on the left, the buttons beside it", async () => {
      mockWindow = TABLET;
      const h = mount({ env: { ...env, terms: () => ({ schema_version: 1, items: [term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 })], truncated: false, next_cursor: null }) } });
      await search(h, "heart");
      const footer = findHost(h, "picker-footer")[0];
      expect(flatStyle(footer)).toMatchObject({ flexDirection: "row", alignItems: "center" });
      expect(flatStyle(scrollerOf(h, "picker-footer-text")).flex).toBe(1);
      expect(withIn(findHost(h, "picker-footer-buttons")[0], labelled("Use complete expression"))).toBe(true);
    });

    it("keeps clear of a side cutout", async () => {
      mockWindow = TABLET;
      mockInsets = { top: 10, bottom: 20, left: 24, right: 48 };
      const h = mount({ env });
      const root = h.tree.root.findAll((node) => typeof node.type === "string" && node.props.accessibilityViewIsModal)[0];
      expect(flatStyle(root)).toMatchObject({ paddingTop: 10, paddingLeft: 24, paddingRight: 48 });
    });

    it("shows a builder in the right pane, with optional axes expanded", async () => {
      mockWindow = TABLET;
      const h = mount({ env: { ...env, terms: () => ({ schema_version: 1, items: [term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 })], truncated: false, next_cursor: null }) } });
      await search(h, "heart");
      const detail = scrollerOf(h, "picker-detail");
      expect(withIn(detail, (node) => node.props.testID === "picker-build")).toBe(true);
      expect(has(h, "Has manifestation MC85 Title MC85")).toBe(true);
      expect(has(h, "Has severity XS1 Title XS1")).toBe(true);
      expect(h.tree.root.findAll((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.includes(", optional"))).toHaveLength(0);
    });

    it("keeps a safe route: a mandatory stem on a tablet still opens the builder, not OK", async () => {
      mockWindow = TABLET;
      const h = mount({ env: { ...env, terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia"), term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 })], truncated: false, next_cursor: null }) } });
      await search(h, "heart");
      await press(h, "BD54 Acute MI");
      expect(calls(h, "postcoordination")).toHaveLength(1);
      expect(withIn(scrollerOf(h, "picker-detail"), (node) => node.props.testID === "picker-build")).toBe(true);
      expect(control(h, "Use complete expression").props.disabled).toBe(true);
    });
  });

  it("caps the footer at 28% of the window and scrolls its text inside it", () => {
    const h = mount();
    const footer = findHost(h, "picker-footer")[0];
    // A phone stacks the buttons under the text.
    expect(flatStyle(footer).flexDirection).toBe("column");
    expect(flatStyle(footer).maxHeight).toBeCloseTo(1334 * 0.28);
    const inner = footer.findAll((node) => node.props.testID === "picker-footer-text" && node.instance);
    expect(inner.length).toBeGreaterThan(0);
    expect(flatStyle(inner[0]).flexShrink).toBe(1);
  });

  it("recomputes the footer cap when the window turns", () => {
    mockWindow = { width: 800, height: 1280, fontScale: 1 };
    const h = mount();
    expect(flatStyle(findHost(h, "picker-footer")[0]).maxHeight).toBeCloseTo(1280 * 0.28);
    mockWindow = { width: 1280, height: 800, fontScale: 1 };
    h.rerender();
    expect(flatStyle(findHost(h, "picker-footer")[0]).maxHeight).toBeCloseTo(800 * 0.28);
  });

  it("writes the code in the muted colour with tabular figures, and tints each badge kind differently", async () => {
    const h = mount({ env: { terms: () => ({ schema_version: 1, items: [rich, term("NC72.7", "Injury", { postcoordination: true, postcoordination_availability: 1 })], truncated: false, next_cursor: null }) } });
    await search(h, "pregnant");
    const code = h.tree.root.findAll((node) => node.props.children === "JA00" && typeof node.type === "string")[0];
    expect(flatStyle(code)).toMatchObject({ color: ui.light.mutedForeground, fontVariant: ["tabular-nums"] });
    const fill = (label: string) => flatStyle(h.tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.type === "string")[0]).backgroundColor;
    const fills = [fill("Mandatory postcoordination"), fill("Postcoordination available"), fill("Open pregnancy related terms"), fill("Open perinatal related terms"), fill("Open coding note")];
    expect(fills).toEqual([ui.light.chart[1].soft, ui.light.chart[1].tint, ui.light.chart[0].soft, ui.light.chart[4].soft, ui.light.chart[2].soft]);
    expect(new Set(fills).size).toBe(5);
  });
});

describe("age-restricted tag", () => {
  const restricted = (extra: Record<string, unknown>) => ({ terms: () => ({ schema_version: 1, items: [term("CA40", "Pneumonia", extra)], truncated: false, next_cursor: null }) });

  it("shows a warning tag with the note when the term carries them", async () => {
    const h = mount({ env: restricted({ age_restricted: true, restriction_note: "Only for children under 5." }) });
    await search(h, "pneu");
    expect(has(h, "Age-restricted: Only for children under 5.")).toBe(false);
    const tag = h.tree.root.findAll((node) => node.props.accessibilityLabel === "Age-restricted: Only for children under 5." && typeof node.type === "string");
    expect(tag).toHaveLength(1);
    expect(flat(tag[0].children)).toBe("age-restricted");
    expect(JSON.stringify(tag[0].props.style)).toContain(ui.light.warning);
    expect(text(h)).toContain("Only for children under 5.");
  });

  it("uses the web's default wording without a note, and draws nothing for an unrestricted term", async () => {
    const h = mount({ env: restricted({ age_restricted: true }) });
    await search(h, "pneu");
    expect(h.tree.root.findAll((node) => node.props.accessibilityLabel === "Age-restricted: Usually used only for certain age groups.")).not.toHaveLength(0);
    const plain = mount();
    await search(plain, "pneu");
    expect(plain.tree.root.findAll((node) => String(node.props.accessibilityLabel ?? "").startsWith("Age-restricted"))).toHaveLength(0);
    expect(text(plain)).not.toContain("age-restricted");
  });
});

/* --------------------------------------------- cards: scroll, back to results */

describe("opened cards", () => {
  const rows = [term("CA40", "Pneumonia"), term("CA41", "Bronchitis"), term("CA42", "Asthma")];
  const env = (extra: Partial<Env> = {}): Env => ({ terms: () => ({ schema_version: 1, items: rows, truncated: false, next_cursor: null }), ...extra, guidance: { details: () => ({ schema_version: 1, definition: "Text." }), postcoordination: () => postcoordination(), hierarchy: () => ({ schema_version: 1, selected: opt("CA41"), ancestors: [], siblings: [], children: [], related_maternal: [], related_perinatal: [], truncated: false }), ...(extra.guidance ?? {}) } });
  const layout = (y: number) => ({ nativeEvent: { layout: { x: 0, y, width: 300, height: 100 } } });
  const scroller = (h: Harness) => h.tree.root.findAll((node) => node.props.testID === "picker-results" && node.instance)[0].instance as { scrollTo: jest.Mock };
  /** Laid-out hosts with onLayout, in render order: the rows first, then each card's wrapper. */
  const hosts = (h: Harness) => h.tree.root.findAll((node) => node.props.testID === "picker-results" && node.instance)[0].findAll((node) => typeof node.type === "string" && typeof node.props.onLayout === "function");
  const layOutRows = (h: Harness) => hosts(h).slice(0, 3).forEach((node, index) => act(() => node.props.onLayout(layout(index * 112))));

  it("scrolls once to a card the coder opened, laid out below the rows, and does not move the list when it appears", async () => {
    const h = mount({ env: env() });
    await search(h, "pneu");
    layOutRows(h);
    scroller(h).scrollTo.mockClear();
    await press(h, "Details of CA41");
    const card = hosts(h)[3];
    act(() => card.props.onLayout(layout(420)));
    expect(scroller(h).scrollTo).toHaveBeenCalledTimes(1);
    expect(scroller(h).scrollTo).toHaveBeenCalledWith({ y: 420, animated: true });
    act(() => card.props.onLayout(layout(430)));
    expect(scroller(h).scrollTo).toHaveBeenCalledTimes(1);
    // The rows sit above the card in the content, in result order, so opening a card never shifts them.
    const order = h.tree.root.findAll((node) => typeof node.type === "string" && (node.props.accessibilityLabel === "CA42 Asthma" || node.props.testID === "picker-details")).map((node) => node.props.testID ?? node.props.accessibilityLabel);
    expect(order).toEqual(["CA42 Asthma", "picker-details"]);
  });

  it("'Back to results' returns to the row that opened the card", async () => {
    const h = mount({ env: env() });
    await search(h, "pneu");
    layOutRows(h);
    await press(h, "Details of CA42");
    scroller(h).scrollTo.mockClear();
    await press(h, "Back to results");
    expect(scroller(h).scrollTo).toHaveBeenCalledWith({ y: 224, animated: true });
    // A card opened from another row goes back to that row.
    await press(h, "Details of CA41");
    await press(h, "Back to results");
    expect(scroller(h).scrollTo).toHaveBeenLastCalledWith({ y: 112, animated: true });
  });

  it("goes back to the top of the list when the row was never laid out", async () => {
    const h = mount({ env: env() });
    await search(h, "pneu");
    await press(h, "Details of CA42");
    scroller(h).scrollTo.mockClear();
    await press(h, "Back to results");
    expect(scroller(h).scrollTo).toHaveBeenCalledWith({ y: 0, animated: true });
  });

  it("the Hierarchy button in a card scrolls to the hierarchy, and Back still returns to the row", async () => {
    const h = mount({ env: env() });
    await search(h, "pneu");
    layOutRows(h);
    await press(h, "Details of CA41");
    await press(h, "Hierarchy of CA41");
    const card = hosts(h).find((node) => flat(node.children).includes("See in hierarchy")) as ReactTestInstance;
    scroller(h).scrollTo.mockClear();
    act(() => card.props.onLayout(layout(700)));
    expect(scroller(h).scrollTo).toHaveBeenCalledWith({ y: 700, animated: true });
    scroller(h).scrollTo.mockClear();
    await press(h, "Back to results");
    expect(scroller(h).scrollTo).toHaveBeenCalledWith({ y: 112, animated: true });
  });

  it("neither scrolls nor offers a way back for the builder a search opens by itself, and the details a Use loads do not scroll", async () => {
    const mandatory = term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 });
    const h = mount({ env: env({ terms: () => ({ schema_version: 1, items: [mandatory, term("CA40", "Pneumonia")], truncated: false, next_cursor: null }) }) });
    await search(h, "heart");
    expect(text(h)).toContain("Build expression");
    expect(has(h, "Back to results")).toBe(false);
    scroller(h).scrollTo.mockClear();
    hosts(h).forEach((node) => act(() => node.props.onLayout(layout(900))));
    expect(scroller(h).scrollTo).not.toHaveBeenCalled();
    // Use stages the code and loads its details below the list without scrolling.
    await press(h, "CA40 Pneumonia");
    hosts(h).forEach((node) => act(() => node.props.onLayout(layout(900))));
    expect(text(h)).toContain("SELECTED");
    expect(scroller(h).scrollTo).not.toHaveBeenCalled();
    // The coder's own tap on the same stem's title does scroll.
    await press(h, "BD54 Acute MI");
    const builds = hosts(h).filter((node) => flat(node.children).includes("Build expression"));
    act(() => builds[0].props.onLayout(layout(333)));
    expect(scroller(h).scrollTo).toHaveBeenCalledWith({ y: 333, animated: true });
  });

  it("a card opened again is a new card: it scrolls again", async () => {
    const h = mount({ env: env() });
    await search(h, "pneu");
    layOutRows(h);
    await press(h, "Details of CA41");
    act(() => hosts(h)[3].props.onLayout(layout(400)));
    await press(h, "Details of CA42");
    act(() => hosts(h)[3].props.onLayout(layout(410)));
    expect(scroller(h).scrollTo).toHaveBeenLastCalledWith({ y: 410, animated: true });
  });
});

/* ---------------------------------------------------------------- sticky footer */

describe("building footer", () => {
  const mandatory = term("BD54", "Acute MI", { postcoordination: true, postcoordination_availability: 2 });
  const env = (extra: Partial<Env> = {}): Env => ({
    terms: () => ({ schema_version: 1, items: [mandatory, term("CA40", "Pneumonia")], truncated: false, next_cursor: null }),
    ...extra,
    guidance: { postcoordination: () => postcoordination(), details: () => ({ schema_version: 1 }), ...(extra.guidance ?? {}) },
  });
  const footer = (h: Harness) => h.tree.root.findAll((node) => node.props.testID === "picker-footer" && typeof node.type === "string")[0];

  it("shows BUILDING with the live expression and the Use buttons, and the card keeps no copy of them", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await openAxis(h, "Has manifestation");
    expect(flat(footer(h).children)).toContain("BUILDING");
    expect(flat(footer(h).children)).toContain("BD54 — Acute MI");
    expect(flat(footer(h).children)).toContain("Required axis missing");
    expect(h.tree.root.findAll((node) => node.props.testID === "picker-build")[0].findAll((node) => node.props.testID === "build-preview")).toHaveLength(0);
    expect(text(h)).not.toContain("Complete code preview");
    const inFooter = (label: string) => footer(h).findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function").length > 0;
    expect(inFooter("Use complete expression")).toBe(true);
    expect(inFooter("Use stem without extensions")).toBe(false);
    expect(control(h, "Use complete expression").props.disabled).toBe(true);
    await press(h, "Has causing condition 5A11 Title 5A11");
    await press(h, "Has manifestation MC85 Title MC85");
    expect(previewCode(h)).toBe("BD54/MC85/5A11");
    expect(flat(footer(h).children)).toContain("BD54/MC85/5A11 — Acute MI; Title MC85; Title 5A11");
    expect(flat(footer(h).children)).not.toContain("Required axis missing");
    expect(control(h, "Use complete expression").props.disabled).toBe(false);
    await press(h, "Use complete expression");
    expect(flat(footer(h).children)).toContain("SELECTED");
    expect(flat(footer(h).children)).not.toContain("BUILDING");
    expect(has(h, "Use the selected code")).toBe(true);
  });

  it("offers the stem alone from the footer when no axis is required", async () => {
    const optionalAxes = axes().filter((axis) => !axis.required);
    const h = mount({ env: env({ terms: () => ({ schema_version: 1, items: [term("NC72.7", "Injury", { postcoordination: true, postcoordination_availability: 1 })], truncated: false, next_cursor: null }), guidance: { postcoordination: () => postcoordination({ stem: opt("NC72.7", { title: "Injury" }), axes: optionalAxes }) } }) });
    await search(h, "injury");
    await press(h, "Postcoordination available");
    expect(flat(footer(h).children)).toContain("BUILDING");
    await press(h, "Use stem without extensions");
    expect(flat(footer(h).children)).toContain("SELECTED");
    expect(flat(footer(h).children)).toContain("NC72.7 — Injury");
  });

  it("goes back to the card when a code is staged meanwhile, and returns to the footer when the choice goes", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await press(h, "CA40 Pneumonia");
    expect(flat(footer(h).children)).toContain("SELECTED");
    expect(text(h)).toContain("Complete code preview");
    expect(has(h, "Use complete expression")).toBe(true);
    await typeInto(h, SEARCH, "heart a");
    expect(text(h)).not.toContain("SELECTED");
  });

  it("keeps the preview and the Use buttons in the card while another code is staged", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await press(h, "CA40 Pneumonia");
    await press(h, "Has causing condition 5A11 Title 5A11");
    expect(footer(h).findAll((node) => node.props.accessibilityLabel === "Use complete expression")).toHaveLength(0);
    await press(h, "Use complete expression");
    expect(flat(footer(h).children)).toContain("BD54/5A11");
    expect(h.tree.root.findAll((node) => node.props.testID === "picker-build")).toHaveLength(0);
    const optionalAxes = axes().filter((axis) => !axis.required);
    const g = mount({ env: env({ guidance: { postcoordination: () => postcoordination({ axes: optionalAxes }) } }) });
    await search(g, "heart");
    await press(g, "CA40 Pneumonia");
    await press(g, "Use stem without extensions");
    expect(flat(footer(g).children)).toContain("BD54 — Acute MI");
  });

  it("leaves the footer when the builder is cancelled", async () => {
    const h = mount({ env: env() });
    await search(h, "heart");
    await press(h, "Cancel Build expression");
    expect(flat(footer(h).children)).not.toContain("BUILDING");
    expect(flat(footer(h).children)).toContain("No code selected");
    expect(has(h, "Use complete expression")).toBe(false);
  });
});

/* ------------------------------------------------------- bridge replaced in flight */

describe("a replaced bridge", () => {
  const hang = () => { const box: { release?: (value: unknown) => void } = {}; const promise = new Promise((resolve) => { box.release = resolve; }); return { box, promise }; };
  const verified = { schema_version: 1, item: { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40", release: "r", postcoordination: false, primary_stem: null } };

  it("starts over like a revision change: the pending verification is dropped and OK is free again", async () => {
    const { box, promise } = hang();
    const h = mount({ env: { check: () => promise } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(text(h)).toContain("Verifying CA40…");
    expect(control(h, "Use the selected code").props.disabled).toBe(true);
    const before = (h.api.searchDorisTerms as jest.Mock).mock.calls.length;
    h.replaceBridge();
    await settle();
    expect(text(h)).not.toContain("Verifying");
    expect(text(h)).not.toContain("SELECTED");
    expect(text(h)).toContain("No code selected");
    expect((h.api.searchDorisTerms as jest.Mock).mock.calls.length).toBe(before + 1);
    expect(text(h)).toContain("CA40 — Pneumonia");
    await act(async () => { box.release?.(verified); });
    await settle();
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    await press(h, "CA40 Pneumonia");
    expect(control(h, "Use the selected code").props.disabled).toBe(false);
  });

  it("closes the cards that were waiting on the old bridge", async () => {
    const h = mount({ env: { guidance: { details: () => new Promise(() => undefined) } } });
    await search(h, "pneu");
    await press(h, "Details of CA40");
    expect(text(h)).toContain("Loading WHO code details…");
    h.replaceBridge();
    await settle();
    expect(text(h)).not.toContain("Loading WHO code details…");
  });

  it("works with nothing typed", async () => {
    const h = mount();
    h.replaceBridge();
    await settle();
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
    expect(text(h)).toContain("No code selected");
  });
});

/* ---------------------------------------------------------- protocol and unmount */

describe("protocol", () => {
  const verified = { schema_version: 1, item: { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40", release: "r", postcoordination: false, primary_stem: null } };

  it("stays quiet after it is unmounted while a choice is being verified", async () => {
    let release!: (value: unknown) => void;
    const h = mount({ env: { check: () => new Promise((resolve) => { release = resolve; }) } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    expect(h.api.checkDorisSelection).toHaveBeenCalledTimes(1);
    act(() => h.tree.unmount());
    await act(async () => { release(verified); });
    await advance(1000);
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
  });

  it("stays quiet after it is unmounted while a search is in flight", async () => {
    let release!: (value: unknown) => void;
    const h = mount({ env: { terms: () => new Promise((resolve) => { release = resolve; }) } });
    await search(h, "pneu");
    act(() => h.tree.unmount());
    await act(async () => { release({ schema_version: 1, items: [], truncated: false, next_cursor: null }); });
    await advance(1000);
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
  });

  it("hands a choice on when the same verification arrives with the picker still open", async () => {
    // The control for the two quiet cases above: the verified pair is delivered when nothing was replaced.
    let release!: (value: unknown) => void;
    const h = mount({ env: { check: () => new Promise((resolve) => { release = resolve; }) } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    await act(async () => { release(verified); });
    await settle();
    expect(h.handlers.onSelect).toHaveBeenCalledWith({ code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40" });
  });

  it("does not hand a choice on when the bridge was replaced at the same revision while it was verified", async () => {
    let release!: (value: unknown) => void;
    const h = mount({ env: { check: () => new Promise((resolve) => { release = resolve; }) } });
    await search(h, "pneu");
    await press(h, "CA40 Pneumonia");
    await press(h, "Use the selected code");
    h.replaceBridge();
    await settle();
    await act(async () => { release(verified); });
    await settle();
    expect(h.handlers.onSelect).not.toHaveBeenCalled();
    expect(text(h)).toContain("No code selected");
  });

  it("a card closed before WHO answers stays quiet when the answer comes", async () => {
    let release!: (value: unknown) => void;
    let fail!: (error: Error) => void;
    let first = true;
    const h = mount({ env: { guidance: { details: () => new Promise((resolve, reject) => { if (first) { first = false; release = resolve; } else fail = reject; }) } } });
    await search(h, "pneu");
    await press(h, "Details of CA40");
    await press(h, "Close CA40 — Pneumonia");
    await act(async () => { release({ schema_version: 1, definition: "Too late." }); });
    await press(h, "Details of CA40");
    await press(h, "Close CA40 — Pneumonia");
    await act(async () => { fail(new Error("Too late.")); });
    await settle();
    expect(text(h)).not.toContain("Too late.");
  });

  it("clears a pending debounce on unmount", async () => {
    const h = mount();
    await typeInto(h, SEARCH, "pneu");
    act(() => h.tree.unmount());
    await advance(500);
    expect(h.api.searchDorisTerms).not.toHaveBeenCalled();
  });

  it("an item that needs a build but is in a complete expression stays usable", async () => {
    const h = mount({ env: { terms: () => ({ schema_version: 1, items: [term("BD54/MC85", "Complete", { postcoordination: true, postcoordination_availability: 2 })], truncated: false, next_cursor: null }) } });
    await search(h, "heart");
    await press(h, "BD54/MC85 Complete");
    expect(text(h)).toContain("SELECTED");
    expect(calls(h, "postcoordination")).toEqual([]);
  });
});
