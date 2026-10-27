import { attentionMessage, loadFailureMessage } from "../src/revisionMessages";
import { isIsoTimestamp } from "../src/revisions";
import { t } from "../src/i18n";

describe("revision open failures (digitva-owbz)", () => {
  it("keeps the cause as a Ref line instead of a bare retry text", () => {
    const text = loadFailureMessage(new Error("revision_instrument_mismatch"));
    expect(text).toContain(t("revisionRetry"));
    expect(text).toContain("Ref:");
    expect(text).toContain("revision_instrument_mismatch");
  });

  it("says the phone storage is full instead of a generic error", () => {
    expect(loadFailureMessage(new Error("Error code 13: database or disk is full"))).toContain(t("phoneStorageFull"));
  });

  it("explains a damaged definition pin instead of Retry revision", () => {
    expect(attentionMessage("invalid_definition_pin")).toBe(t("revisionPinInvalid"));
    expect(attentionMessage("invalid_definition_pin")).not.toBe(t("revisionRetry"));
  });

  it("accepts server isoformat times with microseconds", () => {
    expect(isIsoTimestamp("2026-10-23T08:30:00.123456+00:00")).toBe(true);
    expect(isIsoTimestamp("2026-10-23T08:30:00Z")).toBe(true);
    expect(isIsoTimestamp("yesterday")).toBe(false);
    expect(isIsoTimestamp(5)).toBe(false);
  });
});
