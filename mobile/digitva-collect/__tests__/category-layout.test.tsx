import React from "react";
import { Text } from "react-native";
import { act, create } from "react-test-renderer";

import { CategoryPanel } from "../src/workspace/CategoryPanel";
import { CategoryPanel as WebCategoryPanel } from "../src/workspace/CategoryPanel.web";
import { groupDiseaseHistory, subcategoryHeading, summaryPlacement } from "../src/workspace/categoryLayout";
import type { CategoryPayload, WorkspaceCategoryNav } from "../src/workspace/contracts";

const it_ = (label: string, value: string) => ({ label, value, flip: false, info: false });
function cat(mode: string, subs: Array<{ code: string; label: string; render_mode?: string; source_category?: string; items: ReturnType<typeof it_>[] }>, summary = ["Fever"]): CategoryPayload {
  return { code: "c", label: "Cat", render_mode: mode, summary_items: summary, subcategories: subs.map((s) => ({ render_mode: "default", ...s })) } as unknown as CategoryPayload;
}
function out(Panel: any, category: CategoryPayload, props: object = {}): string {
  let r: any;
  act(() => { r = create(<Panel category={category} {...props} />); });
  return JSON.stringify(r.toJSON());
}
const panels: Array<[string, any]> = [["phone", CategoryPanel], ["web", WebCategoryPanel]];

test("pure helpers: gating, headings, grouping", () => {
  expect(summaryPlacement("table_sections", ["x"])).toBeNull();
  expect(summaryPlacement("health_history_summary", ["x"])).toBeNull();
  expect(summaryPlacement("attachments", ["x"])).toBe("after");
  expect(summaryPlacement("workflow_panel", ["x"])).toBe("before");
  expect(summaryPlacement("attachments", [])).toBeNull();
  expect(subcategoryHeading("default")).toBeNull();
  expect(subcategoryHeading("risk_factors")).toBe("Risk factors");
  expect(subcategoryHeading("Duration of illness")).toBe("Duration of illness");
  const g = groupDiseaseHistory([it_("Asthma", "Yes"), it_("TB", "No"), it_("Other", "Maybe")]);
  expect(g).toEqual({ positive: ["Asthma"], negative: ["TB"], remaining: [it_("Other", "Maybe")] });
});

describe.each(panels)("%s panel", (panelName, Panel) => {
  test("symptoms card on workflow panels; on the narrative tab only on the web (the phone's is the NQA screen)", () => {
    const subs = [{ code: "n", label: "Narrative", items: [it_("Story", "Text")] }];
    expect(out(Panel, cat("table_sections", subs))).not.toContain("Symptoms on VA Interview");
    const attachments = out(Panel, cat("attachments", subs), { afterContent: <Text>Quality review</Text> });
    expect(attachments).toContain("Story");
    if (panelName === "web") expect(attachments.indexOf("Story")).toBeLessThan(attachments.indexOf("Symptoms on VA Interview"));
    else expect(attachments).not.toContain("Symptoms on VA Interview");
    const workflow = out(Panel, cat("workflow_panel", subs));
    expect(workflow.indexOf("Symptoms on VA Interview")).toBeGreaterThan(-1);
    expect(workflow.indexOf("Symptoms on VA Interview")).toBeLessThan(workflow.indexOf("Story"));
  });

  test("default heading hidden, raw keys humanized", () => {
    const o = out(Panel, cat("table_sections", [
      { code: "a", label: "default", items: [it_("Q1", "Text")] },
      { code: "b", label: "risk_factors", items: [it_("Q2", "Text")] },
    ], []));
    expect(o).toContain("Q1");
    expect(o).not.toContain('"default"');
    expect(o).not.toContain("risk_factors");
    expect(o).toContain("Risk factors");
  });

  test("history subcategory groups Diagnosed / Absent / other", () => {
    const nav: WorkspaceCategoryNav[] = [{ code: "c", label: "Cat", nav_label: "Cat", render_mode: "health_history_summary" } as WorkspaceCategoryNav];
    const o = out(Panel, cat("health_history_summary", [
      { code: "h", label: "history", render_mode: "health_history_summary", items: [it_("Asthma", "Yes"), it_("Malaria", "No"), it_("Notes", "Free text")] },
    ], []), { categoryNav: nav });
    expect(o).toContain("Diagnosed by Health Professional");
    expect(o).toContain("Absent");
    expect(o.indexOf("Asthma")).toBeLessThan(o.indexOf("Absent"));
    expect(o.indexOf("Malaria")).toBeGreaterThan(o.indexOf("Absent"));
    expect(o).toContain("Free text");
  });
});

test("phone workflow panel orders narration, disease group, then the rest", () => {
  const nav: WorkspaceCategoryNav[] = [
    { code: "nar", label: "N", nav_label: "N", render_mode: "attachments" } as WorkspaceCategoryNav,
    { code: "his", label: "H", nav_label: "H", render_mode: "health_history_summary" } as WorkspaceCategoryNav,
  ];
  const o = out(CategoryPanel, cat("workflow_panel", [
    { code: "x", label: "Other bits", items: [it_("Other Q", "Text")] },
    { code: "h", label: "hist", source_category: "his", items: [it_("Asthma", "Yes")] },
    { code: "n", label: "Narrative", source_category: "nar", items: [it_("Story", "Text")] },
  ]), { categoryNav: nav });
  const at = (s: string) => o.indexOf(s);
  expect(at("Symptoms on VA Interview")).toBeLessThan(at("Story"));
  expect(at("Story")).toBeLessThan(at("Disease / Co-morbidity"));
  expect(at("Disease / Co-morbidity")).toBeLessThan(at("Other Q"));
});

test("splitFieldId takes the WHO id off the question and leaves other labels whole", () => {
  const { splitFieldId } = require("../src/workspace/answerTone");
  expect(splitFieldId("(Id10123) Deceased died suddenly")).toEqual({ id: "Id10123", text: "Deceased died suddenly" });
  expect(splitFieldId("(Id10248_b) Months").id).toBe("Id10248_b");
  expect(splitFieldId("(narr_language) Narration language")).toEqual({ id: "narr_language", text: "Narration language" });
  expect(splitFieldId("Survey district")).toEqual({ id: null, text: "Survey district" });
});
