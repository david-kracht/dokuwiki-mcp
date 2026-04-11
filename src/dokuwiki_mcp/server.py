"""MCP server for DokuWiki JSON-RPC.

Design contract for agents and tooling:
- Endpoints without API parameters are exposed as MCP resources.
- Endpoints with one or more API parameters are exposed as MCP tools.
- Tool names follow the generated client method names (camelCase).
- Parameters and return values are passed through transparently from the client.
- Errors are returned as `RPCError` objects.
"""

import base64
import logging
from typing import Any, List, Optional, Union

from mcp.server.fastmcp import Context, FastMCP

from .client import (
    DokuWikiClient,
    RPCError,
    getMediaHistoryResult,
    getMediaInfoResult,
    getPageHistoryResult,
    getPageInfoResult,
    getPageLinksResult,
    getRecentMediaChangesResult,
    getRecentPageChangesResult,
    listMediaResult,
    listPagesResult,
    searchPagesResult,
    whoAmIResult,
)

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DokuWikiMCP")

mcp = FastMCP("DokuWiki")

def get_client(ctx: Context = None) -> DokuWikiClient:
    logger.info("Creating DokuWiki client with context: %s", ctx)
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
async def getAPIVersionResource(ctx: Context = None) -> Union[int, RPCError]:
    """Returns the DokuWiki JSON-RPC API version for compatibility checks and capability gating."""
    client = get_client(ctx)
    result, err = await client.getAPIVersion()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/getWikiTime")
async def getWikiTimeResource(ctx: Context = None) -> Union[int, RPCError]:
    """Returns the current server Unix timestamp to align revision and change-window logic across clients."""
    client = get_client(ctx)
    result, err = await client.getWikiTime()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/getWikiTitle")
async def getWikiTitleResource(ctx: Context = None) -> Union[str, RPCError]:
    """Returns the configured wiki title for user-facing context and interface labeling."""
    client = get_client(ctx)
    result, err = await client.getWikiTitle()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/getWikiVersion")
async def getWikiVersionResource(ctx: Context = None) -> Union[str, RPCError]:
    """Returns the DokuWiki version string to support diagnostics and feature awareness."""
    client = get_client(ctx)
    result, err = await client.getWikiVersion()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/whoAmI")
async def whoAmIResource(ctx: Context = None) -> Union[whoAmIResult, RPCError]:
    """Returns the authenticated user profile and roles to determine permission context for subsequent operations."""
    client = get_client(ctx)
    result, err = await client.whoAmI()
    return _unwrap(result, err)


@mcp.resource("dokuwiki://core/logoff")
async def logoffResource(ctx: Context = None) -> Union[int, RPCError]:
    """Logs off the current session when cookie-based authentication is used and returns a success flag."""
    client = get_client(ctx)
    result, err = await client.logoff()
    return _unwrap(result, err)

# ==============================================================================
# TOOLS (API calls with one or more parameters)
# ==============================================================================

@mcp.tool()
async def aclCheck(page: str, user: str = "", groups: List = "[]", ctx: Context = None) -> Union[int, RPCError]:
    """Checks effective ACL permissions for a page or media target, optionally for a specific user and groups."""
    client = get_client(ctx)
    result, err = await client.aclCheck(page=page, user=user, groups=groups)
    return _unwrap(result, err)


@mcp.tool()
async def appendPage(page: str, text: str, summary: str = "", isminor: bool = False, ctx: Context = None) -> Union[bool, RPCError]:
    """Appends wiki syntax to the end of a page and creates a new revision if permissions allow."""
    client = get_client(ctx)
    result, err = await client.appendPage(page=page, text=text, summary=summary, isminor=isminor)
    return _unwrap(result, err)


@mcp.tool()
async def deleteMedia(media: str, ctx: Context = None) -> Union[bool, RPCError]:
    """Deletes an existing media file from the wiki storage when delete permission is granted."""
    client = get_client(ctx)
    result, err = await client.deleteMedia(media=media)
    return _unwrap(result, err)


@mcp.tool()
async def getMedia(media: str, rev: int = 0, ctx: Context = None) -> Union[str, RPCError]:
    """Returns Base64-encoded content of a media file for the current or a specific revision timestamp."""
    client = get_client(ctx)
    result, err = await client.getMedia(media=media, rev=rev)
    return _unwrap(result, err)


@mcp.tool()
async def getMediaHistory(media: str, first: int = 0, ctx: Context = None) -> Union[List[getMediaHistoryResult], RPCError]:
    """Returns revision history entries for a media file, with optional offset for pagination-like retrieval."""
    client = get_client(ctx)
    result, err = await client.getMediaHistory(media=media, first=first)
    return _unwrap(result or [], err)


@mcp.tool()
async def getMediaInfo(media: str, rev: int = 0, author: bool = False, hash: bool = False, ctx: Context = None) -> Union[getMediaInfoResult, RPCError]:
    """Returns technical metadata for a media file, optionally including author and content hash details."""
    client = get_client(ctx)
    result, err = await client.getMediaInfo(media=media, rev=rev, author=author, hash=hash)
    return _unwrap(result, err)


@mcp.tool()
async def getMediaUsage(media: str, ctx: Context = None) -> Union[List[Any], RPCError]:
    """Returns pages that reference a given media file to support impact analysis before updates or deletion."""
    client = get_client(ctx)
    result, err = await client.getMediaUsage(media=media)
    return _unwrap(result or [], err)


@mcp.tool()
async def getPage(page: str, rev: int = 0, ctx: Context = None) -> Union[str, RPCError]:
    """Returns raw DokuWiki syntax for a page at the current revision or an older revision timestamp."""
    client = get_client(ctx)
    result, err = await client.getPage(page=page, rev=rev)
    return _unwrap(result, err)


@mcp.tool()
async def getPageBackLinks(page: str, ctx: Context = None) -> Union[List[Any], RPCError]:
    """Returns pages linking to the target page to evaluate dependencies and navigation impact."""
    client = get_client(ctx)
    result, err = await client.getPageBackLinks(page=page)
    return _unwrap(result or [], err)


@mcp.tool()
async def getPageHTML(page: str, rev: int = 0, ctx: Context = None) -> Union[str, RPCError]:
    """Returns the rendered HTML body for a page revision for previewing or downstream extraction."""
    client = get_client(ctx)
    result, err = await client.getPageHTML(page=page, rev=rev)
    return _unwrap(result, err)


@mcp.tool()
async def getPageHistory(page: str, first: int = 0, ctx: Context = None) -> Union[List[getPageHistoryResult], RPCError]:
    """Returns page revision history entries, optionally skipping the newest entries via offset."""
    client = get_client(ctx)
    result, err = await client.getPageHistory(page=page, first=first)
    return _unwrap(result or [], err)


@mcp.tool()
async def getPageInfo(page: str, rev: int = 0, author: bool = False, hash: bool = False, ctx: Context = None) -> Union[getPageInfoResult, RPCError]:
    """Returns technical page metadata including revision, size, permissions, and optional author/hash fields."""
    client = get_client(ctx)
    result, err = await client.getPageInfo(page=page, rev=rev, author=author, hash=hash)
    return _unwrap(result, err)


@mcp.tool()
async def getPageLinks(page: str, ctx: Context = None) -> Union[List[getPageLinksResult], RPCError]:
    """Returns all links found on a page, including internal, external, and interwiki targets."""
    client = get_client(ctx)
    result, err = await client.getPageLinks(page=page)
    return _unwrap(result or [], err)


@mcp.tool()
async def getRecentMediaChanges(timestamp: int = 0, ctx: Context = None) -> Union[List[getRecentMediaChangesResult], RPCError]:
    """Returns recent media changes, optionally constrained to entries newer than a Unix timestamp."""
    client = get_client(ctx)
    result, err = await client.getRecentMediaChanges(timestamp=timestamp)
    return _unwrap(result or [], err)


@mcp.tool()
async def getRecentPageChanges(timestamp: int = 0, ctx: Context = None) -> Union[List[getRecentPageChangesResult], RPCError]:
    """Returns recent page changes, optionally constrained to entries newer than a Unix timestamp."""
    client = get_client(ctx)
    result, err = await client.getRecentPageChanges(timestamp=timestamp)
    return _unwrap(result or [], err)


@mcp.tool()
async def listMedia(namespace: str = "", pattern: str = "", depth: int = 1, hash: bool = False, ctx: Context = None) -> Union[List[listMediaResult], RPCError]:
    """Lists media files in a namespace tree with optional regex filtering and depth control."""
    client = get_client(ctx)
    result, err = await client.listMedia(namespace=namespace, pattern=pattern, depth=depth, hash=hash)
    return _unwrap(result or [], err)


@mcp.tool()
async def listPages(namespace: str = "", depth: int = 1, hash: bool = False, ctx: Context = None) -> Union[List[listPagesResult], RPCError]:
    """Lists wiki pages in a namespace tree with configurable traversal depth and optional page hash output."""
    client = get_client(ctx)
    result, err = await client.listPages(namespace=namespace, depth=depth, hash=hash)
    return _unwrap(result or [], err)


@mcp.tool()
async def lockPages(pages: List, ctx: Context = None) -> Union[List[Any], RPCError]:
    """Attempts to lock a set of pages and returns those successfully locked for coordinated edits."""
    client = get_client(ctx)
    result, err = await client.lockPages(pages=pages)
    return _unwrap(result or [], err)


@mcp.tool()
async def login(user: str, pass_: str, ctx: Context = None) -> Union[int, RPCError]:
    """Attempts login with explicit credentials and returns the DokuWiki login status indicator."""
    client = get_client(ctx)
    result, err = await client.login(user=user, pass_=pass_)
    return _unwrap(result, err)


@mcp.tool()
async def saveMedia(media: str, base64: str, overwrite: bool = False, ctx: Context = None) -> Union[bool, RPCError]:
    """Uploads Base64-encoded media content and optionally overwrites an existing file with the same ID."""
    client = get_client(ctx)
    result, err = await client.saveMedia(media=media, base64=base64, overwrite=overwrite)
    return _unwrap(result, err)


@mcp.tool()
async def savePage(page: str, text: str, summary: str = "", isminor: bool = False, ctx: Context = None) -> Union[bool, RPCError]:
    """Creates or updates a page by writing raw wiki syntax with optional edit summary and minor flag."""
    client = get_client(ctx)
    result, err = await client.savePage(page=page, text=text, summary=summary, isminor=isminor)
    return _unwrap(result, err)

@mcp.tool()
async def searchPages(query: str, ctx: Context = None) -> Union[List[searchPagesResult], RPCError]:
    """Runs DokuWiki full-text search syntax and returns scored page matches with snippets when available."""
    client = get_client(ctx)
    result, err = await client.searchPages(query=query)
    return _unwrap(result or [], err)


@mcp.tool()
async def unlockPages(pages: List, ctx: Context = None) -> Union[List[Any], RPCError]:
    """Attempts to unlock a set of pages and returns those successfully unlocked."""
    client = get_client(ctx)
    result, err = await client.unlockPages(pages=pages)
    return _unwrap(result or [], err)

if __name__ == "__main__":
    import os
    if os.environ.get("MCP_TRANSPORT", "sse").lower() == "sse":
        import uvicorn
        original_init = uvicorn.Config.__init__
        def patched_init(self, *args, **kwargs):
            kwargs['host'] = '0.0.0.0'
            original_init(self, *args, **kwargs)
        uvicorn.Config.__init__ = patched_init
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")