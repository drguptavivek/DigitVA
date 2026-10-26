/**
 * Web twin of the Collect Plus offline coding screen (offlineCoding.native.tsx): the web app has no
 * interviewer store and no offline engine, so this route only ever redirects home and must not pull the
 * native-only modules (drafts' expo-sqlite store, SecureStore, the DORIS editor) into the web bundle.
 */
import { Redirect } from "expo-router";

export default function OfflineCodingWeb() {
  return <Redirect href="/" />;
}
