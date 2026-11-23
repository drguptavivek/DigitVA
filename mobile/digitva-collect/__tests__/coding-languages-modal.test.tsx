import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ApiError } from "../src/api";
import { CodingLanguagesModal } from "../src/workspace/CodingLanguagesModal";
import type { JsonRequester } from "../src/workspace/api";

const profile = {
  languages: ["hindi", "retired"],
  available_languages: [{ code: "english", name: "English" }, { code: "hindi", name: "Hindi" }],
};

async function render(request: JsonRequester, onSaved = jest.fn(), onClose = jest.fn()) {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<CodingLanguagesModal request={request} onSaved={onSaved} onClose={onClose} />); });
  return tree;
}

const byId = (tree: ReactTestRenderer, id: string) => tree.root.find((node) => node.props.testID === id && typeof node.props.onPress === "function");
const has = (tree: ReactTestRenderer, id: string) => tree.root.findAll((node) => node.props.testID === id).length > 0;

describe("CodingLanguagesModal", () => {
  it("ticks the coder's active languages and saves the chosen codes", async () => {
    const request = jest.fn<ReturnType<JsonRequester>, Parameters<JsonRequester>>(async (path) =>
      path === "/api/v1/profile/" ? profile : { message: "Coding languages updated.", languages: ["english", "hindi"] });
    const onSaved = jest.fn();
    const tree = await render(request, onSaved);
    expect(byId(tree, "coding-language-hindi").props.accessibilityState.checked).toBe(true);
    expect(byId(tree, "coding-language-english").props.accessibilityState.checked).toBe(false);
    await act(async () => { byId(tree, "coding-language-english").props.onPress(); });
    await act(async () => { byId(tree, "coding-languages-save").props.onPress(); });
    // The inactive "retired" is not sent back; the order is the server's list.
    expect(request).toHaveBeenLastCalledWith("/api/v1/profile/languages", { method: "PATCH", json: { languages: ["english", "hindi"] } });
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("disables Save with the server's message when nothing is ticked", async () => {
    const request = jest.fn(async () => profile);
    const tree = await render(request);
    expect(has(tree, "coding-languages-none")).toBe(false);
    await act(async () => { byId(tree, "coding-language-hindi").props.onPress(); });
    expect(has(tree, "coding-languages-none")).toBe(true);
    expect(JSON.stringify(tree.toJSON())).toContain("At least one language must be selected.");
    expect(byId(tree, "coding-languages-save").props.disabled).toBe(true);
  });

  it("shows a failed save inline and stays open", async () => {
    const request = jest.fn(async (path: string) => {
      if (path === "/api/v1/profile/") return profile;
      throw new ApiError(0, "network_error");
    });
    const onSaved = jest.fn();
    const tree = await render(request, onSaved);
    await act(async () => { byId(tree, "coding-languages-save").props.onPress(); });
    expect(onSaved).not.toHaveBeenCalled();
    expect(tree.root.findAll((node) => node.props.accessibilityRole === "alert").length).toBeGreaterThan(0);
  });

  it("refuses a server without available_languages", async () => {
    const tree = await render(jest.fn(async () => ({ languages: ["hindi"] })));
    expect(has(tree, "coding-languages-save")).toBe(false);
    expect(tree.root.findAll((node) => node.props.accessibilityRole === "alert").length).toBeGreaterThan(0);
  });
});

it("names a language once when its code only repeats the name, and keeps a differing code", async () => {
  const request = jest.fn(async () => ({ languages: ["english"], available_languages: [{ code: "english", name: "English" }, { code: "or", name: "Odia" }] })) as unknown as JsonRequester;
  const tree = await render(request);
  const text = JSON.stringify(tree.toJSON());
  expect(text).toContain("English");
  expect(text).not.toContain("English (english)");
  expect(text).toContain("Odia (or)");
});
