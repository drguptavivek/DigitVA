import { isRefused, refusalAnswers } from "../src/refusalBoundary";

test("either independent consent refusal stops the interview", () => {
  expect(isRefused({ Id10013: "no" }, "granted")).toBe(true);
  expect(isRefused({ Id10013: "yes" }, "refused")).toBe(true);
  expect(isRefused({}, undefined)).toBe(false);
});

test("refusal retains only an actual decision and valid broad profile", () => {
  expect(refusalAnswers({ Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female", Id10007: "name", narrative: "private" }))
    .toEqual({ Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female" });
  expect(refusalAnswers({ refusal_sex: "other", refusal_age_group: "23" })).toEqual({});
  expect(refusalAnswers({})).toEqual({});
});
