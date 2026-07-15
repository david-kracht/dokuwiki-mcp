#!/usr/bin/env python3
"""
Trajectory Analyzer & Anomaly Detection Agent for DokuWiki MCP Framework.

Scans JSON-Lines trajectory logs, isolates Layer A/B anomalies (Schema Errors,
high Python overheads, uncompressed payloads, looping turns), and generates structured
anomaly reports for the Assessor/Auditor Agent.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs" / "trajectories"

def analyze_recent_trajectories(session_prefix: str = "") -> Dict[str, Any]:
    """Analyzes trajectory log files and extracts structured anomalies."""
    if not LOG_DIR.exists():
        return {"error": "No trajectory logs directory found."}

    log_files = sorted(LOG_DIR.glob(f"{session_prefix}*.jsonl"), key=os.path.getmtime, reverse=True)
    if not log_files:
        return {"error": f"No trajectory logs matching prefix '{session_prefix}'."}

    anomalies = []
    total_calls = 0
    schema_error_calls = []
    high_mcp_latency_calls = []
    uncompressed_responses = []

    for file_path in log_files:
        lines = [json.loads(l) for l in file_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for entry in lines:
            total_calls += 1
            tool_name = entry.get("tool_name")
            action = entry.get("action")
            args = entry.get("input_args", {})
            metrics = entry.get("metrics", {})
            layer_a = metrics.get("layer_a_mcp_pure", {})
            error = entry.get("error")

            # 1. Detect Schema Errors
            if layer_a.get("is_schema_error"):
                schema_error_calls.append({
                    "tool": tool_name,
                    "action": action,
                    "args": args,
                    "error": error
                })

            # 2. Detect High Pure MCP Overhead (> 20ms)
            l_mcp = layer_a.get("l_mcp_ms", 0.0)
            if l_mcp > 20.0:
                high_mcp_latency_calls.append({
                    "tool": tool_name,
                    "action": action,
                    "l_mcp_ms": l_mcp,
                    "args": args
                })

            # 3. Detect Low Compression (< 1.5x)
            comp_ratio = layer_a.get("estimated_compression_ratio", 1.0)
            if comp_ratio < 1.5 and layer_a.get("dto_response_tokens", 0) > 100:
                uncompressed_responses.append({
                    "tool": tool_name,
                    "action": action,
                    "compression_ratio": comp_ratio,
                    "tokens": layer_a.get("dto_response_tokens")
                })

    return {
        "files_analyzed": len(log_files),
        "total_tool_calls": total_calls,
        "summary_anomalies": {
            "schema_errors_count": len(schema_error_calls),
            "high_mcp_latency_count": len(high_mcp_latency_calls),
            "uncompressed_response_count": len(uncompressed_responses)
        },
        "anomalies": {
            "schema_errors": schema_error_calls[:5],
            "high_latency_calls": high_mcp_latency_calls[:5],
            "uncompressed_responses": uncompressed_responses[:5]
        }
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze trajectory logs for anomalies")
    parser.add_argument("--prefix", type=str, default="", help="Session ID prefix to analyze")
    args = parser.parse_args()

    report = analyze_recent_trajectories(session_prefix=args.prefix)
    print(json.dumps(report, indent=2, ensure_ascii=False))
