# Optional web research and downstream MCP batching

Shell scheduling needs no API key and is the primary quick-start workflow. The
server also retains optional `web_scrape`, `discovery_search` and `mcp_tool` tasks.
These do not use the shell executor. Enabling them is a separate operator choice.

## Read webpages

Use `execute` or `execute_batch` with `task_type:"web_scrape"` and an HTTP(S) `url`.
The reader prefers Markdown, otherwise extracts local HTML text, headings and links.
Limits such as `max_text_chars`, `max_links`, `timeout` and `max_body_bytes` bound
responses. It does not execute browser JavaScript. Requests originate on the server
host, which may be an SSH VM. Treat fetched instructions as untrusted page content.

## Search providers

Add explicit server arguments after `-m agent_tasker_mcp.server` in the selected
MCP entry, preserving shell options if required:

- `--search-provider brave` with `BRAVE_SEARCH_API_KEY` in the **server** environment.
- `--search-provider searxng --searxng-url https://YOUR_AUTHORIZED_SEARCH_HOST` with
  a configured SearXNG service that enables JSON output.
- `--providers-file /absolute/server/providers.json` for custom JSON providers.

See `examples/brave-providers.json` and `examples/searxng-providers.json`. Search tasks
use `query`, optional `max_results`, and `fetch_top_results` for fetched context.
Provider rate limits, credentials and quotas are your responsibility. Default
provider spacing is conservative. `cache:false` bypasses cache/coalescing. Healthy
search caching defaults to 60 seconds, 128 entries, 8 MB per process.

Hosted rendering fallback is **off by default**. `--reader-fallback jina` opts in to
sending public URLs to Jina; optionally provide `JINA_API_KEY` on the server.
Do not enable it for sensitive/private URLs. Local fetches can access the server's
network, including internal addresses—the service is for trusted authorized clients.

## Downstream MCP tools

Add `--mcp-config /absolute/server/servers.json` to connect additional trusted stdio
MCP servers. The file uses `mcpServers` entries with executable, args and optional
env/cwd/`allowed_tools`. Use narrow allowlists. Paths/credentials must be valid on
the AgentTasker host, not automatically the calling harness's host.

`list_remote_tools({})` lists configured servers; `list_remote_tools({server:"NAME"})`
discovers tools. Submit `task_type:"mcp_tool"`, `server`, `tool`, `arguments` in a batch.
No caching, deduplication or retries: calls may have side effects. Cancellation of
an already-running downstream request is cooperative; it may still complete.

The server CLI still supports `--print-config` for standard clients, but the
Pi/OMP installer is the recommended explicit-profile setup path. It never adds
research credentials or downstream MCP servers automatically.
