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
