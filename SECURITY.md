# Security and execution boundaries

## Arbitrary commands, not a sandbox

Shell tasks are disabled unless the server is launched with `--allow-shell`.
Enabling them gives authorized MCP callers arbitrary Bash execution as the server
user. Commands inherit that process's environment and can read/write files, contact
networks and launch other programs. Cwd is not a filesystem jail. Use a low-privilege
account and VM/container isolation for untrusted work. Never expose the stdio server
to untrusted callers, run it as root, or treat task validation as shell sanitization.

No service account or API key is needed for shell tasks. Your coding model is still
provided by Pi/OMP. Optional search providers/downstream MCP servers have their own
credentials, network behavior and side effects; they are not enabled automatically.

## Local versus remote

An MCP subprocess does not inherit the coding harness's SSH route. Local transport
means execution on the MCP process's host. Remote-only users must launch the server
on the authorized host over an explicit SSH transport. The installer does not scan
for VMs, open ports, collect passwords, copy keys, change known_hosts, or provision
machines. SSH uses batch authentication and strict host-key checking; establish trust
through the user's normal SSH workflow first. There is no local fallback.

Generated SSH commands quote the remote argv, including paths with spaces. SSH config
files and executables are trusted infrastructure; a user-supplied proxy/jump command
can itself run software on the client. Review that configuration under your existing
security policy. The generator disables LocalCommand and shared control sockets.

## Client permissions still apply

Pi/OMP approval extensions and VM-only guards may block AgentTasker even after it
connects. Do not disable them or blindly allow `mcp__agent_tasker_*`.
Review a narrow rule that checks native MCP provenance, the active profile's trusted
configuration, and its exact SSH transport. Project overrides must not inherit a
trusted user-entry approval. Do not allow a local launcher because it has a familiar
server/tool name. A command batch may receive one client approval, not one per command.

This repository intentionally does not install or modify private profile guards.
Transport success and a successful real model-session call are separate checks.

## Cancellation, data and lifecycle

Shell jobs have a deadline and separate process groups. Cancellation sends TERM,
then KILL after a short grace period. Background descendants are cleaned up after
normal completion too. Processes deliberately creating a new session, SIGKILL,
SSH loss or host failure can escape/prevent cleanup. Do not launch daemons here.
HTTP/downstream MCP operations already running may finish after cancellation.

Results are process-local, bounded, and expire. They do not survive client/server
restart or SSH disconnect. Output returns to your coding harness/model provider;
commands may reveal secrets in their stdout/stderr. There is no telemetry/hosted
AgentTasker backend, but configured commands and optional web/MCP tasks can send
network traffic. Protect your harness transcripts and any files you create as logs.

The installer only merges `agent-tasker` when `--apply` is specified, preserves
other entries, refuses unapproved replacement and writes a private backup. Backups
may contain credentials from unrelated MCP entries—never commit/share them.

## Reporting a vulnerability

Do not paste secrets, private host details or exploit data into public issues.
Use GitHub's private vulnerability reporting feature if available on this repository.
If it is unavailable, open a minimal issue requesting a private reporting channel
without disclosing the vulnerability, credentials or a working exploit publicly.
No supported-version or response-time SLA is promised; this is an early public release.
