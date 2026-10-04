// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";

import type { InstrumentDefinition } from "../src/index.js";
import { resolveUiMessages, WHO_VA_BUILT_IN_UI_TRANSLATIONS } from "../src/index.js";
import hindi from "../src/languages/hi.js";
import { defineWhoVaElement, type WhoVaFormElement } from "../src/web-component.js";

// A host-translated instrument, as DigitVA builds one: Hindi text already in
// the instrument, no UI strings supplied (digitva-5mu).
const instrument: InstrumentDefinition = {
  id: "host-ui-translations-test",
  title: "Host UI translations test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "s", sourceRow: 1, order: 1, label: { en: "Section", hi: "खंड" } }],
  questions: [
    {
      name: "death_date",
      order: 1,
      sourceRow: 2,
      sourceType: "date",
      dataType: "date",
      control: "date",
      label: { en: "Date of death", hi: "मृत्यु की तारीख" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["s"]
    }
  ]
};

afterEach(() => document.body.replaceChildren());

async function mount(tag: string, configure: (element: WhoVaFormElement) => void): Promise<WhoVaFormElement> {
  defineWhoVaElement(tag);
  const element = document.createElement(tag) as WhoVaFormElement;
  element.instrument = instrument;
  element.setAttribute("locale", "hi");
  configure(element);
  document.body.append(element);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return element;
}

function ariaLabels(element: HTMLElement): string[] {
  return [...element.querySelectorAll("[aria-label]")].map((node) => node.getAttribute("aria-label") ?? "");
}

describe("host-supplied instrument UI strings", () => {
  it("uses the built-in pack for the locale when the host passes none", async () => {
    const element = await mount("who-va-host-ui-default-test", () => undefined);

    expect(element.textContent).toContain("मृत्यु की तारीख");
    expect(element.textContent).toContain("अनुभाग");
    expect(element.textContent).toContain("दिन-माह-वर्ष (DD-MMM-YYYY)");
    expect(ariaLabels(element)).toContain("जवाब सेव करें");
    expect(ariaLabels(element)).not.toContain("Save draft");
    const issue = element.validate().issues.find((item) => item.question === "death_date");
    expect(issue?.message).toBe("मृत्यु की तारीख आवश्यक है");
  });

  it("lets the host override strings, and an explicit empty set keeps English", async () => {
    const overridden = await mount("who-va-host-ui-override-test", (element) => {
      element.uiTranslations = { hi: { saveDraft: "ड्राफ़्ट रखें" } };
    });
    expect(ariaLabels(overridden)).toContain("ड्राफ़्ट रखें");
    // A supplied set replaces the built-in pack; its gaps are English.
    expect(overridden.textContent).toContain("DD-MMM-YYYY, for example 16-Jul-1986");

    overridden.uiTranslations = {};
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(ariaLabels(overridden)).toContain("Save draft");

    overridden.uiTranslations = undefined;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(ariaLabels(overridden)).toContain("जवाब सेव करें");
  });

  it("falls back to English per string the built-in pack lacks", () => {
    const messages = resolveUiMessages("hi-IN", WHO_VA_BUILT_IN_UI_TRANSLATIONS);
    expect(messages.requiredShort).toBe("यह प्रश्न आवश्यक है।");
    expect(WHO_VA_BUILT_IN_UI_TRANSLATIONS.hi?.scanBarcode).toBeUndefined();
    expect(messages.scanBarcode).toBe("Scan");
    // A locale with no pack at all (Kannada) is English throughout.
    expect(resolveUiMessages("kn", WHO_VA_BUILT_IN_UI_TRANSLATIONS).saveDraft).toBe("Save draft");
    // The language file and the built-in pack are one object, not two copies.
    expect(hindi.ui).toBe(WHO_VA_BUILT_IN_UI_TRANSLATIONS.hi);
  });
});
