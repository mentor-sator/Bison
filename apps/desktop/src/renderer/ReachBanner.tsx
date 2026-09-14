import type { ReachView } from "./useReach";
import { button, mark } from "./ui";

interface ReachBannerProps {
  reach: ReachView;
  onRetry: () => void;
}

export function ReachBanner({ reach, onRetry }: ReachBannerProps) {
  const reaching = reach.reach === "reaching";

  return (
    <div className="flex items-center gap-3">
      <span className={`${mark.dot} ${reaching ? "bg-status-wait" : "bg-status-fail"}`} />

      <span className="text-[13px] font-medium text-ink">
        {reaching ? "Reaching the gateway" : "The gateway is not answering"}
      </span>

      <span className="min-w-0 flex-1 truncate text-[13px] text-ink-faint">
        {reaching ? reach.origin : `Nothing answered at ${reach.origin}`}
      </span>

      <button type="button" className={button.secondary} disabled={reaching} onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
