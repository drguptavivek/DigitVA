/**
 * React Native package entry point, binding shared form and question-control
 * factories to native primitives while re-exporting the headless API.
 */
import { Image, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import Svg, { Circle as SvgCircle, Path as SvgPath } from "react-native-svg";

import { createWhoVaForm } from "./ui/create-who-va-form.js";
import { createWhoVaQuestionControls } from "./ui/question-controls.js";
import { loadWhoVa2022Instrument } from "./instrument-loader.js";

export * from "./core.js";
export {
  WHO_VA_2022_LANGUAGES,
  loadWhoVa2022Instrument,
  loadWhoVa2022Language
} from "./instrument-loader.js";
export { processNativeImageAttachment } from "./native-attachments.js";
export type * from "./native-attachments.js";
export type { WhoVaDraftController, WhoVaFormProps, WhoVaPlatformServices } from "./ui/create-who-va-form.js";

export const WhoVaForm = createWhoVaForm(
  { View, Text, TextInput, Pressable, ScrollView, Image, Svg, SvgCircle, SvgPath },
  loadWhoVa2022Instrument
);
export const WhoVaQuestionControls = createWhoVaQuestionControls({ View, Text, TextInput, Pressable, Image });
export type { WhoVaQuestionControlProps } from "./ui/question-controls.js";
