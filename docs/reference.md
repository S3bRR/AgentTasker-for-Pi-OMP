# Tools, results and limits

Five stdio MCP tools: `execute`, `execute_batch`, `get_batch`, `cancel_batch`,
`list_remote_tools`. Traditional MCP protocol versions 2025-11-25, 2025-06-18,
2025-03-26 and 2024-11-05 are supported. These are application-level background
batches, not native MCP Tasks. Tool calls are side-effectful, not read-only or
safely repeatable. No push progress notifications or HTTP server transport.

## Shell task

Requires server startup with `--allow-shell` on Linux/macOS/WSL and `/bin/bash`.

| Field | Meaning |
| --- | --- |
| `task_type` | `shell` |
| `name` | Unique batch name; optional generated name if omitted |
| `command` | Non-empty Bash command; no interactive stdin |
| `cwd` | Optional existing absolute directory on the server host; otherwise server default |
| `env` | Optional string environment overrides for this task only |
| `timeout` | Positive integer seconds; default 30 |
| `max_output_bytes` | Retained tail bytes **per stream**; default 8192, max 65536 |
| `depends_on` | Array of other task names in this batch; graph must be acyclic |

`execute` runs one task synchronously. `execute_batch` takes a non-empty `tasks`
array, `concurrency` (1 through server worker count) and `wait` (default true).
Use `wait:false` for jobs that may outlast the client's tool-call timeout. It returns
a `batch_id` immediately, not completed command results. The whole batch is validated
before execution. Failed dependencies block dependent tasks, not unrelated jobs.
Each task has a fresh shell; environment and `cd` do not propagate to later jobs.
No shell caching, deduplication or automatic retries.

Collect with `get_batch({batch_id, wait_seconds, output_mode})`. `wait_seconds`
is 0–30, default 0, and limits only that collection call—not the shell deadline.
Use a bounded positive wait instead of tight polling. Compact mode (default) returns
only finished tasks. `output_mode:"full"` includes queued/running placeholders,
counts, per-task timestamps and original results.

Finished shell results include `host`, resolved `cwd`, `exit_code`, `stdout`,
`stderr`, per-stream observed byte counts/truncation flags, `timed_out`, `cancelled`.
Output is continuously drained to avoid pipe deadlock; retained tails are bounded.
UTF-8 decoding replaces invalid/partial characters. Truncated bytes cannot be
recovered from the result. For full logs, redirect to a host file and read bounded
chunks through authorized tools. Live stdout is not streamed through get_batch.

Nonzero exit/timeout marks a task failed; cancellation marks it cancelled. Mixed
batches retain successes and report failures through MCP `isError`. Check the task
results, not just the outer response. Terminal batch states: completed/failed/cancelled.

`cancel_batch` skips queued work and terminates running shell process groups using
TERM then KILL after 0.5 seconds. Shell background children are cleaned up on normal
completion too. Deliberately detached processes and hard failures can evade cleanup.
HTTP/MCP calls already running may finish normally after cancellation.

## Scheduling and lifecycle

One execution worker pool is shared across batches **in one server process**.
The installer sets four workers; server CLI `--workers` controls the actual limit.
Separate client sessions/processes have separate limits. At most twice the worker
count tool requests can be in flight. Request/background coordinators are bounded.

Batches, status and results live in memory. They disappear on restart/disconnect.
Completed batches expire or may be evicted early to admit new work; active batches
are not evicted. Full capacity of active batches rejects new submissions.

| Environment | Default |
| --- | --- |
| `AGENT_TASKER_MAX_TASKS` | 1000 tasks per batch |
| `AGENT_TASKER_MAX_PAYLOAD_BYTES` | 1,000,000 bytes per task |
| `AGENT_TASKER_MAX_BATCHES` | 32 retained background batches |
| `AGENT_TASKER_BATCH_TTL_SECONDS` | 3600 completed-batch retention seconds |
| `AGENT_TASKER_MAX_MEMORY_MB` | 0; optional soft high-water RSS guard |

Input MCP messages are capped at 8 MB. Limits are resource bounds, not a sandbox.
An orderly stdin close/SIGTERM cancels shell work. Never rely on cleanup after
SIGKILL, transport loss or host failure. There is no persistent queue.

## Optional research/downstream tasks

- `web_scrape`: `url` required; website retrieval works without a key.
- `discovery_search`: `query` and configured/explicit HTTP providers required.
- `mcp_tool`: configured `server`, `tool`, optional `arguments`, response `timeout`.

The installer configures only shell scheduling. Search/downstream servers need
explicit server arguments or environment configuration: [web tools](web-retrieval.md).
AgentTasker cannot borrow other MCP connections from the calling harness.
Generic downstream MCP calls are never cached/retried; remote servers determine
whether their calls truly execute in parallel. External content is untrusted data.
