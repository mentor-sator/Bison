import { describe, expect, it } from "vitest";
import {
  blockedReason,
  describeReach,
  firstHaltReason,
  haltedServices,
  isHaltStateReport,
  silentServices,
  type HaltStateReport,
  type RecipientHaltState,
} from "./halt";

const recipient = (overrides: Partial<RecipientHaltState>): RecipientHaltState => ({
  service: "task-runner-service",
  reachable: true,
  halted: false,
  boundary: null,
  reason: null,
  signal_id: null,
  halted_at: null,
  status: 200,
  detail: null,
  latency_ms: 4,
  ...overrides,
});

const report = (recipients: RecipientHaltState[]): HaltStateReport => ({
  halted: recipients.some((entry) => entry.halted === true),
  halted_count: recipients.filter((entry) => entry.halted === true).length,
  reachable_count: recipients.filter((entry) => entry.reachable).length,
  silent_count: recipients.filter((entry) => !entry.reachable).length,
  recipients,
});

describe("blockedReason", () => {
  it("names the mediator before anything else", () => {
    expect(blockedReason(true, true, report([]))).toBe("the mediator is not answering");
  });

  it("reports a halt before an unread state", () => {
    expect(blockedReason(false, true, null)).toBe("work is halted");
  });

  it("does not claim a halt state it has not read", () => {
    expect(blockedReason(false, false, null)).toBe("the halt state has not been read");
  });

  it("names every recipient a halt could not reach", () => {
    const silent = report([
      recipient({ service: "automation-service", reachable: false, halted: null }),
      recipient({ service: "dev-env-service", reachable: false, halted: null }),
      recipient({ service: "mediator-service" }),
    ]);

    expect(blockedReason(false, false, silent)).toBe(
      "a halt could not reach automation-service, dev-env-service",
    );
  });

  it("blocks nothing when every recipient answers", () => {
    expect(blockedReason(false, false, report([recipient({})]))).toBeNull();
  });
});

describe("report helpers", () => {
  it("counts answers against the full set", () => {
    const mixed = report([recipient({}), recipient({ reachable: false, halted: null })]);

    expect(describeReach(mixed)).toBe("1 of 2 answered");
    expect(silentServices(mixed)).toEqual(["task-runner-service"]);
  });

  it("lists only halted services", () => {
    const stopped = report([
      recipient({ service: "automation-service", halted: true, reason: "kill_switch" }),
      recipient({}),
    ]);

    expect(haltedServices(stopped)).toEqual(["automation-service"]);
    expect(firstHaltReason(stopped)).toBe("kill_switch");
  });

  it("returns no reason when nothing is halted", () => {
    expect(firstHaltReason(report([recipient({})]))).toBeNull();
  });

  it("rejects a report missing a required field", () => {
    expect(isHaltStateReport({ halted: true, halted_count: 1, reachable_count: 1 })).toBe(false);
  });
});
