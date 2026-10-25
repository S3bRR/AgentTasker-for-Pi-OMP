# Setup, profiles, updates and uninstall

See [INSTALL.md](../INSTALL.md) for the agent workflow, [SSH](ssh.md) for remote-only
execution and [security](../SECURITY.md) before enabling arbitrary shell commands.

## Installer behavior

`python3 install.py --help` lists the options. `./setup.sh` is just a Bash wrapper
for that Python entry point. Both can be run from any directory.

- Local mode creates `.venv` inside the checkout and installs the source package.
- It prints an MCP config entry. **No client config changes without `--apply`.**
- Default installation concurrency is 4; `--workers N` accepts 1–256.
- Shell is enabled only with `--allow-shell` and an explicit existing `--cwd`.
- `--skip-install` performs config generation/merge only, using an existing venv.
- `--replace --apply` permits replacing only a different `agent-tasker` entry.
- Existing JSON is parsed before installation. Malformed/duplicate-key JSON,
  non-object `mcpServers`, and symlink config targets are refused.
- Original config bytes are backed up with private permissions beside the config.
  Updates use a temporary file and atomic replacement. A detected concurrent config
  change aborts rather than discarding it. Never share backups containing credentials.
- Models, authentication, custom guards and AGENTS.md are not changed.

The default installer needs Python's venv/pip and may download setuptools/build
requirements. On Debian-like systems, a missing venv module commonly requires
`python3-venv`; ask the user before installing system packages. No sudo is used by
the installer. Runtime shell execution uses only the Python standard library.

## Choose the correct profile

Pi: `--client pi` uses `PI_CODING_AGENT_DIR` or `~/.pi/agent/mcp.json`.
`--config PATH` selects an exact custom profile file. Reload/restart Pi and inspect
`/mcp`; `/reload` is supported in current Pi. Other/older Pi installations may use
an MCP adapter—use that adapter's documented configuration path instead.

OMP: `--client omp --config PATH` is the safest explicit choice.
`--profile NAME` selects `~/.omp/profiles/NAME/agent/mcp.json` for a named profile.
OMP's standard default directory is `~/.omp/agent`; customized launchers may differ.
Do not infer the active profile from the launching terminal's environment. Restart
that profile after changes. `--client generic` prints a standard `mcpServers` entry
for other compatible clients; automatic support outside Pi/OMP is not claimed.

Each config contains a single command executable and an argument array. The absolute
venv path allows clients launched without your terminal PATH to start the server.
Keep the checkout/venv in place or regenerate the entry after moving them.

## Verify and troubleshoot

```bash
.venv/bin/agent-tasker-doctor --config /absolute/active/mcp.json --shell-test
```

This starts only `agent-tasker`, not unrelated configured servers. A doctor probe
is a new MCP process, so it cannot inspect a running session's existing batch IDs.
Its `--shell-test` creates four harmless commands, checks overlap and prints the host
and directory. Check those match the intended boundary. Protocol-only mode omits
shell execution. The doctor does not expand credential/environment expressions in
handwritten configs; use plain generated entries or your client's own MCP diagnostics.

- **Unreviewed tool blocked:** a custom guard needs an approved narrow integration;
  see [agent guide](agent-guide.md#custom-tool-guards). Do not disable it.
- **Unknown OMP tools on cold start:** let discovery finish, or use the temporary
  environment `OMP_MCP_STARTUP_TIMEOUT_MS=5000` for a headless acceptance session.
- **Shell disabled:** check the actual server command contains `--allow-shell`.
- **Invalid cwd:** local cwd must exist locally; SSH cwd must exist on the VM.
- **SSH failed:** fix the authorized route/host key through the user's workflow;
  do not fall back to local commands or retry side effects automatically.
- **Model timed out after submitting:** the scheduler may have completed while the
  model stalled. Keep the session alive and collect the batch; do not rerun blindly.

## Updating

Stop/collect active work first; results do not survive server restart. Review changes
before pulling/running new source:

```bash
git pull --ff-only
.venv/bin/python -m pip install .
.venv/bin/python -m unittest discover -s tests
```

For optional official MCP SDK tests, install `'.[test]'` instead. Otherwise those
SDK tests are explicitly skipped. Restart/reload the client, then run the doctor
and a real-session check. No self-updating daemon or automatic package publication.

## Uninstalling

Collect/cancel active jobs. Remove **only** the `agent-tasker` entry from the selected
profile's `mcpServers`, preserving every other entry. Reload/restart that client.
Then delete the checkout/venv if no other profile references them. For SSH mode,
remove the VM installation only if no other client uses it. Never replace your
entire config with an old backup after unrelated settings have changed.
