# Contributing

Use Python 3.10+ and keep runtime code standard-library only unless a current need
justifies a dependency. Prefer small changes and focused regression tests. Preserve
existing task semantics, client permissions and explicit local/SSH boundaries.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m build  # install the optional build tool first
```

CI covers Linux/macOS on Python 3.10 and 3.12, official MCP SDK interoperability,
package build and a clean-install doctor test. Tests must use local fixtures and
harmless commands—no paid APIs, personal VMs, credentials or model accounts.

For installer changes, test malformed config, duplicate keys, collision refusal,
backup bytes/permissions, unrelated-entry preservation, quoted SSH argv, and no
configuration writes without --apply. For execution changes, test actual overlapping
subprocesses, resource bounds, failure/dependency behavior, cancellation and shutdown.

Keep public examples portable: use placeholders/example domains, never your own
home path, SSH destination, config, tokens, model transcripts or raw test logs.
Before committing, inspect the staged diff and run `python3 scripts/check_public_tree.py`.
Never commit generated MCP configs/backups, private keys, environment files or .venv.

Update docs alongside behavior. Do not claim native Windows shell support, durable
queues, sandboxing, automatic guard approval or client-version coverage that has not
been verified. Report security concerns through [SECURITY.md](SECURITY.md), not a
public issue containing secrets or exploits. Releases are not automatically pushed
to PyPI/MCP registries; package-name/registry availability is not assumed.
