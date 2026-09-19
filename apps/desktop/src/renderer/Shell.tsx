import type { ReactNode } from "react";

interface ShellProps {
  topBar: ReactNode;
  sidebar: ReactNode;
  main: ReactNode;
  tracker: ReactNode;
}

export function Shell({ topBar, sidebar, main, tracker }: ShellProps) {
  return (
    <div className="app-shell grid h-screen grid-cols-[248px_minmax(0,1fr)_380px] grid-rows-[auto_minmax(0,1fr)]">
      <header className="col-span-3 border-b border-line-subtle">{topBar}</header>

      <aside className="min-h-0 overflow-y-auto border-r border-line-subtle bg-surface-1">
        {sidebar}
      </aside>

      <main className="flex min-h-0 min-w-0 flex-col">{main}</main>

      <section className="flex min-h-0 flex-col border-l border-line-subtle bg-surface-1">
        {tracker}
      </section>
    </div>
  );
}
