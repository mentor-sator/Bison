import type { ProjectState } from "./projects";
import type { ProjectsView } from "./useProjects";
import { button, field, mark } from "./ui";

interface ProjectBarProps {
  projects: ProjectsView;
}

const STATE_LABEL: Record<ProjectState, string> = {
  draft: "not started",
  active: "active",
  paused: "paused",
  archived: "archived",
};

export function ProjectBar({ projects }: ProjectBarProps) {
  const { projectsState, current, targets, capacity, pending, error } = projects;

  if (projectsState === "loading") {
    return <p className="text-[13px] text-ink-faint">Reading the project list</p>;
  }

  if (projectsState === "failed") {
    return (
      <div className="flex items-center gap-3">
        <span className={mark.dot + " bg-status-fail"} />

        <span className="text-[13px] text-red-400">The project list is unavailable</span>

        <button type="button" className={button.secondary} onClick={projects.refresh}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline gap-3">
        <span className="truncate text-[15px] font-semibold text-ink">
          {current === null ? "No project active" : current.name}
        </span>

        <span className="min-w-0 flex-1 truncate text-[13px] text-ink-muted">
          {current === null ? "Nothing is being worked on" : current.goal}
        </span>

        {capacity !== null && <span className={mark.tag}>{capacity}</span>}

        <select
          className={field.select}
          value=""
          disabled={pending || targets.length === 0}
          onChange={(changeEvent) => projects.switchTo(changeEvent.target.value)}
        >
          <option value="" disabled>
            {targets.length === 0 ? "Nothing to switch to" : "Switch project — stops all work"}
          </option>
          {targets.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name} — {STATE_LABEL[project.state]}
            </option>
          ))}
        </select>
      </div>

      {error !== null && <p className="text-[13px] text-red-400">{error}</p>}
    </div>
  );
}
