/**
 * Routes Android hardware back and the back-swipe through a screen's own leave() (policy: "Leaving a form").
 * By default only back/pop actions are caught (replace/push navigations the screen starts itself pass through);
 * `anyAction` also catches replace/navigate, e.g. a tab switch.
 * Set `guard.handler.current` to the screen's leave (undefined lets the navigation through, e.g. while loading) and
 * `guard.holds.current` when it should hold only sometimes. The handler gets `proceed`, which runs the held
 * navigation; call `guard.release()` just before a navigation leave() makes itself, so it is not caught again.
 */
import { useNavigation } from "expo-router";
import { useEffect, useRef } from "react";

export function useLeaveGuard(anyAction = false) {
  const navigation = useNavigation();
  const handler = useRef<((proceed: () => void) => void) | undefined>(undefined);
  const holds = useRef<(() => boolean) | undefined>(undefined);
  const released = useRef(false);
  useEffect(
    () =>
      navigation.addListener("beforeRemove", (event) => {
        const type = event.data.action.type;
        if (released.current || !handler.current || (holds.current && !holds.current())) return;
        if (!anyAction && type !== "GO_BACK" && type !== "POP") return;
        event.preventDefault();
        handler.current(() => {
          released.current = true;
          navigation.dispatch(event.data.action);
        });
      }),
    [navigation, anyAction],
  );
  return { handler, holds, release: () => { released.current = true; } };
}
