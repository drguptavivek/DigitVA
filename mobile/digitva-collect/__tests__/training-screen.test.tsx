import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockPush = jest.fn();
const mockReload = jest.fn(async () => undefined);
const mockGetMe = jest.fn();
const mockStart = jest.fn();
let mockBootstrap: any;

jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: mockBootstrap, reload: mockReload }),
  TrainingScope: ({ children }: { children: React.ReactNode }) => children,
}));
jest.mock("../src/i18n", () => ({ t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key} ${JSON.stringify(vars)}` : key) }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", { label, onPress }),
    useUiStyles: () => ({ error: {}, muted: {}, text: {}, headline: {}, card: {} }),
  };
});
jest.mock("../src/web/common", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    WebShell: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("web-shell", null, children),
    browserErrorText: () => "server-error",
  };
});
jest.mock("../src/web/roleHome", () => ({ openServerPage: jest.fn() }));
jest.mock("../src/web/DeathsList", () => ({ DeathsListPanel: ({ headerAction }: { headerAction?: React.ReactNode }) => require("react").createElement("deaths-list", null, headerAction) }));
jest.mock("../src/web/SupervisionPanel", () => ({ SupervisionPanel: () => require("react").createElement("supervision-panel") }));
jest.mock("../src/web/LazyInterviewScreen", () => ({ DeathRegistrationScreen: () => require("react").createElement("registration") }));
jest.mock("../src/training", () => ({
  ...jest.requireActual("../src/training"),
  getTrainingMe: (...args: unknown[]) => mockGetMe(...args),
  startTraining: (...args: unknown[]) => mockStart(...args),
}));

import { TrainingInterviewScreen, TrainingOverviewScreen, TrainingRegisterScreen } from "../src/web/TrainingScreen";

const part = (role: string, extra: object = {}) => ({ role, coder_slot: null, onboarded_at: null, session_code: "S001", session_name: "Training one", ...extra });
const me = (parts: object[], pending = true, areas = ["coding"]) => ({ project_id: "TRN01", areas, pending, participations: parts });

async function render(element: React.ReactElement) {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
    await Promise.resolve();
    await Promise.resolve();
  });
  return renderer;
}
const text = (renderer: ReactTestRenderer) => JSON.stringify(renderer.toJSON());
const button = (renderer: ReactTestRenderer, label: string) => renderer.root.findAll((node) => node.type === ("button" as never) && String(node.props.label).startsWith(label));

describe("Training overview", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBootstrap = { user: { user_id: "u", name: "U" }, csrf: { header: "X-CSRFToken", token: "csrf" }, access: { training: { areas: ["coding"], pending: true } } };
  });

  test("shows the confidentiality notice, the session and the coder slot, with Start while pending", async () => {
    mockGetMe.mockResolvedValue(me([part("coder", { coder_slot: 4 })]));
    const renderer = await render(<TrainingOverviewScreen />);
    const shown = text(renderer);
    for (const key of ["trainingConfidentialCases", "trainingConfidentialMedia", "trainingSession", "S001", "Training one", "trainingCoderSlot"]) expect(shown).toContain(key);
    expect(button(renderer, "trainingStart")).toHaveLength(1);
    expect(mockGetMe).toHaveBeenCalledWith(mockBootstrap.csrf);
    await act(async () => { renderer.unmount(); });
  });

  test("Start records the onboarding through the API, reloads access and hides itself", async () => {
    mockGetMe.mockResolvedValue(me([part("coder")]));
    mockStart.mockResolvedValue(me([part("coder", { onboarded_at: "2026-10-23T00:00:00Z" })], false));
    const renderer = await render(<TrainingOverviewScreen />);
    await act(async () => { button(renderer, "trainingStart")[0].props.onPress(); await Promise.resolve(); });
    expect(mockStart).toHaveBeenCalledWith(mockBootstrap.csrf);
    expect(mockReload).toHaveBeenCalled();
    expect(button(renderer, "trainingStart")).toHaveLength(0);
    expect(text(renderer)).toContain("trainingStarted");
    await act(async () => { renderer.unmount(); });
  });

  test("a refused Start shows the error and keeps the button", async () => {
    mockGetMe.mockResolvedValue(me([part("coder")]));
    mockStart.mockRejectedValue(new Error("no"));
    const renderer = await render(<TrainingOverviewScreen />);
    await act(async () => { button(renderer, "trainingStart")[0].props.onPress(); await Promise.resolve(); });
    expect(text(renderer)).toContain("server-error");
    expect(button(renderer, "trainingStart")).toHaveLength(1);
    await act(async () => { renderer.unmount(); });
  });

  test("opens each area it holds; nothing to open or start without a participation", async () => {
    mockGetMe.mockResolvedValue(me([part("coder"), part("interviewer")], false, ["interview", "coding"]));
    const renderer = await render(<TrainingOverviewScreen />);
    expect(button(renderer, "trainingOpen")).toHaveLength(2);
    button(renderer, "trainingOpen")[1].props.onPress();
    expect(mockPush).toHaveBeenCalledWith("/training/coding");
    expect(button(renderer, "trainingStart")).toHaveLength(0);
    await act(async () => { renderer.unmount(); });

    mockGetMe.mockResolvedValue(me([], false, []));
    const none = await render(<TrainingOverviewScreen />);
    expect(text(none)).toContain("trainingNone");
    expect(text(none)).not.toContain("trainingConfidentialCases");
    expect(button(none, "trainingStart")).toHaveLength(0);
    await act(async () => { none.unmount(); });
  });
});

describe("Training interview area", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBootstrap = { user: { user_id: "u", name: "U" }, csrf: { header: "X-CSRFToken", token: "csrf" }, access: {} };
  });

  test("lists the checklist lines of the roles held and the work list; a supervisor also gets the supervision panel", async () => {
    mockGetMe.mockResolvedValue(me([part("death_reporter"), part("interview_supervisor")], false, ["interview"]));
    const renderer = await render(<TrainingInterviewScreen />);
    const shown = text(renderer);
    expect(shown).toContain("trainingInterviewDeathReporter");
    expect(shown).toContain("trainingInterviewSupervisor");
    expect(shown).not.toContain("trainingInterviewInterviewer");
    expect(renderer.root.findAllByType("deaths-list" as never)).toHaveLength(1);
    expect(renderer.root.findAllByType("supervision-panel" as never)).toHaveLength(1);
    button(renderer, "trainingReportDeath")[0].props.onPress();
    expect(mockPush).toHaveBeenCalledWith("/training/register");
    await act(async () => { renderer.unmount(); });
  });

  test("an interviewer without the supervisor role gets no supervision panel", async () => {
    mockGetMe.mockResolvedValue(me([part("interviewer")], false, ["interview"]));
    const renderer = await render(<TrainingInterviewScreen />);
    expect(renderer.root.findAllByType("supervision-panel" as never)).toHaveLength(0);
    expect(renderer.root.findAllByType("deaths-list" as never)).toHaveLength(1);
    await act(async () => { renderer.unmount(); });
  });

  test("the registration route renders the ordinary registration screen", async () => {
    const renderer = await render(<TrainingRegisterScreen />);
    expect(renderer.root.findAllByType("registration" as never)).toHaveLength(1);
    await act(async () => { renderer.unmount(); });
  });
});
