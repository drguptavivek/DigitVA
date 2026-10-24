/** @jest-environment jsdom */
import React, { act } from "react";
import { Text } from "react-native";

// The real web DOM output (nativeID -> id), not the native mock the jest-expo preset gives.
jest.mock("react-native", () => ({
  ...jest.requireActual("react-native-web"),
  useWindowDimensions: () => ({ width: 1280, height: 900, scale: 1, fontScale: 1 }),
}));

jest.mock("expo-secure-store", () => ({}));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRoot } = require("react-dom/client") as { createRoot: (el: Element) => { render(node: React.ReactNode): void; unmount(): void } };
import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout.web";
import type { WorkspacePayload } from "../src/workspace/contracts";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const workspace = {
  case: { va_sid: "s", instance_name: "form-9", form_type_code: "WHO", project_code: "P", site_code: "S", age: 46, gender: "male", is_demo_project: false, project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
  categories: [{ code: "one", label: "One", nav_label: "One", render_mode: "table_sections", icon_name: "fa-user", count: 1 }],
  default_category: "one", step: "initial", blocked_by: [],
  assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
  smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
} as unknown as WorkspacePayload;

test("notes panel and its close button mount under document.body, and close works", () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<WorkspaceLayout identity={{ vaSid: "s", mode: "coding" }} workspace={workspace} categories={workspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()} notes={<Text>note body</Text>}><Text>content</Text></WorkspaceLayout>));

  const panel = document.getElementById("digitva-notes-panel");
  const close = document.getElementById("digitva-notes-close");
  expect(panel).not.toBeNull();
  expect(close).not.toBeNull();
  expect(panel!.parentElement).toBe(document.body);
  expect(host.contains(panel)).toBe(false);

  act(() => { document.getElementById("digitva-notes-trigger")!.click(); });
  expect(getComputedStyle(panel!).display).not.toBe("none");
  act(() => { close!.click(); });
  expect(getComputedStyle(panel!).display).toBe("none");
  act(() => root.unmount());
});

test("the notes content can close the panel through NotesCloseContext (Close beside Save private note)", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { NotesCloseContext } = require("../src/workspace/notesClose") as typeof import("../src/workspace/notesClose");
  const { Pressable } = jest.requireActual("react-native-web") as typeof import("react-native");
  function CloseFromInside() {
    const close = React.useContext(NotesCloseContext);
    return <Pressable nativeID="inner-close" onPress={close}><Text>Close</Text></Pressable>;
  }
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<WorkspaceLayout identity={{ vaSid: "s", mode: "coding" }} workspace={workspace} categories={workspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()} notes={<CloseFromInside />}><Text>content</Text></WorkspaceLayout>));
  const panel = document.getElementById("digitva-notes-panel")!;
  act(() => { document.getElementById("digitva-notes-trigger")!.click(); });
  expect(getComputedStyle(panel).display).not.toBe("none");
  act(() => { document.getElementById("inner-close")!.click(); });
  expect(getComputedStyle(panel).display).toBe("none");
  act(() => root.unmount());
});
