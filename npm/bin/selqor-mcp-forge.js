#!/usr/bin/env node
// Copyright (c) Selqor Labs.
// SPDX-License-Identifier: Apache-2.0
//
// Node wrapper for the `selqor-mcp-forge` Python CLI.
//
// Resolves a Python >= 3.11 interpreter and invokes `python -m selqor_forge`,
// forwarding stdin/stdout/exit code. If Python or the package are missing,
// prints install guidance and exits with a non-zero status.

"use strict";

const { spawnSync, execFileSync } = require("child_process");
const os = require("os");

const IS_WINDOWS = process.platform === "win32";
const PKG_VERSION = require("../package.json").version;

function printInstallHelp(reason) {
  const msg = [
    "",
    "selqor-mcp-forge requires Python 3.11+ and the selqor-mcp-forge Python package.",
    `Reason: ${reason}`,
    "",
    "Install with either:",
    "  pipx install selqor-mcp-forge          # isolated, recommended",
    "  pip install --user selqor-mcp-forge    # user site-packages",
    "",
    "Docs: https://github.com/Selqor-Labs/Selqor-MCP-Forge#quick-start-5-minutes",
    "",
  ].join("\n");
  process.stderr.write(msg);
}

function which(cmd) {
  try {
    const finder = IS_WINDOWS ? "where" : "which";
    const out = execFileSync(finder, [cmd], { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim()
      .split(/\r?\n/)[0];
    return out || null;
  } catch (_err) {
    return null;
  }
}

function tryPythonInterpreters() {
  const candidates = IS_WINDOWS
    ? ["py", "python", "python3"]
    : ["python3", "python"];
  for (const candidate of candidates) {
    const path = which(candidate);
    if (!path) continue;
    // `py` on Windows is the launcher; pass `-3` so it picks a Python 3.
    const probeArgs = candidate === "py" ? ["-3", "--version"] : ["--version"];
    try {
      const probe = spawnSync(candidate, probeArgs, {
        stdio: ["ignore", "pipe", "pipe"],
      });
      if (probe.status !== 0) continue;
      const version = (probe.stdout.toString() + probe.stderr.toString()).trim();
      const match = version.match(/Python\s+(\d+)\.(\d+)/);
      if (!match) continue;
      const major = Number(match[1]);
      const minor = Number(match[2]);
      if (major < 3 || (major === 3 && minor < 11)) continue;
      return { cmd: candidate, prefixArgs: candidate === "py" ? ["-3"] : [] };
    } catch (_err) {
      continue;
    }
  }
  return null;
}

function main(argv) {
  const args = argv.slice(2);

  // Always drive the Python engine via `python -m selqor_forge`. We intentionally
  // do NOT shortcut through a native `selqor-mcp-forge` binary on PATH: the npm
  // shim itself is installed under that same name, so any PATH lookup risks
  // resolving back to this script.
  const python = tryPythonInterpreters();
  if (!python) {
    printInstallHelp("no Python 3.11+ interpreter was found on PATH.");
    process.exit(1);
    return;
  }

  const result = spawnSync(
    python.cmd,
    [...python.prefixArgs, "-m", "selqor_forge", ...args],
    { stdio: "inherit" }
  );

  if (result.status === null) {
    const sig = result.signal ? ` (signal ${result.signal})` : "";
    process.stderr.write(`selqor-mcp-forge: child terminated unexpectedly${sig}\n`);
    process.exit(1);
    return;
  }

  // Detect missing Python package and surface a clearer message.
  if (result.status !== 0) {
    const probe = spawnSync(
      python.cmd,
      [...python.prefixArgs, "-c", "import selqor_forge"],
      { stdio: ["ignore", "ignore", "pipe"] }
    );
    if (probe.status !== 0) {
      printInstallHelp(
        "the selqor-mcp-forge Python package is not installed in the interpreter resolved from PATH."
      );
      process.exit(1);
      return;
    }
  }

  process.exit(result.status);
}

if (process.argv[2] === "--npm-wrapper-version") {
  process.stdout.write(`selqor-mcp-forge npm wrapper ${PKG_VERSION} (node ${process.version}, ${os.platform()}-${os.arch()})\n`);
  process.exit(0);
}

main(process.argv);
