import { createContext } from "react";

/** Set by the web notes side panel: closes it. The note stays mounted, so an unsaved draft is kept. */
export const NotesCloseContext = createContext<(() => void) | undefined>(undefined);
