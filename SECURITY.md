# Security

Shell execution is disabled unless the server starts with `--allow-shell`.
Enabling it gives authorized MCP callers arbitrary Bash execution as the server
user, including access to that user's files, environment and network. Cwd is not
a jail. Use a low-privilege account and VM/container isolation for untrusted work;
never expose this stdio server to untrusted callers or run it as root.

Commands execute on the MCP server's host. They do not inherit the client's SSH
route. Remote-only users must configure an explicit SSH transport; there is no
local fallback. SSH uses batch authentication and strict host-key checking.
The executable/config/keys are trusted infrastructure; user-configured proxies
can run client-side programs. No keys are copied or host-key checks disabled.

Client approval and VM-only guards still apply. A successful doctor verifies the
transport/server, not a real model's permission to call it. Never blindly allow a
namespace or disable a guard. Review native MCP provenance, the effective trusted
profile entry and exact approved SSH transport, including executable device calls.
Project overrides and local launchers must not inherit remote approval.

Commands are not automatically retried. After a disconnect, verify side effects
before retrying. Cancellation sends TERM then KILL to shell process groups, but
intentional process detachment, SIGKILL, SSH loss or host failure can prevent cleanup.
Do not launch daemons. Results are process-local, bounded tails—not durable logs.
Output goes to your coding harness/model provider and may contain secrets.
There is no AgentTasker telemetry or hosted backend; commands can send network traffic.

The installer merges only `agent-tasker` with `--apply`, preserves other settings
and makes private backups. Configs/backups/transcripts may contain credentials;
never commit or upload them. Custom policies and model settings are not modified.

Report vulnerabilities through GitHub private vulnerability reporting if available.
Otherwise request a private channel in a minimal issue, without secrets or exploit
details. No response-time SLA is promised for this early public release.
