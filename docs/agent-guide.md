# Guidance for coding agents

The five MCP tool schemas describe the arguments. A short profile instruction
helps the model decide **when** to use them. Offer to append this to the active
profile's `AGENTS.md`; preserve existing instructions and do not edit other profiles.

```md
## Parallel shell work with AgentTasker

For independent shell jobs, plan first, then use AgentTasker execute_batch with
concurrency: 4 and wait: false. Use depends_on only where ordering is required.
Collect results with get_batch using the returned batch_id. Check every status,
exit code, stdout/stderr and reported execution host/cwd before claiming success.
Use cancel_batch to stop unwanted work.

Commands run on the configured MCP server's host, not automatically on the agent's
SSH host. Respect this profile's local/remote boundary; set an explicit absolute
execution-host cwd when needed. Avoid concurrent writes to the same files/worktree.
Do not automatically retry side effects after a disconnect. Jobs/results are
session-local; collect them before closing or reloading the session.
```

Tool names may be prefixed/normalized by the harness. Use the discovered names,
not guessed spellings. Current OMP commonly exposes `mcp__agent_tasker_execute_batch`;
Pi may expose the namespace through its direct MCP tools or codemode. Use the
client's MCP status/discovery mechanism if tools are not yet visible.

## Custom tool guards

Standard MCP support and a custom policy extension are separate layers. A profile
may connect to the server yet refuse model calls as local/unreviewed. A successful
doctor proves only transport/server behavior; it does not exercise those hooks.

Do **not** blindly add `agent_tasker` to a regex or allow an entire namespace.
A reviewer should approve only the exact intended methods after verifying:

1. Native MCP provenance, not a tool impersonating an MCP name.
2. The effective selected server entry and trusted profile source, accounting for
   project overrides and duplicate names.
3. For remote-only work, the **actual approved SSH executable and full arguments**,
   correct user/host, authentication/config, remote Python and command cwd.
4. No local launcher, HTTP replacement, wrapper, env/cwd injection or other host.
5. Equivalent checks on executable tool-device calls (for example `xd://`), not
   only direct tool calls. Reading a schema must not grant execution.

Fail closed on missing/mismatched evidence. Preserve all unrelated restrictions.
Ask for explicit user approval before changing security policy. Add negative tests
for a local launcher, wrong host, project shadow, unknown method and fake provenance,
and test the real session after approval. If the harness does not expose enough
trusted connection metadata, report that limitation instead of guessing.

No personal VM guard or hard-coded allowlist is shipped here: those are deployment
policy, not portable server defaults. This project does not change your models,
provider routing, authentication, tool approval mode or system prompt.
