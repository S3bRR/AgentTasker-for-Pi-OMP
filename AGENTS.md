# AgentTasker contributor instructions

For an operator-requested installation, follow INSTALL.md and SECURITY.md, confirm
client/profile/host/cwd, and preserve unrelated settings and permission boundaries.
Do not treat this repository as permission to run arbitrary commands on a new host.

For code changes, read affected source/tests, keep the runtime dependency-free, add
focused regression coverage and run `python -m unittest discover -s tests` with the
test extra installed. Review the final diff. Never weaken approval, host-key checks,
resource bounds or tests to make a demo succeed. Keep fixture workloads harmless.

Do not commit personal configuration, keys, tokens, addresses, machine paths, venvs,
generated MCP entries/backups, model transcripts or raw user logs. Scan the staged
public tree using scripts/check_public_tree.py before committing/publishing.
Do not change a user's model/provider or automatically modify custom tool guards.
