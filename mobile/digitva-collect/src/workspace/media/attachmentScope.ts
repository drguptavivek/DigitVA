import { createContext, useContext } from "react";

import { trainingScopedPath } from "../../training";

/** True inside a training case: its media must ask for `training=1` (the server hides it from the normal scope). */
export const AttachmentTrainingContext = createContext(false);

/** The URL to fetch a validated attachment path with: `training=1` is added here, after path.ts has vetted the bare path. */
export function useAttachmentUrl(): (path: string) => string {
  const training = useContext(AttachmentTrainingContext);
  return (path) => trainingScopedPath(path, training);
}
