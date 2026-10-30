/**
 * Web twin of the Collect Plus "Try DORIS" demo (dorisDemo.native.tsx): the web app has no on-phone engine, so
 * this route only ever redirects home and must not pull the engine or the editor into the web bundle.
 */
import { Redirect } from "expo-router";

export default function DorisDemoWeb() {
  return <Redirect href="/" />;
}
