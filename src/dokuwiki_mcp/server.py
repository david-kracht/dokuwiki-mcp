"""MCP server for DokuWiki JSON-RPC.

Design contract for agents and tooling:
- Endpoints without API parameters are exposed as MCP resources.
- Endpoints with one or more API parameters are exposed as MCP tools.
- Tool names follow the generated client method names (camelCase).
- Parameters and return values are passed through transparently from the client.
- Errors are returned as `RPCError` objects.
"""
import difflib
import base64
import logging
from typing import Any, List, Optional, Union

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import PromptMessage, TextContent

from .config import get_settings

from .client import (
    DokuWikiClient,
    RPCError,
    # Request parameter types
    ReqAuthorType,
    ReqBase64Type,
    ReqDepthType,
    ReqFirstType,
    ReqGroupsType,
    ReqHashType,
    ReqIsminorType,
    ReqMediaType,
    ReqNamespaceType,
    ReqOverwriteType,
    ReqPageType,
    ReqPagesType,
    ReqPassType,
    ReqPatternType,
    ReqQueryType,
    ReqRevType,
    ReqSummaryType,
    ReqTextType,
    ReqTimestampType,
    ReqUserType,
    # Response result types
    ResAclcheckresultType,
    ResAppendpageresultType,
    ResDeletemediaresultType,
    ResGetapiversionresultType,
    ResGetmediaresultType,
    ResGetmediausageresultType,
    ResGetpagebacklinksresultType,
    ResGetpagehtmlresultType,
    ResGetpageresultType,
    ResGetwikitimeresultType,
    ResGetwikititleresultType,
    ResGetwikiversionresultType,
    ResLockpagesresultType,
    ResLoginresultType,
    ResLogoffresultType,
    ResSavemediaresultType,
    ResSavepageresultType,
    ResUnlockpagesresultType,
    # Result models
    GetmediahistoryResult,
    GetmediainfoResult,
    GetpagehistoryResult,
    GetpageinfoResult,
    GetpagelinksResult,
    GetrecentmediachangesResult,
    GetrecentpagechangesResult,
    ListmediaResult,
    ListpagesResult,
    SearchpagesResult,
    WhoamiResult,
)

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DokuWikiMCP")

mcp = FastMCP("DokuWiki")

# ==============================================================================
# LLM SEO & CONTEXT INJECTION
# ==============================================================================

# Dies ist der globale Scope, den das LLM bei JEDEM Tool sehen wird.
COMMON_CONTEXT = "Wiki,DokuWiki,API:"
# Knowledge, Projects, Stations, Documentation
# Internal knowledge, Project documentation, Product documentation, Manuals, Guides,
# How-tos, Troubleshooting, Technical details, Instructions, Installation, Configuration,
# Customer support, Internal tools, Internal processes, Internal documents

def common_context(func):
    """
    Ein Decorator, der den COMMON_CONTEXT automatisch an den 
    existierenden Docstring der Funktion anhängt.
    """
    specific = (func.__doc__ or "").strip()
    sections = [COMMON_CONTEXT]
    if specific:
        sections.append(specific)
    func.__doc__ = " ".join(sections)
    return func

# ==============================================================================
# DOKUWIKI API CLIENT FACTORY
# ==============================================================================

def get_client(ctx: Context = None) -> DokuWikiClient:
    if ctx:
        headers = {}
        try:
            request_context = ctx.request_context
            request = getattr(request_context, "request", None)
            if request is not None:
                headers = getattr(request, "headers", {}) or {}
                if not headers and hasattr(request, "scope"):
                    scope_headers = request.scope.get("headers", [])
                    headers = {
                        key.decode("latin-1").lower(): value.decode("latin-1")
                        for key, value in scope_headers
                    }
        except Exception:
            headers = {}

        auth = headers.get("authorization") or headers.get("Authorization")
        if auth and auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                if ":" in decoded:
                    username, password = decoded.split(":", 1)
                    return DokuWikiClient(username=username, password=password)
            except Exception:
                pass
        elif auth and auth.lower().startswith("bearer "):
            try:
                token = auth.split(" ", 1)[1].strip()
                if token:
                    return DokuWikiClient(token=token)
            except Exception:
                pass
    return DokuWikiClient()


def _unwrap(result: Any, err: Optional[RPCError]) -> Any:
    return err if err else result

# ==============================================================================
# RESOURCES (API calls without parameters)
# ==============================================================================

@mcp.resource("dokuwiki://core/getAPIVersion")
@common_context
async def wiki_getAPIVersion(ctx: Context = None) -> Union[ResGetapiversionresultType, RPCError]:
    """Purpose: Returns the DokuWiki JSON-RPC API version number.
    Use when: Deciding compatibility before calling version-dependent API methods.
    Avoid when: Wiki release diagnostics are needed; use wiki_getWikiVersion for product version details."""
    client = get_client(ctx)
    result, err = await client.getAPIVersion()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/getWikiTime")
@common_context
async def wiki_getWikiTime(ctx: Context = None) -> Union[ResGetwikitimeresultType, RPCError]:
    """Purpose: Returns the current wiki server Unix timestamp.
    Use when: Building time-based queries (rev/timestamp windows) to avoid client clock drift.
    Avoid when: Inspecting content revisions; use wiki_getPageHistory or wiki_getMediaHistory for revision timelines."""
    client = get_client(ctx)
    result, err = await client.getWikiTime()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/getWikiTitle")
@common_context
async def wiki_getWikiTitle(ctx: Context = None) -> Union[ResGetwikititleresultType, RPCError]:
    """Purpose: Returns the configured wiki title string.
    Use when: An agent needs the canonical site label for UI messages, reports, or context grounding.
    Avoid when: Authentication or permission decisions are needed; use wiki_whoAmI and wiki_aclCheck instead."""
    client = get_client(ctx)
    result, err = await client.getWikiTitle()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/getWikiVersion")
@common_context
async def wiki_getWikiVersion(ctx: Context = None) -> Union[ResGetwikiversionresultType, RPCError]:
    """Purpose: Returns the DokuWiki application version string.
    Use when: Troubleshooting, feature gating, and environment diagnostics tied to DokuWiki release behavior.
    Avoid when: JSON-RPC protocol compatibility is needed; use wiki_getAPIVersion for API-level compatibility checks."""
    client = get_client(ctx)
    result, err = await client.getWikiVersion()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/whoAmI")
@common_context
async def wiki_whoAmI(ctx: Context = None) -> Union[WhoamiResult, RPCError]:
    """Purpose: Returns the authenticated identity (user and roles/groups) for the active session.
    Use when: Permission-sensitive operations require confirmed execution context.
    Avoid when: Credential authentication is needed; use wiki_login for explicit login."""
    client = get_client(ctx)
    result, err = await client.whoAmI()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/logoff")
@common_context
async def wiki_logoff(ctx: Context = None) -> Union[ResLogoffresultType, RPCError]:
    """Purpose: Logs off the current authenticated session and returns a success indicator.
    Use when: An agent explicitly needs to terminate a cookie/session-based login.
    Avoid when: Permission reset or token revocation is intended; this is not a substitute for ACL checks or token lifecycle control."""
    client = get_client(ctx)
    result, err = await client.logoff()
    return _unwrap(result, err)

# ==============================================================================
# TOOLS (API calls with one or more parameters)
# ==============================================================================

@mcp.tool()
@common_context
async def wiki_aclCheck(page: ReqPageType, user: ReqUserType = "", groups: ReqGroupsType = [], ctx: Context = None) -> Union[ResAclcheckresultType, RPCError]:
    """Purpose: Returns effective ACL permission level for a page/media target, optionally for a specified user/groups context.
    Use when: Write, delete, lock, or media operations require permission validation.
    Avoid when: Content discovery or search is needed; this endpoint only evaluates access rights."""
    client = get_client(ctx)
    result, err = await client.aclCheck(page=page, user=user, groups=groups)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_appendPage(page: ReqPageType, text: ReqTextType, summary: ReqSummaryType = "", isminor: ReqIsminorType = False, ctx: Context = None) -> Union[ResAppendpageresultType, RPCError]:
    """Purpose: Appends raw DokuWiki markup to the end of an existing page and creates a new revision.
    Use when: Additive updates (logs, notes, changelog entries) should preserve existing page content.
    Avoid when: Full-page replacement or structured rewrite is required; use wiki_savePage instead."""
    client = get_client(ctx)
    result, err = await client.appendPage(page=page, text=text, summary=summary, isminor=isminor)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_deleteMedia(media: ReqMediaType, ctx: Context = None) -> Union[ResDeletemediaresultType, RPCError]:
    """Purpose: Permanently deletes a media file by media ID/path.
    Use when: Obsolete or invalid binary assets must be removed intentionally.
    Avoid when: Only metadata, usage analysis, or replacement upload is needed; use wiki_getMediaInfo, wiki_getMediaUsage, or wiki_saveMedia."""
    client = get_client(ctx)
    result, err = await client.deleteMedia(media=media)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_getMedia(media: ReqMediaType, rev: ReqRevType = 0, ctx: Context = None) -> Union[ResGetmediaresultType, RPCError]:
    """Purpose: Returns Base64-encoded binary content for a media file (latest or specified revision timestamp).
    Use when: The actual file payload is needed for download, transformation, or external processing.
    Avoid when: Metadata checks, link impact checks, or history browsing is needed; use wiki_getMediaInfo, wiki_getMediaUsage, or wiki_getMediaHistory."""
    client = get_client(ctx)
    result, err = await client.getMedia(media=media, rev=rev)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_getMediaHistory(media: ReqMediaType, first: ReqFirstType = 0, ctx: Context = None) -> Union[List[GetmediahistoryResult], RPCError]:
    """Purpose: Returns revision history entries for a media file with optional offset pagination.
    Use when: Auditing change chronology or selecting a historical media revision.
    Avoid when: Media bytes are needed; use wiki_getMedia."""
    client = get_client(ctx)
    result, err = await client.getMediaHistory(media=media, first=first)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_getMediaInfo(media: ReqMediaType, rev: ReqRevType = 0, author: ReqAuthorType = False, hash: ReqHashType = False, ctx: Context = None) -> Union[GetmediainfoResult, RPCError]:
    """Purpose: Returns technical metadata for a media file (size, revision info, and optional author/hash fields).
    Use when: Validation, deduplication, or preflight checks are needed before media mutation.
    Avoid when: Full binary content is required; use wiki_getMedia."""
    client = get_client(ctx)
    result, err = await client.getMediaInfo(media=media, rev=rev, author=author, hash=hash)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_getMediaUsage(media: ReqMediaType, ctx: Context = None) -> Union[ResGetmediausageresultType, RPCError]:
    """Purpose: Returns pages that reference a specific media object.
    Use when: Deleting or replacing media requires downstream impact analysis.
    Avoid when: Listing all media in a namespace is needed; use wiki_listMedia."""
    client = get_client(ctx)
    result, err = await client.getMediaUsage(media=media)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_getPage(page: ReqPageType, rev: ReqRevType = 0, ctx: Context = None) -> Union[ResGetpageresultType, RPCError]:
    """Purpose: Returns raw DokuWiki markup for a page (latest or specified historical revision).
    Use when: Editable source text is needed for analysis, patching, or controlled rewrite workflows.
    Avoid when: Rendered view output is needed; use wiki_getPageHTML."""
    client = get_client(ctx)
    result, err = await client.getPage(page=page, rev=rev)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_getPageBackLinks(page: ReqPageType, ctx: Context = None) -> Union[ResGetpagebacklinksresultType, RPCError]:
    """Purpose: Returns pages that link to the target page (inbound references/backlinks).
    Use when: Renaming, moving, or deleting pages requires incoming dependency analysis.
    Avoid when: Outbound link extraction from the page itself is needed; use wiki_getPageLinks."""
    client = get_client(ctx)
    result, err = await client.getPageBackLinks(page=page)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_getPageHTML(page: ReqPageType, rev: ReqRevType = 0, ctx: Context = None) -> Union[ResGetpagehtmlresultType, RPCError]:
    """Purpose: Returns rendered HTML for a page revision.
    Use when: Downstream systems require rendered structure, preview output, or HTML parsing.
    Avoid when: Editing or diffing source wiki syntax is needed; use wiki_getPage."""
    client = get_client(ctx)
    result, err = await client.getPageHTML(page=page, rev=rev)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_getPageHistory(page: ReqPageType, first: ReqFirstType = 0, ctx: Context = None) -> Union[List[GetpagehistoryResult], RPCError]:
    """Purpose: Returns revision history entries for a page with optional offset pagination.
    Use when: Audit trails, rollback decisions, and revision navigation are needed.
    Avoid when: The actual page body for a revision is needed; use wiki_getPage with rev."""
    client = get_client(ctx)
    result, err = await client.getPageHistory(page=page, first=first)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_getPageInfo(page: ReqPageType, rev: ReqRevType = 0, author: ReqAuthorType = False, hash: ReqHashType = False, ctx: Context = None) -> Union[GetpageinfoResult, RPCError]:
    """Purpose: Returns technical metadata for a page (revision, size, permissions, optional author/hash details).
    Use when: Lightweight inspection is needed before deciding to read or update full content.
    Avoid when: Full source text or rendered output is needed; use wiki_getPage or wiki_getPageHTML."""
    client = get_client(ctx)
    result, err = await client.getPageInfo(page=page, rev=rev, author=author, hash=hash)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_getPageLinks(page: ReqPageType, ctx: Context = None) -> Union[List[GetpagelinksResult], RPCError]:
    """Purpose: Returns all outbound links contained in a page (internal, external, and interwiki).
    Use when: Link graph extraction, validation, or migration impact analysis is needed.
    Avoid when: Inbound reference discovery is needed; use wiki_getPageBackLinks."""
    client = get_client(ctx)
    result, err = await client.getPageLinks(page=page)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_getRecentMediaChanges(timestamp: ReqTimestampType = 0, ctx: Context = None) -> Union[List[GetrecentmediachangesResult], RPCError]:
    """Purpose: Returns recent media changes, optionally filtered to events newer than a Unix timestamp.
    Use when: Polling, incremental sync, or change-feed workflows for media assets are required.
    Avoid when: Full historical audit of one media item is needed; use wiki_getMediaHistory."""
    client = get_client(ctx)
    result, err = await client.getRecentMediaChanges(timestamp=timestamp)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_getRecentPageChanges(timestamp: ReqTimestampType = 0, ctx: Context = None) -> Union[List[GetrecentpagechangesResult], RPCError]:
    """Purpose: Returns recent page changes, optionally filtered to events newer than a Unix timestamp.
    Use when: Incremental page indexing, event polling, or delta-based synchronization is needed.
    Avoid when: Relevance-ranked content search is needed; use wiki_searchPages."""
    client = get_client(ctx)
    result, err = await client.getRecentPageChanges(timestamp=timestamp)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_listMedia(namespace: ReqNamespaceType = "", pattern: ReqPatternType = "", depth: ReqDepthType = 1, hash: ReqHashType = False, ctx: Context = None) -> Union[List[ListmediaResult], RPCError]:
    """Purpose: Lists media files in a namespace tree with optional regex filtering, depth limit, and optional hash output.
    Use when: Namespace inventory, crawl, or batch media management is required.
    Avoid when: Content-based discovery is needed; this is not a full-text search endpoint."""
    client = get_client(ctx)
    result, err = await client.listMedia(namespace=namespace, pattern=pattern, depth=depth, hash=hash)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_listPages(namespace: ReqNamespaceType = "", depth: ReqDepthType = 1, hash: ReqHashType = False, ctx: Context = None) -> Union[List[ListpagesResult], RPCError]:
    """Purpose: Lists pages in a namespace hierarchy with configurable traversal depth and optional hash values.
    Use when: Structural navigation, inventory generation, or scoped batch operations are required.
    Avoid when: Keyword relevance search across page content is needed; use wiki_searchPages."""
    client = get_client(ctx)
    result, err = await client.listPages(namespace=namespace, depth=depth, hash=hash)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_lockPages(pages: ReqPagesType, ctx: Context = None) -> Union[ResLockpagesresultType, RPCError]:
    """Purpose: Attempts to lock multiple pages and returns the subset successfully locked.
    Use when: Coordinated multi-page edits need conflict reduction.
    Avoid when: Permission probing or authentication checks are intended; use wiki_aclCheck and wiki_whoAmI."""
    client = get_client(ctx)
    result, err = await client.lockPages(pages=pages)
    return _unwrap(result or [], err)


@mcp.tool()
@common_context
async def wiki_login(user: ReqUserType, pass_: ReqPassType, ctx: Context = None) -> Union[ResLoginresultType, RPCError]:
    """Purpose: Performs explicit credential login and returns the login status indicator.
    Use when: An authenticated session must be established with username/password.
    Avoid when: Identity introspection of an already-authenticated session is needed; use wiki_whoAmI."""
    client = get_client(ctx)
    result, err = await client.login(user=user, pass_=pass_)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_saveMedia(media: ReqMediaType, base64: ReqBase64Type, overwrite: ReqOverwriteType = False, ctx: Context = None) -> Union[ResSavemediaresultType, RPCError]:
    """Purpose: Uploads Base64-encoded media content and optionally overwrites an existing media object.
    Use when: Creating or updating binary attachments and media assets.
    Avoid when: Textual page updates are needed; use wiki_savePage or wiki_appendPage."""
    client = get_client(ctx)
    result, err = await client.saveMedia(media=media, base64=base64, overwrite=overwrite)
    return _unwrap(result, err)


@mcp.tool()
@common_context
async def wiki_savePage(page: ReqPageType, text: ReqTextType, summary: ReqSummaryType = "", isminor: ReqIsminorType = False, ctx: Context = None) -> Union[ResSavepageresultType, RPCError]:
    """Purpose: Creates a page or fully replaces page content with provided raw wiki syntax.
    Use when: Target page content should be set to a specific complete state.
    Avoid when: Additive-only updates should preserve existing content; use wiki_appendPage."""
    client = get_client(ctx)
    result, err = await client.savePage(page=page, text=text, summary=summary, isminor=isminor)
    return _unwrap(result, err)

@mcp.tool()
@common_context
async def wiki_unlockPages(pages: ReqPagesType, ctx: Context = None) -> Union[ResUnlockpagesresultType, RPCError]:
    """Purpose: Attempts to unlock multiple pages and returns the subset successfully unlocked.
    Use when: Locks must be released after coordinated edit workflows.
    Avoid when: Saving or conflict resolution logic is required; this endpoint only changes lock state."""
    client = get_client(ctx)
    result, err = await client.unlockPages(pages=pages)
    return _unwrap(result or [], err)


# ==============================================================================
# PROMPTS (Workflow-Vorlagen für das LLM)
# ==============================================================================

# @mcp.prompt()
# @common_context
# def wiki_researcher(topic: str) -> list[PromptMessage]:
#     """
#     Startet einen Recherche-Workflow im Wiki mit garantierter Quellenangabe (URLs).
#     """
#     settings = get_settings()
#     base_root = settings.dokuwiki_url.rstrip("/")
#     if settings.dokuwiki_url_rewrite == 1:
#         base_url = f"{base_root}/"
#     elif settings.dokuwiki_url_rewrite == 2:
#         base_url = f"{base_root}/doku.php/"
#     else:
#         base_url = f"{base_root}/doku.php?id="

#     # Trick 1: Wir definieren die Regeln als "UNVERHANDELBAR"
#     rules = f"""
#         ### FORMATIERUNGS-GESETZ:
#         1. Jede Information bekommt eine Nummer [1], [2] etc.
#         2. Am Ende folgt die Sektion "### Quellen & Links".
#         3. Jeder Link MUSS absolut sein: {base_url}page
#         4. Nutze Markdown-Links: [Titel der Seite]({base_url}page)
#     """.strip()

#     # --- 1. SYSTEM PROMPT (Die Identität und das Regelwerk) ---
#     system_content = f"""
#         Du bist ein technischer Recherche-Assistent für unser internes Firmen-Wiki.
#         Deine Aufgabe ist es, Informationen präzise zu finden, zusammenzufassen und Quellen korrekt zu belegen.

#         GEHE STRENG NACH DIESEM WORKFLOW VOR:
#         1. Listen: Nutze 'wiki_listPages', um ausgehend von Namespace '{{namespace}}' bis Tiefe '{{depth}}' Seiten zu finden.
#         2. Suchen: Nutze 'wiki_searchPages' mit einer optimierten '{{query}}' für das Thema.
#         3. Lesen: Nutze 'wiki_getPage', um die Inhalte der relevantesten Seiten zu extrahieren.
#         4. Aktualität: Nutze 'wiki_getRecentPageChanges', um Änderungen seit '{{unix_timestamp}}' zu prüfen.
#         5. Historie: Nutze 'wiki_getPageHistory' für Seite '{{page}}', überspringe dabei '{{first}}' Revisionen.
#         6. Synthese: Erstelle eine strukturierte Zusammenfassung.

#         {rules}

#         ANTWORTE NUR WENN DU LINKS GENERIERST.
#     """.strip()

#     # --- 2. USER PROMPT (Der spezifische Arbeitsauftrag) ---
#     user_content = f"Recherchiere bitte alle verfügbaren Informationen zum Thema: '{topic}'."

#     # --- Die Rückgabe mit den richtigen MCP-Typen ---
#     return [
#         PromptMessage(
#             # should be system role, but FastMCP currently only supports user prompts, 
#             # so we use user role for both (1st with higher priority in the prompt template)
#             role="user",
#             content=TextContent(type="text", text=' '.join(system_content.split()))
#         ),
#         PromptMessage(
#             role="user",
#             content=TextContent(type="text", text=' '.join(user_content.split()))
#         )
#     ]



# --- HILFSFUNKTION FÜR KORREKTE LINKS ---
def get_markdown_link(page: str, title: str = None) -> str:
    """
    Baut einen fertigen, klickbaren Markdown-Link für VS Code.
    Nutzt die DokuWiki URL-Rewrite Einstellungen aus deiner Config.
    """
    settings = get_settings()
    base_root = settings.dokuwiki_url.rstrip("/")
    
    if settings.dokuwiki_url_rewrite == 1:
        url = f"{base_root}/{page}"
    elif settings.dokuwiki_url_rewrite == 2:
        url = f"{base_root}/doku.php/{page}"
    else:
        url = f"{base_root}/doku.php?id={page}"
        
    display_text = title if title else page
    # Gibt z.B. zurück: [wiki:syntax](http://localhost:8080/doku.php?id=wiki:syntax)
    return f"[{display_text}]({url})"


# --- TOOL 1: SUCHE MIT FERTIGEN LINKS ---
@mcp.tool()
@common_context
async def wiki_searchPages(query: ReqQueryType, ctx: Context = None) -> str:
    """
    Sucht im Wiki. Liefert klickbare Markdown-Links zurück, 
    die der Agent direkt an den User weitergeben MUSS.
    """
    client = get_client(ctx)
    results, err = await client.searchPages(query=query)
    
    if not results:
        return f"Keine Ergebnisse für '{query}' gefunden."

    # Wir zwingen das Markdown direkt in die Tool-Antwort!
    output_lines = [f"Ergebnisse für '{query}':"]
    for res in results[:15]: # Max 15
        page = res.get('id')
        title = res.get('title', page)
        # HIER PASSIERT DIE MAGIE:
        md_link = get_markdown_link(page, title)
        output_lines.append(f"- {md_link}")
        
    return "\n".join(output_lines)


# --- TOOL 2: DAS PREVIEW / DIFF TOOL ---
@mcp.tool()
@common_context
async def wiki_preview_edit(page: ReqPageType, new_content: ReqTextType, ctx: Context = None) -> str:
    """
    Zeigt einen Markdown-Diff VOR dem Speichern.
    """
    try:
        client = get_client(ctx)
        old_content, err = await client.getPage(page=page)
        
        # Diff berechnen
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"Original",
            tofile=f"KI-Änderung",
            lineterm=""
        )
        diff_text = "\n".join(diff)
        
        if not diff_text:
            return f"INFO: Keine Änderungen für {page} erkannt."

        # Den fertigen Link zur Seite generieren
        md_link = get_markdown_link(page)

        # Die Rückgabe zwingt das LLM in ein wunderschönes Format
        return (
            f"WICHTIG: Gib dem User exakt diesen Text aus, damit er den Link klicken kann:\n\n"
            f"### Änderungsvorschlag für {md_link}\n"
            f"Bitte prüfe den folgenden Diff:\n"
            f"```diff\n{diff_text}\n```\n"
            f"\n**Soll ich das speichern? (Nutze danach das Tool 'wiki_edit_page')**"
        )
    except Exception as e:
        return f"Fehler bei Vorschau: {str(e)}"


# ==============================================================================
# MAIN ENTRYPOINT - SERVER LAUNCH WITH ENVIRONMENT-BASED CONFIGURATION
# ==============================================================================

if __name__ == "__main__":
    import os
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()

    if transport != "stdio":
        import uvicorn
        
        original_init = uvicorn.Config.__init__
        
        def patched_init(self, *args, **kwargs):
            kwargs['host'] = os.environ.get("HOST", "0.0.0.0")
            
            # --- HOST HEADER FIX (Production-Ready) ---
            # Wird nur aktiviert, wenn MCP_ALLOW_ALL_HOSTS=true gesetzt ist
            allow_all_hosts = os.environ.get("MCP_ALLOW_ALL_HOSTS", "false").lower() == "true"
            
            if allow_all_hosts:
                app = kwargs.get('app')
                if not app and args:
                    app = args[0]
                    args = args[1:]
                    
                if app:
                    async def host_rewrite_app(scope, receive, send):
                        if scope["type"] in ("http", "websocket"):
                            # FastMCP erlaubt standardmäßig localhost nur mit Port-Pattern (localhost:*).
                            # Einige Clients senden jedoch Host ohne Port; daher erzwingen wir localhost:8000.
                            scope["headers"] = [
                                (b"host", b"localhost:8000") if k == b"host" else (k, v)
                                for k, v in scope.get("headers", [])
                            ]
                        await app(scope, receive, send)
                    kwargs['app'] = host_rewrite_app
            # ------------------------------------------
            
            original_init(self, *args, **kwargs)
        uvicorn.Config.__init__ = patched_init


    mcp.run(transport="sse" if transport != "stdio" else "stdio")