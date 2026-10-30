/**
 * Platform entry for the Collect Plus "Try DORIS" demo (dorisDemo.native.tsx carries the screen; dorisDemo.web.tsx
 * the web twin): this shared file only ever redirects home and imports nothing native-only, so both bundles can
 * resolve the route path the app directory imports.
 */
import { Redirect } from "expo-router";

export default function DorisDemoEntry() {
  return <Redirect href="/" />;
}
