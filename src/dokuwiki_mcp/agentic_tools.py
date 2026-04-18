import re
from typing import Union, Optional, Annotated
from pydantic import Field

# Importiere das zentrale mcp Objekt und Hilfsfunktionen aus deiner server.py
from .server import mcp, _unwrap, api_context, api_ext_context, get_client, get_settings
from .client import (
    PageRequestType,
    QueryRequestType,
    RevRequestType,
    RPCError
)
from mcp.server.fastmcp import Context

# ============================================================================
# REUSABLE ANNOTATED TYPES FOR AGENTIC TOOLS
# ============================================================================

SectionTitleRequestType = Annotated[
    str, 
    Field(
        title="sectionTitle", 
        description="The exact title of the section/header you want to extract (without the '=' characters).", 
        examples=["Server Configuration", "Troubleshooting"]
    )
]

# ============================================================================
# AGENTIC TOOLS
# ============================================================================

@mcp.tool(
    annotations={
        "title": "Get page structure (TOC)",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_getPageStructure(page: PageRequestType, rev: RevRequestType = 0, ctx: Context = None) -> Union[str, RPCError]:
    """
    PURPOSE: Extracts and returns only the structural headers (Table of Contents) of a DokuWiki page.
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: You need to understand the layout and contents of a page BEFORE deciding to read specific sections or the full page.
    AVOID WHEN: You already know the exact section you want to read.
    PRECAUTIONS: None.
    COSTS: VERY LOW. Highly token-efficient. ALWAYS prefer this over wiki_getPage for initial exploration.
    EXPECTED OUTPUT: A formatted, indented tree view of all headers on the page.
    NEXT STEPS: Use wiki_readPageSection to read a specific header found in this structure.
    """
    client = get_client(ctx)
    result, err = await client.getPage(page=page, rev=rev)
    
    # Fehler direkt durchreichen, falls die Seite nicht geladen werden konnte
    if err:
        return _unwrap(result, err)
        
    text = result if isinstance(result, str) else str(result)
    
    # DokuWiki Header Regex: Sucht nach == Text == bis ====== Text ======
    # DokuWiki H1 = 6x '=', H5 = 2x '='
    header_pattern = re.compile(r'^={2,6}\s*(.*?)\s*={2,6}$', re.MULTILINE)
    
    structure = []
    for match in header_pattern.finditer(text):
        full_match = match.group(0).strip()
        title = match.group(1).strip()
        
        # Bestimme das Level anhand der '=' Zeichen (6 '=' = Level 1, 2 '=' = Level 5)
        equals_count = 0
        for char in full_match:
            if char == '=':
                equals_count += 1
            else:
                break
                
        level = 7 - equals_count # Umkehrung: 6 -> 1, 5 -> 2, etc.
        
        # Einrückung für den Baum generieren
        indent = "  " * (level - 1)
        structure.append(f"{indent}- [{title}] (Level {level})")
        
    if not structure:
        return f"The page '{page}' exists, but contains no structural headers (no '======' syntax found)."
        
    header_summary = f"Structure for page '{page}':\n" + "\n".join(structure)
    return header_summary


@mcp.tool(
    annotations={
        "title": "Read specific page section",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_context
async def wiki_readPageSection(page: PageRequestType, section_title: SectionTitleRequestType, rev: RevRequestType = 0, ctx: Context = None) -> Union[str, RPCError]:
    """
    PURPOSE: Extracts the content of a specific section (under a given header) from a DokuWiki page.
    PREREQUISITES: You MUST know the exact 'section_title'. Run wiki_getPageStructure first if you are unsure.
    USE WHEN: You only need to read a specific part of a large page (e.g., just the "Setup" instructions).
    AVOID WHEN: You need to rewrite or evaluate the entire page document.
    PRECAUTIONS: The section_title is case-insensitive but must match the header text closely.
    COSTS: LOW TO MEDIUM. Extracts only a fraction of the full page, saving significant tokens.
    EXPECTED OUTPUT: The raw DokuWiki markup contained within the requested section.
    NEXT STEPS: Analyze the returned text or use it to formulate a targeted wiki_sed command.
    """
    client = get_client(ctx)
    result, err = await client.getPage(page=page, rev=rev)
    
    if err:
        return _unwrap(result, err)
        
    text = result if isinstance(result, str) else str(result)
    
    header_pattern = re.compile(r'^={2,6}\s*(.*?)\s*={2,6}$', re.MULTILINE)
    
    start_idx = -1
    target_equals_count = -1
    
    # 1. Finde den Start-Header
    for match in header_pattern.finditer(text):
        title = match.group(1).strip()
        if title.lower() == section_title.lower():
            start_idx = match.end() # Starten NACH dem Header
            
            full_match = match.group(0).strip()
            target_equals_count = 0
            for char in full_match:
                if char == '=':
                    target_equals_count += 1
                else:
                    break
            break
            
    if start_idx == -1:
        return f"ERROR: Section '{section_title}' not found on page '{page}'. Please run wiki_getPageStructure to see available sections."

    # 2. Finde das Ende der Sektion (nächster Header auf gleichem oder höherem Level)
    # Höheres Level in DokuWiki bedeutet MEHR oder GLEICH VIELE '=' Zeichen
    end_idx = len(text)
    
    # Suche ab dem gefundenen Startpunkt
    for match in header_pattern.finditer(text, start_idx):
        full_match = match.group(0).strip()
        current_equals_count = 0
        for char in full_match:
            if char == '=':
                current_equals_count += 1
            else:
                break
                
        # Wenn der nächste Header gleich viele oder mehr '=' hat, ist die aktuelle Sektion zu Ende
        if current_equals_count >= target_equals_count:
            end_idx = match.start()
            break
            
    extracted_content = text[start_idx:end_idx].strip()
    
    if not extracted_content:
        return f"--- Section: {section_title} ---\n[This section is empty]"
        
    return f"--- Content of Section: '{section_title}' ---\n{extracted_content}"


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
@mcp.tool(
    annotations={
        "title": "Search pages and return Markdown links",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_ext_context
async def wiki_searchPagesWithLinks(query: QueryRequestType, ctx: Context = None) -> str:
    """
    PURPOSE: Searches the wiki and returns clickable Markdown links for the results, which the agent must pass directly to the user.
    PREREQUISITES: None.
    USE WHEN: You want to present search results as direct links in Markdown format.
    AVOID WHEN: You need raw data or non-Markdown output.
    PRECAUTIONS: Only the first 15 results are shown.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Markdown-formatted list of links or a no-results message.
    NEXT STEPS: User can click links or refine the search.
    """
    client = get_client(ctx)
    results, err = await client.searchPages(query=query)
    if not results:
        return f"Keine Ergebnisse für '{query}' gefunden."
    output_lines = [f"Ergebnisse für '{query}':"]
    for res in results[:15]:
        page = res.get('id')
        title = res.get('title', page)
        md_link = get_markdown_link(page, title)
        output_lines.append(f"- {md_link}")
    return "\n".join(output_lines)


# --- TOOL 2: DAS PREVIEW / DIFF TOOL ---
@mcp.tool(
    annotations={
        "title": "Preview Markdown diff before saving",
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
)
@api_ext_context
async def wiki_preview_edit(page: PageRequestType, new_content: PageRequestType, ctx: Context = None) -> str:
    """
    PURPOSE: Shows a Markdown diff preview before saving changes to a page.
    PREREQUISITES: Page must exist and user must have read permissions.
    USE WHEN: You want to preview changes and present a diff to the user before saving.
    AVOID WHEN: No preview or diff is needed.
    PRECAUTIONS: Only textual differences are shown; no changes means no diff output.
    COSTS: Minimal response payload.
    EXPECTED OUTPUT: Markdown-formatted diff or info message if no changes.
    NEXT STEPS: User can review and decide to save or discard changes.
    """
    try:
        client = get_client(ctx)
        old_content, err = await client.getPage(page=page)
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
        md_link = get_markdown_link(page)
        return (
            f"WICHTIG: Gib dem User exakt diesen Text aus, damit er den Link klicken kann:\n\n"
            f"### Änderungsvorschlag für {md_link}\n"
            f"Bitte prüfe den folgenden Diff:\n"
            f"```diff\n{diff_text}\n```"
            f"\n**Soll ich das speichern? (Nutze danach das Tool 'wiki_edit_page')**"
        )
    except Exception as e:
        return f"Fehler bei Vorschau: {str(e)}"



# ==============================================================================
# PROMPTS (Workflow-Vorlagen für das LLM)
# ==============================================================================

# @mcp.prompt()
# @api_context
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
