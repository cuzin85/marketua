# marketua

An MCP server that lets AI agents (Claude Desktop, Hermes Agent, Cursor, OpenCode, …)
search Ukrainian marketplaces — **OLX**, **Hotline.ua**, **Prom.ua** and **Rozetka** — from a
plain-language prompt and get back structured offers with links.

> **Status: alpha.** OLX, Hotline and Prom work out of the box (no tokens); Rozetka is
> covered through the optional Bright Data MCP server (free tier: 5 000 requests/month).
> Verified with MCP Inspector and a real agent (OpenCode), including a 4-marketplace
> price comparison from a single prompt. Hermes wiring is the final step.

## Idea

Ask in natural language:

> "SSD 120–560 GB, 2.5\", used, up to 1500 UAH"

and get a structured list of matching offers — title, price, location, link — instead of
a wall of search results.

## Why not just use web search?

| | Built-in web search | This MCP server |
|---|---|---|
| Structured filters (price, form factor, condition) | guesswork | exact API filters |
| Uniform, comparable result list | no | yes |
| Repeatable / schedulable queries | no | yes |
| Fresh marketplace listings | often stale | live |

For one-off lookups the difference is small; for structured comparison and monitoring it is the point.

## How it works

```
natural-language prompt
        │
        ▼
  LLM (OpenCode / Hermes / Claude)  ── maps prompt → tool arguments
        │
        ▼
  MCP tools  ── search, filters, details, references
        │
        ▼
  Marketplace providers ── OLX (JSON API), Hotline / Prom (SSR), Rozetka (Bright Data MCP)
        │
        ▼
  structured offers (title, price, location, url)
```

## Tools

The server exposes these MCP tools (OLX / Hotline / Prom — registered out of the box):

- **`search_offers(query, min_price, max_price, region_id, city_id, category_id, state, filters, limit, offset, include_promoted, sort)`**
  — one page of offers plus the total match count. Category-specific attributes go into
  `filters` as `{"key": "value"}` (choice) or `{"key": [from, to]}` (range).
  `sort`: `newest` (server-side), `price_asc`/`price_desc` (sorts the returned page).
  Promoted listings are excluded unless `include_promoted=True`.
- **`get_offer_details(offer_id)`** — full listing: plain-text description, characteristics,
  photo URLs, seller, status, dates.
- **`list_filters(query, category_id)`** — discovers which category-specific filters exist
  for a query (keys + sample values). Call before `search_offers` when an attribute is mentioned.
  `category_id` restricts the sample to one category (broad queries otherwise mix categories).
- **`list_categories()`** — curated category id/name list (static snapshot; OLX deprecated
  the live category endpoint).
- **`list_regions()`** — OLX region (oblast) and major city ids.
- **`hotline_search_offers(query, min_price, max_price, limit, offset)`** — Hotline product
  models (new items from shops) with the minimum shop price.
- **`prom_search_offers(query, min_price, max_price, limit, offset)`** — Prom products
  (new items from shops).

Rozetka has no tool in this server — it is queried through the **Bright Data MCP** browser
tools (see [Optional: Bright Data MCP](#optional-bright-data-mcp-for-rozetka)). The server's
instructions tell the agent to do so automatically for price comparisons.

## Example prompts

> Find me an SSD 120–560 GB, 2.5", used, up to 1500 UAH on OLX

> Cheap used monitors in Kyiv up to 2000 UAH, show the 5 cheapest

> Details of offer 931436822

The agent maps these onto the tools: it calls `list_filters` to learn valid filter keys,
`list_regions`/`list_categories` for ids, then `search_offers` with the narrowed arguments.
Server-side instructions tell it to report only filters actually used and to format the
result as a list with prices and links.

## Quick start

```bash
pip install marketua        # or: uvx marketua (no install needed)
marketua                    # runs the MCP server over stdio (a client spawns it)
```

For development from this repo:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q     # tests
```

## Connect an agent

Any MCP client works. **OpenCode**:

```jsonc
// opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "marketua": {
      "type": "local",
      "command": ["uvx", "marketua"],
      "enabled": true
    },
    // Rozetka (and any JS-rendered / Cloudflare-protected site) goes through
    // the Bright Data MCP — free tier: 5 000 requests/month. Token from
    // Bright Data → Settings → API Tokens (see .env.example in this repo).
    "brightdata": {
      "type": "remote",
      "url": "https://mcp.brightdata.com/mcp?token={env:BRIGHT_DATA_API_KEY}&tools=scrape_as_markdown,scrape_as_html,search_engine&groups=browser",
      "enabled": true
    }
  }
}
```

**If the client can't find `uvx`:** GUI apps (VS Code, Claude Desktop, Cursor) often don't inherit your shell's PATH, so a freshly installed `uv` (in `~/.local/bin`) may be invisible to them. Find the path with `which uvx` and put it in `command`, or skip `uvx` entirely: `pip install marketua` and use `marketua` as the command.

**Optional env vars.** The server reads `MARKETUA_DISABLE_PROVIDERS` (comma-separated:
`olx`, `hotline`, `prom`) from its own environment to disable marketplaces. Most MCP clients
(Claude Desktop, Cursor — see below) forward a per-server `env` block from the config;
OpenCode does **not** forward `env` to spawned local MCP servers, so for OpenCode export the
variable in the shell before launching it.

Then ask e.g. "Find me a used monitor up to 2000 UAH". The model picks the right tool
itself: `marketua_*` for OLX / Hotline / Prom (free), `brightdata_*` for Rozetka and other
hard-to-reach sites.

## Optional: Bright Data MCP (for Rozetka)

Rozetka is a Cloudflare-protected Angular SPA — it needs a real browser, so it goes
through Bright Data's official MCP server. **It is optional**: without it the agent
searches OLX / Hotline / Prom and says Rozetka was skipped; with it, price comparisons
cover all four marketplaces.

- Free tier: **5 000 requests/month**, no credit card. Token: Bright Data → **Settings →
  API Tokens** (not the proxy credential). The agent spends ~2–4 requests per search
  (navigate + snapshot + get_text).
- Data lives only in your chat — nothing is stored by us.

**Claude Desktop** (`claude_desktop_config.json`). The `env` block is optional —
include it only to disable marketplaces (comma-separated: `olx`, `hotline`, `prom`):

```json
{
  "mcpServers": {
    "marketua": {
      "command": "uvx",
      "args": ["marketua"],
      "env": {
        "MARKETUA_DISABLE_PROVIDERS": "prom"
      }
    },
    "brightdata": {
      "url": "https://mcp.brightdata.com/mcp?token=YOUR_TOKEN&tools=scrape_as_markdown,scrape_as_html,search_engine&groups=browser"
    }
  }
}
```

**Cursor** (`~/.cursor/mcp.json`) — same optional `env` block for disabling marketplaces:

```json
{
  "mcpServers": {
    "marketua": {
      "command": "uvx",
      "args": ["marketua"],
      "env": {
        "MARKETUA_DISABLE_PROVIDERS": "prom"
      }
    },
    "brightdata": {
      "url": "https://mcp.brightdata.com/mcp?token=YOUR_TOKEN&tools=scrape_as_markdown,scrape_as_html,search_engine&groups=browser"
    }
  }
}
```

> Hermes Agent wiring is planned as the **final milestone**, after publishing (M3) — see the
> section at the bottom of this file.

For manual verification of every tool, use MCP Inspector:

```bash
npx @modelcontextprotocol/inspector --web uvx marketua
```

## Platforms

| Marketplace | Status | Data source | Cost |
|---|---|---|---|
| OLX.ua | MVP (alpha) | public JSON API (`api/v1/offers`) | free |
| Hotline.ua | MVP (alpha) | SSR search page | free |
| Prom.ua | MVP (alpha) | SSR search (embedded JSON-LD) | free |
| Rozetka.ua | via Bright Data MCP | remote browser (JS-rendered site) | free tier: 5 000 req/mo |

## Architecture

One stable interface, many providers:

```
MCP layer (tools)  →  Provider interface  →  [OLXProvider, HotlineProvider, PromProvider]
                                         (Rozetka — via the Bright Data MCP, no provider)
```

- MCP transport: stdio (simplest, the client spawns it as a child process). No hosted
  server — shipped as a Python package (`pip install marketua` / `uvx marketua`), so each
  user runs their own local instance.
- Provider interface keeps marketplace specifics behind one abstraction, so adding a
  platform never touches the agent-facing layer.
- OLX category ids are a static snapshot (the live category endpoint is deprecated); the
  server detects stale ids at query time and warns instead of silently returning wrong
  results.
- Credentials (e.g. the Bright Data token) are configured by you in your client or shell,
  never committed.

## Roadmap

- **M0 — Spike: done.** OLX only; server connected to OpenCode, verified with MCP
  Inspector, end-to-end prompt test passes.
- **M1 — Solid MVP (OLX): done.** enum + range filters (generic discovery), sorting
  (newest server-side, price client-side), pagination, offer details, helper tools,
  prompt instructions, unit tests, E2E verified with OpenCode.
- **M2 — Multi-platform: done.** Hotline and Prom reachable directly (SSR), Rozetka via
  the Bright Data MCP browser tools; a common offer schema across platforms; provider
  config via env vars (`MARKETUA_DISABLE_PROVIDERS`).
- **M3 — Open source: done.** Public repo, MIT license, packaged for PyPI (`pip install
  marketua` / `uvx marketua`); Rozetka stays optional via the Bright Data MCP
  (OLX/Hotline/Prom work without any token).
- **Final milestone — Hermes Agent:** wire the server into Hermes (see below), once
  everything else is stable.

## Hermes Agent (final milestone)

Wiring into Hermes Agent is deliberately left for last. When the time comes:

```yaml
# Hermes config.yaml, key: mcp_servers
mcp_servers:
  marketua:
    command: "uvx"
    args: ["marketua"]
    # tools are prefixed with the server name: marketua_search_offers, ...
```

Then `hermes mcp test marketua`, and `/reload-mcp` in the chat.

## License & disclaimer

MIT. This project is educational. It uses only public, unauthenticated data and respects
`robots.txt` and rate limits. Marketplace ToS may restrict automated access — use
responsibly, keep request rates low, and do not redistribute data at scale or bypass any
access controls. The optional Bright Data MCP is a third-party service with its own ToS and
free-tier limits.
