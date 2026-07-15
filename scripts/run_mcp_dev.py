#!/usr/bin/env python3
"""
Fast-Feedback Development Runner for DokuWiki MCP Server.

Provides sub-second hot-reloading when server.py or schema files are edited,
avoiding full container rebuilds (`docker compose up --build`).
"""

import os
import sys
import uvicorn

# Ensure src/ is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

if __name__ == "__main__":
    # Enable telemetry by default in dev runner mode
    os.environ["MCP_ENABLE_TELEMETRY"] = os.environ.get("MCP_ENABLE_TELEMETRY", "true")
    
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    
    print(f"🚀 Starting DokuWiki MCP Server in DEV HOT-RELOAD mode on http://{host}:{port} ...")
    print(f"📊 Telemetry Enabled: {os.environ.get('MCP_ENABLE_TELEMETRY')}")
    
    # Run Uvicorn with hot reloading watching src/dokuwiki_mcp
    uvicorn.run(
        "dokuwiki_mcp.server:mcp._sse_app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=[os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))],
        factory=False
    )
