import { Modal } from "react-native";
import { act, create } from "react-test-renderer";

import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import { IcdPickerModal } from "../src/workspace/doris/IcdPickerModal";

jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
const mockPlus = { value: false };
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus.value }));
const mockFrame: { props: any } = { props: null };
jest.mock("../src/workspace/doris/IcdPickerFrame", () => ({ IcdPickerFrame: (props: any) => { mockFrame.props = props; return null; } }));

const item = { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40", release: "2025-01", postcoordination: false, primary_stem: null };
const term = { ...item, matching_text: "Pneumonia", postcoordination_availability: 0, related_maternal: false, related_perinatal: false, has_coding_note: false };

function mount(check?: () => Promise<unknown>) {
  const api = {
    searchDorisTerms: jest.fn(async () => ({ schema_version: 1, items: [term], truncated: false, next_cursor: null })),
    getDorisCodeInfo: jest.fn(async () => ({ schema_version: 1, item })),
    checkDorisSelection: jest.fn(check ?? (async () => ({ schema_version: 1, item }))),
  } as unknown as WorkspaceApi;
  const handlers = { onSelect: jest.fn(), onUncoded: jest.fn(), onClose: jest.fn(), onForbidden: jest.fn() };
  const request = jest.fn() as unknown as JsonRequester;
  const element = (requestGeneration: number) => <IcdPickerModal init={{ title: "Immediate cause", accent: "#1D4ED8", allowUncoded: true, query: "pneu", theme: "light" }} api={api} request={request} identity={{ vaSid: "sid-1", mode: "coding" }} revision={1} requestGeneration={requestGeneration} {...handlers} />;
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(element(0)); });
  return { api, handlers, tree, setGeneration: (generation: number) => act(() => tree.update(element(generation))) };
}
const flat = (node: unknown): string => (node == null ? "" : typeof node === "string" ? node : Array.isArray(node) ? node.map(flat).join("") : flat((node as { children?: unknown }).children));
const settle = async () => { for (let i = 0; i < 10; i++) await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };

beforeEach(() => { mockFrame.props = null; });

test("the Collect Plus build shows the React picker, and a choice reaches the modal's owner only after the server verified it", async () => {
  mockPlus.value = true;
  const { api, handlers, tree } = mount();
  await settle();
  expect(mockFrame.props).toBeNull();
  expect(flat(tree.toJSON())).toContain("CA40 — Pneumonia");
  // Tablets rotate: the modal must allow both orientations on iOS too (Android follows the activity).
  expect(tree.root.findByType(Modal).props.supportedOrientations).toEqual(["portrait", "landscape"]);
  expect(api.searchDorisTerms).toHaveBeenCalledWith("sid-1", "pneu", { limit: 20 });
  const press = async (label: string) => {
    act(() => tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0].props.onPress());
    await settle();
  };
  await press("CA40 Pneumonia");
  expect(handlers.onSelect).not.toHaveBeenCalled();
  await press("Use the selected code");
  expect(api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "CA40", "https://who.int/CA40");
  expect(handlers.onSelect).toHaveBeenCalledWith({ code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40" });
  await press("Close search");
  expect(handlers.onClose).toHaveBeenCalledTimes(1);
});

test("plain Collect and the browser build keep the shared web picker page", async () => {
  mockPlus.value = false;
  const { api, tree } = mount();
  await settle();
  expect(mockFrame.props).not.toBeNull();
  expect(mockFrame.props.init.title).toBe("Immediate cause");
  expect(flat(tree.toJSON())).not.toContain("Search a condition or ICD-11 code");
  expect(api.searchDorisTerms).not.toHaveBeenCalled();
});

test("a rebuilt bridge (the host's request generation moved) cannot leave the React picker waiting for a reply that never comes", async () => {
  mockPlus.value = true;
  let release!: (value: unknown) => void;
  const { api, handlers, tree, setGeneration } = mount(() => new Promise((resolve) => { release = resolve; }));
  await settle();
  const control = (label: string) => tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
  const press = async (label: string) => { act(() => control(label).props.onPress()); await settle(); };
  await press("CA40 Pneumonia");
  await press("Use the selected code");
  expect(flat(tree.toJSON())).toContain("Verifying CA40…");
  const searches = (api.searchDorisTerms as jest.Mock).mock.calls.length;
  setGeneration(1);
  await settle();
  // Same revision, new bridge: the picker starts over and searches again through the new bridge.
  expect((api.searchDorisTerms as jest.Mock).mock.calls.length).toBe(searches + 1);
  expect(flat(tree.toJSON())).not.toContain("Verifying");
  expect(flat(tree.toJSON())).toContain("No code selected");
  await act(async () => { release({ schema_version: 1, item }); });
  await settle();
  expect(handlers.onSelect).not.toHaveBeenCalled();
  expect(control("Use the selected code").props.disabled).toBe(true);
  // ... and works again through the new bridge.
  (api.checkDorisSelection as jest.Mock).mockImplementation(async () => ({ schema_version: 1, item }));
  await press("CA40 Pneumonia");
  await press("Use the selected code");
  expect(handlers.onSelect).toHaveBeenCalledWith({ code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40" });
});
