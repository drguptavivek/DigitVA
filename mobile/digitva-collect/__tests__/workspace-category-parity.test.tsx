import React from "react";
import { Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { CategoryPanel } from "../src/workspace/CategoryPanel.web";
import type { CategoryPayload, WorkspaceCategoryNav } from "../src/workspace/contracts";

type Subcategory = CategoryPayload["subcategories"][number] & { source_category?: string };

function render(category: CategoryPayload, props: Partial<React.ComponentProps<typeof CategoryPanel>> = {}) {
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(<CategoryPanel category={category} {...props} />);
  });
  return renderer;
}

function category(overrides: Partial<CategoryPayload> = {}, subcategories: Subcategory[] = []): CategoryPayload {
  return {
    code: "custom-category",
    label: "Custom category",
    render_mode: "table_sections",
    summary_items: [],
    subcategories,
    ...overrides,
  };
}

function sub(code: string, items: Array<{ label: string; value: string; flip?: boolean; info?: boolean }>, overrides: Partial<Subcategory> = {}): Subcategory {
  return {
    code,
    label: code.replace(/_/g, " "),
    render_mode: "default",
    items: items.map((item) => ({ flip: false, info: false, ...item })),
    ...overrides,
  };
}

test("uses configured custom history subcategory and preserves unknown answers", () => {
  const output = JSON.stringify(render(category({ render_mode: "health_history_summary" }, [
    sub("configured_history", [
      { label: "Hypertension", value: "Yes" },
      { label: "Diabetes", value: "No" },
      { label: "Unknown condition", value: "Unknown" },
    ], { render_mode: "health_history_summary" }),
    sub("other_section", [{ label: "Other", value: "Recorded" }]),
  ])).toJSON());

  expect(output).toContain("Diagnosed by Health Professional");
  expect(output).toContain("Hypertension");
  expect(output).toContain("Absent");
  expect(output).toContain("Diabetes");
  expect(output).toContain("Unknown condition");
  expect(output).toContain("Other");
  expect(output).toContain("Medical History (Responses)");
});

test("category-level history mode keeps the first configured section even when answers are non-binary", () => {
  const output = JSON.stringify(render(category({ render_mode: "health_history_summary" }, [
    sub("configured_history", [{ label: "Unknown condition", value: "Unknown" }]),
    sub("another_section", [{ label: "Hypertension", value: "Yes" }]),
  ])).toJSON());

  expect(output).toContain("Medical History (Responses)");
  expect(output).toContain("Unknown condition");
  expect(output).toContain("another section");
  expect(output).toContain("Hypertension");
});

test("flips only Yes/No colours while retaining the served answer text", () => {
  const output = JSON.stringify(render(category({}, [sub("answers", [
    { label: "Positive", value: "Yes", flip: true },
    { label: "Absent", value: "No", flip: true },
  ])])).toJSON());

  expect(output).toContain('"children":["Yes"]');
  expect(output).toContain('"children":["No"]');
  expect(output).toContain("#bc2938");
  expect(output).toContain("#3f9366");
});

test("workflow panels order interview summary, source-grouped evidence and notes", () => {
  const nav: WorkspaceCategoryNav[] = [
    { code: "vanarrationanddocuments", label: "Narration", nav_label: "Narration", render_mode: "attachments" },
    { code: "configured-history", label: "Disease", nav_label: "Disease", render_mode: "health_history_summary" },
  ];
  const output = JSON.stringify(render(category({ code: "workflow", label: "COD assessment", render_mode: "workflow_panel", summary_items: ["Fever"] }, [
    sub("narrative", [{ label: "Narrative", value: "Text" }], { source_category: "vanarrationanddocuments" }),
    sub("history", [{ label: "Asthma", value: "Yes" }], { source_category: "configured-history" }),
  ]), { categoryNav: nav, notesSummary: <Text>Saved note</Text>, afterContent: <Text>Assessment controls</Text> }).toJSON());

  expect(output.indexOf("Symptoms on VA Interview")).toBeLessThan(output.indexOf("Narration and Documents"));
  expect(output.indexOf("Narration and Documents")).toBeLessThan(output.indexOf("Disease / Co-Morbidity"));
  expect(output).toContain("Saved note");
  expect(output).toContain("Assessment controls");
});

test("attachments render NQA before the interview symptom summary, and table sections render their after-content slot", () => {
  const nav: WorkspaceCategoryNav[] = [
    { code: "attachments-source", label: "Narration", nav_label: "Narration", render_mode: "attachments" },
  ];
  const attachments = render(category({ code: "attachments", label: "Narration / Documents", render_mode: "attachments", summary_items: ["Fever"] }, [
    sub("narrative", [{ label: "Narrative", value: "Text" }], { source_category: "attachments-source" }),
  ]), { categoryNav: nav, afterContent: <Text>Quality review</Text> }).toJSON();
  const attachmentOutput = JSON.stringify(attachments);
  expect(attachmentOutput.indexOf("Narrative / Documents")).toBeLessThan(attachmentOutput.indexOf("Quality review"));
  expect(attachmentOutput.indexOf("Quality review")).toBeLessThan(attachmentOutput.indexOf("Symptoms on VA Interview"));

  const tableOutput = JSON.stringify(render(category({}, [sub("questions", [{ label: "Fever", value: "Yes" }])]), { afterContent: <Text>Social autopsy</Text> }).toJSON());
  expect(tableOutput).toContain("Social autopsy");
});

test("unknown and empty modes fall back to an accessible query/response table", () => {
  const empty = render(category({ render_mode: "unknown_mode" }, [sub("empty", [])])).toJSON();
  expect(JSON.stringify(empty)).toContain("Query");
  expect(JSON.stringify(empty)).toContain("Response");

  const media = jest.fn((path: string) => <Text>media:{path}</Text>);
  const output = JSON.stringify(render(category({}, [sub("files", [
    { label: "Safe", value: "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg" },
    { label: "Unsafe", value: "https://outside.example/file.jpg" },
  ])]), { renderMedia: media }).toJSON());
  expect(media).toHaveBeenCalledWith("/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg");
  expect(media).not.toHaveBeenCalledWith("https://outside.example/file.jpg");
  expect(output).toContain("https://outside.example/file.jpg");
});
