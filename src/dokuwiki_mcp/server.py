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
from typing import Any, List, Optional, Union, Annotated
from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import PromptMessage, TextContent

from .config import get_settings

from .client import (
    DokuWikiClient,
    RPCError,
    # New request parameter types
    AuthorRequestType,
    Base64RequestType,
    DepthRequestType,
    FirstRequestType,
    GroupsRequestType,
    HashRequestType,
    IsminorRequestType,
    MediaRequestType,
    NamespaceRequestType,
    OverwriteRequestType,
    PageRequestType,
    PagesRequestType,
    PassRequestType,
    PatternRequestType,
    QueryRequestType,
    RevRequestType,
    SummaryRequestType,
    TextRequestType,
    TimestampRequestType,
    UserRequestType,
    # New response/result types
    AclCheckResultType,
    AppendPageResultType,
    DeleteMediaResultType,
    GetAPIVersionResultType,
    GetMediaResultType,
    GetMediaUsageResultType,
    GetPageBackLinksResultType,
    GetPageHTMLResultType,
    GetPageResultType,
    GetWikiTimeResultType,
    GetWikiTitleResultType,
    GetWikiVersionResultType,
    LockPagesResultType,
    LoginResultType,
    LogoffResultType,
    SaveMediaResultType,
    SavePageResultType,
    UnlockPagesResultType,
    # New result models
    GetMediaHistoryResult,
    GetMediaInfoResult,
    GetPageHistoryResult,
    GetPageInfoResult,
    GetPageLinksResult,
    GetRecentMediaChangesResult,
    GetRecentPageChangesResult,
    ListMediaResult,
    ListPagesResult,
    SearchPagesResult,
    WhoAmIResult,
)


# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DokuWikiMCP")

mcp = FastMCP("DokuWiki")

# ==============================================================================
# LLM SEO & CONTEXT INJECTION
# ==============================================================================

# Dies ist der globale Scope, den das LLM bei JEDEM Tool sehen wird.
COMMON_CONTEXT = "Wiki,DokuWiki"
# Knowledge, Projects, Stations, Documentation
# Internal knowledge, Project documentation, Product documentation, Manuals, Guides,
# How-tos, Troubleshooting, Technical details, Instructions, Installation, Configuration,
# Customer support, Internal tools, Internal processes, Internal documents

def common_context(func, context=COMMON_CONTEXT):
    """
    Ein Decorator, der den COMMON_CONTEXT automatisch an den 
    existierenden Docstring der Funktion anhängt.
    """
    specific = (func.__doc__ or "").strip()
    sections = [context.strip()]
    if specific:
        sections.append(specific)
    func.__doc__ = ". ".join(sections)
    return func

def api_context(func):
    return common_context(func, context="DokuWiki JSON-RPC API (Wrapper)")

def api_ext_context(func):
    return common_context(func, context="DokuWiki JSON-RPC API (extended)")


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

@mcp.resource(
    "dokuwiki://core/getAPIVersion",
    annotations={
        "title": "Get DokuWiki JSON-RPC API version",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getAPIVersion(ctx: Context = None) -> Union[GetAPIVersionResultType, RPCError]:
    """
    PURPOSE: Returns the DokuWiki JSON-RPC API version number.
    PREREQUISITES: None.
    USE WHEN: Deciding compatibility before calling version-dependent API methods.
    AVOID WHEN: Wiki release diagnostics are needed; use wiki_getWikiVersion for product version details.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: API version string or error details.
    NEXT STEPS: Use version for compatibility checks.
    """
    client = get_client(ctx)
    result, err = await client.getAPIVersion()
    return _unwrap(result, err)


@mcp.resource(
    "dokuwiki://core/getWikiTime",
    annotations={
        "title": "Get current wiki server time",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getWikiTime(ctx: Context = None) -> Union[GetWikiTimeResultType, RPCError]:
    """
    PURPOSE: Returns the current wiki server Unix timestamp.
    PREREQUISITES: None.
    USE WHEN: Building time-based queries (rev/timestamp windows) to avoid client clock drift.
    AVOID WHEN: Inspecting content revisions; use wiki_getPageHistory or wiki_getMediaHistory for revision timelines.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Current Unix timestamp or error details.
    NEXT STEPS: Use timestamp for time-based queries.
    """
    client = get_client(ctx)
    result, err = await client.getWikiTime()
    return _unwrap(result, err)


@mcp.resource(
    "dokuwiki://core/getWikiTitle",
    annotations={
        "title": "Get configured wiki title",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getWikiTitle(ctx: Context = None) -> Union[GetWikiTitleResultType, RPCError]:
    """
    PURPOSE: Returns the configured wiki title string.
    PREREQUISITES: None.
    USE WHEN: An agent needs the canonical site label for UI messages, reports, or context grounding.
    AVOID WHEN: Authentication or permission decisions are needed; use wiki_whoAmI and wiki_aclCheck instead.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Wiki title string or error details.
    NEXT STEPS: Use for UI or context display.
    """
    client = get_client(ctx)
    result, err = await client.getWikiTitle()
    return _unwrap(result, err)


@mcp.resource(
    "dokuwiki://core/getWikiVersion",
    annotations={
        "title": "Get DokuWiki application version",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getWikiVersion(ctx: Context = None) -> Union[GetWikiVersionResultType, RPCError]:
    """
    PURPOSE: Returns the DokuWiki application version string.
    PREREQUISITES: None.
    USE WHEN: Troubleshooting, feature gating, and environment diagnostics tied to DokuWiki release behavior.
    AVOID WHEN: JSON-RPC protocol compatibility is needed; use wiki_getAPIVersion for API-level compatibility checks.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Application version string or error details.
    NEXT STEPS: Use for diagnostics or feature gating.
    """
    client = get_client(ctx)
    result, err = await client.getWikiVersion()
    return _unwrap(result, err)


@mcp.resource(
    "dokuwiki://core/whoAmI",
    annotations={
        "title": "Get current authenticated identity",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_whoAmI(ctx: Context = None) -> Union[WhoAmIResult, RPCError]:
    """
    PURPOSE: Returns the authenticated identity (user and roles/groups) for the active session.
    PREREQUISITES: None.
    USE WHEN: Permission-sensitive operations require confirmed execution context.
    AVOID WHEN: Credential authentication is needed; use wiki_login for explicit login.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: User identity and group info or error details.
    NEXT STEPS: Use for permission checks or UI display.
    """
    client = get_client(ctx)
    result, err = await client.whoAmI()
    return _unwrap(result, err)


@mcp.resource(
    "dokuwiki://core/logoff",
    annotations={
        "title": "Log off current session",
        "readOnlyHint": False,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_logoff(ctx: Context = None) -> Union[LogoffResultType, RPCError]:
    """
    PURPOSE: Logs off the current authenticated session and returns a success indicator.
    PREREQUISITES: User must be authenticated.
    USE WHEN: An agent explicitly needs to terminate a cookie/session-based login.
    AVOID WHEN: Permission reset or token revocation is intended; this is not a substitute for ACL checks or token lifecycle control.
    PRECAUTIONS: Session will be terminated; further calls require re-authentication.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Success indicator (true/false) or error details.
    NEXT STEPS: Re-authenticate if further actions are needed.
    """
    client = get_client(ctx)
    result, err = await client.logoff()
    return _unwrap(result, err)

# ==============================================================================
# TOOLS (API calls with one or more parameters)
# ==============================================================================

@mcp.tool(
    annotations={
        "title": "Check ACL permissions for page/media",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_aclCheck(page: PageRequestType, user: UserRequestType = "", groups: GroupsRequestType = [], ctx: Context = None) -> Union[AclCheckResultType, RPCError]:
    """
    PURPOSE: Returns effective ACL permission level for a page/media target, optionally for a specified user/groups context.
    PREREQUISITES: None.
    USE WHEN: Write, delete, lock, or media operations require permission validation.
    AVOID WHEN: Content discovery or search is needed; this endpoint only evaluates access rights.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Permission level or error details.
    NEXT STEPS: Use result to control access or UI state.
    """
    client = get_client(ctx)
    result, err = await client.aclCheck(page=page, user=user, groups=groups)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Append text to page (new revision)",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_appendPage(page: PageRequestType, text: TextRequestType, summary: SummaryRequestType = "", isminor: IsminorRequestType = False, ctx: Context = None) -> Union[AppendPageResultType, RPCError]:
    """
    PURPOSE: Appends raw DokuWiki markup to the end of an existing page and creates a new revision.
    PREREQUISITES: Page must exist and user must have write permissions.
    USE WHEN: Additive updates (logs, notes, changelog entries) should preserve existing page content.
    AVOID WHEN: Full-page replacement or structured rewrite is required; use wiki_savePage instead.
    PRECAUTIONS: Appends to existing content.
    COSTS: New revision created, minimal payload.
    EXPECTED OUTPUT: Success indicator or error details.
    NEXT STEPS: Use for incremental updates or logging.
    """
    client = get_client(ctx)
    result, err = await client.appendPage(page=page, text=text, summary=summary, isminor=isminor)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Delete media file",
        "readOnlyHint": False,
        "idempotentHint": True,
        "destructiveHint": True,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_deleteMedia(media: MediaRequestType, ctx: Context = None) -> Union[DeleteMediaResultType, RPCError]:
    """
    PURPOSE: Permanently deletes a media file by media ID/path.
    PREREQUISITES: Media must exist and user must have delete permissions.
    USE WHEN: Obsolete or invalid binary assets must be removed intentionally.
    AVOID WHEN: Only metadata, usage analysis, or replacement upload is needed; use wiki_getMediaInfo, wiki_getMediaUsage, or wiki_saveMedia.
    PRECAUTIONS: You MUST acknowledge deletion: Deletion is irreversible; ensure correct media ID.
    COSTS: Media file is removed, minimal payload.
    EXPECTED OUTPUT: Success indicator or error details.
    NEXT STEPS: Confirm deletion or update references.
    """
    client = get_client(ctx)
    result, err = await client.deleteMedia(media=media)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Get media file (Base64)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getMedia(media: MediaRequestType, rev: RevRequestType = 0, ctx: Context = None) -> Union[GetMediaResultType, RPCError]:
    """
    PURPOSE: Returns Base64-encoded binary content for a media file (latest or specified revision timestamp).
    PREREQUISITES: Media must exist and user must have read permissions.
    USE WHEN: The actual file payload is needed for download, transformation, or external processing.
    AVOID WHEN: Metadata checks, link impact checks, or history browsing is needed; use wiki_getMediaInfo, wiki_getMediaUsage, or wiki_getMediaHistory.
    PRECAUTIONS: Large files may impact response size.
    COSTS: Returns binary content as Base64 string.
    EXPECTED OUTPUT: Base64-encoded file or error details.
    NEXT STEPS: Use for download or processing.
    """
    client = get_client(ctx)
    result, err = await client.getMedia(media=media, rev=rev)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Get media file revision history",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getMediaHistory(media: MediaRequestType, first: FirstRequestType = 0, ctx: Context = None) -> Union[List[GetMediaHistoryResult], RPCError]:
    """
    PURPOSE: Returns revision history entries for a media file with optional offset pagination.
    PREREQUISITES: Media must exist and user must have read permissions.
    USE WHEN: Auditing change chronology or selecting a historical media revision.
    AVOID WHEN: Media bytes are needed; use wiki_getMedia.
    PRECAUTIONS: Large history may impact response size.
    COSTS: Returns list of revision entries.
    EXPECTED OUTPUT: List of revision history or error details.
    NEXT STEPS: Use for audit or rollback decisions.
    """
    client = get_client(ctx)
    result, err = await client.getMediaHistory(media=media, first=first)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Get media file metadata",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getMediaInfo(media: MediaRequestType, rev: RevRequestType = 0, author: AuthorRequestType = False, hash: HashRequestType = False, ctx: Context = None) -> Union[GetMediaInfoResult, RPCError]:
    """
    PURPOSE: Returns technical metadata for a media file (size, revision info, and optional author/hash fields).
    PREREQUISITES: Media must exist and user must have read permissions.
    USE WHEN: Validation, deduplication, or preflight checks are needed before media mutation.
    AVOID WHEN: Full binary content is required; use wiki_getMedia.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Metadata object or error details.
    NEXT STEPS: Use for validation or deduplication.
    """
    client = get_client(ctx)
    result, err = await client.getMediaInfo(media=media, rev=rev, author=author, hash=hash)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Get pages referencing media",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getMediaUsage(media: MediaRequestType, ctx: Context = None) -> Union[GetMediaUsageResultType, RPCError]:
    """
    PURPOSE: Returns pages that reference a specific media object.
    PREREQUISITES: Media must exist and user must have read permissions.
    USE WHEN: Deleting or replacing media requires downstream impact analysis.
    AVOID WHEN: Listing all media in a namespace is needed; use wiki_listMedia.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: List of referencing pages or error details.
    NEXT STEPS: Use for impact analysis before deletion.
    """
    client = get_client(ctx)
    result, err = await client.getMediaUsage(media=media)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Get raw page markup",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPage(page: PageRequestType, rev: RevRequestType = 0, ctx: Context = None) -> Union[GetPageResultType, RPCError]:
    """
    PURPOSE: Returns raw DokuWiki markup for a page (latest or specified historical revision).
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: Editable full source text is needed for analysis, patching, or controlled rewrite workflows.
    AVOID WHEN: Only partial information is sufficient. Rendered view output is needed: use wiki_getPageHTML.
    PRECAUTIONS: None.
    COSTS: Can be very high for large pages. Consider using dedicating more specific tools before fetching full page content.
    EXPECTED OUTPUT: Page markup or error details.
    NEXT STEPS: Use for editing or analysis.
    """
    client = get_client(ctx)
    result, err = await client.getPage(page=page, rev=rev)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Get inbound page backlinks",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPageBackLinks(page: PageRequestType, ctx: Context = None) -> Union[GetPageBackLinksResultType, RPCError]:
    """
    PURPOSE: Returns pages that link to the target page (inbound references/backlinks).
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: Renaming, moving, or deleting pages requires incoming dependency analysis.
    AVOID WHEN: Outbound link extraction from the page itself is needed; use wiki_getPageLinks.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: List of inbound links or error details.
    NEXT STEPS: Use for dependency analysis before changes.
    """
    client = get_client(ctx)
    result, err = await client.getPageBackLinks(page=page)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Get rendered page HTML",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPageHTML(page: PageRequestType, rev: RevRequestType = 0, ctx: Context = None) -> Union[GetPageHTMLResultType, RPCError]:
    """
    PURPOSE: Returns rendered HTML for a page revision.
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: Downstream systems require fully rendered structure, preview output, or HTML parsing.
    AVOID WHEN: Only partial information is sufficient. Editing or diffing source wiki syntax is needed; use wiki_getPage.
    PRECAUTIONS: None.
    COSTS: Can be very high for large pages. Consider using dedicating more specific tools before fetching full page content.
    EXPECTED OUTPUT: Rendered HTML or error details.
    NEXT STEPS: Use for preview or downstream processing.
    """
    client = get_client(ctx)
    result, err = await client.getPageHTML(page=page, rev=rev)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Get page revision history",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPageHistory(page: PageRequestType, first: FirstRequestType = 0, ctx: Context = None) -> Union[List[GetPageHistoryResult], RPCError]:
    """
    PURPOSE: Returns revision history entries for a page with optional offset pagination.
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: Audit trails, rollback decisions, and revision navigation are needed.
    AVOID WHEN: The actual page body for a revision is needed; use wiki_getPage with rev.
    PRECAUTIONS: Large history may impact response size.
    COSTS: Returns list of revision entries.
    EXPECTED OUTPUT: List of revision history or error details.
    NEXT STEPS: Use for audit or rollback decisions.
    """
    client = get_client(ctx)
    result, err = await client.getPageHistory(page=page, first=first)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Get page metadata",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPageInfo(page: PageRequestType, rev: RevRequestType = 0, author: AuthorRequestType = False, hash: HashRequestType = False, ctx: Context = None) -> Union[GetPageInfoResult, RPCError]:
    """
    PURPOSE: Returns technical metadata for a page (revision, size, permissions, optional author/hash details).
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: Lightweight inspection is needed before deciding to read or update full content.
    AVOID WHEN: Full source text or rendered output is needed; use wiki_getPage or wiki_getPageHTML.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Metadata object or error details.
    NEXT STEPS: Use for inspection or validation.
    """
    client = get_client(ctx)
    result, err = await client.getPageInfo(page=page, rev=rev, author=author, hash=hash)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Get outbound page links",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPageLinks(page: PageRequestType, ctx: Context = None) -> Union[List[GetPageLinksResult], RPCError]:
    """
    PURPOSE: Returns all outbound links contained in a page (internal, external, and interwiki).
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: Link graph extraction, validation, or migration impact analysis is needed.
    AVOID WHEN: Inbound reference discovery is needed; use wiki_getPageBackLinks.
    PRECAUTIONS: None.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: List of outbound links or error details.
    NEXT STEPS: Use for link graph or migration analysis.
    """
    client = get_client(ctx)
    result, err = await client.getPageLinks(page=page)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Get recent media changes",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getRecentMediaChanges(timestamp: TimestampRequestType = 0, ctx: Context = None) -> Union[List[GetRecentMediaChangesResult], RPCError]:
    """
    PURPOSE: Returns recent media changes, optionally filtered to events newer than a Unix timestamp.
    PREREQUISITES: None.
    USE WHEN: Polling, incremental sync, or change-feed workflows for media assets are required.
    AVOID WHEN: Full historical audit of one media item is needed; use wiki_getMediaHistory.
    PRECAUTIONS: None.
    COSTS: Can be high if many changes; consider using timestamp filters to limit results.
    EXPECTED OUTPUT: List of recent changes or error details.
    NEXT STEPS: Use for sync or monitoring.
    """
    client = get_client(ctx)
    result, err = await client.getRecentMediaChanges(timestamp=timestamp)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Get recent page changes",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getRecentPageChanges(timestamp: TimestampRequestType = 0, ctx: Context = None) -> Union[List[GetRecentPageChangesResult], RPCError]:
    """
    PURPOSE: Returns recent page changes, optionally filtered to events newer than a Unix timestamp.
    PREREQUISITES: None.
    USE WHEN: Incremental page indexing, event polling, or delta-based synchronization is needed.
    AVOID WHEN: Relevance-ranked content search is needed; use wiki_searchPages.
    PRECAUTIONS: None.
    COSTS: Can be high if many changes; consider using timestamp filters to limit results.
    EXPECTED OUTPUT: List of recent changes or error details.
    NEXT STEPS: Use for sync or monitoring.
    """
    client = get_client(ctx)
    result, err = await client.getRecentPageChanges(timestamp=timestamp)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "List media files in namespace",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_listMedia(namespace: NamespaceRequestType = "", pattern: PatternRequestType = "", depth: DepthRequestType = 1, hash: HashRequestType = False, ctx: Context = None) -> Union[List[ListMediaResult], RPCError]:
    """
    PURPOSE: Lists media files in a namespace tree with optional regex filtering, depth limit, and optional hash output.
    PREREQUISITES: None.
    USE WHEN: Namespace inventory, crawl, or batch media management is required.
    AVOID WHEN: Content-based discovery is needed; this is not a full-text search endpoint.
    PRECAUTIONS: None.
    COSTS: Can be high if many media files; consider using pattern and depth filters to limit results.
    EXPECTED OUTPUT: List of media files or error details.
    NEXT STEPS: Use for inventory or batch operations.
    """
    client = get_client(ctx)
    result, err = await client.listMedia(namespace=namespace, pattern=pattern, depth=depth, hash=hash)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "List pages in namespace hierarchy",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_listPages(namespace: NamespaceRequestType = "", depth: DepthRequestType = 1, hash: HashRequestType = False, ctx: Context = None) -> Union[List[ListPagesResult], RPCError]:
    """
    PURPOSE: Lists pages in a namespace hierarchy with configurable traversal depth and optional hash values.
    PREREQUISITES: None.
    USE WHEN: Structural navigation, inventory generation, or scoped batch operations are required.
    AVOID WHEN: Keyword relevance search across page content is needed; use wiki_searchPages.
    PRECAUTIONS: None.
    COSTS: Can be high if many pages; consider using depth and hash filters to limit results.
    EXPECTED OUTPUT: List of pages or error details.
    NEXT STEPS: Use for navigation or batch operations.
    """
    client = get_client(ctx)
    result, err = await client.listPages(namespace=namespace, depth=depth, hash=hash)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Lock multiple pages",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_lockPages(pages: PagesRequestType, ctx: Context = None) -> Union[LockPagesResultType, RPCError]:
    """
    PURPOSE: Attempts to lock multiple pages and returns the subset successfully locked.
    PREREQUISITES: Pages must exist and user must have lock permissions.
    USE WHEN: Coordinated multi-page edits need conflict reduction.
    AVOID WHEN: Permission probing or authentication checks are intended; use wiki_aclCheck and wiki_whoAmI.
    PRECAUTIONS: Locks may expire or be overridden.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: List of locked pages or error details.
    NEXT STEPS: Proceed with coordinated edits.
    """
    client = get_client(ctx)
    result, err = await client.lockPages(pages=pages)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Login with credentials",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_login(user: UserRequestType, pass_: PassRequestType, ctx: Context = None) -> Union[LoginResultType, RPCError]:
    """
    PURPOSE: Performs explicit credential login and returns the login status indicator.
    PREREQUISITES: Valid username and password required.
    USE WHEN: An authenticated session must be established with username/password.
    AVOID WHEN: Identity introspection of an already-authenticated session is needed; use wiki_whoAmI.
    PRECAUTIONS: Credentials are sensitive; handle securely.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Login status or error details.
    NEXT STEPS: Use session for further API calls.
    """
    client = get_client(ctx)
    result, err = await client.login(user=user, pass_=pass_)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Upload or overwrite media file",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_saveMedia(media: MediaRequestType, base64: Base64RequestType, overwrite: OverwriteRequestType = False, ctx: Context = None) -> Union[SaveMediaResultType, RPCError]:
    """
    PURPOSE: Uploads Base64-encoded media content and optionally overwrites an existing media object.
    PREREQUISITES: User must have upload permissions.
    USE WHEN: Creating or updating binary attachments and media assets.
    AVOID WHEN: Textual page updates are needed; use wiki_savePage or wiki_appendPage.
    PRECAUTIONS: Overwrite may replace existing files.
    COSTS: Media file is created or replaced.
    EXPECTED OUTPUT: Success indicator or error details.
    NEXT STEPS: Use for media management.
    """
    client = get_client(ctx)
    result, err = await client.saveMedia(media=media, base64=base64, overwrite=overwrite)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Create or replace page content",
        "readOnlyHint": False,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_savePage(page: PageRequestType, text: TextRequestType, summary: SummaryRequestType = "", isminor: IsminorRequestType = False, ctx: Context = None) -> Union[SavePageResultType, RPCError]:
    """
    PURPOSE: Creates a page or fully replaces page content with provided raw wiki syntax.
    PREREQUISITES: User must have write permissions.
    USE WHEN: Target page content should be set to a specific complete state.
    AVOID WHEN: Additive-only updates should preserve existing content; use wiki_appendPage.
    PRECAUTIONS: Overwrites existing content.
    COSTS: New revision created, minimal payload.
    EXPECTED OUTPUT: Success indicator or error details.
    NEXT STEPS: Use for full page updates.
    """
    client = get_client(ctx)
    result, err = await client.savePage(page=page, text=text, summary=summary, isminor=isminor)
    return _unwrap(result, err)


@mcp.tool(
    annotations={
        "title": "Search pages by content/title",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_searchPages(query: QueryRequestType, ctx: Context = None) -> Union[List[SearchPagesResult], RPCError]:
    """
    PURPOSE: Searches pages by content and title, returning relevance-ranked results.
    PREREQUISITES: None.
    USE WHEN: Keyword-based discovery across page content is needed.
    AVOID WHEN: Exact page listing or structural navigation is required; use wiki_listPages or wiki_getPageInfo.
    PRECAUTIONS: None.
    COSTS: Can be high for broad queries; consider using specific keywords to limit results.
    EXPECTED OUTPUT: List of search results or error details.
    NEXT STEPS: Use for discovery or navigation.
    """
    client = get_client(ctx)
    result, err = await client.searchPages(query=query)
    return _unwrap(result or [], err)


@mcp.tool(
    annotations={
        "title": "Unlock multiple pages",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_unlockPages(pages: PagesRequestType, ctx: Context = None) -> Union[UnlockPagesResultType, RPCError]:
    """
    PURPOSE: Attempts to unlock multiple pages and returns the subset successfully unlocked.
    PREREQUISITES: Pages must exist and user must have unlock permissions.
    USE WHEN: Locks must be released after coordinated edit workflows.
    AVOID WHEN: Saving or conflict resolution logic is required; this endpoint only changes lock state.
    PRECAUTIONS: Unlocks may fail if not locked by user.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: List of unlocked pages or error details.
    NEXT STEPS: Proceed with further edits or release locks.
    """
    client = get_client(ctx)
    result, err = await client.unlockPages(pages=pages)
    return _unwrap(result or [], err)


# ==============================================================================
# TOOLS (API calls with one or more parameters) (extensions)
# ==============================================================================

DeletePageResultType = Annotated[bool, Field(title="deletePageResult", description='Returns true on success', examples=[True])]

# Annotation	Type	Description
#####################################
# title	string	    A human-readable title for the tool, useful for displaying in user interfaces. This is particularly useful when your tool's function name isn't descriptive enough for end users.
# readOnlyHint	    boolean	Indicates whether the tool only reads data without making any modifications. This is crucial for tools that query information versus those that change system state.
# destructiveHint	boolean	For non-read-only tools, this signals whether the changes made are destructive or reversible. This helps client applications implement appropriate warnings and confirmations.
# idempotentHint	boolean	Specifies whether repeated identical calls have the same effect as a single call. This is important for understanding whether a tool can be safely retried.
# openWorldHint	    boolean	Indicates whether the tool interacts with external systems beyond the local environment. This helps in understanding the tool's scope and potential dependencies.

@mcp.tool(
    annotations={
        "title": "Delete page via API",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
@api_ext_context
async def wiki_deletePage(page: PageRequestType, text: TextRequestType, summary: SummaryRequestType = "deleted", ctx: Context = None) -> Union[DeletePageResultType, RPCError]:
    """
    PURPOSE: Deletes single page and add specific deletion summary note.
    PREREQUISITES: Page must exist and user must have delete permissions.
    USE WHEN: Intentional page removal while preserving revision history.
    AVOID WHEN: Page need to be accessible via API.
    PRECAUTIONS: You MUST acknowledge deletion: Deleted page becomes inaccessible via API (manual action required to restore).
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Acknowledgment of deletion success (true/false) or error details. 
    NEXT STEPS: Any (unconditional).
    """
    client = get_client(ctx)
    result, err = await client.savePage(page=page, text=text, summary=summary, isminor=False)
    return _unwrap(result, err)


# ============================================================================
# AGENTIC TOOLS
# ============================================================================

# Registriere die Agentic Tools
import src.dokuwiki_mcp.agentic_tools

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


    mcp.run(transport=transport)