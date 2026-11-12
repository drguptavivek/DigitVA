import { goHome } from "../src/goHome";

// A stack that behaves as the root Stack does: push adds, replace swaps the top, dismissAll keeps the first.
function fakeRouter(stack: string[]) {
  return {
    stack,
    canDismiss: () => stack.length > 1,
    dismissAll: () => void stack.splice(1),
    replace: (href: string) => void (stack[stack.length - 1] = href),
    push: (href: string) => void stack.push(href),
  };
}

test("lock / unlock cycles keep the stack at one screen", () => {
  const router = fakeRouter(["/"]);
  for (let cycle = 0; cycle < 20; cycle++) {
    router.push("/unlock");
    router.replace("/worklist");
    goHome(router as never);
  }
  expect(router.stack).toEqual(["/"]);
});

test("from a pushed screen it pops to the accounts list instead of stacking another", () => {
  const router = fakeRouter(["/", "/worklist", "/case"]);
  goHome(router as never);
  expect(router.stack).toEqual(["/"]);
});

test("on a one-screen stack it only replaces and never dismisses", () => {
  const router = fakeRouter(["/"]);
  const dismiss = jest.spyOn(router, "dismissAll");
  goHome(router as never);
  expect(dismiss).not.toHaveBeenCalled();
  expect(router.stack).toEqual(["/"]);
});

// dismissTo as the root Stack's POP_TO: pop to the last route of that name, else swap the top for it.
function stackRouter(stack: string[]) {
  const name = (href: string | { pathname: string }) => (typeof href === "string" ? href : href.pathname);
  return {
    ...fakeRouter(stack),
    dismissTo: (href: string | { pathname: string }) => {
      const index = stack.lastIndexOf(name(href));
      if (index === -1) stack[stack.length - 1] = name(href);
      else stack.splice(index + 1);
    },
  };
}

test("Settings <-> engine check / DORIS demo / offline coding loops stay bounded", () => {
  const router = stackRouter(["/", "/worklist"]);
  router.push("/settings");
  for (let cycle = 0; cycle < 20; cycle++) {
    router.push("/engine-check");
    router.dismissTo({ pathname: "/settings" });
  }
  expect(router.stack).toEqual(["/", "/worklist", "/settings"]);
});

test("revision / registration / draft-delete / workspace exits pop back to where they land", () => {
  const router = stackRouter(["/", "/worklist"]);
  for (let cycle = 0; cycle < 20; cycle++) {
    router.push("/case");
    router.push("/revision");
    router.dismissTo({ pathname: "/worklist" });
  }
  expect(router.stack).toEqual(["/", "/worklist"]);
  const coding = stackRouter(["/", "/coding"]);
  for (let cycle = 0; cycle < 20; cycle++) {
    coding.push("/workspace");
    coding.dismissTo({ pathname: "/coding" });
  }
  expect(coding.stack).toEqual(["/", "/coding"]);
});

test("enabling fingerprint / screen lock leaves no pre-lock screens under the PIN screen", () => {
  const router = stackRouter(["/"]);
  for (let cycle = 0; cycle < 20; cycle++) {
    router.push("/worklist");
    router.push("/settings");
    goHome(router as never);
    router.push("/unlock");
    router.replace("/worklist");
    goHome(router as never);
  }
  expect(router.stack).toEqual(["/"]);
});

test("re-enrolment replaces the accounts list on a one-screen stack", () => {
  const router = stackRouter(["/", "/worklist", "/settings"]);
  goHome(router as never, "/enrol");
  expect(router.stack).toEqual(["/enrol"]);
});
