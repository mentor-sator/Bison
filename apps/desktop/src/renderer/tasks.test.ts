import { describe, expect, it } from "vitest";
import { formatPercentage, isCriterion } from "./tasks";

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

describe("isCriterion", () => {
  const criterion = {
    id: "c1",
    task_id: "t1",
    statement: "the port answers",
    check_kind: "deterministic",
    check_spec: { port: 5432 },
    weight: 2,
    status: "verified",
    status_reason: null,
    verified_by: "inspector",
  };

  it("accepts a criterion the service returned", () => {
    expect(isCriterion(criterion)).toBe(true);
  });

  it("rejects one whose weight is not a number", () => {
    expect(isCriterion({ ...criterion, weight: "2" })).toBe(false);
  });

  it("rejects anything that is not an object", () => {
    expect([isCriterion(null), isCriterion("c1")]).toEqual([false, false]);
  });
});
