"""
Zero-Overhead Telemetry & Layered Trajectory Tracing Module for DokuWiki MCP Server.

Provides conditional execution tracing with zero performance impact when disabled (MCP_ENABLE_TELEMETRY=false).
Traces Layer A (Pure MCP Latency, Token Compression, Schema Errors), Layer B (Trajectory/Turns),
and Layer C (Subsystem/DokuWiki Backend Latency) into structured JSON-Lines log files.
"""

import os
import time
import json
import logging
from typing import Callable, Any, Dict, Optional, Tuple
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger("DokuWikiMCP.Telemetry")

LOG_DIR = Path("logs/trajectories")

# ContextVar to accumulate backend DokuWiki HTTP call durations (L_wiki) within a single tool call
_backend_time_var: ContextVar[float] = ContextVar("backend_time_var", default=0.0)
_raw_backend_bytes_var: ContextVar[int] = ContextVar("raw_backend_bytes_var", default=0)

def is_telemetry_enabled() -> bool:
    val = os.environ.get("MCP_ENABLE_TELEMETRY", "false")
    res = val.lower() in ("true", "1", "yes")
    return res

def reset_call_telemetry():
    """Reset per-call backend accumulator context variables."""
    if is_telemetry_enabled():
        _backend_time_var.set(0.0)
        _raw_backend_bytes_var.set(0)

def record_backend_call(duration_seconds: float, raw_bytes_count: int = 0):
    """Record a DokuWiki HTTP backend call duration and payload size (Layer C)."""
    if is_telemetry_enabled():
        current_time = _backend_time_var.get(0.0)
        _backend_time_var.set(current_time + duration_seconds)
        if raw_bytes_count > 0:
            current_bytes = _raw_backend_bytes_var.get(0)
            _raw_backend_bytes_var.set(current_bytes + raw_bytes_count)

def _estimate_token_count(text_or_obj: Any) -> int:
    """Rough estimation of token count based on string length (1 token ≈ 4 chars)."""
    if isinstance(text_or_obj, str):
        return max(1, len(text_or_obj) // 4)
    try:
        s = json.dumps(text_or_obj, default=str)
        return max(1, len(s) // 4)
    except Exception:
        return 1

def log_trajectory_step(
    session_id: str,
    tool_name: str,
    action: str,
    input_args: Dict[str, Any],
    result_obj: Any,
    error: Optional[Exception],
    total_duration_sec: float
):
    """Writes a structured trajectory event to logs/trajectories/{session_id}.jsonl."""
    if not is_telemetry_enabled():
        return

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = (LOG_DIR / f"{session_id or 'default_session'}.jsonl").resolve()
        # Print confirmation for telemetry writer
        print(f"📝 Telemetry log written to: {log_file}")

        l_wiki_ms = round(_backend_time_var.get(0.0) * 1000, 2)
        total_ms = round(total_duration_sec * 1000, 2)
        l_mcp_ms = round(max(0.0, total_ms - l_wiki_ms), 2)

        dto_tokens = _estimate_token_count(result_obj) if result_obj is not None else 0
        raw_backend_bytes = _raw_backend_bytes_var.get(0)
        raw_tokens = max(dto_tokens, raw_backend_bytes // 4) if raw_backend_bytes > 0 else dto_tokens
        compression_ratio = round(raw_tokens / dto_tokens, 2) if dto_tokens > 0 else 1.0

        is_schema_error = False
        is_rpc_error = False
        error_type = None
        error_msg = None

        if error:
            error_type = type(error).__name__
            error_msg = str(error)
            if "ValidationError" in error_type or "TypeError" in error_type or "ValueError" in error_type:
                is_schema_error = True
            else:
                is_rpc_error = True

        def make_serializable(obj):
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            if hasattr(obj, "dict"):
                return obj.dict()
            if hasattr(obj, "value"):
                return obj.value
            if isinstance(obj, list):
                return [make_serializable(x) for x in obj]
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            return obj

        serializable_args = make_serializable(input_args)

        action_str = action.value if hasattr(action, "value") else str(action)

        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id or "default_session",
            "tool_name": tool_name,
            "action": action_str,
            "input_args": serializable_args,
            "metrics": {
                "layer_a_mcp_pure": {
                    "l_mcp_ms": l_mcp_ms,
                    "dto_response_tokens": dto_tokens,
                    "estimated_compression_ratio": compression_ratio,
                    "is_schema_error": is_schema_error
                },
                "layer_b_trajectory": {
                    "has_error": error is not None
                },
                "layer_c_subsystem": {
                    "l_wiki_backend_ms": l_wiki_ms,
                    "raw_backend_bytes": raw_backend_bytes,
                    "is_rpc_error": is_rpc_error
                },
                "total_duration_ms": total_ms
            },
            "error": {
                "type": error_type,
                "message": error_msg
            } if error else None
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as ex:
        print(f"⚠️ Telemetry log failed: {ex}")
        logger.warning(f"Failed to write trajectory event: {ex}")


from functools import wraps

def trace_mcp_tool_execution(tool_name: str, action: str):
    """
    Decorator for tool functions.
    If MCP_ENABLE_TELEMETRY=false, returns a pure zero-overhead pass-through.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, ctx: Any = None, **kwargs):
            if ctx is not None:
                kwargs["ctx"] = ctx

            if not is_telemetry_enabled():
                return await func(*args, **kwargs)

            reset_call_telemetry()
            t0 = time.perf_counter()
            error = None
            result = None

            # Extract session_id directly from ctx
            session_id = getattr(ctx, "session_id", None) if ctx else None
            if not session_id and ctx:
                try:
                    session_id = getattr(ctx.request_context.request.headers, "get", lambda k: None)("mcp-session-id")
                except Exception:
                    pass

            logged_args = {k: v for k, v in kwargs.items() if k != "ctx"}

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as ex:
                error = ex
                raise
            finally:
                t1 = time.perf_counter()
                log_trajectory_step(
                    session_id=session_id or "default_session",
                    tool_name=tool_name,
                    action=action or logged_args.get("action", ""),
                    input_args=logged_args,
                    result_obj=result,
                    error=error,
                    total_duration_sec=t1 - t0
                )

        return async_wrapper

    return decorator
