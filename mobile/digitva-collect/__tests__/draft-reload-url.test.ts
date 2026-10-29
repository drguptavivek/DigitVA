import { draftReloadUrl } from "../src/web/draftReload";

test("reloads a new interview onto its draft, not onto another new one", () => {
  expect(draftReloadUrl("https://example.test/app/interview?projectId=HP0001&siteId=O001&orgUnitId=x", "d-1"))
    .toBe("https://example.test/app/interview?draftId=d-1");
  expect(draftReloadUrl("https://example.test/app/training/interview?draftId=old#top", "d 2"))
    .toBe("https://example.test/app/training/interview?draftId=d+2");
});
