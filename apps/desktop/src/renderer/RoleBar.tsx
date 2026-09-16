import { ROLES, type Role, type RoleBinding } from "./broker";
import type { BindingsState } from "./useBindings";

interface RoleBarProps {
  bindingsState: BindingsState;
  bindings: RoleBinding[];
  onPick: (role: Role) => void;
}

const BAR = "flex flex-wrap gap-2 border-b border-line-subtle px-3 py-2 text-[11px] text-ink-faint";
const CHIP =
  "inline-flex items-baseline gap-1.5 rounded-tag border border-line px-2 py-0.5 transition-colors duration-[140ms] ease-ui hover:border-line-strong";

function localityTone(locality: string | undefined): string {
  if (locality === "local") {
    return "text-status-ok";
  }

  return locality === "remote" ? "text-status-wait" : "text-status-fail";
}

export function RoleBar({ bindingsState, bindings, onPick }: RoleBarProps) {
  if (bindingsState === "loading") {
    return <div className={BAR}>loading role bindings</div>;
  }

  if (bindingsState === "failed") {
    return <div className={BAR}>role bindings unavailable</div>;
  }

  return (
    <div className={BAR}>
      {ROLES.map((role) => {
        const binding = bindings.find((candidate) => candidate.role === role);

        return (
          <button type="button" className={CHIP} key={role} onClick={() => onPick(role)}>
            <span className="text-[10px] uppercase tracking-[0.04em] text-ink-muted">{role}</span>

            <span className={localityTone(binding?.locality)}>
              {binding?.model_id ?? "unbound"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
