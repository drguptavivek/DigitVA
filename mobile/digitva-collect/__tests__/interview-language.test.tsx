import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockChoose = jest.fn(async () => undefined);
const mockBootstrap = {csrf: {header: "X-CSRFToken", token: "csrf"}, links: {intakeDrafts: "/api/v1/intake/drafts", intakeCases: "/api/v1/intake/cases"}};
let mockParams: {draftId?: string; deathId?: string} = {draftId: "draft-1"};
const mockRouter = {back: jest.fn(), replace: jest.fn()};
jest.mock("expo-router", () => ({useRouter: () => mockRouter, useLocalSearchParams: () => mockParams}));
jest.mock("../src/AppState", () => ({useAppState: () => ({bootstrap: mockBootstrap, chooseUiLocale: mockChoose})}));
jest.mock("../src/theme", () => ({useTheme: () => ({colors: {}})}));
jest.mock("../src/ui", () => ({Button: () => null, useUiStyles: () => ({})}));
jest.mock("../src/web/common", () => ({WebShell: ({children}: {children: ReactNode}) => <>{children}</>, browserErrorText: (error: Error) => error.message}));
jest.mock("../src/client/api", () => ({
  ...jest.requireActual("../src/client/api"),
  getIntakeContext: jest.fn(async () => ({})),
  getDraft: jest.fn(), getProjectFormOptions: jest.fn(), getInstrumentTranslations: jest.fn(), getCaseDetail: jest.fn(), startDraft: jest.fn(), submitDraft: jest.fn()
}));
jest.mock("../src/client/serverDraftStore", () => ({ServerDraftStore: jest.fn().mockImplementation(() => ({load: jest.fn(async () => ({})), flush: jest.fn(async () => undefined), getLocaleMetadata: () => ({}), getServerUpdatedAt: () => "revision-1", restoreLocaleMetadata: jest.fn(), setLocaleMetadata: jest.fn()}))}));
jest.mock("@drguptavivek/who-2022-va", () => ({createWhoVa2022Instrument: () => ({id: "WHO", version: "1", sections: [], questions: []})}), {virtual: true});
jest.mock("@drguptavivek/who-2022-va/web", () => ({WhoVaForm: () => null}), {virtual: true});

import InterviewScreen from "../src/web/InterviewScreen";
import { ClientApiError, getCaseDetail, getDraft, getProjectFormOptions, getInstrumentTranslations, startDraft, submitDraft } from "../src/client/api";
import { ServerDraftStore } from "../src/client/serverDraftStore";
import { WhoVaForm } from "@drguptavivek/who-2022-va/web";
import { t, setUiLocale } from "../src/i18n";

jest.mock("../src/prefill", () => ({initialDataFromPrefill: () => ({})}));

beforeEach(() => {
  window.addEventListener = jest.fn();
  window.removeEventListener = jest.fn();
  jest.clearAllMocks();
  mockParams = {draftId: "draft-1"};
  setUiLocale("en");
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P", updated_at: "revision-1"}, envelope: {locale: "hi", translation_version: 7}, prefill: {}});
  (getProjectFormOptions as jest.Mock).mockResolvedValue({form_types: [{instrument_code: "WHO_2022_VA", is_default: true}], available_locales: [{code: "en", label: "English"}], translation_versions: {hi: 9}});
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(404, "not_found"));
  mockRouter.replace.mockClear();
});

it("starts a later-page case using its authorized detail by id", async () => {
  mockParams = {deathId: "later-page"};
  (getCaseDetail as jest.Mock).mockResolvedValue({case: {project_id: "P2", site_id: "S2", org_unit_id: "U2", prefill: {}}});
  (startDraft as jest.Mock).mockResolvedValue({draft: {draft_id: "new-draft"}});
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P2"}, envelope: {locale: "en"}, prefill: {}});
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(getCaseDetail).toHaveBeenCalledWith("/api/v1/intake/cases", "later-page", mockBootstrap.csrf);
  expect(startDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", {project_id: "P2", site_id: "S2", org_unit_id: "U2", death_id: "later-page"}, mockBootstrap.csrf);
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("does not start an interview when case detail access is denied", async () => {
  mockParams = {deathId: "unavailable"};
  (getCaseDetail as jest.Mock).mockRejectedValue(new ClientApiError(404, "not_found"));
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(startDraft).not.toHaveBeenCalled();
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("keeps saved locale/version when its translation is missing or disabled", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  const form = tree.root.findByType(WhoVaForm);
  expect(form.props.locale).toBe("hi");
  expect(JSON.stringify(tree.toJSON())).toContain(t("questionnaireEnglishFallback"));
  expect(ServerDraftStore).toHaveBeenCalledWith(expect.objectContaining({locale: "hi", translationVersion: 7}));
  await act(async () => {form.props.onDraftSaved();});
  expect(JSON.stringify(tree.toJSON())).toContain(t("questionnaireEnglishFallback"));
  await act(async () => tree.unmount());
});

it.each([401, 403])("blocks access for translation HTTP %s", async status => {
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(status, "forbidden"));
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  expect(ServerDraftStore).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain(`HTTP ${status}`);
  await act(async () => tree.unmount());
});

it.each([429, 500])("surfaces translation HTTP %s without replacing saved language metadata", async status => {
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(status, "temporary_failure"));
  const savedDraft = {draft: {project_id: "P"}, envelope: {locale: "hi", translation_version: 7}, prefill: {}};
  (getDraft as jest.Mock).mockResolvedValue(savedDraft);
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  expect(ServerDraftStore).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain(`HTTP ${status} temporary_failure`);
  expect(savedDraft.envelope).toEqual({locale: "hi", translation_version: 7});
  await act(async () => tree.unmount());
});

it("removes an already rendered form when a language request loses permission", async () => {
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P"}, envelope: {locale: "en"}, prefill: {}});
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(403, "forbidden"));
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findByType(WhoVaForm)).toBeDefined();
  const shell = tree.root.findByType(jest.requireMock("../src/web/common").WebShell);
  await act(async () => {await shell.props.headerAction.props.onSelect("hi");});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("blocks a deep-linked new interview when the valid case detail omits prefill", async () => {
  mockParams = { deathId: "held-by-other-worker" };
  (getCaseDetail as jest.Mock).mockResolvedValue({ case: { project_id: "P2", site_id: "S2", informant: { name: "Contact" } } });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  expect(getCaseDetail).toHaveBeenCalled();
  expect(startDraft).not.toHaveBeenCalled();
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("returns to collection after a normal 201 draft submission", async () => {
  (submitDraft as jest.Mock).mockResolvedValue({ va_sid: "sid-1", draft: { draft_id: "draft-1", project_id: "P", site_id: "S" }, superseded: false, validation_err: [] });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(submitDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", "draft-1", { valid: true, issues: [] }, mockBootstrap.csrf, "revision-1");
  expect(mockRouter.replace).toHaveBeenCalledWith("/collection");
  await act(async () => tree.unmount());
});

it("returns to collection with a notice after a superseded 200 response", async () => {
  (submitDraft as jest.Mock).mockResolvedValue({ va_sid: null, draft: { draft_id: "draft-1", project_id: "P", site_id: "S" }, superseded: true, validation_err: null });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/collection", params: { superseded: "1" } });
  await act(async () => tree.unmount());
});

it("stays on the interview when the submit acknowledgement is malformed", async () => {
  (submitDraft as jest.Mock).mockRejectedValue(new ClientApiError(200, "malformed_response"));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("HTTP 200 malformed_response");
  await act(async () => tree.unmount());
});

it("shows the server stale-draft explanation and stays on the interview", async () => {
  (submitDraft as jest.Mock).mockRejectedValue(new ClientApiError(409, "draft_stale", undefined, undefined, {
    error: "This interview was also edited on another device; reload before saving."
  }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("This interview was also edited on another device; reload before saving.");
  await act(async () => tree.unmount());
});
