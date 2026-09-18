import { describe, expect, it } from "vitest";
import { criterionNote, formatPercentage, isCriterion, isPlan, planCaption } from "./tasks";

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

describe("criterionNote", () => {
  const criterion = {
    id: "c1",
    task_id: "t1",
    statement: "the port answers",
    check_kind: "deterministic",
    check_spec: null,
    weight: 1,
    status: "failed",
    status_reason: null,
    verified_by: null,
  };

  it("joins the verifier and the reason when both are present", () => {
    expect(
      criterionNote({ ...criterion, verified_by: "inspector", status_reason: "port 5432 refused" }),
    ).toBe("inspector · port 5432 refused");
  });

  it("returns whichever one is present on its own", () => {
    expect([
      criterionNote({ ...criterion, verified_by: "inspector" }),
      criterionNote({ ...criterion, status_reason: "port 5432 refused" }),
    ]).toEqual(["inspector", "port 5432 refused"]);
  });

  it("says nothing when the service reported nothing", () => {
    expect([
      criterionNote(criterion),
      criterionNote({ ...criterion, status_reason: "   " }),
    ]).toEqual([null, null]);
  });
});

describe("planCaption", () => {
  const plan = {
    id: "p1",
    task_id: "t1",
    intent: "make the port answer",
    steps_total: 3,
    gated_count: 0,
    steps: [{ id: "s1" }, { id: "s2" }, { id: "s3" }] as never,
  };

  it("counts the steps it was actually given", () => {
    expect(planCaption(plan)).toBe("3 steps");
  });

  it("names how many wait for confirmation", () => {
    expect(planCaption({ ...plan, gated_count: 2 })).toBe("3 steps, 2 needing confirmation");
  });

  it("says step rather than steps for one", () => {
    expect(planCaption({ ...plan, steps: [{ id: "s1" }] as never })).toBe("1 step");
  });
});

describe("isPlan", () => {
  it("accepts a plan the service returned", () => {
    expect(
      isPlan({ id: "p1", task_id: "t1", intent: "x", steps_total: 0, gated_count: 0, steps: [] }),
    ).toBe(true);
  });

  it("rejects the null a task with no plan returns", () => {
    expect([isPlan(null), isPlan({ id: "p1", intent: "x" })]).toEqual([false, false]);
  });
});
