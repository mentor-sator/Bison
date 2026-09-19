import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { gotoTarget, installRoots, launchEnvironment, parseLauncher, run } from "./editor.js";

const ROOT = "C:\\Users\\dev\\AppData\\Local\\Programs\\Microsoft VS Code";

const SCRIPT = [
  "@echo off",
  "setlocal",
  "set VSCODE_DEV=",
  "set ELECTRON_RUN_AS_NODE=1",
  '"%~dp0..\\Code.exe" "%~dp0..\\7debcd0e2a\\resources\\app\\out\\cli.js" %*',
  "IF %ERRORLEVEL% NEQ 0 EXIT /b %ERRORLEVEL%",
  "endlocal",
].join("\r\n");

describe("parseLauncher", () => {
  it("reads the executable and the versioned cli from the launcher script", () => {
    expect(parseLauncher(SCRIPT, ROOT)).toEqual({
      program: `${ROOT}\\Code.exe`,
      cli: `${ROOT}\\7debcd0e2a\\resources\\app\\out\\cli.js`,
    });
  });

  it("follows the cli into whatever folder an update moved it to", () => {
    const moved = SCRIPT.replace("7debcd0e2a", "a1b2c3d4e5");

    expect(parseLauncher(moved, ROOT)?.cli).toBe(
      `${ROOT}\\a1b2c3d4e5\\resources\\app\\out\\cli.js`,
    );
  });

  it("reads an older launcher that keeps the cli at the top of the install", () => {
    const older = '"%~dp0..\\Code.exe" "%~dp0..\\resources\\app\\out\\cli.js" %*';

    expect(parseLauncher(older, ROOT)?.cli).toBe(`${ROOT}\\resources\\app\\out\\cli.js`);
  });

  it("gives up on a script that does not name both parts", () => {
    expect(parseLauncher('"%~dp0..\\Code.exe" %*', ROOT)).toBeNull();
    expect(parseLauncher("echo hello", ROOT)).toBeNull();
  });
});

describe("installRoots", () => {
  it("puts an explicit override first, then the user and machine installs", () => {
    expect(
      installRoots({
        BISON_DEV_ENV_VSCODE_DIR: "D:\\Tools\\VSCode",
        LOCALAPPDATA: "C:\\Users\\dev\\AppData\\Local",
        ProgramFiles: "C:\\Program Files",
      }),
    ).toEqual([
      "D:\\Tools\\VSCode",
      "C:\\Users\\dev\\AppData\\Local\\Programs\\Microsoft VS Code",
      "C:\\Program Files\\Microsoft VS Code",
    ]);
  });

  it("adds the parent of every bin folder on the path, once", () => {
    expect(
      installRoots({
        LOCALAPPDATA: "C:\\Users\\dev\\AppData\\Local",
        Path: `C:\\Windows;${ROOT}\\bin;E:\\Editors\\Code\\bin\\;${ROOT.toUpperCase()}\\BIN`,
      }),
    ).toEqual([ROOT, "E:\\Editors\\Code"]);
  });

  it("knows no location when the environment names none", () => {
    expect(installRoots({})).toEqual([]);
  });
});

describe("gotoTarget", () => {
  it("appends the line when there is one", () => {
    expect(gotoTarget("C:\\scope\\app.py", 12)).toBe("C:\\scope\\app.py:12");
  });

  it("opens at the top when there is none", () => {
    expect(gotoTarget("C:\\scope\\app.py", null)).toBe("C:\\scope\\app.py");
  });
});

describe("launchEnvironment", () => {
  it("runs the executable as node and never in development mode", () => {
    const env = launchEnvironment({ VSCODE_DEV: "1", Path: "C:\\Windows" });

    expect(env.ELECTRON_RUN_AS_NODE).toBe("1");
    expect("VSCODE_DEV" in env).toBe(false);
    expect(env.Path).toBe("C:\\Windows");
  });
});

describe("run", () => {
  async function script(source: string): Promise<string> {
    const folder = await mkdtemp(join(tmpdir(), "bison-dev-env-"));
    const path = join(folder, "cli.js");
    await writeFile(path, source, "utf8");
    return path;
  }

  it("passes the arguments through untouched, with no shell in between", async () => {
    const cli = await script(
      "process.stdout.write(JSON.stringify([process.env.ELECTRON_RUN_AS_NODE, ...process.argv.slice(2)]));",
    );
    const outcome = await run(
      { program: process.execPath, cli },
      ["--goto", "C:\\scope\\a & b.py:3"],
      process.env,
      10000,
    );

    expect(outcome.exitCode).toBe(0);
    expect(JSON.parse(outcome.stdout)).toEqual(["1", "--goto", "C:\\scope\\a & b.py:3"]);
  });

  it("reports the exit code and what was written to stderr", async () => {
    const cli = await script("process.stderr.write('no such profile'); process.exit(3);");
    const outcome = await run({ program: process.execPath, cli }, [], process.env, 10000);

    expect(outcome).toMatchObject({ exitCode: 3, timedOut: false, stderr: "no such profile" });
  });

  it("stops waiting and says so when the editor hangs", async () => {
    const cli = await script("setTimeout(() => {}, 60000);");
    const outcome = await run({ program: process.execPath, cli }, [], process.env, 200);

    expect(outcome.timedOut).toBe(true);
  });

  it("reports a program that cannot be started instead of throwing", async () => {
    const outcome = await run(
      { program: join(tmpdir(), "missing-editor.exe"), cli: "cli.js" },
      [],
      process.env,
      10000,
    );

    expect(outcome.exitCode).toBeNull();
    expect(outcome.stderr).toContain("ENOENT");
  });
});
