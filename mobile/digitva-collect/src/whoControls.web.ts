// Match the native adapter's .ts extension so Metro chooses this web entry
// before whoControls.ts, then load the app-owned JSX controls.
export { WhoVaQuestionControls } from "./whoControlsWeb";
export type { LightweightAnswer, WhoVaQuestionControlProps } from "./whoControlsWeb";
