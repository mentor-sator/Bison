import { useEffect, useState } from "react";
import { fetchCriteria, type Criterion } from "./tasks";
import { mark } from "./ui";

interface TaskDetailProps {
  httpUrl: string;
  taskId: string;
}

type DetailState = "loading" | "ready" | "failed";

const PANEL = "flex flex-col gap-1.5 rounded-tag border border-line bg-sunken px-2.5 py-2";
const ROW = "flex items-baseline gap-2";

const STATUS_TONE: Record<string, string> = {
  verified: "bg-status-ok",
  failed: "bg-status-fail",
  unverified: "bg-status-idle",
  ignored: "bg-status-idle",
  skipped: "bg-status-idle",
  inconclusive: "bg-status-wait",
};

function statusTone(status: string): string {
  return STATUS_TONE[status] ?? "bg-status-idle";
}

export function TaskDetail({ httpUrl, taskId }: TaskDetailProps) {
  const [detailState, setDetailState] = useState<DetailState>("loading");
  const [criteria, setCriteria] = useState<Criterion[]>([]);

  useEffect(() => {
    let cancelled = false;

    setDetailState("loading");

    fetchCriteria(httpUrl, taskId)
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setCriteria(loaded);
        setDetailState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setDetailState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl, taskId]);

  if (detailState === "loading") {
    return <div className={PANEL}>reading the criteria</div>;
  }

  if (detailState === "failed") {
    return <div className={PANEL}>the criteria could not be read</div>;
  }

  if (criteria.length === 0) {
    return <div className={PANEL}>this task carries no criteria</div>;
  }

  return (
    <div className={PANEL}>
      {criteria.map((criterion) => (
        <div className={ROW} key={criterion.id}>
          <span className={`${mark.dot} ${statusTone(criterion.status)} translate-y-[3px]`} />

          <span className="flex-1 text-ink">{criterion.statement}</span>

          <span className="shrink-0 text-[11px]">{criterion.check_kind}</span>

          <span className="w-14 shrink-0 text-right text-[11px] tabular-nums">
            {criterion.status}
          </span>
        </div>
      ))}
    </div>
  );
}
