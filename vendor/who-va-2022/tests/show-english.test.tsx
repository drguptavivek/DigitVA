// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { InstrumentDefinition } from "../src/index.js";
import { defineWhoVaElement, type WhoVaFormElement } from "../src/web-component.js";
import { WhoVaForm } from "../src/web.js";

// A translated label, hint and choice, one untranslated choice, and nothing
// else, so every English line the form draws is one of these.
const instrument: InstrumentDefinition = {
  id: "show-english-test",
  title: "Show English test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "s", sourceRow: 1, order: 1, label: { en: "Section", hi: "खंड" } }],
  questions: [
    {
      name: "fever",
      order: 1,
      sourceRow: 2,
      sourceType: "select_one yes_no",
      dataType: "string",
      control: "singleChoice",
      label: { en: "Did she have a <b>fever</b>?", hi: "क्या उसे <b>बुखार</b> था?" },
      hint: { en: "Ask the respondent.", hi: "उत्तरदाता से पूछें।" },
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      choices: [
        { value: "yes", sourceRow: 3, label: { en: "Yes", hi: "हाँ" } },
        { value: "dk", sourceRow: 4, label: { en: "Doesn't know" } }
      ],
      sectionPath: ["s"]
    }
  ]
};

function englishSpans(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[lang="en"]')].map((node) => node.textContent ?? "");
}

async function renderForm(locale: string, showEnglish?: boolean) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  root.render(
    <WhoVaForm
      instrument={instrument}
      locale={locale}
      {...(showEnglish === undefined ? {} : { showEnglish })}
    />
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { container, root };
}

afterEach(() => document.body.replaceChildren());

describe("show-english", () => {
  it("shows the English beneath a translated label, hint and choice", async () => {
    const { container, root } = await renderForm("hi", true);

    // Present first: the translation is what is displayed.
    expect(container.textContent).toContain("क्या उसे बुखार था?");
    expect(container.textContent).toContain("हाँ");
    const english = englishSpans(container);
    expect(english).toContain("Did she have a fever?");
    expect(english).toContain("Ask the respondent.");
    expect(english).toContain("Yes");
    // Rendered through RichText: the markup is a styled span, not literal tags.
    expect(container.textContent).not.toContain("<b>");
    root.unmount();
  });

  it("draws no English line for an untranslated string", async () => {
    const { container, root } = await renderForm("hi", true);
    expect(container.textContent).toContain("Doesn't know");
    expect(englishSpans(container)).not.toContain("Doesn't know");
    root.unmount();
  });

  it("draws no English line when show-english is unset", async () => {
    const { container, root } = await renderForm("hi");
    expect(container.textContent).toContain("क्या उसे बुखार था?");
    expect(englishSpans(container)).toEqual([]);
    root.unmount();
  });

  it("draws no English line when the locale is English", async () => {
    const { container, root } = await renderForm("en", true);
    expect(container.textContent).toContain("Did she have a fever?");
    expect(englishSpans(container)).toEqual([]);
    root.unmount();
  });

  it("is driven by the web component's show-english attribute", async () => {
    defineWhoVaElement("who-va-show-english-test");
    const element = document.createElement("who-va-show-english-test") as WhoVaFormElement;
    element.instrument = instrument;
    element.setAttribute("locale", "hi");
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(element.textContent).toContain("क्या उसे बुखार था?");
    expect(englishSpans(element)).toEqual([]);

    element.setAttribute("show-english", "");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(englishSpans(element)).toContain("Did she have a fever?");
  });
});
