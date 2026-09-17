import { describe, expect, it } from "vitest";
import { originOf, silentDelay } from "./useReach";

describe("silentDelay", () => {
  it("starts at three seconds", () => {
    expect(silentDelay(1)).toBe(3000);
  });

  it("doubles with each consecutive failure", () => {
    expect([silentDelay(2), silentDelay(3), silentDelay(4)]).toEqual([6000, 12000, 24000]);
  });

  it("stops at thirty seconds", () => {
    expect([silentDelay(5), silentDelay(20)]).toEqual([30000, 30000]);
  });

  it("treats a zeroth failure as the floor", () => {
    expect(silentDelay(0)).toBe(3000);
  });
});

describe("originOf", () => {
  it("keeps the origin and drops the path", () => {
    expect(originOf("http://127.0.0.1:8000/health")).toBe("http://127.0.0.1:8000");
  });

  it("returns the input when it is not a url", () => {
    expect(originOf("gateway")).toBe("gateway");
  });
});
