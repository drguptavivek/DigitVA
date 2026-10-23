// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { ENGLISH_UI_MESSAGES } from "../src/i18n.js";
import { createSectionNavigation } from "../src/ui/section-navigation.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const el = (tag: string) =>
  React.forwardRef<HTMLElement, Record<string, unknown>>(({ children, style, testID }, ref) =>
    React.createElement(tag, { ref, "data-testid": testID, "data-style": JSON.stringify(style) }, children as React.ReactNode)
  );

describe("Sections drawer on a phone with system bars", () => {
  it("pads its panel by the bottom and top insets so the last section is reachable", async () => {
    const primitives = { View: el("div"), Text: el("span"), Pressable: el("button"), ScrollView: el("div") };
    const { SectionDrawer } = createSectionNavigation(primitives);
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <SectionDrawer
          items={[{ name: "a", label: "1. A", status: "empty", active: true, depth: 0 }]}
          messages={ENGLISH_UI_MESSAGES}
          moreToCome={false}
          onClose={() => undefined}
          onSelect={() => undefined}
          open
          safeInsets={{ top: 24, bottom: 34 }}
          toggleRef={{ current: null }}
        />
      );
    });
    const style = container.querySelector('[data-testid="section-drawer"]')!.getAttribute("data-style")!;
    expect(style).toContain('"paddingBottom":44');
    expect(style).toContain('"paddingTop":34');
    // The list scrolls inside the panel.
    expect(container.querySelector('[data-testid="section-drawer"] div')).not.toBeNull();
    await act(async () => root.unmount());
  });
});
