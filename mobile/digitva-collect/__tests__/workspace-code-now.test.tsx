import React from "react";
import { Alert } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ApiError } from "../src/api";
import { CodeNowButton } from "../src/workspace/CodeNowButton";
import type { WorkspaceApi } from "../src/workspace/api";

function makeApi(overrides: Partial<WorkspaceApi> = {}): WorkspaceApi {
  return {
    codeOwnSubmission: jest.fn(),
    releaseCoding: jest.fn().mockResolvedValue({ va_sid: "sid", workflow_state: "ready_for_coding" }),
    ...overrides,
  } as unknown as WorkspaceApi;
}

function button(root: ReactTestInstance, label: string) {
  return root.findAll((node) => node.props.accessibilityRole === "button" && node.props.accessibilityLabel === label)[0];
}

async function render(api: WorkspaceApi, onOpen = jest.fn(), onAccessLost = jest.fn()) {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<CodeNowButton api={api} vaSid="sid" onOpen={onOpen} onAccessLost={onAccessLost} />);
  });
  return { renderer, onOpen, onAccessLost };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("CodeNowButton", () => {
  test("does not allocate until pressed and opens the submitted case after success", async () => {
    const api = makeApi({ codeOwnSubmission: jest.fn().mockResolvedValue({ va_sid: "sid" }) });
    const screen = await render(api);
    expect(api.codeOwnSubmission).not.toHaveBeenCalled();
    await act(async () => { button(screen.renderer.root, "Code this case now")?.props.onPress(); await Promise.resolve(); });
    await settle();
    expect(api.codeOwnSubmission).toHaveBeenCalledWith("sid");
    expect(screen.onOpen).toHaveBeenCalledWith("sid");
    await act(async () => { screen.renderer.unmount(); });
  });

  test("ignores duplicate taps in the same turn and reports any 403 as access loss", async () => {
    const api = makeApi({ codeOwnSubmission: jest.fn().mockRejectedValue(new ApiError(403, "terms_required")) });
    const screen = await render(api);
    const target = button(screen.renderer.root, "Code this case now");
    await act(async () => { target?.props.onPress(); target?.props.onPress(); await Promise.resolve(); });
    await settle();
    expect(api.codeOwnSubmission).toHaveBeenCalledTimes(1);
    expect(screen.onAccessLost).toHaveBeenCalledTimes(1);
    await act(async () => { screen.renderer.unmount(); });
  });

  test("retries not-ready at most twice and then reports that the case is still preparing", async () => {
    jest.useFakeTimers();
    const api = makeApi({
      codeOwnSubmission: jest.fn()
        .mockRejectedValueOnce(new ApiError(409, "not_ready"))
        .mockRejectedValueOnce(new ApiError(409, "not_ready"))
        .mockRejectedValueOnce(new ApiError(409, "not_ready")),
    });
    const screen = await render(api);
    await act(async () => { button(screen.renderer.root, "Code this case now")?.props.onPress(); await Promise.resolve(); });
    await settle();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await act(async () => { jest.advanceTimersByTime(2_000); await Promise.resolve(); await Promise.resolve(); });
      await settle();
    }
    expect(api.codeOwnSubmission).toHaveBeenCalledTimes(3);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain("Still preparing");
    await act(async () => { screen.renderer.unmount(); });
    jest.useRealTimers();
  });

  test("hides a case held by another coder", async () => {
    const api = makeApi({ codeOwnSubmission: jest.fn().mockRejectedValue(new ApiError(409, "held_by_another")) });
    const screen = await render(api);
    await act(async () => { button(screen.renderer.root, "Code this case now")?.props.onPress(); await Promise.resolve(); });
    await settle();
    expect(button(screen.renderer.root, "Code this case now")).toBeUndefined();
    await act(async () => { screen.renderer.unmount(); });
  });

  test("ignores an old allocation after the account-bound API and case change", async () => {
    let resolveFirst!: (value: { va_sid: string }) => void;
    const firstApi = makeApi({ codeOwnSubmission: jest.fn(() => new Promise((resolve) => { resolveFirst = resolve; })) });
    const nextApi = makeApi({ codeOwnSubmission: jest.fn().mockResolvedValue({ va_sid: "next-sid" }) });
    const onOpen = jest.fn();
    const screen = await render(firstApi, onOpen);
    await act(async () => { button(screen.renderer.root, "Code this case now")?.props.onPress(); });
    await act(async () => {
      screen.renderer.update(<CodeNowButton api={nextApi} vaSid="next-sid" onOpen={onOpen} onAccessLost={jest.fn()} />);
    });
    await act(async () => { resolveFirst({ va_sid: "sid" }); await Promise.resolve(); });
    expect(onOpen).not.toHaveBeenCalled();
    expect(nextApi.codeOwnSubmission).not.toHaveBeenCalled();
    await act(async () => { screen.renderer.unmount(); });
  });

  test("requires explicit confirmation before releasing an existing allocation", async () => {
    const api = makeApi({
      codeOwnSubmission: jest.fn()
        .mockRejectedValueOnce(new ApiError(403, "allocation_exists"))
        .mockResolvedValueOnce({ va_sid: "sid" }),
    });
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    const screen = await render(api);
    await act(async () => { button(screen.renderer.root, "Code this case now")?.props.onPress(); await Promise.resolve(); });
    await settle();
    expect(api.releaseCoding).not.toHaveBeenCalled();
    await act(async () => { button(screen.renderer.root, "Release my other case and continue")?.props.onPress(); });
    const actions = alert.mock.calls[0]?.[2];
    expect(alert.mock.calls[0]?.[1]).toContain("unfinished Step 1 work");
    await act(async () => { actions?.find((action) => action.text === "Release and continue")?.onPress?.(); await Promise.resolve(); await Promise.resolve(); });
    await settle();
    expect(api.releaseCoding).toHaveBeenCalledTimes(1);
    expect(api.codeOwnSubmission).toHaveBeenCalledTimes(2);
    expect(screen.onOpen).toHaveBeenCalledWith("sid");
    alert.mockRestore();
    await act(async () => { screen.renderer.unmount(); });
  });
});
