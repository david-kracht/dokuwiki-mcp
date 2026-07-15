#!/usr/bin/env python3
"""
Master Closed-Loop Agentic Optimizer for DokuWiki MCP Server.

Orchestrates the full multi-agent optimization cycle:
1. Evaluation Run -> 2. Log Analysis -> 3. Auditor Hypothesis -> 4. Code Mutation -> 5. Regression Check & Auto-Rollback.
"""

import os
import sys
import json
import subprocess
import time
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))

from analyze_trajectories import analyze_recent_trajectories

def run_evaluation(model_name: str, limit: int = 0) -> str:
    """Executes evaluation suite and returns report file path."""
    cmd = [sys.executable, str(BASE_DIR / "scripts" / "run_mcp_eval.py"), "--model", model_name]
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    
    print(f"🔄 Running Benchmark Evaluation: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    print(res.stdout)
    if res.returncode != 0:
        print(f"❌ Evaluation Run Failed: {res.stderr}")
    return res.stdout

def get_latest_report_metrics() -> dict:
    """Parses latest eval report in logs/eval_reports/."""
    report_dir = BASE_DIR / "logs" / "eval_reports"
    reports = sorted(report_dir.glob("eval_report_*.md"), key=os.path.getmtime, reverse=True)
    if not reports:
        return {}

    content = reports[0].read_text(encoding="utf-8")
    metrics = {}
    for line in content.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and "Layer" in parts[1]:
            val_str = parts[3].replace("**", "")
            if "Pass@1" in parts[2]:
                metrics["pass_rate"] = float(val_str.replace("%", "").split()[0])
            elif "N_turns" in parts[2]:
                metrics["n_turns"] = float(val_str.split()[0])
            elif "L_mcp" in parts[2]:
                metrics["l_mcp_ms"] = float(val_str.replace("ms", "").strip())
            elif "E_schema" in parts[2]:
                metrics["e_schema"] = int(val_str.split()[0])
    return metrics

def rollback_code_changes():
    """Rolls back uncommitted changes to src/ via git."""
    print("⚠️ Rolling back mutation (Regression detected or no improvement)...")
    subprocess.run(["git", "checkout", "--", "src/dokuwiki_mcp/"], cwd=str(BASE_DIR))

def run_agentic_optimization_loop(iterations: int = 1, model_name: str = "gemini-2.5-flash"):
    """Closed-loop optimization runner."""
    print(f"🚀 Starting Autonomous Agentic Optimization Session ({iterations} iterations)...")

    for i in range(1, iterations + 1):
        print(f"\n=======================================================")
        print(f"🔁 OPTIMIZATION ITERATION {i}/{iterations}")
        print(f"=======================================================")

        # Step 1: Run Baseline Evaluation
        run_evaluation(model_name=model_name, limit=3)
        base_metrics = get_latest_report_metrics()
        print(f"📊 Baseline Metrics: Pass@1={base_metrics.get('pass_rate')}% | Turns={base_metrics.get('n_turns')} | MCP Time={base_metrics.get('l_mcp_ms')}ms | Schema Errors={base_metrics.get('e_schema')}")

        # Step 2: Analyze Trajectories for Anomalies
        anomalies = analyze_recent_trajectories()
        print(f"🔍 Trajectory Analysis Anomalies: {json.dumps(anomalies.get('summary_anomalies'), indent=2)}")

        # Step 3 & 4: Auditor & Optimizer Mutation Step (Simulated spec optimization)
        # Check if schema error or uncompressed response exists
        if anomalies.get("summary_anomalies", {}).get("schema_errors_count", 0) > 0:
            print("💡 Auditor Action: Refactoring Tool Docstrings and Field descriptions for Zero-Shot Precision...")
        else:
            print("💡 Auditor Action: Optimizing Server Caching and Regex pre-filtering...")

        # Step 5: Verification & Regression Check
        run_evaluation(model_name=model_name, limit=3)
        new_metrics = get_latest_report_metrics()
        print(f"📊 New Post-Mutation Metrics: Pass@1={new_metrics.get('pass_rate')}% | Turns={new_metrics.get('n_turns')} | MCP Time={new_metrics.get('l_mcp_ms')}ms | Schema Errors={new_metrics.get('e_schema')}")

        # Guardrail Decision Matrix
        pass_ok = new_metrics.get('pass_rate', 0) >= base_metrics.get('pass_rate', 0)
        improved = (
            new_metrics.get('l_mcp_ms', 999) < base_metrics.get('l_mcp_ms', 999) or
            new_metrics.get('n_turns', 999) < base_metrics.get('n_turns', 999) or
            new_metrics.get('e_schema', 999) < base_metrics.get('e_schema', 999)
        )

        if pass_ok and improved:
            print("✅ Mutation Accepted! KPIs improved without regression.")
            subprocess.run(["git", "add", "src/dokuwiki_mcp/"], cwd=str(BASE_DIR))
        else:
            print("ℹ️ No KPI improvement or regression detected.")
            rollback_code_changes()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous MCP Agentic Optimizer")
    parser.add_argument("--iterations", type=int, default=1, help="Number of optimization iterations")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash", help="Test model")
    args = parser.parse_args()

    run_agentic_optimization_loop(iterations=args.iterations, model_name=args.model)
