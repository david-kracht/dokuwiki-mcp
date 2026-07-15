#!/usr/bin/env python3
"""
Benchmark Evaluator Engine for DokuWiki MCP Server.

Executes test tasks, collects telemetry logs, computes Layer A/B/C KPIs,
evaluates Pass@1 via verifier.py, and generates structured Markdown reports.
"""

import os
import sys

# Ensure Telemetry is enabled for evaluation benchmark runs
os.environ["MCP_ENABLE_TELEMETRY"] = "true"

import json
import time
import argparse
import asyncio
from pathlib import Path
from typing import Dict, Any, List

# Add paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

def load_dotenv(env_path: Path):
    """Loads key-value pairs from .env file into os.environ."""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v

load_dotenv(BASE_DIR / ".env")

from dokuwiki_mcp.telemetry import LOG_DIR
from dokuwiki_mcp.server import wiki_search_and_explore, SearchAndExploreAction
from reset_testbed import reset_wiki_state

# Import verifier
sys.path.insert(0, str(BASE_DIR / "tests" / "benchmarks"))
from verifier import verify_task_state

BENCHMARK_FILE = BASE_DIR / "tests" / "benchmarks" / "benchmarks.json"
REPORT_DIR = BASE_DIR / "logs" / "eval_reports"

def parse_trajectory_metrics(session_id: str) -> Dict[str, Any]:
    """Parses JSON-Lines trajectory log for a session and computes aggregated KPIs."""
    log_file = LOG_DIR / f"{session_id}.jsonl"
    if not log_file.exists():
        return {
            "n_turns": 0,
            "l_mcp_ms": 0.0,
            "l_wiki_ms": 0.0,
            "dto_tokens": 0,
            "schema_errors": 0,
            "rpc_errors": 0,
            "compression_ratio": 1.0
        }

    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    n_turns = len(lines)
    l_mcp_total = 0.0
    l_wiki_total = 0.0
    dto_tokens_total = 0
    schema_errors = 0
    rpc_errors = 0
    compression_ratios = []

    for item in lines:
        m = item.get("metrics", {})
        layer_a = m.get("layer_a_mcp_pure", {})
        layer_c = m.get("layer_c_subsystem", {})

        l_mcp_total += layer_a.get("l_mcp_ms", 0.0)
        l_wiki_total += layer_c.get("l_wiki_backend_ms", 0.0)
        dto_tokens_total += layer_a.get("dto_response_tokens", 0)

        if layer_a.get("is_schema_error"):
            schema_errors += 1
        if layer_c.get("is_rpc_error"):
            rpc_errors += 1

        ratio = layer_a.get("estimated_compression_ratio", 1.0)
        if ratio > 0:
            compression_ratios.append(ratio)

    avg_compression = round(sum(compression_ratios) / len(compression_ratios), 2) if compression_ratios else 1.0

    return {
        "n_turns": n_turns,
        "l_mcp_ms": round(l_mcp_total, 2),
        "l_wiki_ms": round(l_wiki_total, 2),
        "dto_tokens": dto_tokens_total,
        "schema_errors": schema_errors,
        "rpc_errors": rpc_errors,
        "compression_ratio": avg_compression
    }

async def run_benchmark_eval(model_name: str = "gemini-2.5-flash", limit: int = 0, live_mode: bool = False):
    """Main execution loop for running benchmarks."""
    os.environ["MCP_ENABLE_TELEMETRY"] = "true"
    mode_str = "LIVE LLM Agent (Stufe 2)" if live_mode else "Deterministic Harness (Stufe 1)"
    print(f"🎯 Starting MCP Benchmark Evaluation Suite [{mode_str}] using model: '{model_name}'")

    if not BENCHMARK_FILE.exists():
        print(f"❌ Error: Benchmark dataset not found at {BENCHMARK_FILE}")
        sys.exit(1)

    dataset = json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))
    tasks = dataset.get("tasks", [])
    if limit > 0:
        tasks = tasks[:limit]

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    results = []

    for idx, task in enumerate(tasks, 1):
        task_id = task["id"]
        session_id = f"eval_{timestamp}_task_{task_id}"
        print(f"\n▶ [{idx}/{len(tasks)}] Running Task '{task_id}' ({task['category']}) ...")

        # 1. Reset wiki state
        reset_wiki_state()

        # 2. Mock / Execute task via FastMCP direct engine or LLM agent runner
        t0 = time.perf_counter()
        
        class MockContext:
            def __init__(self, sess_id):
                self.session_id = sess_id
        
        mock_ctx = MockContext(session_id)

        from dokuwiki_mcp.server import (
            wiki_search_and_explore, SearchAndExploreAction,
            wiki_read_content, ReadContentAction,
            wiki_write_and_modify, WriteModifyAction,
            wiki_admin_and_meta, AdminMetaAction,
            wiki_batch_execute, BatchTaskItem
        )

        if live_mode:
            # Stufe 2: Live LLM Agent Execution via Google Gemini API
            from google import genai
            from google.genai import types
            from typing import Optional, List

            gemini_client = genai.Client()

            import concurrent.futures

            def run_async(coro):
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(asyncio.run, coro).result()

            def search_and_explore(
                action: str, query: Optional[str] = None, namespace: Optional[str] = "",
                depth: int = 1, exclusions: Optional[List[str]] = None, pattern: Optional[str] = None,
                modified_after: Optional[str] = None, limit: int = 50
            ) -> str:
                """Explores the wiki by searching pages ('search'), listing namespace items ('list'), or tracking recent modifications ('recent_changes')."""
                try:
                    act_enum = SearchAndExploreAction(action) if action in [a.value for a in SearchAndExploreAction] else action
                except Exception:
                    act_enum = action
                return run_async(wiki_search_and_explore(
                    action=act_enum, query=query, namespace=namespace, depth=depth,
                    exclusions=exclusions, pattern=pattern, modified_after=modified_after,
                    limit=limit, ctx=mock_ctx
                ))

            def read_content(
                action: str, target_id: Optional[str] = None, version: Optional[str] = None,
                regex_filter: Optional[str] = None, max_insights: int = 5
            ) -> str:
                """Reads wiki page contents ('read_page'), retrieves section structure/TOC ('get_structure'), extracts insights ('extract_insights'), gets link relationships ('get_links'), or reads media metadata ('read_media')."""
                try:
                    act_enum = ReadContentAction(action) if action in [a.value for a in ReadContentAction] else action
                except Exception:
                    act_enum = action
                return run_async(wiki_read_content(
                    action=act_enum, target_id=target_id, version=version,
                    regex_filter=regex_filter, max_insights=max_insights, ctx=mock_ctx
                ))

            def write_and_modify(
                action: str, target_id: Optional[str] = None, content: Optional[str] = None,
                summary: Optional[str] = None, section_id: Optional[int] = None,
                patch_diff: Optional[str] = None, transaction_id: Optional[str] = None
            ) -> str:
                """Modifies or creates wiki content ('save_page'), patches content ('patch_page'), edits sections ('modify_section'), manages drafts/locks ('prepare_write', 'commit', 'rollback', 'lock', 'unlock'), or handles media attachments ('save_media', 'delete_media')."""
                try:
                    act_enum = WriteModifyAction(action) if action in [a.value for a in WriteModifyAction] else action
                except Exception:
                    act_enum = action
                return run_async(wiki_write_and_modify(
                    action=act_enum, target_id=target_id, content=content, summary=summary,
                    section_id=section_id, patch_diff=patch_diff, transaction_id=transaction_id,
                    ctx=mock_ctx
                ))

            def admin_and_meta(
                action: str, page_id: Optional[str] = None, user: Optional[str] = "",
                groups: Optional[List[str]] = None, namespace: Optional[str] = None
            ) -> str:
                """Administrative and metadata actions: evaluate ACL rights ('acl_check'), retrieve user identity ('who_ami'), view server/API versions ('system_info'), or set default namespace ('set_namespace')."""
                try:
                    act_enum = AdminMetaAction(action) if action in [a.value for a in AdminMetaAction] else action
                except Exception:
                    act_enum = action
                return run_async(wiki_admin_and_meta(
                    action=act_enum, page_id=page_id, user=user, groups=groups,
                    namespace=namespace, ctx=mock_ctx
                ))

            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    gemini_client.models.generate_content(
                        model=model_name,
                        contents=task["prompt"],
                        config=types.GenerateContentConfig(
                            tools=[search_and_explore, read_content, write_and_modify, admin_and_meta],
                            system_instruction="Du bist ein autonomer DokuWiki Assistent. Wähle und benutze die bereitgestellten Tools präzise, um die Benutzeranfrage vollständig zu lösen."
                        )
                    )
                    break
                except Exception as live_err:
                    err_str = str(live_err)
                    if ("429" in err_str or "503" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries:
                        wait_sec = 12 * attempt
                        print(f"  ⏳ Live Rate Limit / Quota Spurt ({err_str[:40]}...). Warte {wait_sec}s vor Versuch {attempt + 1}/{max_retries}...")
                        time.sleep(wait_sec)
                    else:
                        print(f"  ⚠️ Live LLM Execution Note: {live_err}")
                        break
        else:
            # Stufe 1: Simulating execution harness (In-process execution test)
            if task_id == "search_01_keycloak":
                await wiki_search_and_explore(action=SearchAndExploreAction.search, query="Keycloak", ctx=mock_ctx)

            elif task_id == "search_02_exclusion":
                await wiki_search_and_explore(action=SearchAndExploreAction.list_items, namespace="", exclusions=["drafts"], ctx=mock_ctx)

            elif task_id == "search_03_structure_toc":
                await wiki_read_content(action=ReadContentAction.get_structure, target_id="wiki:welcome", ctx=mock_ctx)

            elif task_id == "search_04_regex_filter":
                await wiki_read_content(action=ReadContentAction.read_page, target_id="wiki:welcome", regex_filter="(?i)(benchmark|test)", ctx=mock_ctx)

            elif task_id == "search_05_namespace_list":
                await wiki_search_and_explore(action=SearchAndExploreAction.list_items, namespace="wiki", ctx=mock_ctx)

            elif task_id == "search_06_recent_changes":
                await wiki_search_and_explore(action=SearchAndExploreAction.recent_changes, modified_after="0", ctx=mock_ctx)

            elif task_id == "search_07_media_search":
                await wiki_search_and_explore(action=SearchAndExploreAction.list_items, namespace="wiki", ctx=mock_ctx)

            elif task_id == "search_08_extract_insights":
                await wiki_read_content(action=ReadContentAction.extract_insights, target_id="wiki:welcome", ctx=mock_ctx)

            elif task_id == "search_09_page_links":
                await wiki_read_content(action=ReadContentAction.get_links, target_id="wiki:welcome", ctx=mock_ctx)

            elif task_id == "search_10_media_read":
                await wiki_read_content(action=ReadContentAction.read_media, target_id="wiki:dokuwiki-128.png", ctx=mock_ctx)

            elif task_id == "author_01_create_page":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:architecture", content="= Architektur =\nDies ist ein Testentwurf.", ctx=mock_ctx)

            elif task_id == "author_02_section_edit":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:architecture", content="= Architektur =\nOriginaler Text.", ctx=mock_ctx)
                await wiki_write_and_modify(action=WriteModifyAction.patch_page, target_id="docs:architecture", patch_diff="Abschnitt 2 wurde agentisch aktualisiert.", ctx=mock_ctx)

            elif task_id == "author_03_two_phase_commit":
                prep_res = await wiki_write_and_modify(action=WriteModifyAction.prepare_write, target_id="docs:release_notes", content="Release 1.0 notes.", ctx=mock_ctx)
                tx_id = None
                if isinstance(prep_res, str) and "tx_id" in prep_res:
                    try:
                        import re
                        m = re.search(r'tx_id=["\']?([a-f0-9\-]+)["\']?', prep_res)
                        if m: tx_id = m.group(1)
                    except Exception: pass
                await wiki_write_and_modify(action=WriteModifyAction.commit, transaction_id=tx_id or "latest", ctx=mock_ctx)

            elif task_id == "author_04_modify_section":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:architecture", content="= Header =\nOriginal", ctx=mock_ctx)
                await wiki_write_and_modify(action=WriteModifyAction.modify_section, target_id="docs:architecture", section_id=1, content="Spezifischer Abschnittsinhalt", ctx=mock_ctx)

            elif task_id == "author_05_rollback_write":
                prep_res = await wiki_write_and_modify(action=WriteModifyAction.prepare_write, target_id="docs:draft_page", content="Rollback test content.", ctx=mock_ctx)
                tx_id = None
                if isinstance(prep_res, str) and "tx_id" in prep_res:
                    try:
                        import re
                        m = re.search(r'tx_id=["\']?([a-f0-9\-]+)["\']?', prep_res)
                        if m: tx_id = m.group(1)
                    except Exception: pass
                await wiki_write_and_modify(action=WriteModifyAction.rollback, transaction_id=tx_id or "latest", ctx=mock_ctx)

            elif task_id == "author_06_save_media":
                await wiki_write_and_modify(action=WriteModifyAction.save_media, target_id="wiki:logo_test.png", content="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", ctx=mock_ctx)

            elif task_id == "author_07_lock_page":
                await wiki_write_and_modify(action=WriteModifyAction.lock, target_id="docs:architecture", ctx=mock_ctx)

            elif task_id == "author_08_unlock_page":
                await wiki_write_and_modify(action=WriteModifyAction.unlock, target_id="docs:architecture", ctx=mock_ctx)

            elif task_id == "author_09_delete_media":
                await wiki_write_and_modify(action=WriteModifyAction.delete_media, target_id="wiki:logo_test.png", ctx=mock_ctx)

            elif task_id == "author_10_append_text":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:architecture", content="= Architektur =\nOriginal\nZusätzlicher Anhang", ctx=mock_ctx)

            elif task_id == "refactor_01_tagging":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:architecture", content="= Architektur =\nBase content.\n{{tag>production v1}}", ctx=mock_ctx)

            elif task_id == "refactor_02_clean_draft":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:architecture", content="", ctx=mock_ctx)

            elif task_id == "refactor_03_apply_diff_patch":
                await wiki_write_and_modify(action=WriteModifyAction.patch_page, target_id="docs:architecture", patch_diff="--- old\n+++ new\n@@ -1 +1 @@\n-old text\n+new text", ctx=mock_ctx)

            elif task_id == "refactor_04_clean_media_archive":
                await wiki_write_and_modify(action=WriteModifyAction.delete_media, target_id="archive:old_logo.png", ctx=mock_ctx)

            elif task_id == "refactor_05_reorganize_namespace":
                await wiki_write_and_modify(action=WriteModifyAction.save_page, target_id="docs:guide", content="Refactored content", ctx=mock_ctx)
                await wiki_write_and_modify(action=WriteModifyAction.delete_page, target_id="playground:temp", ctx=mock_ctx)

            elif task_id == "admin_01_acl_check":
                await wiki_admin_and_meta(action=AdminMetaAction.acl_check, page_id="wiki:welcome", ctx=mock_ctx)

            elif task_id == "admin_02_get_version":
                await wiki_admin_and_meta(action=AdminMetaAction.system_info, ctx=mock_ctx)

            elif task_id == "admin_03_who_am_i":
                await wiki_admin_and_meta(action=AdminMetaAction.who_ami, ctx=mock_ctx)

            elif task_id == "batch_01_multi_search":
                item1 = BatchTaskItem(task_id="t1", tool="wiki_search_and_explore", params={"action": "search", "query": "Keycloak"})
                item2 = BatchTaskItem(task_id="t2", tool="wiki_search_and_explore", params={"action": "search", "query": "DokuWiki"})
                await wiki_batch_execute(tasks=[item1, item2], ctx=mock_ctx)

            elif task_id == "batch_02_multi_read":
                item1 = BatchTaskItem(task_id="t1", tool="wiki_read_content", params={"action": "get_structure", "target_id": "wiki:welcome"})
                item2 = BatchTaskItem(task_id="t2", tool="wiki_read_content", params={"action": "get_structure", "target_id": "wiki:syntax"})
                await wiki_batch_execute(tasks=[item1, item2], ctx=mock_ctx)

        t1 = time.perf_counter()

        # 3. Assert task result via verifier
        is_passed, failures = verify_task_state(task, session_id)
        metrics = parse_trajectory_metrics(session_id)

        status_icon = "✅ PASS" if is_passed else "❌ FAIL"
        print(f"  Result: {status_icon} | Turns: {metrics['n_turns']} | MCP Latency: {metrics['l_mcp_ms']}ms | Wiki Latency: {metrics['l_wiki_ms']}ms")
        if failures:
            for f in failures:
                print(f"    - Failure: {f}")

        results.append({
            "task_id": task_id,
            "category": task["category"],
            "prompt": task["prompt"],
            "is_passed": is_passed,
            "failures": failures,
            "metrics": metrics,
            "wall_latency_sec": round(t1 - t0, 3)
        })

    # Generate Summary Report
    generate_markdown_report(timestamp, model_name, results)

def generate_markdown_report(timestamp: str, model_name: str, results: List[Dict[str, Any]]):
    """Generates transparent, layered KPI Markdown report."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"eval_report_{timestamp}.md"

    total_tasks = len(results)
    passed_tasks = sum(1 for r in results if r["is_passed"])
    pass_rate = round((passed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0.0

    avg_mcp_ms = round(sum(r["metrics"]["l_mcp_ms"] for r in results) / total_tasks, 2) if total_tasks else 0.0
    avg_wiki_ms = round(sum(r["metrics"]["l_wiki_ms"] for r in results) / total_tasks, 2) if total_tasks else 0.0
    avg_turns = round(sum(r["metrics"]["n_turns"] for r in results) / total_tasks, 1) if total_tasks else 0.0
    avg_tokens = round(sum(r["metrics"]["dto_tokens"] for r in results) / total_tasks, 0) if total_tasks else 0.0
    total_schema_errors = sum(r["metrics"]["schema_errors"] for r in results)
    avg_compression = round(sum(r["metrics"]["compression_ratio"] for r in results) / total_tasks, 2) if total_tasks else 1.0

    md_lines = [
        f"# MCP Evaluation Summary Report",
        f"",
        f"**Timestamp:** `{timestamp}`  ",
        f"**Test Model:** `{model_name}`  ",
        f"**Tasks Evaluated:** `{total_tasks}`  ",
        f"",
        f"## 📊 High-Level KPI Dashboard",
        f"",
        f"| KPI Category | Metrik | Wert | Ziel / Baseline |",
        f"| :--- | :--- | :--- | :--- |",
        f"| **Layer B (Agent)** | **Task Success Rate (`Pass@1`)** | **{pass_rate}%** ({passed_tasks}/{total_tasks}) | $\\ge 95\\%$ |",
        f"| **Layer B (Agent)** | **Avg. Trajectory Length (`N_turns`)** | **{avg_turns}** turns/task | Minimieren |",
        f"| **Layer B (Agent)** | **Avg. Response Tokens (`T_dto`)** | **{int(avg_tokens)}** tokens/task | Minimieren |",
        f"| **Layer A (Pure MCP)**| **Pure MCP Overhead (`L_mcp`)** | **{avg_mcp_ms} ms** | $< 5.0\\,\\text{{ms}}$ |",
        f"| **Layer A (Pure MCP)**| **Compression Ratio (`C_tokens`)** | **{avg_compression}x** | $> 4.0\\times$ |",
        f"| **Layer A (Pure MCP)**| **Schema Error Count (`E_schema`)** | **{total_schema_errors}** errors | $0$ |",
        f"| **Layer C (Subsystem)**| **DokuWiki Backend Latency (`L_wiki`)**| **{avg_wiki_ms} ms** | Telemetrie (Isoliert) |",
        f"",
        f"---",
        f"",
        f"## 📋 Task Breakdown",
        f"",
        f"| Task ID | Kategorie | Status | Turns | MCP Time (`L_mcp`) | Wiki Time (`L_wiki`) | Tokens | Compression |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for r in results:
        m = r["metrics"]
        icon = "✅ PASS" if r["is_passed"] else "❌ FAIL"
        md_lines.append(
            f"| `{r['task_id']}` | {r['category']} | {icon} | {m['n_turns']} | {m['l_mcp_ms']} ms | {m['l_wiki_ms']} ms | {m['dto_tokens']} | {m['compression_ratio']}x |"
        )

    md_lines.append("")
    report_file.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"📊 Summary Markdown Report saved to: {report_file}")
    
    # Generate visual HTML Dashboard
    generate_html_dashboard(timestamp, model_name, results, pass_rate, passed_tasks, total_tasks, avg_mcp_ms, avg_wiki_ms, avg_turns, avg_tokens, total_schema_errors, avg_compression)

def generate_html_dashboard(timestamp, model_name, results, pass_rate, passed_tasks, total_tasks, avg_mcp_ms, avg_wiki_ms, avg_turns, avg_tokens, total_schema_errors, avg_compression):
    """Generates a sleek, dark-mode visual HTML dashboard for benchmark results."""
    html_file = REPORT_DIR / f"dashboard_{timestamp}.html"
    
    rows_html = ""
    for r in results:
        m = r["metrics"]
        status_badge = '<span class="badge badge-success">PASS</span>' if r["is_passed"] else '<span class="badge badge-danger">FAIL</span>'
        failures_html = f'<div class="failure-reason">{"<br>".join(r["failures"])}</div>' if r["failures"] else ''
        
        rows_html += f"""
        <tr>
            <td class="has-tooltip tooltip-up">
                <code>{r['task_id']}</code>
                <div class="tooltip-box">
                    <div class="tooltip-header">Task: {r['task_id']}</div>
                    <div><strong>Prompt:</strong> "{r['prompt']}"</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> Definition & Assertions in <code>tests/benchmarks/benchmarks.json</code> anpassen.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up">
                <span class="category-tag">{r['category']}</span>
                <div class="tooltip-box">
                    <div class="tooltip-header">Domäne: {r['category']}</div>
                    <div>Funktionale Zuordnung des Testfalls.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> In <code>server.py</code> Tool-Abgrenzung über klare `@mcp.tool` Metadata &amp; Annotations schärfen.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up">
                {status_badge}
                <div class="tooltip-box">
                    <div class="tooltip-header">Status Verification</div>
                    <div>{ "Vollständig bestanden." if r["is_passed"] else "Assertion fehlgeschlagen!" }</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> Pydantic <code>Field(description=...)</code> im Tool-Parameter verfeinern oder Verifier-Assertion in <code>verifier.py</code> prüfen.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up">
                {m['n_turns']}
                <div class="tooltip-box">
                    <div class="tooltip-header">Turns (Interaktionsschritte)</div>
                    <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser (Ziel: 1 Turn)</span>
                    <div>Benötigte Tool-Aufrufe des Modells bis zur finalen Aufgabenlösung.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> Makro-Tools zusammenfassen und <code>wiki_batch_execute</code> anbieten für Multi-Step Batching.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up">
                <strong>{m['l_mcp_ms']} ms</strong>
                <div class="tooltip-box">
                    <div class="tooltip-header">Pure MCP Overhead (L_mcp)</div>
                    <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser (&lt; 5 ms)</span>
                    <div>Reine Python-Verarbeitungszeit im MCP Server für diesen Call.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> Regex pre-compilen, YAKE Parameter abstimmen, FastMCP LRU-Cache nutzen.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up">
                {m['l_wiki_ms']} ms
                <div class="tooltip-box">
                    <div class="tooltip-header">DokuWiki Backend Zeit (L_wiki)</div>
                    <span class="tooltip-badge tooltip-info">ℹ Infrastruktur (DokuWiki Engine)</span>
                    <div>HTTP JSON-RPC Antwortdauer des PHP Backends.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> Redundante RPC Aufrufe durch intelligentes MCP In-Memory Caching (<code>cached_get_page</code>) minimieren.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up tooltip-left">
                {m['dto_tokens']}
                <div class="tooltip-box">
                    <div class="tooltip-header">Response Payload (T_dto)</div>
                    <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser</span>
                    <div>Tokenanzahl der an das Modell gesendeten Antwort.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> <code>format="markdown"</code> nutzen, Filter-Parameter (<code>regex_filter</code>, <code>exclusions</code>, <code>get_structure</code>) in Tool-Prompts bewerben.
                    </div>
                </div>
            </td>
            <td class="has-tooltip tooltip-up tooltip-left">
                <span class="highlight-text">{m['compression_ratio']}x</span>{failures_html}
                <div class="tooltip-box">
                    <div class="tooltip-header">Kompression (C_tokens)</div>
                    <span class="tooltip-badge tooltip-higher">▲ Größer ist besser (&gt; 4.0x)</span>
                    <div>Verhältnis von ungefilterter Backend-Antwort zu kompakter DTO-Antwort.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Stellschraube im MCP:</span> Unnötige HTML-Tags, Metadaten und Rauschen in den DTO-Transformationen in <code>server.py</code> filtern.
                    </div>
                </div>
            </td>
        </tr>
        """

    pass_color = "#10b981" if pass_rate >= 80 else "#f59e0b" if pass_rate >= 50 else "#ef4444"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Benchmark Dashboard - {timestamp}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --border-color: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-purple: #c084fc;
            --accent-amber: #f59e0b;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 30px;
        }}
        .container {{
            max-width: 1280px;
            margin: 0 auto;
            position: relative;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 26px;
            font-weight: 700;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .meta-info {{
            font-size: 14px;
            color: var(--text-muted);
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 20px;
            margin-bottom: 35px;
            overflow: visible;
        }}
        .card {{
            position: relative;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            cursor: help;
            overflow: visible !important;
        }}
        .card-title {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 10px;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .card-title::after {{
            content: "ℹ️";
            font-size: 12px;
            opacity: 0.6;
        }}
        .card-value {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 10px;
        }}
        .progress-bar-bg {{
            background: #334155;
            height: 8px;
            border-radius: 4px;
            overflow: hidden;
        }}
        .progress-bar-fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }}

        /* --- Global Tooltip Engine --- */
        .has-tooltip {{
            position: relative;
            cursor: help;
        }}
        .has-tooltip .tooltip-box {{
            visibility: hidden;
            opacity: 0;
            position: absolute;
            width: 290px;
            background-color: #020617;
            color: #e2e8f0;
            border: 1px solid #475569;
            padding: 12px 14px;
            border-radius: 8px;
            font-size: 12px;
            line-height: 1.5;
            font-weight: 400;
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.7);
            z-index: 9999;
            pointer-events: none;
            transition: opacity 0.2s ease, transform 0.2s ease, visibility 0.2s;
            text-transform: none;
            letter-spacing: normal;
            word-wrap: break-word;
        }}

        /* Default: Pop DOWNWARDS (for Top Cards & Table Headers) */
        .has-tooltip.tooltip-down .tooltip-box,
        .card.has-tooltip .tooltip-box,
        th.has-tooltip .tooltip-box {{
            top: 110%;
            bottom: auto;
            left: 50%;
            transform: translateX(-50%) translateY(-5px);
        }}
        .has-tooltip.tooltip-down .tooltip-box::after,
        .card.has-tooltip .tooltip-box::after,
        th.has-tooltip .tooltip-box::after {{
            content: "";
            position: absolute;
            bottom: 100%;
            left: 50%;
            margin-left: -6px;
            border-width: 6px;
            border-style: solid;
            border-color: transparent transparent #020617 transparent;
        }}

        /* Tooltip Pop UPWARDS (for Data Cells) */
        .has-tooltip.tooltip-up .tooltip-box {{
            bottom: 115%;
            top: auto;
            left: 50%;
            transform: translateX(-50%) translateY(5px);
        }}
        .has-tooltip.tooltip-up .tooltip-box::after {{
            content: "";
            position: absolute;
            top: 100%;
            left: 50%;
            margin-left: -6px;
            border-width: 6px;
            border-style: solid;
            border-color: #020617 transparent transparent transparent;
        }}

        /* Align Left for edge columns */
        .has-tooltip.tooltip-left .tooltip-box {{
            left: auto;
            right: 0;
            transform: translateY(0);
        }}
        .has-tooltip.tooltip-left .tooltip-box::after {{
            left: auto;
            right: 15px;
            margin-left: 0;
        }}

        .has-tooltip:hover .tooltip-box {{
            visibility: visible;
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }}
        .has-tooltip.tooltip-left:hover .tooltip-box {{
            transform: translateY(0);
        }}

        .tooltip-header {{
            font-weight: 700;
            color: var(--accent-blue);
            margin-bottom: 4px;
            font-size: 13px;
        }}
        .tooltip-badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            margin-bottom: 6px;
        }}
        .tooltip-higher {{ background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .tooltip-lower {{ background: rgba(56, 189, 248, 0.2); color: var(--accent-blue); border: 1px solid var(--accent-blue); }}
        .tooltip-info {{ background: rgba(148, 163, 184, 0.2); color: var(--text-muted); border: 1px solid var(--text-muted); }}
        .tooltip-section {{
            margin-top: 6px;
            border-top: 1px dashed #334155;
            padding-top: 6px;
        }}
        .tooltip-label {{
            color: var(--accent-purple);
            font-weight: 600;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            overflow: visible;
        }}
        th, td {{
            padding: 14px 18px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            font-size: 14px;
            position: relative;
        }}
        th {{
            background: #0f172a;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
            letter-spacing: 0.05em;
        }}
        tr:last-child td {{ border-bottom: none; }}
        code {{ font-family: monospace; background: #0f172a; padding: 3px 6px; border-radius: 4px; color: var(--accent-blue); }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-success {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .badge-danger {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid var(--accent-red); }}
        .category-tag {{ color: var(--accent-purple); font-size: 12px; font-weight: 500; }}
        .highlight-text {{ color: var(--accent-blue); font-weight: 600; }}
        .failure-reason {{ font-size: 11px; color: var(--accent-red); margin-top: 4px; font-family: monospace; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>DokuWiki MCP Benchmark Dashboard</h1>
                <div class="meta-info">Run Timestamp: {timestamp} &bull; Model: {model_name} &bull; Total Tasks: {total_tasks}</div>
            </div>
        </div>

        <div class="grid">
            <div class="card has-tooltip tooltip-down">
                <div class="card-title">Layer B: Task Success Rate (Pass@1)</div>
                <div class="card-value" style="color: {pass_color};">{pass_rate}%</div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" style="width: {pass_rate}%; background-color: {pass_color};"></div>
                </div>
                <div class="tooltip-box">
                    <div class="tooltip-header">Pass@1 (Task Success Rate)</div>
                    <span class="tooltip-badge tooltip-higher">▲ Größer ist besser (Ziel ≥ 95%)</span>
                    <div>Prozentsatz aller Test-Tasks, die beim ersten Durchlauf deterministisch alle State-Assertions erfüllen.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Wie im MCP beeinflussen?</span> Schärfung von Pydantic <code>Field(description=...)</code> in <code>server.py</code> für eindeutiges LLM Tool-Routing.
                    </div>
                </div>
            </div>

            <div class="card has-tooltip tooltip-down">
                <div class="card-title">Layer A: Pure MCP Latency (L_mcp)</div>
                <div class="card-value" style="color: var(--accent-blue);">{avg_mcp_ms} ms</div>
                <div class="meta-info">Isolated Python processing time</div>
                <div class="tooltip-box">
                    <div class="tooltip-header">Pure MCP Overhead (L_mcp)</div>
                    <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser (Ziel &lt; 5.0 ms)</span>
                    <div>Isolierte Ausführungsdauer der Python-Logik im MCP Server (DTO-Transformation, YAKE, Regex-Filtering).</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Wie im MCP beeinflussen?</span> Ineffiziente Regexes vorkompilieren, FastMCP Caching nutzen, YAKE Keyword-Limit reduzieren.
                    </div>
                </div>
            </div>

            <div class="card has-tooltip tooltip-down">
                <div class="card-title">Layer A: Compression Ratio (C_tokens)</div>
                <div class="card-value" style="color: var(--accent-purple);">{avg_compression}x</div>
                <div class="meta-info">Payload compression factor</div>
                <div class="tooltip-box">
                    <div class="tooltip-header">Token Compression (C_tokens)</div>
                    <span class="tooltip-badge tooltip-higher">▲ Größer ist besser (Ziel &gt; 4.0x)</span>
                    <div>Verhältnis von ungefilterter DokuWiki-Antwort zu kompakter MCP DTO-Response (Raw / DTO Tokens).</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Wie im MCP beeinflussen?</span> Redundantes HTML/Wikitext-Markup im Preprocessing strippen und schlanke DTO-Formate zurückgeben.
                    </div>
                </div>
            </div>

            <div class="card has-tooltip tooltip-down">
                <div class="card-title">Layer C: Wiki Backend Latency (L_wiki)</div>
                <div class="card-value" style="color: var(--text-muted);">{avg_wiki_ms} ms</div>
                <div class="meta-info">DokuWiki HTTP RPC duration</div>
                <div class="tooltip-box">
                    <div class="tooltip-header">Wiki Subsystem Latency (L_wiki)</div>
                    <span class="tooltip-badge tooltip-info">ℹ Telemetrie (Infrastruktur)</span>
                    <div>Reine HTTP-Netzwerk- und PHP-Ausführungszeit des DokuWiki-Containers.</div>
                    <div class="tooltip-section">
                        <span class="tooltip-label">⚙️ Wie im MCP beeinflussen?</span> MCP In-Memory Cache (<code>cached_get_page</code>) nutzen, um unötige HTTP-RPC Calls komplett einzusparen.
                    </div>
                </div>
            </div>
        </div>

        <div class="card" style="padding: 0; overflow: visible !important;">
            <table>
                <thead>
                    <tr>
                        <th class="has-tooltip tooltip-down">
                            Task ID
                            <div class="tooltip-box">
                                <div class="tooltip-header">Task ID</div>
                                <div>Eindeutiger Bezeichner des Szenarios in <code>benchmarks.json</code>.</div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down">
                            Category
                            <div class="tooltip-box">
                                <div class="tooltip-header">Kategorie</div>
                                <div>Funktionale Domäne des Tests (z.B. <code>read_search</code>, <code>authoring</code>, <code>refactoring</code>).</div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down">
                            Status
                            <div class="tooltip-box">
                                <div class="tooltip-header">Evaluation Status</div>
                                <div><span class="badge badge-success">PASS</span> = Verifier Assertions erfüllt.<br><span class="badge badge-danger">FAIL</span> = Assertion verfehlt.</div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down">
                            Turns
                            <div class="tooltip-box">
                                <div class="tooltip-header">Turns (Interaktionsschritte)</div>
                                <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser</span>
                                <div>Anzahl der LLM Tool-Calls bis zur Aufgabenlösung (1 Turn optimal).</div>
                                <div class="tooltip-section">
                                    <span class="tooltip-label">⚙️ Wie beeinflussen?</span> Makro-Tools &amp; Batching für Multi-Step Execution nutzen.
                                </div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down">
                            MCP Time (L_mcp)
                            <div class="tooltip-box">
                                <div class="tooltip-header">Pure MCP Time (L_mcp)</div>
                                <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser (&lt; 5 ms)</span>
                                <div>Reiner Python-Verarbeitungsaufwand im MCP Server.</div>
                                <div class="tooltip-section">
                                    <span class="tooltip-label">⚙️ Wie beeinflussen?</span> Python-Preprocessing in <code>server.py</code> beschleunigen.
                                </div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down">
                            Wiki Time (L_wiki)
                            <div class="tooltip-box">
                                <div class="tooltip-header">Subsystem Latency (L_wiki)</div>
                                <div>DokuWiki HTTP JSON-RPC Antwortzeit für diese Task.</div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down tooltip-left">
                            Response Tokens
                            <div class="tooltip-box">
                                <div class="tooltip-header">Response Tokens (T_dto)</div>
                                <span class="tooltip-badge tooltip-lower">▼ Kleiner ist besser</span>
                                <div>Tokenanzahl der MCP-Antwort an das LLM.</div>
                                <div class="tooltip-section">
                                    <span class="tooltip-label">⚙️ Wie beeinflussen?</span> <code>format="markdown"</code> oder Selective Filtering nutzen.
                                </div>
                            </div>
                        </th>
                        <th class="has-tooltip tooltip-down tooltip-left">
                            Compression / Notes
                            <div class="tooltip-box">
                                <div class="tooltip-header">Compression &amp; Failure Log</div>
                                <span class="tooltip-badge tooltip-higher">▲ Größer ist besser</span>
                                <div>Einsparungsfaktor gegenüber unkomprimierten Rohdaten. Bei Fehlern steht hier der Grund.</div>
                            </div>
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <script>
    document.addEventListener("DOMContentLoaded", () => {{
        const table = document.querySelector("table");
        if (!table) return;
        const headers = table.querySelectorAll("th");
        const tbody = table.querySelector("tbody");

        let currentSort = {{ colIndex: -1, asc: true }};

        headers.forEach((th, index) => {{
            th.style.cursor = "pointer";
            
            const sortIndicator = document.createElement("span");
            sortIndicator.className = "sort-icon";
            sortIndicator.style.marginLeft = "4px";
            sortIndicator.style.fontSize = "10px";
            sortIndicator.style.opacity = "0.4";
            sortIndicator.innerHTML = "↕";
            th.insertBefore(sortIndicator, th.querySelector(".tooltip-box"));

            th.addEventListener("click", (e) => {{
                if (e.target.closest(".tooltip-box")) return;

                const isAsc = (currentSort.colIndex === index) ? !currentSort.asc : true;
                currentSort = {{ colIndex: index, asc: isAsc }};

                headers.forEach((h, i) => {{
                    const icon = h.querySelector(".sort-icon");
                    if (icon) {{
                        if (i === index) {{
                            icon.innerHTML = isAsc ? "▲" : "▼";
                            icon.style.opacity = "1";
                            icon.style.color = "var(--accent-blue)";
                        }} else {{
                            icon.innerHTML = "↕";
                            icon.style.opacity = "0.3";
                            icon.style.color = "inherit";
                        }}
                    }}
                }});

                const rows = Array.from(tbody.querySelectorAll("tr"));
                rows.sort((rowA, rowB) => {{
                    const cellA = rowA.children[index].textContent.trim();
                    const cellB = rowB.children[index].textContent.trim();

                    const cleanA = cellA.replace(/ms|x|%|\s+/g, "");
                    const cleanB = cellB.replace(/ms|x|%|\s+/g, "");

                    const numA = parseFloat(cleanA);
                    const numB = parseFloat(cleanB);

                    if (!isNaN(numA) && !isNaN(numB) && cleanA.length > 0 && cleanB.length > 0 && !isNaN(cleanA) && !isNaN(cleanB)) {{
                        return isAsc ? numA - numB : numB - numA;
                    }} else {{
                        return isAsc ? cellA.localeCompare(cellB) : cellB.localeCompare(cellA);
                    }}
                }});

                rows.forEach(row => tbody.appendChild(row));
            }});
        }});
    }});
    </script>
</body>
</html>
"""
    html_file.write_text(html_content, encoding="utf-8")
    print(f"🎨 Visual Dashboard saved to: {html_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DokuWiki MCP Evaluation Suite")
    parser.add_argument("--model", type=str, default="gemini-flash-latest", help="Model name used for test agent")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of benchmark tasks to run")
    parser.add_argument("--live", action="store_true", help="Execute Stufe 2 Live LLM Evaluation via Google API")
    args = parser.parse_args()

    asyncio.run(run_benchmark_eval(model_name=args.model, limit=args.limit, live_mode=args.live))
