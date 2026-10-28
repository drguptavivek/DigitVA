import { acquireDraftUpload, acquireLocalCodingEditor } from "../src/localCodingLeases";

describe("local coding leases", () => {
  it("excludes the other side for one user and draft, and releases idempotently", () => {
    const releaseEditor = acquireLocalCodingEditor("user", "draft");
    expect(releaseEditor).toEqual(expect.any(Function));
    expect(acquireDraftUpload("user", "draft")).toBeNull();
    expect(acquireLocalCodingEditor("other", "draft")).toEqual(expect.any(Function));

    releaseEditor!();
    releaseEditor!();
    const releaseUpload = acquireDraftUpload("user", "draft");
    expect(releaseUpload).toEqual(expect.any(Function));
    releaseUpload!();
  });

  it("keeps other drafts independent", () => {
    const releaseUpload = acquireDraftUpload("user", "draft-a");
    expect(acquireLocalCodingEditor("user", "draft-b")).toEqual(expect.any(Function));
    releaseUpload!();
  });
});
