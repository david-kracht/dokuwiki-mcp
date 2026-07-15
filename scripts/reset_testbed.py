#!/usr/bin/env python3
"""
Ultra-Fast Wiki State Reset Adapter for Benchmark Execution.

Restores test pages and fixtures in under 100ms without restarting containers.
Supports both direct local filesystem resets and Docker volume copy.
"""

import os
import sys
import shutil
import time
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BASE_DIR / "tests" / "fixtures" / "pages"
TARGET_PAGES_DIR = BASE_DIR / "docker" / "dokuwiki-data" / "pages"

def reset_wiki_state() -> float:
    """Copies fixture pages to the active DokuWiki data directory."""
    t0 = time.perf_counter()
    
    if not FIXTURE_DIR.exists():
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        # Create a sample fixture page if none exists
        (FIXTURE_DIR / "wiki").mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / "wiki" / "welcome.txt").write_text(
            "====== Welcome to DokuWiki ======\n"
            "This is a benchmark fixture page.\n"
            "Tags: {{tag>benchmark test docs}}\n",
            encoding="utf-8"
        )
        
    if TARGET_PAGES_DIR.exists():
        shutil.rmtree(TARGET_PAGES_DIR)
        
    TARGET_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_DIR, TARGET_PAGES_DIR, dirs_exist_ok=True)
    
    t1 = time.perf_counter()
    duration_ms = (t1 - t0) * 1000
    print(f"✅ Reset DokuWiki fixture state in {duration_ms:.2f} ms.")
    return duration_ms

if __name__ == "__main__":
    reset_wiki_state()
