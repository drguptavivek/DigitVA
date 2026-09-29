// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createInsecureWhoVaBrowserDefaults,
  defineWhoVaElement,
  type WhoVaFormElement
} from "../src/web-component.js";
import type { WhoVaPlatformServices } from "../src/web.js";
import { whoVa2022Instrument } from "../src/instrument.js";

afterEach(() => {
  document.body.replaceChildren();
  localStorage.clear();
});

// The element only knows it is safe to overwrite a draft once its mount-time
// restore has settled (digitva-ybz); tests that save or autosave wait for
// who-va-ready rather than a fixed tick, or a click against the still-loading
// Save-draft button (disabled until then) would silently do nothing.
function waitForReady(element: WhoVaFormElement): Promise<void> {
  return new Promise((resolve) => element.addEventListener("who-va-ready", () => resolve(), { once: true }));
}

describe("framework-independent web embedding", () => {
  it("does not enable plaintext browser persistence by default", async () => {
    defineWhoVaElement("who-va-secure-default-test");
    const element = document.createElement("who-va-secure-default-test") as WhoVaFormElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    const saveDraft = [...element.querySelectorAll('[role="button"]')].find(
      (button) => button.getAttribute("aria-label") === "Save draft"
    );
    expect(saveDraft?.getAttribute("aria-disabled")).toBe("true");
    expect(localStorage.length).toBe(0);
  });

  it("registers one custom element with imperative data and validation APIs", async () => {
    defineWhoVaElement("who-va-test-form");
    const element = document.createElement("who-va-test-form") as WhoVaFormElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(element.getData().Id10011).toEqual(expect.any(String));
    expect(element.textContent).not.toContain("Once filled in ODK Collect");
    // The WHO code is a chip beside the label, not the label's first word.
    expect(element.querySelector('[data-testid="question-code-Id10010"]')?.textContent).toBe("Id10010");
    expect(element.textContent).toContain("Name of VA interviewer");
    expect(element.textContent).not.toContain("(Id10010)");
    element.setAttribute("hide-question-codes", "");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(element.querySelector('[data-testid="question-code-Id10010"]')).toBeNull();
    element.removeAttribute("hide-question-codes");
    await new Promise((resolve) => setTimeout(resolve, 0));
    element.setData({ Id10010b: "female" });
    expect(element.getData().Id10010b).toBe("female");
    expect(element.validate().valid).toBe(false);
    expect(() => element.setData({ Id10010b: "invalid" })).toThrow(/WHO choice list/);
  });

  it("routes frontend navigation errors through the shared validator", async () => {
    defineWhoVaElement("who-va-validation-test");
    const element = document.createElement("who-va-validation-test") as WhoVaFormElement;
    let validationDetail: unknown;
    element.addEventListener("who-va-validation", (event) => {
      validationDetail = (event as CustomEvent).detail;
    });
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(element.querySelector('[data-testid="question-Id10010"]')).not.toBeNull();
    const next = [...element.querySelectorAll('[role="button"]')].find(
      (button) => button.textContent === "Next"
    );
    expect(next).toBeDefined();
    next?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(validationDetail).toEqual(
      expect.arrayContaining([expect.objectContaining({ question: "Id10010", code: "required" })])
    );
  });

  it("saves the current form as a UUID-addressed local draft", async () => {
    defineWhoVaElement("who-va-draft-test");
    const element = document.createElement("who-va-draft-test") as WhoVaFormElement;
    element.draftStore = createInsecureWhoVaBrowserDefaults().draftStore;
    let savedDraft: { id: string } | undefined;
    element.addEventListener("who-va-draft-saved", (event) => {
      savedDraft = (event as CustomEvent<{ id: string }>).detail;
    });
    const ready = waitForReady(element);
    document.body.append(element);
    await ready;

    const saveDraft = [...element.querySelectorAll('[role="button"]')].find(
      (button) => button.getAttribute("aria-label") === "Save draft"
    );
    saveDraft?.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => expect(savedDraft).toBeDefined());
    expect(savedDraft?.id).toBe(element.getDraftId());
    expect(savedDraft?.id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(JSON.parse(localStorage.getItem(`who-va-2022:draft:${savedDraft?.id}`) ?? "null")).toEqual(
      expect.objectContaining({ id: savedDraft?.id, instrumentId: "va_who_2022" })
    );
  });

  it("uses a host-provided draft store instead of unencrypted localStorage", async () => {
    defineWhoVaElement("who-va-secure-draft-test");
    const element = document.createElement("who-va-secure-draft-test") as WhoVaFormElement;
    const save = vi.fn();
    element.draftStore = { save };
    const ready = waitForReady(element);
    document.body.append(element);
    await ready;

    const saveDraft = [...element.querySelectorAll('[role="button"]')].find(
      (button) => button.getAttribute("aria-label") === "Save draft"
    );
    saveDraft?.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ id: element.getDraftId() }));
    expect(localStorage.length).toBe(0);
  });

  it("accepts host-controlled attachment and recording services before connection", () => {
    defineWhoVaElement("who-va-secure-platform-test");
    const element = document.createElement("who-va-secure-platform-test") as WhoVaFormElement;
    const platform: WhoVaPlatformServices = {
      removeAttachment: vi.fn(async () => undefined),
      resolveAttachmentUri: vi.fn(async () => "secure-app://attachment")
    };

    element.platform = platform;

    expect(element.platform).toBe(platform);
  });

  it("autosaves the latest submission data when Next is pressed", async () => {
    defineWhoVaElement("who-va-autosave-test");
    const element = document.createElement("who-va-autosave-test") as WhoVaFormElement;
    element.draftStore = createInsecureWhoVaBrowserDefaults().draftStore;
    let savedDraft: { data: Record<string, unknown> } | undefined;
    element.addEventListener("who-va-draft-saved", (event) => {
      savedDraft = (event as CustomEvent<{ data: Record<string, unknown> }>).detail;
    });
    const ready = waitForReady(element);
    document.body.append(element);
    await ready;
    element.setData({ Id10010: "Autosaved interviewer" });

    const next = [...element.querySelectorAll('[role="button"]')].find(
      (button) => button.textContent === "Next"
    );
    next?.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => expect(savedDraft?.data.Id10010).toBe("Autosaved interviewer"));
  });
});

describe("section stepper", () => {
  it("lists every visible section, notes that more will appear, and opens no drawer when wide", async () => {
    defineWhoVaElement("who-va-stepper-test");
    const element = document.createElement("who-va-stepper-test") as WhoVaFormElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));
    // jsdom reports no layout, so the form takes its wide layout: a rail, no drawer toggle.
    expect(element.querySelector('[data-testid="section-rail"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="section-drawer-toggle"]')).toBeNull();
    const items = element.querySelectorAll('[data-testid="section-slider-item"]');
    // Three WHO sections before consent, plus DigitVA's always-relevant interview outcome.
    expect(items).toHaveLength(4);
    expect(items[0]?.getAttribute("aria-label")).toBe("1. VA interviewer");
    expect(items[3]?.getAttribute("aria-label")).toBe("4. Interview outcome");
    expect(element.textContent).toContain("More sections appear as you answer");
    element.setData({
      Id10013: "yes",
      Id10019: "male",
      Id10020: "yes",
      Id10021: "1980-01-01",
      Id10022: "yes",
      Id10023_a: "2026-07-17"
    });
    await vi.waitFor(() =>
      expect(element.querySelectorAll('[data-testid="section-slider-item"]').length).toBeGreaterThan(10)
    );
    expect(element.textContent).not.toContain("More sections appear as you answer");
    element.remove();
  });
});

describe("host-supplied instrument after connect", () => {
  it("binds the form to the new session so setData reaches what is shown", async () => {
    defineWhoVaElement("who-va-swap-test");
    const element = document.createElement("who-va-swap-test") as WhoVaFormElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));
    element.instrument = { ...whoVa2022Instrument };
    await new Promise((resolve) => setTimeout(resolve, 0));
    element.setData({
      Id10013: "yes",
      Id10019: "male",
      Id10020: "yes",
      Id10021: "1980-01-01",
      Id10022: "yes",
      Id10023_a: "2026-07-17"
    });
    await vi.waitFor(() =>
      expect(element.querySelectorAll('[data-testid="section-slider-item"]').length).toBeGreaterThan(10)
    );
    element.remove();
  });
});
