"""Provider seam: the CLI-agnostic types (`providers.base`) plus the one
implementation this ticket ships (`providers.claude_cli.ClaudeCliProvider`).

Nothing here is re-exported at the top level; import from the submodules
directly (`lib_python_harness.providers.base`, `.claude_cli`).
"""
from __future__ import annotations
