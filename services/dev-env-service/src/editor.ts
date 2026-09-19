import { spawn } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import { win32 } from "node:path";

export const LAUNCHER_SCRIPT = win32.join("bin", "code.cmd");

const EXECUTABLE_PATTERN = /"%~dp0\.\.\\([^"]+?\.exe)"/i;
const CLI_PATTERN = /"%~dp0\.\.\\([^"]+?\\cli\.js)"/i;

export interface Launcher {
  program: string;
  cli: string;
}

export interface EditorRun {
  exitCode: number | null;
  timedOut: boolean;
  stdout: string;
  stderr: string;
}

export interface Editor {
  open(path: string, line: number | null): Promise<EditorRun>;
}

export class EditorUnavailableError extends Error {
  constructor(readonly searched: readonly string[]) {
    super(
      searched.length === 0
        ? "no VS Code install location is known on this machine"
        : `VS Code was not found in ${searched.join(", ")}`,
    );
    this.name = "EditorUnavailableError";
  }
}

export function installRoots(env: NodeJS.ProcessEnv): string[] {
  const roots: string[] = [];
  const add = (root: string | undefined): void => {
    if (!root) return;
    const normalised = win32.normalize(root);
    if (!roots.some((known) => known.toLowerCase() === normalised.toLowerCase())) {
      roots.push(normalised);
    }
  };

  add(env.BISON_DEV_ENV_VSCODE_DIR);

  if (env.LOCALAPPDATA) add(win32.join(env.LOCALAPPDATA, "Programs", "Microsoft VS Code"));
  if (env.ProgramFiles) add(win32.join(env.ProgramFiles, "Microsoft VS Code"));

  for (const entry of (env.Path ?? env.PATH ?? "").split(";")) {
    const trimmed = entry.trim();
    if (trimmed && win32.basename(win32.normalize(trimmed)).toLowerCase() === "bin") {
      add(win32.dirname(win32.normalize(trimmed)));
    }
  }

  return roots;
}

export function parseLauncher(script: string, root: string): Launcher | null {
  const executable = EXECUTABLE_PATTERN.exec(script)?.[1];
  const cli = CLI_PATTERN.exec(script)?.[1];

  if (!executable || !cli) return null;

  return {
    program: win32.join(root, executable),
    cli: win32.join(root, cli),
  };
}

export function gotoTarget(path: string, line: number | null): string {
  return line === null ? path : `${path}:${line}`;
}

export function launchEnvironment(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const { VSCODE_DEV: _dropped, ...rest } = env;

  return { ...rest, ELECTRON_RUN_AS_NODE: "1" };
}

async function isFile(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
}

export async function locate(env: NodeJS.ProcessEnv): Promise<Launcher> {
  const roots = installRoots(env);

  for (const root of roots) {
    let script: string;

    try {
      script = await readFile(win32.join(root, LAUNCHER_SCRIPT), "utf8");
    } catch {
      continue;
    }

    const launcher = parseLauncher(script, root);

    if (launcher && (await isFile(launcher.program)) && (await isFile(launcher.cli))) {
      return launcher;
    }
  }

  throw new EditorUnavailableError(roots);
}

export function run(
  launcher: Launcher,
  args: readonly string[],
  env: NodeJS.ProcessEnv,
  timeoutMs: number,
): Promise<EditorRun> {
  return new Promise((resolve) => {
    const child = spawn(launcher.program, [launcher.cli, ...args], {
      env: launchEnvironment(env),
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let settled = false;

    const finish = (exitCode: number | null): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ exitCode, timedOut, stdout, stderr });
    };

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, timeoutMs);

    child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      stderr += error.message;
      finish(null);
    });
    child.on("close", (code) => finish(code));
  });
}

export function vsCode(env: NodeJS.ProcessEnv, timeoutMs: number): Editor {
  return {
    async open(path, line) {
      const launcher = await locate(env);

      return run(launcher, ["--goto", gotoTarget(path, line)], env, timeoutMs);
    },
  };
}
