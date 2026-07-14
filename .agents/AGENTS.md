# MCP Tooling Gold Standards & Development Guidelines

This document outlines mandatory coding and architectural gold-standards for developing and extending the DokuWiki MCP server. All AI coding assistants and developers **SHALL** adhere to these rules when modifying or adding MCP tools.

---

## 1. Parameter & Tool Annotation Standards

- **Parameter Description (`Annotated` & `Field`)**:
  - Every parameter in every MCP tool function **SHALL** be annotated using `typing.Annotated[<Type>, Field(description="...")]`.
  - All parameter descriptions **SHALL** be written in concise, clear English.
  - For parameters taking an `Enum` type (e.g., dispatcher `action` parameters), the `Field(description=...)` **SHALL** explicitly list all enum options and summarize their specific functionality and parameter dependencies.

- **Tool Decorator Metadata (`@mcp.tool`)**:
  - Every MCP tool function **SHALL** specify an `annotations` dictionary inside the `@mcp.tool(...)` decorator.
  - The `annotations` dict **SHALL** explicitly include the following hints:
    - `title`: Short, descriptive English name for the tool.
    - `description`: High-level summary of the tool capability and prerequisites.
    - `readOnlyHint` (bool): `True` if the tool strictly reads data without side effects.
    - `idempotentHint` (bool): `True` if repeating the exact tool call yields identical results.
    - `destructiveHint` (bool): `True` if the tool deletes or irreversibly modifies content.
    - `openWorldHint` (bool): `True` if the tool queries an external/unbounded environment.

- **Function Docstrings**:
  - Tool functions **SHALL** include a clean docstring detailing `PURPOSE`, `PREREQUISITES`, and expected outputs.

---

## 2. Dispatcher Tools & Enum Design

- **String Enums**:
  - All multi-action tools **SHALL** use string-backed enums (`class ActionName(str, enum.Enum)`).
  - Enum member values **SHALL** strictly follow `snake_case` naming conventions.

- **Structured Invocation Logging**:
  - Tools **SHALL** be decorated with `@common_context` and accept `ctx: Context = None` for invocation tracing.

- **Predictable Output Formatting**:
  - Tool responses **SHALL** return structured, token-efficient Markdown or text outputs optimized for LLM parsing.
