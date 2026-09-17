import { DOWNSTREAM_NAMES, type DownstreamName } from "./useReach";
import { mark } from "./ui";

interface ServiceBarProps {
  unreachable: readonly DownstreamName[];
}

const BAR = "flex flex-wrap items-center gap-2 border-b border-line-subtle px-3 py-2 text-[11px]";
const CHIP = "inline-flex items-center gap-1.5 rounded-tag border px-2 py-0.5";

const LABEL: Record<DownstreamName, string> = {
  task_store: "task store",
  bootstrap: "bootstrap",
  model_broker: "model broker",
  project_service: "project service",
  mediator: "mediator",
};

export function ServiceBar({ unreachable }: ServiceBarProps) {
  const total = DOWNSTREAM_NAMES.length;
  const silent = unreachable.length;

  return (
    <div className={BAR}>
      <p className="w-full text-ink-muted">
        {silent === 0 ? (
          `All ${total} services answering`
        ) : (
          <>
            <span className="text-red-400">
              {silent} of {total}
            </span>{" "}
            services not answering
          </>
        )}
      </p>

      {DOWNSTREAM_NAMES.map((name) => {
        const answering = !unreachable.includes(name);

        return (
          <span
            className={`${CHIP} ${answering ? "border-line" : "border-(--line-accent)"}`}
            key={name}
          >
            <span className={`${mark.dot} ${answering ? "bg-status-ok" : "bg-status-fail"}`} />

            <span className="text-ink-muted">{LABEL[name]}</span>

            {!answering && <span className="text-status-fail">no answer</span>}
          </span>
        );
      })}
    </div>
  );
}
