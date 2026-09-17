import { describe, expect, it } from "vitest";
import { formatPercentage } from "./tasks";

describe("formatPercentage", () => {
  it("floors rather than rounds, so it never claims completion early", () => {
    expect([formatPercentage(35.7143), formatPercentage(99.9)]).toEqual(["35%", "99%"]);
  });

  it("shows an exact hundred", () => {
    expect(formatPercentage(100)).toBe("100%");
  });

  it("separates nothing verified from nearly nothing verified", () => {
    expect([formatPercentage(0), formatPercentage(0.4)]).toEqual(["0%", "<1%"]);
  });
});
