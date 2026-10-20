// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWhoVaSession, type InstrumentDefinition } from "../src/index.js";
import { WhoVaForm } from "../src/web.js";

// Four pages; pages two to four appear once a name is given, so with no name
// one of four is visible and the form says more sections will come.
const sectionNames = ["one", "two", "three", "four"];
const instrument: InstrumentDefinition = {
  id: "footer-test",
  title: "Footer test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: sectionNames.map((name, index) => ({
    name,
    sourceRow: index * 2 + 1,
    order: index + 1,
    label: { en: name },
    ...(index === 0 ? {} : { relevant: { source: "${name} = 'Amina'" } })
  })),
  questions: sectionNames.map((section, index) => ({
    name: index === 0 ? "name" : `detail_${section}`,
    order: index + 1,
    sourceRow: index * 2 + 2,
    sourceType: "text",
    dataType: "string",
    control: "text",
    label: { en: index === 0 ? "Name" : `Detail ${section}` },
    hint: {},
    guidance: {},
    required: false,
    readOnly: false,
    constraintMessage: {},
    sectionPath: [section]
  }))
};

afterEach(() => {
  document.body.replaceChildren();
  history.replaceState(null, "");
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  root.render(element);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { container, root };
}

describe("form footer", () => {
  it("renders Back, Save draft, Preview, Next as one row of equal-width buttons", async () => {
    const session = createWhoVaSession(instrument, { initialData: { name: "Amina" } });
    expect(session.next().advanced).toBe(true);
    const save = vi.fn(async () => undefined);
    const { container, root } = await mount(
      <WhoVaForm
        instrument={instrument}
        session={session}
        draftId="d1"
        draftStore={{ save, load: async () => undefined }}
      />
    );

    const footer = container.querySelector<HTMLElement>('[data-testid="form-footer"]');
    expect(footer).not.toBeNull();
    const buttons = Array.from(footer!.children) as HTMLElement[];
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Back",
      "Save draft",
      "Preview answers",
      "Next"
    ]);
    expect(getComputedStyle(footer!).flexDirection).toBe("row");
    expect(getComputedStyle(footer!).flexWrap).toBe("nowrap");
    for (const button of buttons) {
      const style = getComputedStyle(button);
      expect(style.flexGrow).toBe("1");
      expect(style.flexBasis).toMatch(/^0(%|px)?$/);
      expect(style.minHeight).toBe("44px");
    }

    const footerButton = (index: number) =>
      container.querySelector('[data-testid="form-footer"]')!.children[index] as HTMLElement;
    // The session starts on page two, so Back is enabled and returns to one.
    expect(buttons[0]!.getAttribute("aria-disabled")).toBeNull();
    footerButton(0).click();
    await vi.waitFor(() => expect(session.getSnapshot().currentSection.name).toBe("one"));
    footerButton(3).click();
    await vi.waitFor(() => expect(session.getSnapshot().currentSection.name).toBe("two"));

    // Save draft is enabled once the mount-time restore settles and no save is in flight.
    await vi.waitFor(() => expect(footerButton(1).getAttribute("aria-disabled")).toBeNull());
    save.mockClear();
    footerButton(1).click();
    await vi.waitFor(() => expect(save).toHaveBeenCalled());

    footerButton(2).click();
    await vi.waitFor(() => expect(container.textContent).toContain("Answer preview"));
    root.unmount();
  });

  it("omits the more-sections note when the host blanks it", async () => {
    const session = createWhoVaSession(instrument);
    const shown = await mount(<WhoVaForm instrument={instrument} session={session} />);
    // Assert the subject exists first: section two is still hidden, so the note shows.
    expect(shown.container.textContent).toContain("More sections appear as you answer");
    shown.root.unmount();

    const hidden = await mount(
      <WhoVaForm
        instrument={instrument}
        session={createWhoVaSession(instrument)}
        uiTranslations={{ en: { moreSectionsNote: "" } }}
      />
    );
    expect(hidden.container.textContent).toContain("Name");
    expect(hidden.container.textContent).not.toContain("More sections appear as you answer");
    hidden.root.unmount();
  });
});
