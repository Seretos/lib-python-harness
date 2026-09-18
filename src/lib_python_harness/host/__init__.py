"""What a running Claude Code session knows about itself:
`host.plugins.config_dir`/`enabled_plugins` (the settings merge) and
`host.context.HostContext` (the per-run snapshot `resolve.resolve` reads).
"""
from __future__ import annotations
