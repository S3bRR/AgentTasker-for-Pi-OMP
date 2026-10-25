# AgentTasker for Pi & OMP

[![Verify](https://github.com/S3bRR/AgentTasker-for-Pi-OMP/actions/workflows/test.yml/badge.svg)](https://github.com/S3bRR/AgentTasker-for-Pi-OMP/actions/workflows/test.yml)

**Plan work. Run four shell jobs at once. Collect the results.**

A dependency-free stdio MCP server for [Pi](https://pi.dev) and
[OMP](https://github.com/can1357/oh-my-pi). Your existing model makes the plan;
AgentTasker runs the commands. No extra model account, API key or hosted service.

- Configurable concurrency, background batch IDs and dependency ordering.
- Per-command exit codes, stdout/stderr tails, host, cwd and timing.
- Timeouts and cancellation of running shell process groups.
- Explicit local or SSH execution; no silent local fallback.
- Profile-aware installer that preserves other MCP entries and makes private backups.

**Requires:** Python 3.10+, Git and Bash on Linux/macOS/WSL. First installation
needs pip/build-tool downloads. SSH mode needs OpenSSH and an already-authorized
POSIX host. Native Windows shell execution is not supported.

> `--allow-shell` permits arbitrary commands as the server user. This is **not a
> sandbox**. Commands run on the MCP server's host, not automatically on your
> agent's SSH host. [Security and boundaries](SECURITY.md).

## Copy this to your agent

```text
Install https://github.com/S3bRR/AgentTasker-for-Pi-OMP from a fresh clone in a
stable location. Read README.md, SECURITY.md and the installer before running it.
Confirm my client (Pi/OMP), active profile's exact mcp.json, execution host
(local or an explicitly authorized SSH host), and existing workspace directory.
Ask for missing choices; never guess a VM or copy another profile's route.

Use install.py with four workers and --allow-shell only on my chosen host.
Preview the generated entry, then merge with --apply. Preserve other servers,
models, credentials and safety policies. Ask before replacing a different
agent-tasker entry with --replace. Never print secrets or bypass host-key checks.

Run the doctor --shell-test, then verify in a fresh/reloaded agent session:
execute_batch(wait=false, concurrency=4), collect with get_batch, and check
outputs, exits, host/cwd and overlap. A client-only check does not verify a
custom tool guard. If blocked, report it; do not disable policies or fall back
locally. Report config changes, backups, checks and anything unverified.
```

## Install locally

Clone to a stable location. Replace the workspace placeholder with an existing
directory **on the machine where commands should run**:

```bash
git clone --depth 1 https://github.com/S3bRR/AgentTasker-for-Pi-OMP.git
cd AgentTasker-for-Pi-OMP
./setup.sh --client pi --cwd /absolute/workspace --allow-shell --apply
```

- **Pi:** respects `PI_CODING_AGENT_DIR`, otherwise uses `~/.pi/agent/mcp.json`.
  Pass `--config /absolute/active/mcp.json` for a custom profile.
- **OMP:** replace `--client pi` with `--client omp --config /absolute/active/mcp.json`,
  or `--client omp --profile YOUR_NAMED_PROFILE`. Its standard default config is
  `~/.omp/agent/mcp.json`; the active profile is never guessed.
- **Preview:** omit `--apply` to install and print config without changing client settings.
- **Options:** `python3 install.py --help`. Default workers: 4; configurable 1–256.
  `--skip-install` generates/merges config using an existing `--venv`.

The installer creates `.venv` in the checkout. Keep both in place. It rejects
malformed/duplicate-key JSON, symlink config targets and unapproved collisions.
`--replace --apply` changes only an existing AgentTasker entry after review.
Backups are private `mcp.json.backup-*` files beside your config; never share them.
No models, approval policies or agent instructions are changed.

## Run on a VM instead

Do **not** use the local entry for a remote-only profile.

1. On the authorized VM, clone this repo and run
   `python3 install.py --client generic --cwd /absolute/remote/workspace --allow-shell`.
   This installs there and prints the remote venv's absolute Python path.
2. On the client, generate the SSH entry using that path:

```bash
python3 install.py --client pi --transport ssh \
  --ssh-host YOUR_AUTHORIZED_SSH_ALIAS \
  --remote-python /absolute/remote/AgentTasker-for-Pi-OMP/.venv/bin/python \
  --cwd /absolute/remote/workspace --allow-shell --apply
```

Use the same OMP/profile options described above. Optional: `--ssh-config PATH`
for an existing client SSH config, or `--ssh-port PORT`. SSH mode does not create
a local execution server or connect automatically. Authenticate and verify the
host key through your normal workflow first. No credentials are copied.

## Verify and use

Reload/restart the selected client. From the checkout:

```bash
python3 -m agent_tasker_mcp.doctor --config /absolute/active/mcp.json --shell-test
```

Or use `.venv/bin/agent-tasker-doctor` after local installation. The doctor checks
four-way overlap, outputs/exits, failed-dependency isolation, cancellation and
timeouts using harmless commands on the configured host. Check its reported host
and cwd. Omit `--shell-test` for protocol-only verification.

Then ask the model to run four harmless jobs through AgentTasker and collect them.
A custom VM-only guard may still block model calls even if the doctor passes.
Obtain approval for the **exact trusted MCP source and SSH transport**—never a
namespace wildcard. Do not disable the guard. Headless OMP tests with explicit
`--tools` may need process-only `OMP_MCP_STARTUP_TIMEOUT_MS=5000` on cold startup.

| Tool | Purpose |
| --- | --- |
| `execute` | Run one shell task and wait |
| `execute_batch` | Run a plan; `wait:false` returns a batch ID immediately |
| `get_batch` | Collect progress/results; `wait_seconds` 0–30 |
| `cancel_batch` | Cancel queued work and terminate running shell groups |

Example `execute_batch` arguments:

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

Collect with `{"batch_id":"RETURNED_ID","wait_seconds":5,"output_mode":"full"}`.
Use `depends_on:["earlier-name"]` only for ordering. Optional task fields: absolute
execution-host `cwd`, string `env` overrides, `timeout` (default 30 seconds), and
`max_output_bytes` (retained tail per stream: default 8192, maximum 65536).
Compact output shows finished tasks; full output includes queued/running placeholders.
Check every status, exit code and truncation flag. A failure blocks dependants,
not unrelated jobs. `cd` and environment changes do not persist across tasks.

For your active profile's `AGENTS.md`, a short optional note is enough:

> Use AgentTasker for independent shell work: plan first, execute_batch with
> wait:false and concurrency:4, then get_batch. Check outputs, exits and host/cwd.
> Use depends_on for ordering and cancel_batch to stop work. Avoid concurrent
> writes to the same worktree. Never retry side effects blindly after disconnect.

## Limits and maintenance

- Jobs/results are **session-local** and disappear on MCP/client restart or SSH loss.
- No live stdout streaming or durable log storage. Redirect to a host file for full logs.
- Four workers per server process, not per entire machine. Separate clients have separate limits.
- No automatic shell retries. Process-group cleanup cannot contain deliberately detached
  processes or guarantee cleanup after SIGKILL, transport loss or host failure.
- Resource defaults: 1000 tasks/batch, 1 MB payload/task, 32 retained batches, 1-hour
  completed retention. Override with `AGENT_TASKER_MAX_TASKS`, `AGENT_TASKER_MAX_PAYLOAD_BYTES`,
  `AGENT_TASKER_MAX_BATCHES`, `AGENT_TASKER_BATCH_TTL_SECONDS` on the server.
- **2.0 is shell-only:** optional web/search/downstream-MCP tasks and their CLI flags
  from 1.x were removed. Existing shell task/config arguments are unchanged.

Update after collecting active work: `git pull --ff-only`, then `.venv/bin/python -m pip install .`.
Reload the client and rerun verification. To uninstall, remove **only** `agent-tasker`
from the selected config, reload, then remove unused installations. Do not restore
an old whole-config backup over unrelated newer settings.

CI verifies source/wheel installs and the doctor on Linux/macOS with Python 3.10/3.12.
Build with `.venv/bin/python -m pip install build && .venv/bin/python -m build`. No test suite or extra
runtime dependencies are shipped. MIT license; original attribution is preserved.
