"""Claude Code subagent definition discovery: parsing `.md` frontmatter
(`agents.frontmatter`), the normalized `AgentDefinition` model
(`agents.model`), one file-tree source (`agents.sources`), and the
project/user/plugin walk (`agents.discovery.discover`).

Nothing here is re-exported from this `__init__.py` on purpose — the public
surface is `lib_python_harness`'s own top-level `__init__.py`; importing a
name from `lib_python_harness.agents.<submodule>` directly (as this
package's own tests do) is the documented, supported route for the pieces
that are not part of the top-level `__all__`.
"""
from __future__ import annotations
