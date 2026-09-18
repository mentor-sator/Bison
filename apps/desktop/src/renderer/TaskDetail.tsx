import { useEffect, useState } from "react";
import { criterionNote, fetchCriteria, type Criterion } from "./tasks";
import { mark } from "./ui";

interface TaskDetailProps {
  httpUrl: string;
  taskId: string;
}

type DetailState = "loading" | "ready" | "failed";

const PANEL = "flex flex-col gap-1.5 rounded-tag border border-line bg-sunken px-2.5 py-2";
const ROW = "flex items-baseline gap-2";
const NOTE = "pl-4 text-[11px] text-ink-muted";

const STATUS_TONE: Record<string, { dot: string; word: string }> = {
  verified: { dot: "bg-status-ok", word: "text-status-ok" },
  failed: { dot: "bg-status-fail", word: "text-status-fail" },
  unverified: { dot: "bg-status-idle", word: "text-ink-muted" },
  ignored: { dot: "bg-status-idle", word: "text-ink-muted" },
  skipped: { dot: "bg-status-idle", word: "text-ink-muted" },
  inconclusive: { dot: "bg-status-wait", word: "text-status-wait" },
};

const UNKNOWN_TONE = { dot: "bg-status-idle", word: "text-ink-muted" };

function statusTone(status: string): { dot: string; word: string } {
  return STATUS_TONE[status] ?? UNKNOWN_TONE;
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
      {criteria.map((criterion) => {
        const tone = statusTone(criterion.status);
        const note = criterionNote(criterion);

        return (
          <div className="flex flex-col gap-0.5" key={criterion.id}>
            <div className={ROW}>
              <span className={`${mark.dot} ${tone.dot} translate-y-[3px]`} />

              <span className="flex-1 text-ink">{criterion.statement}</span>

              <span className="shrink-0 text-[11px]">{criterion.check_kind}</span>

              <span className={`w-14 shrink-0 text-right text-[11px] ${tone.word}`}>
                {criterion.status}
              </span>
            </div>

            {note !== null && <p className={NOTE}>{note}</p>}
          </div>
        );
      })}
    </div>
  );
}
