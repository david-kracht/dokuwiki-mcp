 
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

## Maturity Matrix & Implementation Coverage

Die folgende Tabelle gibt den aktuellen Reifegrad und die Abdeckung der Architektur-Konzepte (gemäß `architecture_adr_prd/02_matrix_category_concept.md` und `03_future_maturity_plan.md`) im Codebase wieder:

| Kategorie | Konzept | Status | Tool & Methode (`src/dokuwiki_mcp/server.py`) | Abgedeckte Teilaspekte | Offene / Fehlende Aspekte |
|---|---|---|---|---|---|
| **Architecture Base** | **DTO Pattern** | ✅ Implementiert | Super-Tools (`wiki_*`) vs. Pydantic RPC Client (`client.py`) | Entkopplung von internen RPC-Typen zu verdichteten, LLM-optimierten Interfaces | - |
| | **Polymorphic Tooling** | ✅ Implementiert | 5 Super-Tools mit `action` Enums | Konsolidierung der API-Fläche zur Tool-Bloat-Vermeidung | - |
| | **Graceful Degradation** | ✅ Implementiert | `wiki_raw_proxy` & `dokuwiki://raw_api_spec` Resource | Sicheres Fallback auf raw JSON-RPC mit auto-generierter Dokumentations-Spec | - |
| | **Error as Actionable Prompts** | ✅ Implementiert | `_unwrap`, `ActionableDokuWikiError`, `_log_error_trace_stack` | Konkrete Handlungsempfehlungen (Hints) bei HTTP/RPC-Fehlern statt Stacktraces | - |
| **Read & Search (Input-Kompression)** | **Layout Stripping** | ✅ Implementiert | `wiki_read_content` (`format="markdown"`, `_dokuwiki_to_markdown`) | DokuWiki-Markup Transformation in sauberes Markdown | - |
| | **Lokale Keyword-Extraktion** | ✅ Implementiert | `wiki_read_content` (`action="extract_insights"`, YAKE) | Lokale NLP-Extraktion der Top-Keywords ohne LLM-Tokenverbrauch | - |
| | **Progressive Disclosure** | ✅ Implementiert | `wiki_read_content` (`action="get_structure"`, `section_id`) | Abruf des TOC-Trees & bedarfsgerechtes Nachladen von Kapiteln | - |
| | **Meta-Data Aggregation** | ✅ Implementiert | Tool Output Headers & `wiki_admin_and_meta` | Kompakte Zusammenfassung von ACLs, Autoren und Revisionsdaten | - |
| | **Pagination Abstraction** | ✅ Implementiert | `wiki_search_and_explore` | Transparente serverseitige Aggregation großer Listen/Treffer | - |
| | **Extrahierende Zusammenfassung** | ⏳ Geplant (P2) | `wiki_read_content` | Konzept definiert (TF-IDF / TextRank) | Fehlt im Code (Lokaler Sentence Summarizer Engine) |
| | **Backlink Contextualization** | ⏳ Geplant (P2) | `wiki_read_content` (`action="get_links"`) | Link-Discovery | Fehlt im Code (Satz-Kontext aus verweisenden Seiten) |
| | **Content Chunking / Flat-File Read** | 🛑 Postponed | Dateisystem / PHP Plugin | - | Direkter `.txt` Datei-Zugriff / AST Tree Parsing auf später verschoben |
| **Read & Search (Output-Optimierung)** | **Multi-Query Batching & Compound Action Chaining** | ✅ Implementiert | `wiki_batch_execute` & `wiki_search_and_explore` | Heterogene Parallel-Ausführung von Macro-Tool-Arrays in einem einzigen Roundtrip | - |
| | **Negative Prompting** | ✅ Implementiert | `wiki_search_and_explore` (`exclusions: List[str]`) | Serverseitiges Filtern und Ausschließen irrelevanter Namespaces | - |
| | **Fuzzy Resolution** | ✅ Implementiert | `_resolve_page_id`, `_resolve_media_id`, `_resolve_namespace` | Levenshtein-Distanz Korrektur bei Tippfehlern in Page/Media IDs & Namespaces | - |
| | **Regex-gestützte Extraktion** | ✅ Implementiert | `wiki_search_and_explore` (`pattern`), `wiki_read_content` (`regex_filter`) | Zeilen- & ID-Filtering nach Regex-Muster | - |
| | **Zeitliche Filter** | ✅ Implementiert | `wiki_search_and_explore` (`modified_after`) | Datums- & Timestamp-basierte Einschränkung der Treffermenge | - |
| | **Stateful Namespace Traversal** | ✅ Implementiert | `wiki_admin_and_meta` (`action="set_namespace"`), `_SESSION_NAMESPACES` | In-Memory Session-Speicherung des aktiven Namespace Contexts | - |
| **Agentic Authoring (Schreiben)** | **Two-Phase Commit (Plan/Exec)** | ✅ Implementiert | `wiki_write_and_modify` (`prepare_write`, `dry_run`, `commit`, `rollback`) | Entwurfs-Speicherung (UUID), Diff-Vorschau und explizites Commit | - |
| | **Section-Level Edits** | ✅ Implementiert | `wiki_write_and_modify` (`action="modify_section"`, `section_id`) | Gezieltes Editieren einzelner Kapitel-Blöcke | - |
| | **Syntax Linting Hook** | ✅ Implementiert | `_lint_dokuwiki_syntax()` | Validierung der DokuWiki-Syntax vor Schreib- & Patch-Aktionen | - |
| | **Conflict Resolution** | ⏳ Geplant (P1) | `wiki_write_and_modify` | Concurrent Edit Erkennung (Timestamp Match) | Fehlt im Code (Zwei-Wege Merge mit Diff-Conflict-Markern) |
| | **Tone & Voice Alignment** | ⏳ Geplant (P1) | `wiki_read_content` | Standard Output Formatting | Fehlt im Code (Namespace-spezifische Stilrichtlinien im Response-Header) |
| | **Automated Taxonomy** | ⏳ Geplant (P1) | `wiki_write_and_modify` | YAKE Keyword Matcher vorbereitet | Fehlt im Code (Auto-Injektion des `{{tag>...}}` Blocks beim Speichern) |
| **Tracing & Infrastructure** | **Session Metrics & Traceability** | ✅ Implementiert | `_log_tool_invocation`, `_log_tool_error`, `_log_error_trace_stack` | Request-ID Tracing, strukturierte JSON Audit Logs & Error Metrics | - |
| | **6-Tier Domain Caching & Invalidation** | ✅ Implementiert | `cachetools.TTLCache` in `server.py` | Granulare 6-Tier Caches (Page/Media List, Info, Content + System Meta) & Hit Metrics Summary Logger | - |

