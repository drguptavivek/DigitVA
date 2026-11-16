import { deathDirectionsUrls, deathFix, deathShareUrl } from "../src/deathWorkflow";

describe("death location helpers", () => {
  const fix = deathFix({ latitude: 28.6, longitude: 77.2, accuracy_m: 12 })!;

  it("accepts a valid fix and keeps accuracy when known", () => {
    expect(fix).toEqual({ latitude: 28.6, longitude: 77.2, accuracy_m: 12 });
    expect(deathFix({ latitude: 0, longitude: 0 })?.accuracy_m).toBeNull();
  });

  it.each([
    [undefined], [null], [{}], [{ latitude: 28.6 }], [{ latitude: null, longitude: null }],
    [{ latitude: "28.6", longitude: "77.2" }], [{ latitude: NaN, longitude: 1 }],
    [{ latitude: 91, longitude: 0 }], [{ latitude: 0, longitude: 181 }],
  ])("gives no fix for %j", (value) => {
    expect(deathFix(value as never)).toBeNull();
  });

  it("builds Android and iOS directions urls", () => {
    expect(deathDirectionsUrls(fix, "android")).toEqual(["google.navigation:q=28.6,77.2", "geo:28.6,77.2?q=28.6,77.2"]);
    expect(deathDirectionsUrls(fix, "ios")).toEqual(["http://maps.apple.com/?daddr=28.6,77.2"]);
    expect(deathDirectionsUrls(fix, "ios", "google")).toEqual([
      "comgooglemaps://?daddr=28.6,77.2&directionsmode=driving",
      "https://www.google.com/maps/dir/?api=1&destination=28.6,77.2",
    ]);
  });

  it("builds the share link", () => {
    expect(deathShareUrl(fix)).toBe("https://www.google.com/maps/dir/?api=1&destination=28.6,77.2");
  });
});
