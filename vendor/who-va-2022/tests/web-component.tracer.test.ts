// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createInsecureWhoVaBrowserDefaults,
  defineWhoVaElement,
  type WhoVaFormElement
} from "../src/web-component.js";
import type { WhoVaPlatformServices } from "../src/web.js";

afterEach(() => {
  document.body.replaceChildren();
  localStorage.clear();
});

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
    expect(element.textContent).toContain("(Id10010) Name of VA interviewer");
    expect(element.textContent).not.toContain("(Id10010) [Name of VA interviewer]");
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
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

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
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

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
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));
    element.setData({ Id10010: "Autosaved interviewer" });

    const next = [...element.querySelectorAll('[role="button"]')].find(
      (button) => button.textContent === "Next"
    );
    next?.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => expect(savedDraft?.data.Id10010).toBe("Autosaved interviewer"));
  });
});
