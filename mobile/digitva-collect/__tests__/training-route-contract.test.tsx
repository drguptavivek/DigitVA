import React from "react";

let mockParams: Record<string, string | string[]> = {};

jest.mock("expo-router", () => ({
  Redirect: (props: { href: unknown }) => require("react").createElement("redirect", props),
  useLocalSearchParams: () => mockParams,
}));
jest.mock("react-native", () => {
  return { Platform: { OS: "web" } };
});
jest.mock("../src/browserScreens", () => ({
  InterviewScreen: () => require("react").createElement("ordinary-interview"),
  CaseDetailScreen: () => require("react").createElement("ordinary-case"),
  DeathRegistrationScreen: () => require("react").createElement("ordinary-reporting"),
  WorkspaceScreen: () => require("react").createElement("ordinary-workspace"),
}));
jest.mock("../src/web/LazyInterviewScreen", () => ({
  InterviewScreen: () => require("react").createElement("ordinary-interview"),
  CaseDetailScreen: () => require("react").createElement("ordinary-case"),
  DeathRegistrationScreen: () => require("react").createElement("ordinary-reporting"),
}));

import InterviewRoute from "../app/interview";
import BrowserCase from "../app/case.web";
import DeathRegistrationRoute from "../app/death-registration";
import WorkspaceRoute from "../app/workspace";
import TrainingRegisterRoute from "../app/training/register";
import TrainingReviewRoute from "../app/training/review";

function redirectOf(element: React.ReactElement) {
  return (element as React.ReactElement<{ href: unknown }>).props.href;
}

describe("training route compatibility", () => {
  beforeEach(() => { mockParams = {}; });

  test("normal interview and case links redirect before rendering data screens", () => {
    mockParams = { training: "1", draftId: "draft-1", revisionDraftId: "revision-1", section: "doris" };
    expect(redirectOf(InterviewRoute())).toEqual({ pathname: "/training/interview/form", params: mockParams });
    expect(redirectOf(BrowserCase())).toEqual({ pathname: "/training/interview/case", params: mockParams });
  });

  test("legacy reporting, review and workspace links preserve their identifiers", () => {
    mockParams = { training: "1", deathId: "death-1", mode: "reviewing", vaSid: "va-1", section: "nqa" };
    expect(redirectOf(DeathRegistrationRoute())).toEqual({ pathname: "/training/reporting", params: mockParams });
    expect(redirectOf(TrainingRegisterRoute())).toEqual({ pathname: "/training/reporting", params: mockParams });
    expect(redirectOf(TrainingReviewRoute())).toEqual({ pathname: "/training/reviewing", params: mockParams });
    expect(redirectOf(WorkspaceRoute())).toEqual({ pathname: "/training/reviewing/case", params: mockParams });
  });
});
