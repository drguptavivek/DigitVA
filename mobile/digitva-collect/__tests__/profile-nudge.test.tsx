/** @jest-environment jsdom */
import React, { act } from "react";

let mockBootstrap: unknown;
const mockRequest = jest.fn();

jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/api", () => ({ requestClientJson: (...args: unknown[]) => mockRequest(...args) }));
jest.mock("../src/theme", () => ({ useTheme: () => ({ ui: {
  warning: "#fff", warningBorder: "#990", warningForeground: "#330",
} }) }));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRoot } = require("react-dom/client") as { createRoot: (el: Element) => { render(node: React.ReactNode): void; unmount(): void } };
import ProfileNudge from "../src/web/ProfileNudge.web";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const bootstrap = (userId = "u1") => ({
  user: { user_id: userId, name: "Worker" },
  csrf: { header: "X-CSRFToken", token: "csrf-token" },
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  mockBootstrap = bootstrap();
  mockRequest.mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function mount() {
  await act(async () => {
    root.render(<ProfileNudge />);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test("shows missing fields with a normal profile link and fetches once for the signed-in shell", async () => {
  mockRequest.mockResolvedValue({ profile_nudge: true, missing_profile_fields: ["job_title", "sex"] });
  await mount();

  expect(mockRequest).toHaveBeenCalledTimes(1);
  expect(mockRequest).toHaveBeenCalledWith("/api/v1/profile/", { csrf: bootstrap().csrf });
  expect(host.textContent).toContain("Please complete your profile (job title and sex).");
  expect(host.querySelector("a[href='/profile/']")?.textContent).toBe("My Profile");

  await act(async () => { root.render(<ProfileNudge />); await Promise.resolve(); });
  expect(mockRequest).toHaveBeenCalledTimes(1);
});

test("hides the reminder when the profile is complete or the server flag is false", async () => {
  mockRequest.mockResolvedValue({ profile_nudge: false, missing_profile_fields: [] });
  await mount();
  expect(host.textContent).not.toContain("Please complete your profile");

  mockRequest.mockResolvedValue({ profile_nudge: true, missing_profile_fields: [] });
  mockBootstrap = bootstrap("u2");
  await mount();
  expect(host.textContent).not.toContain("Please complete your profile");
});

test("dismisses with the cookie CSRF request and hides only after acknowledgement", async () => {
  mockRequest.mockResolvedValueOnce({ profile_nudge: true, missing_profile_fields: ["year_of_birth"] });
  await mount();
  const dismiss = host.querySelector("[accessibilitylabel='Dismiss profile reminder']") as HTMLElement;

  mockRequest.mockResolvedValueOnce({ profile_nudge: false });
  await act(async () => { dismiss.click(); await Promise.resolve(); });
  expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/profile/nudge/dismiss", {
    method: "POST", csrf: bootstrap().csrf,
  });
  expect(host.textContent).not.toContain("Please complete your profile");
});

test("retains the reminder after a failed dismiss so it can be retried", async () => {
  mockRequest.mockResolvedValueOnce({ profile_nudge: true, missing_profile_fields: ["sex"] });
  await mount();
  const dismiss = () => host.querySelector("[accessibilitylabel='Dismiss profile reminder']")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));

  mockRequest.mockRejectedValueOnce(new Error("offline"));
  await act(async () => { dismiss(); await Promise.resolve(); });
  expect(host.textContent).toContain("Please complete your profile (sex).");

  mockRequest.mockResolvedValueOnce({ profile_nudge: false });
  await act(async () => { dismiss(); await Promise.resolve(); });
  expect(mockRequest).toHaveBeenCalledTimes(3);
  expect(host.textContent).not.toContain("Please complete your profile");
});
