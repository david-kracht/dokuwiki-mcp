 
# DokuWiki-MCP

An [MCP](https://modelcontextprotocol.io/) server that exposes DokuWiki's JSON-RPC API as structured tools and resources for LLM agents. Built with [FastMCP](https://github.com/jlowin/fastmcp) over SSE transport.

## Scope

- Wraps the full DokuWiki JSON-RPC surface: pages, media, ACLs, locks, search, recent changes
- Auto-generated typed client (`client.py`) from `codegen/dokuwiki.json` via Jinja2
- Auth priority: Bearer JWT → Basic Auth → `.env` fallback credentials
- 6 MCP **resources** (no params: `wiki_whoAmI`, `wiki_getWikiTitle`, …) + 20+ **tools** (parameterized: `wiki_savePage`, `wiki_searchPages`, …)

## Stack

| Layer | Technology |
|---|---|
| MCP framework | FastMCP + Uvicorn (SSE) |
| HTTP client | httpx |
| Config | pydantic-settings + `.env` |
| Wiki backend | DokuWiki (LinuxServer image) |
| Debug UI | MCP Inspector (Node.js, port 6274) |

## Quickstart

```bash
# start all services (wiki + mcp server + inspector)
docker compose up -d --build
```

| Service | URL |
|---|---|
| DokuWiki | http://localhost:8080 |
| MCP Server (SSE) | http://localhost:8000 |
| MCP Inspector | http://localhost:6274 |

## Configuration

All settings via `.env` (or environment variables in `docker-compose.yml`):

```bash
DOKUWIKI_URL=http://localhost:8080   # target wiki base URL
DOKUWIKI_URL_REWRITE=0               # 0=doku.php?id=  1=/page  2=doku.php/page

DOKUWIKI_TOKEN=<JWT>                 # preferred: short-lived JWT from DokuWiki admin
DOKUWIKI_USER=mcp-read               # fallback basic auth (ignored if token is set)
DOKUWIKI_PASSWORD=mcp

MCP_TRANSPORT=sse                    # transport protocol (sse | stdio)
HOST=0.0.0.0                         # bind address
MCP_ALLOW_ALL_HOSTS=true             # allow cross-origin requests
```

## Code Generation

The typed JSON-RPC client is generated from the DokuWiki API schema:

```bash
python codegen/generate_client.py    # regenerates src/dokuwiki_mcp/client.py
```

## Dev Accounts (docker test setup)

```bash
# admin
username: root  /  password: root

# read-only api user
username: mcp-read  /  password: mcp
groups: api, read

# write api user
username: mcp-write  /  password: mcp
groups: api, write
```

See [docker/DOKUWIKI.md](docker/DOKUWIKI.md) for full tokens and curl examples. 