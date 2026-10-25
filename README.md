# AgentTasker for Pi & OMP

[![Tests](https://github.com/S3bRR/AgentTasker-for-Pi-OMP/actions/workflows/test.yml/badge.svg)](https://github.com/S3bRR/AgentTasker-for-Pi-OMP/actions/workflows/test.yml)

**Plan work. Run four shell jobs at once. Collect the results.**

A small, local stdio MCP server for [Pi](https://pi.dev) and
[OMP](https://github.com/can1357/oh-my-pi). Your existing coding model makes the
plan; AgentTasker runs the commands concurrently. No extra model account, API key,
agent subscription, hosted service, or third-party Python runtime dependency.

- **Real background batches:** return a batch ID immediately; keep working.
- **Configurable concurrency:** four workers in the installer, shared across batches.
- **Dependency plans:** sequence only the jobs that need earlier results.
- **Useful results:** exit codes, stdout/stderr tails, host, cwd, timing and truncation flags.
- **Cancellation and deadlines:** stop queued work and terminate shell process groups.
- **Local or SSH:** choose where the MCP server—and therefore commands—run.
- **Non-destructive setup:** explicit profile selection, backups, no config writes without `--apply`.

**Requirements:** Python 3.10+, Git, and Bash on Linux/macOS (or WSL).
First local installation needs pip/build-tool downloads. SSH mode also needs
OpenSSH, a POSIX server with AgentTasker installed, and already-authorized access.
Native Windows shell execution is not supported. Pi/OMP must support stdio MCP.

> **Security:** `--allow-shell` enables arbitrary commands with the server user's
> permissions. This is not a sandbox. MCP does **not** inherit your agent's SSH
> routing. Commands run on the MCP server's host. Choose local or SSH explicitly.
> [Read the security boundary →](SECURITY.md)

## Let your agent install it

**Copy this entire block into Pi or OMP:**

```text
Install AgentTasker for Pi & OMP from:
https://github.com/S3bRR/AgentTasker-for-Pi-OMP

Read README.md, INSTALL.md and SECURITY.md before executing installation code.
Use a fresh clone in a stable location; do not execute a remote curl-to-shell script.
Confirm my client (Pi or OMP), active profile's exact mcp.json, workspace directory,
and whether commands should run locally or on an explicitly authorized SSH host.
Ask me for missing choices; never guess a VM or copy another profile's SSH route.

Use the repository's installer with four workers and --allow-shell only on my
chosen execution host. Preview the generated entry, then merge it with --apply.
Preserve other MCP entries, models, credentials and safety policies. If agent-tasker
already exists, show the difference and ask before using --replace. Never print
secrets or disable host-key checking, authentication, or a VM-only policy.

Run the documented doctor --shell-test, then verify from a fresh/reloaded agent
session: launch four harmless jobs with execute_batch(wait=false, concurrency=4),
collect them with get_batch, and check host/cwd, outputs, exit codes and overlap.
Client-only tests are not enough if this profile has a custom tool guard.
If a policy blocks it, report the exact blocker; do not bypass it or fall back locally.

Offer to add the short AGENTS.md guidance from docs/agent-guide.md to my active
profile. Report exactly what changed, backup locations, tests and anything unverified.
```

Full instructions for the installing agent: **[INSTALL.md](INSTALL.md)**.

## Manual quick start: local execution

Clone to a location you will keep, and choose an **existing workspace**:

```bash
git clone https://github.com/S3bRR/AgentTasker-for-Pi-OMP.git
cd AgentTasker-for-Pi-OMP
```

### Pi

```bash
./setup.sh --client pi --cwd /absolute/path/to/workspace --allow-shell --apply
```

This respects `PI_CODING_AGENT_DIR`, otherwise uses `~/.pi/agent/mcp.json`.
For a different profile, pass `--config /absolute/path/to/active/mcp.json`.
The generated Pi entry exposes the five tools directly.

### OMP

For the **standard default** agent directory:

```bash
./setup.sh --client omp --config "$HOME/.omp/agent/mcp.json" \
  --cwd /absolute/path/to/workspace --allow-shell --apply
```

For a named profile, use `--profile YOUR_PROFILE` instead of `--config`.
If your installation uses a custom agent directory, pass its exact `mcp.json`.
The installer never guesses the active OMP profile or changes your default model.

Omit `--apply` to install and **print the config without changing client settings**.
Existing, different AgentTasker entries require an explicit `--replace`.
Keep the checkout and `.venv` in place. See [setup and uninstall](docs/setup.md).

## Verify it

Restart/reload your selected client so it loads the new MCP entry. Then run:

```bash
.venv/bin/agent-tasker-doctor --config /absolute/path/to/active/mcp.json --shell-test
```

The doctor starts **only the configured AgentTasker entry**, checks MCP, and
explicitly runs four harmless `printf`/`sleep` jobs on that entry's execution host.
It checks the four outputs, exits and overlapping timestamps. It does not change
configuration. Omit `--shell-test` for a protocol-only check.

Then ask your agent:

> Use AgentTasker to run four harmless, independent shell jobs in the background.
> Collect the batch and report each output, exit code, execution host and directory.
> Confirm they really overlapped; do not substitute built-in Bash for this test.

A successful doctor proves the transport/server works—not that a custom
Pi/OMP permission extension permits the model to call it. Test the real session too.

## Run commands on a VM instead

Install AgentTasker **on the VM** and generate an SSH transport on the client.
Do not use the local quick-start entry for a remote-only profile.

**[SSH setup →](docs/ssh.md)** · **[Custom VM-only policies →](docs/agent-guide.md#custom-tool-guards)**

There are no hard-coded hosts, usernames, keys, personal directories or profile
policies. Nothing scans your network, copies credentials or rents a server.

## How the tools work

Your model calls `execute_batch` with a plan like this:

```json
{
  "wait": false,
  "concurrency": 4,
  "tasks": [
    {"name": "identity", "task_type": "shell", "command": "id", "timeout": 10},
    {"name": "directory", "task_type": "shell", "command": "pwd", "timeout": 10},
    {"name": "files", "task_type": "shell", "command": "ls -la | head -20", "timeout": 10},
    {"name": "platform", "task_type": "shell", "command": "uname -s", "timeout": 10}
  ]
}
```

It gets a `batch_id` immediately and collects results with:

```json
{"batch_id": "THE_RETURNED_ID", "wait_seconds": 5, "output_mode": "full"}
```

Use `depends_on: ["earlier-task-name"]` for dependent steps, and `cancel_batch`
to stop unwanted jobs. Every command has its own cwd/environment; `cd` and shell
variables do not persist between commands. Avoid concurrent writes to one worktree.

| Tool | Purpose |
| --- | --- |
| `execute` | Run one task and wait |
| `execute_batch` | Run a plan concurrently; `wait:false` returns immediately |
| `get_batch` | Retrieve status and results, optionally waiting up to 30 seconds |
| `cancel_batch` | Cancel queued jobs and terminate running shell process groups |
| `list_remote_tools` | Discover explicitly configured downstream MCP tools (optional) |

[Task fields, dependencies and limits →](docs/reference.md)

## Honest limits

- **Session-local:** jobs/results do not survive MCP restart, client exit or SSH loss.
- **Not extra autonomous agents:** this runs commands; your existing model plans and interprets.
- **No live stdout streaming:** results appear when each task finishes. Output is bounded tails,
  not a durable log store. Redirect to a host file when you need complete logs.
- **Not a sandbox:** commands can access that user's files, environment and network.
- **No automatic retries for shell commands.** After disconnect, verify side effects before retrying.
- **Four workers per server process**, not per entire computer. Separate clients have separate limits.
- Processes deliberately escaping their process group, SIGKILL and host failure can prevent cleanup.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests
```

Tests use harmless local subprocesses and local HTTP/MCP fixtures—no API keys,
private VMs or paid model calls. CI tests Linux/macOS, builds a wheel, and verifies
a clean install. [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

Optional web fetching/search and downstream MCP batching remain available, disabled
unless configured: [web tools](docs/web-retrieval.md).

MIT licensed. Derived from [AgentTasker MCP](https://github.com/S3bRR/agent-tasker-mcp);
original license attribution is preserved. This repository starts with fresh Git
history and contains no personal deployment/configuration files.
