export const button = {
  secondary:
    "inline-flex shrink-0 items-center gap-2 rounded-control border border-line bg-surface-2 px-3 py-1.5 text-[13px] font-medium text-ink transition-colors duration-[140ms] ease-ui hover:border-line-strong disabled:text-ink-faint",
  ghost:
    "inline-flex shrink-0 items-center gap-2 rounded-control px-2.5 py-1.5 text-[13px] font-medium text-ink-muted transition-colors duration-[140ms] ease-ui hover:text-ink disabled:text-ink-faint",
  halt: "inline-flex shrink-0 items-center gap-2 rounded-control bg-red-500 px-4 py-1.5 text-[13px] font-semibold text-white shadow-accent transition-colors duration-[140ms] ease-ui hover:bg-red-400 active:bg-red-600 disabled:bg-surface-2 disabled:text-ink-faint disabled:shadow-none",
} as const;

export const field = {
  select:
    "shrink-0 rounded-control border border-line bg-surface-2 px-3 py-1.5 text-[13px] text-ink transition-colors duration-[140ms] ease-ui hover:border-line-strong focus:border-red-500 disabled:text-ink-faint",
} as const;

export const mark = {
  tag: "inline-flex shrink-0 items-center rounded-tag bg-(--tint-accent) px-2 py-0.5 text-[11.5px] font-medium text-red-300",
  dot: "inline-block h-2 w-2 shrink-0 rounded-full",
} as const;
