"""
Deterministic Assertion & Verification Engine for DokuWiki MCP Benchmarks.

Validates task completion (Pass@1) by directly inspecting DokuWiki page files (data/pages/)
and trajectory telemetry logs without relying on LLM-as-a-judge for deterministic assertions.
"""

import re
import json
from pathlib import Path
from typing import Dict, Any, Tuple, List

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TARGET_PAGES_DIR = BASE_DIR / "docker" / "dokuwiki-data" / "pages"

def verify_task_state(task_def: Dict[str, Any], session_id: str) -> Tuple[bool, List[str]]:
    """
    Evaluates expected_state_checks for a given task.
    Returns (is_passed: bool, failure_reasons: List[str]).
    """
    checks = task_def.get("expected_state_checks", {})
    check_type = checks.get("type")
    failure_reasons = []

    if not check_type:
        return True, []

    # 1. File existence / Page creation check
    if check_type == "file_exists":
        rel_path = checks.get("rel_path")
        must_contain = checks.get("must_contain", [])
        
        # Check trajectory logs for successful save/patch calls
        log_file = BASE_DIR / "logs" / "trajectories" / f"{session_id}.jsonl"
        found_in_log = False
        if log_file.exists():
            lines = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            for entry in lines:
                if entry.get("tool_name") == "wiki_write_and_modify" and not entry.get("metrics", {}).get("layer_b_trajectory", {}).get("has_error"):
                    args = entry.get("input_args", {})
                    act = args.get("action")
                    if act in ("save_page", "patch_page", "commit", "modify_section"):
                        content_str = str(args.get("content", "")) + str(args.get("patch_diff", ""))
                        if not must_contain or all(exp in content_str for exp in must_contain):
                            found_in_log = True
                            break

        target_file = TARGET_PAGES_DIR / rel_path if rel_path else None
        found_on_disk = False
        if target_file and target_file.exists():
            disk_content = target_file.read_text(encoding="utf-8")
            if not must_contain or all(exp in disk_content for exp in must_contain):
                found_on_disk = True

        if not found_in_log and not found_on_disk:
            return False, [f"Page creation or content update not confirmed for '{rel_path or 'target'}' (expected strings: {must_contain})."]

    # 2. File deletion / empty check
    elif check_type == "file_deleted_or_empty":
        log_file = BASE_DIR / "logs" / "trajectories" / f"{session_id}.jsonl"
        found_delete_in_log = False
        if log_file.exists():
            lines = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            for entry in lines:
                if entry.get("tool_name") == "wiki_write_and_modify" and not entry.get("metrics", {}).get("layer_b_trajectory", {}).get("has_error"):
                    args = entry.get("input_args", {})
                    act = args.get("action")
                    if act in ("delete_page", "save_page") and args.get("content", "X") == "":
                        found_delete_in_log = True
                        break

        if not found_delete_in_log:
            return False, ["No successful page deletion or empty save_page recorded in trajectory."]

    # 3. Trajectory / Read log assertions
    elif check_type in ("read_assertion", "search_assertion", "batch_assertion", "trajectory_assertion"):
        log_file = BASE_DIR / "logs" / "trajectories" / f"{session_id}.jsonl"
        if not log_file.exists():
            return False, [f"Trajectory log file {log_file} does not exist for session {session_id}."]

        lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]

        must_contain_actions = checks.get("must_contain_actions", [])
        if must_contain_actions:
            recorded_actions = [e.get("action", "") for e in lines if not e.get("metrics", {}).get("layer_b_trajectory", {}).get("has_error")]
            for act in must_contain_actions:
                if act not in recorded_actions:
                    failure_reasons.append(f"Required action '{act}' not recorded in trajectory log.")
        
        # Check exclusion namespaces in parameters
        excluded_ns = checks.get("excluded_namespaces", [])
        if excluded_ns:
            found_exclusion = False
            for entry in lines:
                args = entry.get("input_args", {})
                exclusions = args.get("exclusions", [])
                if any(ns in exclusions for ns in excluded_ns):
                    found_exclusion = True
                    break
            if not found_exclusion:
                failure_reasons.append(f"No tool invocation contained exclusions matching {excluded_ns}.")

        # Check required action calls
        must_call = checks.get("must_call_action")
        if must_call:
            found_action = any(entry.get("input_args", {}).get("action") == must_call for entry in lines)
            if not found_action:
                failure_reasons.append(f"No tool invocation called action '{must_call}'.")

        # Check regex pattern in parameters
        regex_pattern = checks.get("regex_pattern")
        if regex_pattern:
            found_regex = False
            for entry in lines:
                args = entry.get("input_args", {})
                pattern = args.get("regex_filter") or args.get("pattern")
                if pattern and re.search(regex_pattern, pattern):
                    found_regex = True
                    break
            if not found_regex:
                failure_reasons.append(f"No tool invocation passed regex pattern matching '{regex_pattern}'.")

    is_passed = len(failure_reasons) == 0
    return is_passed, failure_reasons
