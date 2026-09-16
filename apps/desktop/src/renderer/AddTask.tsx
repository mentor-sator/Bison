import { useState, type FormEvent } from "react";
import type { TaskDraft } from "./tasks";

const KINDS = ["code", "automation", "research", "real_world", "setup", "verification"] as const;

const TITLE_LIMIT = 200;

const ROW = "flex items-center gap-1.5 border-b border-line-subtle px-3 py-2";
const INPUT =
  "min-w-0 rounded-tag border border-line bg-surface-2 px-2 py-1 text-[12px] text-ink transition-colors duration-[140ms] ease-ui placeholder:text-ink-faint focus:border-line-strong disabled:opacity-40";
const SUBMIT =
  "shrink-0 rounded-tag border border-line bg-surface-2 px-3.5 py-1 text-[11px] text-ink-muted transition-colors duration-[140ms] ease-ui hover:border-line-strong hover:text-ink disabled:text-ink-faint disabled:opacity-40";

interface AddTaskProps {
  onAdd: (draft: TaskDraft) => Promise<boolean>;
}

export function AddTask({ onAdd }: AddTaskProps) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<string>(KINDS[0]);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = (submitEvent: FormEvent) => {
    submitEvent.preventDefault();

    const trimmed = title.trim();

    if (trimmed === "" || busy) {
      return;
    }

    setBusy(true);

    void onAdd({ title: trimmed, kind, description: description.trim() })
      .then((added) => {
        if (added) {
          setTitle("");
          setDescription("");
        }
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <form className={ROW} onSubmit={submit}>
      <input
        className={`${INPUT} flex-[2]`}
        value={title}
        onChange={(changeEvent) => setTitle(changeEvent.target.value)}
        placeholder="Add a task"
        maxLength={TITLE_LIMIT}
        disabled={busy}
      />

      <select
        className={`${INPUT} shrink-0 cursor-pointer`}
        value={kind}
        onChange={(changeEvent) => setKind(changeEvent.target.value)}
        disabled={busy}
      >
        {KINDS.map((entry) => (
          <option key={entry} value={entry}>
            {entry.replace("_", " ")}
          </option>
        ))}
      </select>

      <input
        className={`${INPUT} flex-[3]`}
        value={description}
        onChange={(changeEvent) => setDescription(changeEvent.target.value)}
        placeholder="what done looks like (optional)"
        disabled={busy}
      />

      <button type="submit" className={SUBMIT} disabled={busy || title.trim() === ""}>
        Add
      </button>
    </form>
  );
}
