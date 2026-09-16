import type { Activity } from "./activity";
import { mark } from "./ui";

interface ActivityBarProps {
  activity: Activity;
  elapsedSeconds: number;
}

const BAR = "flex items-center gap-2.5 border-t border-line-subtle px-5 py-2 text-[12px]";

export function ActivityBar({ activity, elapsedSeconds }: ActivityBarProps) {
  if (activity.phase === "idle") {
    return null;
  }

  if (activity.phase === "invoking") {
    return (
      <div className={BAR}>
        <span className={`${mark.dot} animate-dot-pulse bg-status-wait`} />

        <span className="text-ink-muted">
          {activity.role} thinking on {activity.modelId}
        </span>

        <span className="text-ink-faint">{activity.locality}</span>

        <span className="ml-auto tabular-nums text-ink-faint">{elapsedSeconds}s</span>
      </div>
    );
  }

  if (activity.phase === "answered") {
    return (
      <div className={BAR}>
        <span className="text-status-ok">
          {activity.modelId} answered in {(activity.latencyMs / 1000).toFixed(1)}s
        </span>

        {activity.failedOverFrom !== null && (
          <span className="text-ink-faint">failed over from {activity.failedOverFrom}</span>
        )}
      </div>
    );
  }

  return (
    <div className={BAR}>
      <span className="text-status-fail">{activity.reason}</span>
    </div>
  );
}
