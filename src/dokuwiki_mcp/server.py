"""MCP server for DokuWiki JSON-RPC.

Design contract for agents and tooling:
- Endpoints without API parameters are exposed as MCP resources.
- Endpoints with one or more API parameters are exposed as MCP tools.
- Tool names follow the generated client method names (camelCase).
- Parameters and return values are passed through transparently from the client.
- Errors are returned as `RPCError` objects.
"""
import re
import asyncio
import subprocess
import tempfile
import enum
import difflib
import yake
import base64
import logging
import uuid
from typing import Any, List, Optional, Union, Annotated, Tuple, Dict
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


import os
from collections import defaultdict

# --- LOGGING SETUP & METRICS ---
# Silence internal framework logging at INFO level to keep container logs focused and readable
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DokuWikiMCP")

mcp = FastMCP("DokuWiki")

_SESSION_TOOL_METRICS: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

def _format_pretty_metrics(sess_id: str, current_tool: str, current_action: str, freqs: Dict[str, int]) -> str:
    """Formats session tool utilization into a clean, pretty-printed block with [LATEST] markers."""
    header = f"=== SESSION METRICS SUMMARY [{sess_id}] ==="
    lines = [header]
    
    current_act_key = f"{current_tool}:{current_action}" if current_action else current_tool
    lines.append(f"  ► LATEST CALL: {current_tool}" + (f" (action='{current_action}')" if current_action else ""))
    lines.append("  ------------------------------------------")
    
    macro_tools = []
    actions = []
    for k, v in freqs.items():
        if ":" in k:
            actions.append((k, v))
        else:
            macro_tools.append((k, v))
            
    lines.append("  [Macro Tool Utilization]")
    for tool, count in sorted(macro_tools, key=lambda x: -x[1]):
        marker = " ◀ [LATEST]" if tool == current_tool else ""
        lines.append(f"    - {tool:<28s} : {count:3d} calls{marker}")
        
    if actions:
        lines.append("  [Action Detail Breakdown]")
        for act, count in sorted(actions, key=lambda x: -x[1]):
            marker = " ◀ [LATEST]" if act == current_act_key else ""
            lines.append(f"    - {act:<28s} : {count:3d} calls{marker}")
            
    lines.append("=" * len(header))
    return "\n".join(lines)

def _log_tool_invocation(tool_name: str, action: str, params: dict, ctx: Optional[Context] = None):
    session_id = get_session_id(ctx) if ctx else None
    sess_key = session_id or "default_session"
    
    # Increment usage frequency
    _SESSION_TOOL_METRICS[sess_key][tool_name] += 1
    if action:
        _SESSION_TOOL_METRICS[sess_key][f"{tool_name}:{action}"] += 1
    
    # Standard INFO log: Pretty-printed frequency distribution with LATEST marker
    pretty_summary = _format_pretty_metrics(sess_key, tool_name, action, dict(_SESSION_TOOL_METRICS[sess_key]))
    logger.info(f"\n[TOOL METRICS UPDATE]\n{pretty_summary}")
    
    # DEBUG log: Full parameter payload for deep debugging
    logger.debug(
        f"[TOOL TRACE/DEBUG] Session: {sess_key} | Tool: {tool_name} | Action: {action} | Full Parameters: {params}"
    )

def _log_error_trace_stack(
    tool_name: str,
    action: str,
    tool_params: dict,
    err: Optional[RPCError] = None,
    error_msg: Optional[str] = None,
    ctx: Optional[Context] = None
):
    """Logs a detailed 4-step error trace stack at INFO level for complete observability."""
    session_id = get_session_id(ctx) if ctx else None
    sess_key = session_id or "default_session"
    
    # Extract API method & parameters from RPCError object or tool_params fallback
    api_method = getattr(err, "method", None) if err else None
    if not api_method and tool_params and isinstance(tool_params, dict) and "method" in tool_params:
        api_method = tool_params["method"]
    api_method = api_method or "N/A"
    
    api_params = getattr(err, "params", None) if err else None
    if not api_params and tool_params and isinstance(tool_params, dict) and "params" in tool_params:
        api_params = tool_params["params"]
    api_params = api_params or "N/A"
    
    code_val = getattr(err, "code", None) if err else None
    if code_val is None:
        code_val = "Validation/Local Error"
    
    response_text = error_msg or (f"RPCError (Code {err.code}): {err.message}\n→ Agent Hint: {err.actionable_hint}" if err else "")
    
    header = f"=== ❌ MCP ERROR TRACE STACK [{sess_key}] ==="
    lines = [
        "",
        header,
        f"  1. MACRO TOOL CALL  : {tool_name}" + (f" (action='{action}')" if action else ""),
        f"     • Tool Input Params: {tool_params}",
        f"  2. API CLIENT METHOD: {api_method}",
        f"     • API Parameters  : {api_params}",
        f"  3. RECEIVED ERROR   : Code {code_val}",
        f"  4. TOOL LLM RESPONSE: {response_text.strip()}",
        "=" * len(header),
        ""
    ]
    logger.info("\n".join(lines))

def _log_tool_error(tool_name: str, action: str, params: dict, error_msg: Optional[str] = None, err: Optional[RPCError] = None, ctx: Optional[Context] = None):
    _log_error_trace_stack(tool_name=tool_name, action=action, tool_params=params, err=err, error_msg=error_msg, ctx=ctx)

# ==============================================================================
# LLM SEO & CONTEXT INJECTION
# ==============================================================================

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

def _unwrap(result: Any, err: Optional[RPCError], tool_name: str = "", action: str = "", tool_params: dict = None, ctx: Context = None) -> Any:
    if err:
        err_msg = f"RPCError (Code {err.code}): {err.message}\n→ Agent Hint: {err.actionable_hint}"
        _log_error_trace_stack(tool_name=tool_name, action=action, tool_params=tool_params or {}, err=err, error_msg=err_msg, ctx=ctx)
        return err_msg
    return result

def _extract_yake_keywords(text: str, languages: List[str], max_kw: int, n_gram: int = 2) -> List[Tuple[str, float]]:
    if not text or len(text.strip()) < 30: return []
    try:
        import yake
        combined_stopwords = set()
        for lang in languages:
            try:
                dummy = yake.KeywordExtractor(lan=lang)
                if hasattr(dummy, 'stopword_set'): combined_stopwords.update(dummy.stopword_set)
            except: pass
        kw_extractor = yake.KeywordExtractor(lan=languages[0], n=n_gram, dedupLim=0.9, top=max_kw, stopwords=list(combined_stopwords))
        return kw_extractor.extract_keywords(text)
    except: return []

_SESSION_NAMESPACES = {}
_STATEFUL_DRAFTS = {}

def get_session_id(ctx: Context) -> Optional[str]:
    if ctx:
        try:
            request_context = ctx.request_context
            request = getattr(request_context, "request", None)
            if request is not None:
                headers = getattr(request, "headers", {}) or {}
                # Handle dictionary keys case-insensitively
                for k, v in headers.items():
                    if k.lower() == "mcp-session-id":
                        return v
        except Exception:
            pass
    return None

def _parse_timestamp(t_val: Any) -> Optional[float]:
    if not t_val:
        return None
    if isinstance(t_val, (int, float)):
        return float(t_val)
    if isinstance(t_val, str):
        try:
            return float(t_val)
        except ValueError:
            pass
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(t_val.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            pass
    return None

def _dokuwiki_to_markdown(text: str) -> str:
    if not text:
        return ""
    # Headers
    text = re.sub(r'^======\s*(.*?)\s*======\s*$', r'# \1', text, flags=re.MULTILINE)
    text = re.sub(r'^=====\s*(.*?)\s*=====\s*$', r'## \1', text, flags=re.MULTILINE)
    text = re.sub(r'^====\s*(.*?)\s*====\s*$', r'### \1', text, flags=re.MULTILINE)
    text = re.sub(r'^===\s*(.*?)\s*===\s*$', r'#### \1', text, flags=re.MULTILINE)
    text = re.sub(r'^==\s*(.*?)\s*==\s*$', r'##### \1', text, flags=re.MULTILINE)
    # Formatting
    text = re.sub(r'\/\/(.*?)\/\/', r'*\1*', text)
    text = re.sub(r'\'\'(.*?)\'\'', r'`\1`', text)
    # Media
    text = re.sub(r'\{\{([^|}]+)\|([^}]+)\}\}', r'![\2](\1)', text)
    text = re.sub(r'\{\{([^}]+)\}\}', r'![\1](\1)', text)
    # Links
    text = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'[\2](\1)', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'[\1](\1)', text)
    return text

def _lint_dokuwiki_syntax(text: str) -> Optional[str]:
    if not text:
        return None
    if text.count("[[") != text.count("]]"):
        return "Syntax Error: Unbalanced link brackets '[[ ... ]]'."
    if text.count("{{") != text.count("}}"):
        return "Syntax Error: Unbalanced media/image brackets '{{ ... }}'."
    
    # Headings match check
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if line.startswith("=") and line.endswith("="):
            match_left = re.match(r'^={2,6}', line)
            match_right = re.search(r'={2,6}$', line)
            if match_left and match_right:
                left_eqs = len(match_left.group(0))
                right_eqs = len(match_right.group(0))
                if left_eqs != right_eqs:
                    return f"Syntax Error (Line {i}): Mismatched equals signs in heading. Left has {left_eqs}, right has {right_eqs}."
    return None

async def _verified_save(client: DokuWikiClient, page: str, text: str, summary: str = "", isminor: bool = False) -> str:
    """Save a page and verify it was actually persisted or deleted. Returns a result string."""
    res, err = await client.savePage(page=page, text=text, summary=summary, isminor=isminor)
    if err:
        return f"RPCError (Code {err.code}): {err.message}\n→ Agent Hint: {err.actionable_hint}"
    
    # If text is empty, DokuWiki DELETES the page!
    if text == "" or text is None:
        verify_res, verify_err = await client.getPageInfo(page=page)
        if verify_err and verify_err.code == 121:
            return f"Success: Page '{page}' was deleted (DokuWiki deletes pages when saved with empty content)."
        return f"Success: Page '{page}' deletion executed."

    # Post-write verification: DokuWiki may return True but silently fail to write
    verify_res, verify_err = await client.getPageInfo(page=page)
    if verify_err:
        return (
            f"WRITE FAILED (Silent Failure): savePage returned {res} but the page '{page}' "
            f"does not exist after write. This typically indicates a file permission issue "
            f"on the DokuWiki server. Check that the web server user (PUID) has write access to "
            f"the data/pages directory for this namespace.\n"
            f"→ Agent Hint: Do NOT retry this write. Inform the user about the server-side permission problem."
        )
    return str(res)

async def _resolve_page_id(client: DokuWikiClient, page_id: str, ctx: Context = None, allow_create: bool = False) -> str:
    if not page_id:
        return page_id
        
    session_id = get_session_id(ctx)
    active_ns = _SESSION_NAMESPACES.get(session_id) if session_id else None
    
    resolved_id = page_id
    # Only prepend the active namespace for bare (non-namespaced) page names.
    # If the page_id already contains a ':', it is already namespace-qualified
    # and should NOT be prefixed (e.g. 'stadtbibliothek:bestand:zeitschriften').
    if active_ns and ":" not in page_id and not page_id.startswith(":"):
        resolved_id = f"{active_ns}:{page_id}"
        
    if resolved_id.startswith(":"):
        resolved_id = resolved_id[1:]
        
    res, err = await client.getPageInfo(page=resolved_id)
    if not err:
        return resolved_id

    # If the page does not exist and we allow creation (write actions), do not fuzzy-match!
    if allow_create:
        return resolved_id

    pages_res, pages_err = await client.listPages(depth=0, namespace="")
    if pages_err or not pages_res:
        return resolved_id
    
    page_ids = [p.id for p in pages_res if hasattr(p, "id") and p.id]
    lower_page_id = resolved_id.lower()
    for pid in page_ids:
        if pid.lower() == lower_page_id:
            return pid
            
    matches = difflib.get_close_matches(resolved_id, page_ids, n=1, cutoff=0.7)
    if matches:
        return matches[0]
        
    return resolved_id

async def _resolve_namespace(client: DokuWikiClient, namespace: str, ctx: Context = None) -> str:
    session_id = get_session_id(ctx)
    active_ns = _SESSION_NAMESPACES.get(session_id) if session_id else None
    
    resolved_ns = namespace
    if active_ns and not namespace.startswith(active_ns + ":") and not namespace.startswith(":"):
        if namespace:
            resolved_ns = f"{active_ns}:{namespace}"
        else:
            resolved_ns = active_ns
            
    if resolved_ns.startswith(":"):
        resolved_ns = resolved_ns[1:]

    pages_res, pages_err = await client.listPages(depth=0, namespace="")
    if pages_err or not pages_res:
        return resolved_ns
        
    namespaces = {""}
    for p in pages_res:
        if hasattr(p, "id") and p.id and ":" in p.id:
            namespaces.add(p.id.rsplit(":", 1)[0])
            
    lower_ns = resolved_ns.lower()
    for ns in namespaces:
        if ns.lower() == lower_ns:
            return ns
            
    matches = difflib.get_close_matches(resolved_ns, list(namespaces), n=1, cutoff=0.7)
    if matches:
        return matches[0]
        
    return resolved_ns


# --- CONSOLIDATED WIKI RESOURCES ---

@mcp.resource(
    "dokuwiki://raw_api_spec",
    annotations={
        "title": "Raw API Specification & Method Signatures",
        "description": "Lists all available raw DokuWiki JSON-RPC methods, their python signatures, and parameters. To execute these raw methods, use the tool wiki_raw_proxy.",
    }
)
@common_context
async def dokuwiki_raw_api_spec() -> str:
    """Returns a list of all raw JSON-RPC API methods and their python signatures in the client."""
    import inspect
    import re
    methods = inspect.getmembers(DokuWikiClient, predicate=inspect.iscoroutinefunction)
    out = [
        "--- Raw JSON-RPC API Specification ---",
        "This specification documents DokuWiki's low-level JSON-RPC methods and their parameters.",
        "To invoke any of these methods directly, call the tool `wiki_raw_proxy` passing the method name in the 'method' parameter, and argument key-values in the 'params' object matching the parameters below.",
        "All parameters without defaults are REQUIRED. Parameters with defaults are optional.",
        ""
    ]
    for name, func in methods:
        if name.startswith("_"): continue
        try:
            src = inspect.getsource(func)
            match = re.search(r'_rpc_call\(\s*["\']([^"\']+)["\']', src)
            raw_method = match.group(1) if match else f"wiki.{name}"
        except Exception:
            raw_method = f"wiki.{name}"
            
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or "No documentation."
        out.append(
            f"Method: {raw_method}\n"
            f"  Client Signature: {name}{sig}\n"
            f"  Description: {doc}\n"
            f"  Input Format: Call `wiki_raw_proxy` with method='{raw_method}' and params corresponding to client parameters.\n"
        )
    return "\n\n".join(out)


class SearchAndExploreAction(str, enum.Enum):
    search = "search"
    list_items = "list"
    recent_changes = "recent_changes"

@mcp.tool(
    annotations={
        "title": "Search and Explore DokuWiki",
        "description": "Explores the wiki by searching pages, listing namespace contents (pages & media), or tracking recent changes.",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@common_context
async def wiki_search_and_explore(
    action: SearchAndExploreAction,
    query: Optional[Union[str, List[str]]] = Field(default=None, description="Search query or list of queries (required for action='search')"),
    namespace: Optional[str] = Field(default="", description="Namespace to explore or restrict search to"),
    depth: int = Field(default=1, description="Depth of exploration/listing (0 for infinite, defaults to 1)"),
    exclusions: Optional[List[str]] = Field(default=None, description="List of namespaces to exclude"),
    pattern: Optional[str] = Field(default=None, description="Regex pattern (PHP style) to filter IDs"),
    modified_after: Optional[str] = Field(default=None, description="Filter pages modified after timestamp or ISO date string"),
    limit: int = Field(default=50, description="Max results to return (defaults to 50)"),
    ctx: Context = None
) -> str:
    """
    PURPOSE: Explore the wiki by searching pages, listing namespace contents, or tracking recent changes.
    PREREQUISITES: Read permissions.
    """
    act_str = action.value if hasattr(action, "value") else str(action)
    _log_tool_invocation(
        "wiki_search_and_explore",
        act_str,
        {
            "query": query,
            "namespace": namespace,
            "depth": depth,
            "exclusions": exclusions,
            "pattern": pattern,
            "modified_after": modified_after,
            "limit": limit,
        },
        ctx,
    )
    client = get_client(ctx)
    resolved_ns = await _resolve_namespace(client, namespace, ctx)
    
    rx = None
    if pattern:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except Exception as e:
            return f"Error: Invalid regex pattern: {str(e)}"
            
    exclude_set = set(exclusions) if exclusions else set()

    def is_excluded(item_id: str) -> bool:
        for ex in exclude_set:
            if item_id.startswith(ex + ":") or item_id == ex:
                return True
        if rx and not rx.search(item_id):
            return True
        return False

    t_limit = _parse_timestamp(modified_after)

    if action == SearchAndExploreAction.search:
        queries = [query] if isinstance(query, str) else (query or [])
        if not queries:
            return "Error: A 'query' parameter is required for action='search'."
            
        search_tasks = [client.searchPages(query=q) for q in queries]
        search_results = await asyncio.gather(*search_tasks)
        
        merged_results = {}
        for res, err in search_results:
            if err: continue
            for item in res:
                if is_excluded(item.id):
                    continue
                if resolved_ns and not item.id.startswith(resolved_ns + ":"):
                    continue
                # Temporal filtering
                if t_limit is not None:
                    rev_ts = _parse_timestamp(getattr(item, "revision", None))
                    if rev_ts is not None and rev_ts < t_limit:
                        continue
                if item.id not in merged_results or item.score > merged_results[item.id].score:
                    merged_results[item.id] = item
                    
        sorted_items = sorted(merged_results.values(), key=lambda x: x.score, reverse=True)
        
        filtered = []
        for item in sorted_items[:limit]:
            filtered.append(f"- {item.id} (Score: {item.score}) snippet: {item.snippet}")
                
        if not filtered:
            return "No matching search results found."
        return f"--- Search Results for {queries} (in namespace '{resolved_ns or '[ROOT]'}') ---\n" + "\n".join(filtered)

    elif action == SearchAndExploreAction.list_items:
        (p_res, p_err), (m_res, m_err) = await asyncio.gather(
            client.listPages(namespace=resolved_ns, depth=depth),
            client.listMedia(namespace=resolved_ns, depth=depth)
        )
        if p_err and m_err:
            return f"Error: Could not list items in namespace '{resolved_ns}'."
            
        sub_ns, pages, media = set(), [], []
        for it in (p_res or []):
            if is_excluded(it.id): continue
            if t_limit is not None:
                rev_ts = _parse_timestamp(getattr(it, "revision", None))
                if rev_ts is not None and rev_ts < t_limit:
                    continue
            rel = it.id[len(resolved_ns)+1:] if resolved_ns else it.id
            if ":" in rel:
                sub_ns.add(rel.split(":")[0])
            else:
                pages.append(f"{it.id} ({it.title}) [{it.size} Bytes]")
                
        for it in (m_res or []):
            if is_excluded(it.id): continue
            media.append(f"{it.id} [{it.size} Bytes]")
            
        out = [f"--- Namespace Explorer: '{resolved_ns or '[ROOT]'}' ---", "\n[NAMESPACES]"]
        out.extend([f"  - {n}" for n in sorted(sub_ns)] or ["  (None)"])
        out.append("\n[PAGES]")
        out.extend([f"  - {p}" for p in sorted(pages)[:limit]] or ["  (None)"])
        out.append("\n[MEDIA]")
        out.extend([f"  - {m}" for m in sorted(media)[:limit]] or ["  (None)"])
        return "\n".join(out)

    elif action == SearchAndExploreAction.recent_changes:
        (p_res, p_err), (m_res, m_err) = await asyncio.gather(
            client.getRecentPageChanges(timestamp=0),
            client.getRecentMediaChanges(timestamp=0)
        )
        changes = []
        for it in (p_res or []):
            if is_excluded(it.id): continue
            if resolved_ns and not it.id.startswith(resolved_ns + ":"): continue
            m_time = getattr(it, "lastModified", 0)
            if t_limit is not None and m_time < t_limit:
                continue
            changes.append({
                "type": "PAGE",
                "id": it.id,
                "author": getattr(it, "author", "unknown"),
                "summary": getattr(it, "summary", ""),
                "time": m_time
            })
        for it in (m_res or []):
            if is_excluded(it.id): continue
            if resolved_ns and not it.id.startswith(resolved_ns + ":"): continue
            m_time = getattr(it, "lastModified", 0) or getattr(it, "time", 0)
            if t_limit is not None and m_time < t_limit:
                continue
            changes.append({
                "type": "MEDIA",
                "id": it.id,
                "author": getattr(it, "author", "unknown"),
                "summary": getattr(it, "summary", ""),
                "time": m_time
            })
            
        changes.sort(key=lambda x: x["time"], reverse=True)
        out = [f"--- Recent Changes (in namespace '{resolved_ns or '[ROOT]'}') ---"]
        for c in changes[:limit]:
            import datetime
            dt = datetime.datetime.fromtimestamp(c["time"]).strftime('%Y-%m-%d %H:%M:%S') if c["time"] else "unknown"
            out.append(f"[{dt}] {c['type']} - {c['id']} by {c['author']} ({c['summary']})")
        if len(out) == 1:
            return "No recent changes found."
        return "\n".join(out)


class ReadContentAction(str, enum.Enum):
    read_page = "read_page"
    get_structure = "get_structure"
    get_links = "get_links"
    read_media = "read_media"
    extract_insights = "extract_insights"

@mcp.tool(
    annotations={
        "title": "Read and Analyze DokuWiki Content",
        "description": "Reads page source text, extracts structures, links, media properties, or retrieves NLP keywords.",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@common_context
async def wiki_read_content(
    action: ReadContentAction,
    target_id: str = Field(description="Page ID or Media ID to read/inspect"),
    section_id: Optional[Union[str, int]] = Field(default=None, description="Optional 1-based section index (for read_page or get_structure)"),
    rev: int = Field(default=0, description="Revision timestamp (0 for latest)"),
    languages: List[str] = Field(default=["de", "en"], description="Language codes for keyword extraction (e.g. ['de', 'en'])"),
    format: str = Field(default="markdown", description="Format output as 'raw' or translate to 'markdown'"),
    regex_filter: Optional[str] = Field(default=None, description="Optional regex pattern to filter lines returned in read_page"),
    ctx: Context = None
) -> str:
    """
    PURPOSE: Read page source text, extract structures, links, media properties, or retrieve NLP keywords.
    PREREQUISITES: Read permissions.
    """
    act_str = action.value if hasattr(action, "value") else str(action)
    _log_tool_invocation(
        "wiki_read_content",
        act_str,
        {
            "target_id": target_id,
            "section_id": section_id,
            "rev": rev,
            "languages": languages,
            "format": format,
            "regex_filter": regex_filter,
        },
        ctx,
    )
    client = get_client(ctx)
    resolved_id = await _resolve_page_id(client, target_id, ctx, allow_create=False)

    tool_params = {
        "target_id": target_id,
        "section_id": section_id,
        "rev": rev,
        "languages": languages,
        "format": format,
        "regex_filter": regex_filter,
    }

    if action == ReadContentAction.read_page:
        res, err = await client.getPage(page=resolved_id, rev=rev)
        if err: return _unwrap(res, err, tool_name="wiki_read_content", action=act_str, tool_params=tool_params, ctx=ctx)
        text = str(res) if res is not None else ""
        
        # DokuWiki's core.getPage returns empty string "" for non-existing pages.
        # Check getPageInfo to verify if the page actually exists or if it's missing.
        if not text:
            info_res, info_err = await client.getPageInfo(page=resolved_id, rev=rev)
            if info_err:
                return _unwrap(info_res, info_err, tool_name="wiki_read_content", action=act_str, tool_params=tool_params, ctx=ctx)
            text = "[Note: This page currently exists in DokuWiki but has empty content.]"
        
        if section_id is not None:
            try:
                sec_idx = int(section_id)
            except ValueError:
                return "Error: section_id must be a 1-based index (integer)."
                
            headers = list(re.finditer(r'^={2,6}\s*(.*?)\s*={2,6}$', text, re.MULTILINE))
            found_text = None
            for i, m in enumerate(headers, 1):
                if i == sec_idx:
                    eqs = len(re.match(r'={2,6}', m.group(0)).group(0))
                    end = len(text)
                    for nm in headers[i:]:
                        if len(re.match(r'={2,6}', nm.group(0)).group(0)) >= eqs:
                            end = nm.start()
                            break
                    found_text = text[m.end():end].strip()
                    break
            if found_text is None:
                return f"Error: Section index {sec_idx} not found on page '{resolved_id}'."
            text = found_text
            
        # Optional Layout Stripping (DokuWiki -> Markdown)
        if format == "markdown":
            text = _dokuwiki_to_markdown(text)
            
        # Optional Regex-based filtering
        if regex_filter:
            try:
                rx = re.compile(regex_filter, re.IGNORECASE | re.MULTILINE)
            except Exception as e:
                return f"Error: Invalid regex_filter pattern: {str(e)}"
            matches = []
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    matches.append(f"Line {i:03d}: {line}")
            if not matches:
                return "No lines match the regex filter."
            return f"--- Page: {resolved_id} (Regex Filter: '{regex_filter}') ---\n" + "\n".join(matches)
            
        section_label = f" (Section {section_id})" if section_id is not None else ""
        return f"--- Page: {resolved_id}{section_label} ---\n{text}"

    elif action == ReadContentAction.get_structure:
        (t_res, t_err), (i_res, i_err) = await asyncio.gather(
            client.getPage(page=resolved_id, rev=rev), 
            client.getPageInfo(page=resolved_id, rev=rev)
        )
        if t_err: return _unwrap(t_res, t_err)
        text = str(t_res)
        global_kws = _extract_yake_keywords(text, languages, 10, 1)

        matches = list(re.finditer(r'^={2,6}\s*(.*?)\s*={2,6}$', text, re.MULTILINE))
        structure = []
        for i, m in enumerate(matches, 1):
            lvl = 7 - len(re.match(r'={2,6}', m.group(0)).group(0))
            sec_text = text[m.end():matches[i].start() if i < len(matches) else len(text)].strip()
            kws = _extract_yake_keywords(sec_text, languages, 4, 1)
            structure.append(f"[{i}]{'  '*(lvl-1)}- {m.group(1).strip()} (Lvl:{lvl}) (char/words:{len(sec_text)}/{len(sec_text.split())}) (kw: {', '.join([k for k,s in kws])})")
        
        p_title = getattr(i_res, "title", "Unknown")
        p_size = getattr(i_res, "size", len(text))
        
        meta = f"--- META: {resolved_id} | Title: {p_title} | Size: {p_size} Bytes | Keywords: {', '.join([k for k,s in global_kws])} ---\n"
        return meta + "\n".join(structure)

    elif action == ReadContentAction.get_links:
        (l_res, l_err), (bl_res, bl_err) = await asyncio.gather(
            client.getPageLinks(page=resolved_id),
            client.getPageBackLinks(page=resolved_id)
        )
        out = [f"--- Links for Page: '{resolved_id}' ---", "\n[OUTBOUND LINKS]"]
        out.extend([f"  - {l.page} (type: {l.type})" for l in (l_res or [])] or ["  (None)"])
        out.append("\n[INBOUND BACKLINKS]")
        out.extend([f"  - {bl}" for bl in (bl_res or [])] or ["  (None)"])
        return "\n".join(out)

    elif action == ReadContentAction.read_media:
        (i_res, i_err), (m_res, m_err) = await asyncio.gather(
            client.getMediaInfo(media=target_id, rev=rev),
            client.getMedia(media=target_id, rev=rev)
        )
        if i_err: return _unwrap(i_res, i_err)
        
        out = [f"--- Media Info: '{target_id}' ---"]
        for k, v in getattr(i_res, "model_dump", lambda: {})().items():
            out.append(f"  {k}: {v}")
        if not m_err and m_res:
            out.append(f"\n[Media base64 contents available (size: {len(m_res)} chars)]")
            snippet = str(m_res)[:500]
            out.append(f"Snippet: {snippet}...")
        return "\n".join(out)

    elif action == ReadContentAction.extract_insights:
        res, err = await client.getPage(page=resolved_id, rev=rev)
        if err: return _unwrap(res, err)
        text = str(res)
        kws = _extract_yake_keywords(text, languages, 15, 2)
        if not kws: return "No keywords or insights found."
        out = ["--- Semantic Keywords & Scores (Lower is more relevant) ---"]
        out.extend([f"  - {k} (Score: {s:.4f})" for k, s in kws])
        return "\n".join(out)


class WriteModifyAction(str, enum.Enum):
    save_page = "save_page"
    delete_page = "delete_page"
    modify_section = "modify_section"
    patch_page = "patch_page"
    prepare_write = "prepare_write"
    commit = "commit"
    rollback = "rollback"
    save_media = "save_media"
    delete_media = "delete_media"
    lock = "lock"
    unlock = "unlock"

@mcp.tool(
    annotations={
        "title": "Write and Modify DokuWiki Content",
        "description": "Writes page content, edits sections, applies diff patches, uploads/deletes media, or manages locks.",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    }
)
@common_context
async def wiki_write_and_modify(
    action: WriteModifyAction,
    target_id: Optional[str] = Field(default=None, description="Page ID, Media ID, or transaction ID to modify/write"),
    content: Optional[str] = Field(default=None, description="Full page content, section content, or base64 data for media"),
    summary: Optional[str] = Field(default="", description="Edit summary description"),
    section_id: Optional[Union[str, int]] = Field(default=None, description="1-based section index (for action='modify_section')"),
    patch_diff: Optional[str] = Field(default=None, description="Unified diff text (for action='patch_page')"),
    transaction_id: Optional[str] = Field(default=None, description="Transaction ID (required for action='commit' or 'rollback')"),
    overwrite: bool = Field(default=False, description="Whether to overwrite existing media files (action='save_media')"),
    dry_run: bool = Field(default=False, description="Two-Phase Commit: Show dry-run modifications as a diff without saving"),
    ctx: Context = None
) -> str:
    """
    PURPOSE: Write and modify content: save full pages, update specific sections, apply diff patches, upload/delete media, and manage page locks.
    PREREQUISITES: Write permissions.
    """
    act_str = action.value if hasattr(action, "value") else str(action)
    _log_tool_invocation(
        "wiki_write_and_modify",
        act_str,
        {
            "target_id": target_id,
            "summary": summary,
            "section_id": section_id,
            "transaction_id": transaction_id,
            "overwrite": overwrite,
            "dry_run": dry_run,
        },
        ctx,
    )
    client = get_client(ctx)

    # 1. Stateful Two-Phase Commit: Commit/Rollback actions
    if action == WriteModifyAction.commit:
        tx_id = transaction_id or target_id
        if not tx_id or tx_id not in _STATEFUL_DRAFTS:
            return f"Error: Transaction ID '{tx_id}' not found in cache."
        dest_id, draft_content = _STATEFUL_DRAFTS.pop(tx_id)
        return await _verified_save(client, page=dest_id, text=draft_content, summary=summary or "Committed stateful transaction")

    elif action == WriteModifyAction.rollback:
        tx_id = transaction_id or target_id
        if not tx_id or tx_id not in _STATEFUL_DRAFTS:
            return f"Error: Transaction ID '{tx_id}' not found in cache."
        _STATEFUL_DRAFTS.pop(tx_id)
        return f"Transaction '{tx_id}' successfully discarded/rolled back."

    # For other actions, resolve the target ID relative to the namespace context
    if not target_id:
        return f"Error: target_id parameter is required for action '{action}'."
    resolved_id = await _resolve_page_id(client, target_id, ctx, allow_create=True)

    # 2. Syntax Linting Hook
    if action in (WriteModifyAction.save_page, WriteModifyAction.modify_section, WriteModifyAction.prepare_write):
        if content is not None:
            lint_err = _lint_dokuwiki_syntax(content)
            if lint_err:
                err_msg = f"Write Aborted: {lint_err}"
                _log_error_trace_stack(
                    tool_name="wiki_write_and_modify",
                    action=act_str,
                    tool_params={"target_id": target_id, "content": content},
                    error_msg=err_msg,
                    ctx=ctx
                )
                return err_msg

    if action == WriteModifyAction.save_page:
        if content is None:
            return "Error: 'content' parameter is required for save_page."
        if dry_run:
            res, err = await client.getPage(page=resolved_id)
            orig = str(res) if not err else ""
            diff = "".join(difflib.unified_diff(orig.splitlines(True), content.splitlines(True), f"a/{resolved_id}", f"b/{resolved_id}"))
            return f"--- DRY RUN (DIFF PREVIEW) ---\n```diff\n{diff or 'No changes'}\n```"
            
        return await _verified_save(client, page=resolved_id, text=content, summary=summary or "")

    elif action == WriteModifyAction.delete_page:
        if dry_run:
            res, err = await client.getPage(page=resolved_id)
            orig = str(res) if not err else ""
            diff = "".join(difflib.unified_diff(orig.splitlines(True), [""], f"a/{resolved_id}", f"b/{resolved_id} (DELETED)"))
            return f"--- DRY RUN (DELETE PREVIEW) ---\n```diff\n{diff or 'No changes'}\n```"
        return await _verified_save(client, page=resolved_id, text="", summary=summary or "Page deleted")

    elif action == WriteModifyAction.prepare_write:
        if content is None:
            return "Error: 'content' parameter is required for prepare_write."
        res, err = await client.getPage(page=resolved_id)
        orig = str(res) if not err else ""
        diff = "".join(difflib.unified_diff(orig.splitlines(True), content.splitlines(True), f"a/{resolved_id}", f"b/{resolved_id}"))
        tx_id = str(uuid.uuid4())
        _STATEFUL_DRAFTS[tx_id] = (resolved_id, content)
        return (
            f"--- PREPARE TRANSACTION (ID: {tx_id}) ---\n"
            f"```diff\n{diff or 'No changes'}\n```\n\n"
            f"[SYSTEM HINT: If approved, commit this change by calling wiki_write_and_modify with action='commit' and transaction_id='{tx_id}']"
        )

    elif action == WriteModifyAction.modify_section:
        if content is None or section_id is None:
            return "Error: both 'content' and 'section_id' are required for modify_section."
        try:
            sec_idx = int(section_id)
        except ValueError:
            return "Error: section_id must be a 1-based index (integer)."
            
        res, err = await client.getPage(page=resolved_id)
        if err: return _unwrap(res, err)
        text = str(res)
        headers = list(re.finditer(r'^={2,6}\s*(.*?)\s*={2,6}$', text, re.MULTILINE))
        
        found = False
        start, end = 0, len(text)
        for i, m in enumerate(headers, 1):
            if i == sec_idx:
                start = m.end()
                eqs = len(re.match(r'={2,6}', m.group(0)).group(0))
                for nm in headers[i:]:
                    if len(re.match(r'={2,6}', nm.group(0)).group(0)) >= eqs:
                        end = nm.start()
                        break
                found = True
                break
                
        if not found:
            return f"Error: Section index {sec_idx} not found on page '{resolved_id}'."
            
        new_page_text = text[:start] + "\n" + content.strip() + "\n\n" + text[end:]
        
        if dry_run:
            diff = "".join(difflib.unified_diff(text.splitlines(True), new_page_text.splitlines(True), f"a/{resolved_id}", f"b/{resolved_id}"))
            return f"--- DRY RUN (DIFF PREVIEW) ---\n```diff\n{diff or 'No changes'}\n```"
            
        return await _verified_save(client, page=resolved_id, text=new_page_text, summary=summary or f"Section {sec_idx} modified")

    elif action == WriteModifyAction.patch_page:
        if patch_diff is None:
            return "Error: 'patch_diff' parameter is required for patch_page."
        res, err = await client.getPage(page=resolved_id)
        if err: return _unwrap(res, err)
        orig = str(res)
        
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                if not patch_diff.endswith('\n'):
                    patch_diff += '\n'
                path = f"{tmpdir}/p.txt"
                with open(path, "w", encoding="utf-8") as f: f.write(orig)
                p = subprocess.run(["patch", "-p0", "p.txt"], input=patch_diff.encode('utf-8'), capture_output=True, cwd=tmpdir, shell=False)
                if p.returncode != 0:
                    return f"Patch application failed: {p.stderr.decode('utf-8', errors='replace')}"
                with open(path, "r", encoding="utf-8") as f: new_txt = f.read()
                
                # Lint the newly patched page
                lint_err = _lint_dokuwiki_syntax(new_txt)
                if lint_err:
                    return f"Write Aborted (Patched page syntax check failed): {lint_err}"
                
                if dry_run:
                    diff = "".join(difflib.unified_diff(orig.splitlines(True), new_txt.splitlines(True), f"a/{resolved_id}", f"b/{resolved_id}"))
                    return f"--- DRY RUN (DIFF PREVIEW) ---\n```diff\n{diff or 'No changes'}\n```"
                    
                return await _verified_save(client, page=resolved_id, text=new_txt, summary=summary or "Patch applied")
        except Exception as e:
            return f"System Error applying patch: {str(e)}"

    elif action == WriteModifyAction.save_media:
        if content is None:
            return "Error: 'content' base64 data is required for save_media."
        res, err = await client.saveMedia(media=target_id, base64=content, overwrite=overwrite)
        return str(_unwrap(res, err))

    elif action == WriteModifyAction.delete_media:
        res, err = await client.deleteMedia(media=target_id)
        return str(_unwrap(res, err))

    elif action == WriteModifyAction.lock:
        res, err = await client.lockPages(pages=[resolved_id])
        return str(_unwrap(res, err))

    elif action == WriteModifyAction.unlock:
        res, err = await client.unlockPages(pages=[resolved_id])
        return str(_unwrap(res, err))


class AdminMetaAction(str, enum.Enum):
    who_ami = "who_ami"
    acl_check = "acl_check"
    system_info = "system_info"
    logoff = "logoff"
    set_namespace = "set_namespace"

@mcp.tool(
    annotations={
        "title": "DokuWiki Admin and Metadata Properties",
        "description": "Exposes administrative and session info: get current user, check ACLs, view system metadata, set active namespace, or logoff.",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@common_context
async def wiki_admin_and_meta(
    action: AdminMetaAction,
    page_id: Optional[str] = Field(default=None, description="Target Page ID (required for acl_check)"),
    user: Optional[str] = Field(default="", description="User to check ACL permissions for"),
    groups: Optional[List[str]] = Field(default=None, description="Groups to check ACL permissions for"),
    namespace: Optional[str] = Field(default=None, description="Namespace to make active for current session (required for set_namespace)"),
    ctx: Context = None
) -> str:
    """
    PURPOSE: Administration and Metadata - View active user profile, check specific ACL permissions, review wiki software version metadata, set active session namespace, or log off.
    PREREQUISITES: None.
    """
    act_str = action.value if hasattr(action, "value") else str(action)
    _log_tool_invocation(
        "wiki_admin_and_meta",
        act_str,
        {
            "page_id": page_id,
            "user": user,
            "groups": groups,
            "namespace": namespace,
        },
        ctx,
    )
    client = get_client(ctx)
    if action == AdminMetaAction.who_ami:
        res, err = await client.whoAmI()
        if err: return _unwrap(res, err)
        out = ["--- User Session Details ---"]
        for k, v in getattr(res, "model_dump", lambda: {})().items():
            out.append(f"  {k}: {v}")
        return "\n".join(out)

    elif action == AdminMetaAction.acl_check:
        if not page_id:
            return "Error: 'page_id' is required for acl_check."
        resolved_page = await _resolve_page_id(client, page_id, ctx, allow_create=False)
        res, err = await client.aclCheck(page=resolved_page, user=user, groups=groups or [])
        return str(_unwrap(res, err))

    elif action == AdminMetaAction.system_info:
        (v_res, v_err), (w_res, w_err), (t_res, t_err) = await asyncio.gather(
            client.getAPIVersion(),
            client.getWikiVersion(),
            client.getWikiTime()
        )
        import datetime
        dt = datetime.datetime.fromtimestamp(t_res).strftime('%Y-%m-%d %H:%M:%S') if not t_err and t_res else "unknown"
        return (
            f"--- Wiki System Information ---\n"
            f"  API Version: {v_res if not v_err else 'error'}\n"
            f"  DokuWiki Release: {w_res if not w_err else 'error'}\n"
            f"  Server Time: {dt} (Timestamp: {t_res if not t_err else 'error'})"
        )

    elif action == AdminMetaAction.logoff:
        res, err = await client.logoff()
        return str(_unwrap(res, err))

    elif action == AdminMetaAction.set_namespace:
        session_id = get_session_id(ctx)
        if not session_id:
            return "Error: No active MCP session ID found in request headers."
        if namespace is None:
            return "Error: 'namespace' parameter is required for set_namespace."
        resolved_ns = await _resolve_namespace(client, namespace, ctx)
        _SESSION_NAMESPACES[session_id] = resolved_ns
        return f"Success: Session active namespace set to '{resolved_ns}'."


@mcp.tool(
    annotations={
        "title": "Low-level Raw API Proxy Fallback [ULTIMA RATIO / LAST RESORT ONLY]",
        "description": "ULTIMA RATIO / FALLBACK ONLY: Use this tool ONLY if the consolidated macro-tools (wiki_search_and_explore, wiki_read_content, wiki_write_and_modify, wiki_admin_and_meta) do NOT support your required operation. Enables raw JSON-RPC invocations directly against the DokuWiki API. To discover available raw method names, parameter signatures, and types, read the resource dokuwiki://raw_api_spec first.",
        "readOnlyHint": False,
        "idempotentHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    }
)
@common_context
async def wiki_raw_proxy(
    method: str = Field(description="Raw JSON-RPC API method name (e.g. 'core.getPageInfo'). Read 'dokuwiki://raw_api_spec' for method list. ULTIMA RATIO: Prefer macro-tools first!"),
    params: Dict[str, Any] = Field(default_factory=dict, description="JSON object containing key-value parameters matching the client signature parameters (e.g. {'page': 'playground:seite'})."),
    ctx: Context = None
) -> str:
    """
    PURPOSE: [ULTIMA RATIO / LAST RESORT FALLBACK ONLY] Allows invoking any raw JSON-RPC method directly. DO NOT USE THIS TOOL IF HIGH-LEVEL TOOLS (wiki_search_and_explore, wiki_read_content, wiki_write_and_modify, wiki_admin_and_meta) CAN EXECUTE YOUR TASK.
    PREREQUISITES: None.
    INPUT FORMAT: 
      - method: Raw DokuWiki JSON-RPC method name (e.g. 'core.getPageInfo').
      - params: A JSON dictionary where keys and types match the parameters of the client signature documented in 'dokuwiki://raw_api_spec'.
    OUTPUT FORMAT: 
      - Success: Returns the stringified/serialized raw response JSON payload from the DokuWiki server.
      - Failure: Returns a formatted error string 'RPCError (Code X): message'.
    CROSS-REFERENCE: 
      - High-Level Macro-Tools: Always check wiki_search_and_explore, wiki_read_content, wiki_write_and_modify, wiki_admin_and_meta first.
      - Spec: Read 'dokuwiki://raw_api_spec' to see the complete list of available methods and signatures.
    """
    _log_tool_invocation("wiki_raw_proxy", method, {"method": method, "params": params}, ctx)
    client = get_client(ctx)
    res, err = await client._rpc_call(method=method, params=params)
    if err:
        err_msg = f"RPCError (Code {err.code}): {err.message}\n→ Agent Hint: {err.actionable_hint}"
        _log_tool_error("wiki_raw_proxy", method, {"method": method, "params": params}, error_msg=err_msg, err=err, ctx=ctx)
        return err_msg
    if res == "" and method in ("core.getPage", "core.getPageHTML", "core.getPageVersion", "core.getPageInfo"):
        return '""\n[RAW API HINT: DokuWiki returned an empty string. DokuWiki\'s core.getPage API returns "" when a page or revision does not exist. Execute core.getPageInfo or use macro-tool wiki_search_and_explore to check existence.]'
    return str(res)


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
            kwargs['log_level'] = LOG_LEVEL_NAME.lower()
            kwargs['access_log'] = (LOG_LEVEL == logging.DEBUG)
            
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