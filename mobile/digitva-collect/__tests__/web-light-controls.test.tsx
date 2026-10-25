import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/ui", () => ({
  useUiStyles: () => ({ input: {}, secondary: {}, text: {} })
}));
jest.mock("../src/theme", () => ({
  useTheme: () => ({ ui: { primary: "#135", primaryForeground: "#fff", input: "#789", background: "#fff", accent: "#def", destructiveText: "#b00" } })
}));

import { WhoVaQuestionControls } from "../src/whoControls.web";

const question = {
  name: "reason",
  label: { en: "Reason", hi: "कारण" },
  choices: [
    { value: "one", label: { en: "One", hi: "एक" } },
    { value: "two", label: { en: "Two", hi: "दो" } }
  ],
  readOnly: false
};

it("keeps web choice controls lightweight while preserving accessible answer semantics", () => {
  const onAnswer = jest.fn();
  let tree!: ReturnType<typeof create>;
  act(() => {
    tree = create(
      <WhoVaQuestionControls.SingleChoice question={question} value="one" data={{}} locale="en" issues={[]} onAnswer={onAnswer} />
    );
  });
  const one = tree.root.findByProps({ testID: "question-reason-choice-one" });
  const two = tree.root.findByProps({ testID: "question-reason-choice-two" });
  expect(one.props.accessibilityRole).toBe("radio");
  expect(one.props.accessibilityState).toEqual({ selected: true, disabled: false });
  expect(two.props.accessibilityState).toEqual({ selected: false, disabled: false });
  act(() => two.props.onPress());
  expect(onAnswer).toHaveBeenCalledWith("two");
});

it("parses integer text without importing the WHO web renderer", () => {
  const onAnswer = jest.fn();
  let tree!: ReturnType<typeof create>;
  act(() => {
    tree = create(
      <WhoVaQuestionControls.Integer question={{ name: "age", label: { en: "Age" } }} value={12} data={{}} locale="en" issues={[]} onAnswer={onAnswer} />
    );
  });
  const input = tree.root.findByProps({ testID: "question-age" });
  act(() => input.props.onChangeText("-7"));
  expect(onAnswer).toHaveBeenCalledWith(-7);
  act(() => input.props.onChangeText(""));
  expect(onAnswer).toHaveBeenLastCalledWith(undefined);
});
