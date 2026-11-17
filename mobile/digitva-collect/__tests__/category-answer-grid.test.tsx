import React from "react";
import { act, create } from "react-test-renderer";

import { CategoryPanel } from "../src/workspace/CategoryPanel";
import { CategoryPanel as WebCategoryPanel } from "../src/workspace/CategoryPanel.web";
import { answerTone } from "../src/workspace/answerTone";
import { contrastRatio, ui } from "../src/theme";
import { webPalette } from "../src/workspace/webPalette";
import type { CategoryPayload } from "../src/workspace/contracts";

const items = [
  { label: "Fever", value: "Yes", flip: false, info: false },
  { label: "Vaccinated", value: "No", flip: false, info: false },
  { label: "Alcohol (flipped)", value: "Yes", flip: true, info: false },
  { label: "No cough (flipped)", value: "No", flip: true, info: false },
  { label: "Weight", value: "52 kg", flip: false, info: false },
  { label: "Source", value: "Yes", flip: false, info: true },
];
const category = { code: "c", label: "C", render_mode: "table_sections", summary_items: [], subcategories: [{ code: "s", label: "Section", render_mode: "default", items }] } as unknown as CategoryPayload;

function flat(node: any): any[] {
  if (!node || typeof node === "string") return [];
  return [node, ...(node.children ?? []).flatMap(flat)];
}
function text(node: any): string {
  return typeof node === "string" ? node : (node?.children ?? []).map(text).join("");
}
function render(Panel: any) {
  let r: any;
  act(() => { r = create(<Panel category={category} />); });
  return r.toJSON();
}
test("answerTone follows the web rules: info wins, flip swaps Yes and No, other answers have no badge", () => {
  expect(answerTone("Yes", false, false)).toBe("red");
  expect(answerTone(" no ", false, false)).toBe("green");
  expect(answerTone("Yes", true, false)).toBe("green");
  expect(answerTone("No", true, false)).toBe("red");
  expect(answerTone("Yes", true, true)).toBe("info");
  expect(answerTone("52 kg", false, false)).toBeNull();
  expect(answerTone(null, false, false)).toBeNull();
});

test("native rows show question left, answer right, with no Flipped or More information lines", () => {
  const json = render(CategoryPanel);
  const all = text({ children: [json] });
  expect(all).toContain("Fever");
  expect(all).toContain("52 kg");
  expect(all).not.toContain("Flipped");
  expect(all).not.toContain("More information");
  const fever = flat(json).find((n) => n.props?.style && [n.props.style].flat(9).some((s: any) => s?.flexDirection === "row" && s?.borderColor) && text(n).startsWith("Fever"));
  expect(fever.children).toHaveLength(2);
  expect(text(fever.children[0])).toBe("Fever");
  expect(text(fever.children[1])).toBe("Yes");
});

test("question text uses the Petrol ink token, not the muted grey", () => {
  const q = flat(render(CategoryPanel)).find((n) => n.type === "Text" && text(n) === "Fever");
  expect([q.props.style].flat(9).find((s: any) => s?.color)?.color).toBe(ui.light.foreground);
});

test("native answer badges use the same decision as the web table, in Petrol tokens", () => {
  const native = render(CategoryPanel);
  const web = render(WebCategoryPanel);
  const t = ui.light;
  // Web: red fill = w.yes, green = w.no, info = w.bar. Native maps each to its Petrol pair.
  const webYes = webPalette.light.yes, webNo = webPalette.light.no;
  const webRows = flat(web).filter((n) => n.props?.["data-response"]);
  const webFills = webRows.map((r) => flat(r).map((n) => [n.props?.style].flat(9).find((s: any) => s?.backgroundColor)?.backgroundColor).find(Boolean));
  const expectedNative = webFills.map((fill) => fill === webYes ? t.destructive : fill === webNo ? t.success : fill === webPalette.light.bar ? t.primary : undefined);
  const nativeFills = items.map((it) => {
    const row = flat(native).find((n) => n.props?.style && [n.props.style].flat(9).some((s: any) => s?.borderColor) && text(n.children[0]) === it.label);
    return flat(row.children[1]).map((n) => [n.props?.style].flat(9).find((s: any) => s?.backgroundColor)?.backgroundColor).find(Boolean);
  });
  expect(nativeFills).toEqual(expectedNative);
  expect(nativeFills.filter(Boolean)).toHaveLength(5);
});

test("badge text keeps 4.5:1 on its fill in both modes", () => {
  for (const mode of ["light", "dark"] as const) {
    const t = ui[mode];
    expect(contrastRatio(t.destructive, t.destructiveForeground)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(t.success, t.primaryForeground)).toBeGreaterThanOrEqual(4.5);
  }
});

test("native attachment answers sit under their question at full width, not in the half-width answer column", () => {
  const media = { ...category, subcategories: [{ code: "s", label: "Section", render_mode: "default", items: [{ label: "Narration image", value: "/api/v1/attachments/abc.jpg", flip: false, info: false }] }] } as unknown as CategoryPayload;
  let r: any;
  act(() => { r = create(<CategoryPanel category={media} renderMedia={(path: string) => <MediaProbe path={path} />} />); });
  const probe = r.root.findByType(MediaProbe);
  expect(probe.props.path).toBe("/api/v1/attachments/abc.jpg");
  // The row holding the question and the media stacks them (no row direction).
  const row = flat(r.toJSON()).find((node) => node.children?.some((child: any) => text(child) === "Narration image") && flat(node).some((n) => n.props?.testID === "media-probe"));
  expect(row).toBeDefined();
  expect(row.props.style.flexDirection).toBeUndefined();
});

function MediaProbe(_props: { path: string }) {
  const { View } = require("react-native");
  return <View testID="media-probe" />;
}
