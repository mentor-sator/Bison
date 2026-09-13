import {
  describeReach,
  firstHaltReason,
  haltedServices,
  silentServices,
  type HaltReason,
} from "./halt";
import type { HaltView } from "./useGateway";
import { button, mark } from "./ui";

interface HaltBannerProps {
  halt: HaltView;
}

const REASON_LABEL: Record<HaltReason, string> = {
  kill_switch: "the kill switch fired",
  step_failure: "a step failed",
  project_switch: "a project switch",
  user_stop: "you stopped it",
};

export function HaltBanner({ halt }: HaltBannerProps) {
  const { report, signal, halted, pending } = halt;
  const reason = signal?.reason ?? (report === null ? null : firstHaltReason(report));
  const stopped = report === null ? [] : haltedServices(report);
  const silent = report === null ? [] : silentServices(report);

  return (
    <div className="flex flex-col gap-1.5 px-5 pb-3">
      <div className="flex items-center gap-3">
        <span className={`${mark.dot} ${halted ? "bg-status-wait" : "bg-status-ok"}`} />

        <span className="text-[13px] font-medium text-ink">{halted ? "Halted" : "Running"}</span>

        <span className="text-[13px] text-ink-muted">
          {!halted
            ? "nothing is halted"
            : reason === null
              ? "halted for an unreported reason"
              : REASON_LABEL[reason]}
        </span>

        {halted && signal !== null && (
          <span className="text-[11.5px] text-ink-faint tabular">
            {new Date(signal.issued_at).toLocaleTimeString()}
          </span>
        )}

        <span className="min-w-0 flex-1 truncate text-[13px] text-ink-faint">
          {report === null ? "checking services" : describeReach(report)}
        </span>

        <button
          type="button"
          className={button.halt}
          disabled={pending}
          onClick={halted ? halt.resume : halt.stop}
        >
          {halted ? "Resume" : "Stop"}
        </button>
      </div>

      {stopped.length > 0 && (
        <p className="text-[13px] text-ink-muted">stopped: {stopped.join(", ")}</p>
      )}

      {silent.length > 0 && (
        <div className="flex items-center gap-3">
          <span className="text-[13px] text-ink-muted">no answer from {silent.join(", ")}</span>

          <button type="button" className={button.ghost} disabled={pending} onClick={halt.refresh}>
            Recheck
          </button>
        </div>
      )}

      {halt.error !== null && <p className="text-[13px] text-red-400">{halt.error}</p>}
    </div>
  );
}
