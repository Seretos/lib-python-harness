"""A hand-rolled YAML-subset parser/emitter for Claude Code agent-definition
`.md` frontmatter, plus `load_agent_definition` — the loader that composes
the parser with the filename-stem / `FALLBACK_DESCRIPTION` degradation rule.

No YAML dependency: `ruamel.yaml` is not available to this leaf library at
this ticket (`pyproject.toml`'s `dependencies = []`; `lib-python-config`
arrives in #3), and `json`/`configparser` cannot read `---`-fenced
frontmatter. The subset handled: `---` fences, `key: value` scalars, `key:
|`/`>` block scalars, indented `- item` sequences, inline `[a, b]` lists,
single/double-quoted scalars, `true`/`false`/int coercion, and nested block
mappings by indent (recursive) — so `hooks:`/`mcpServers:` parse to real
dicts instead of collapsing the file to the fallback. `dump_frontmatter` is
the same grammar inverted, which is what makes the materialized dispatch
path (`providers.claude_cli.materialize_agent_dir`) round-trippable.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import FrontmatterError
from .model import FALLBACK_DESCRIPTION, AgentDefinition

__all__ = [
    "FrontmatterError",
    "dump_frontmatter",
    "load_agent_definition",
    "parse_frontmatter",
]

_INT_RE = re.compile(r"-?\d+")

# camelCase frontmatter key -> AgentDefinition snake_case attribute.
_FIELD_MAP: dict[str, str] = {
    "model": "model",
    "permissionMode": "permission_mode",
    "effort": "effort",
    "tools": "tools",
    "disallowedTools": "disallowed_tools",
    "skills": "skills",
    "maxTurns": "max_turns",
    "hooks": "hooks",
    "mcpServers": "mcp_servers",
    "omitClaudeMd": "omit_claude_md",
}


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split `text` into (frontmatter fields, body).

    No opening `---` fence at all -> `({}, text)`, the whole file is body.
    An opening fence with no matching closing fence is genuinely malformed
    -> raises `FrontmatterError`. A closing fence is found -> the header
    lines between the fences are parsed as a mapping (see module docstring
    for the supported grammar) and the body is everything after the closing
    fence, verbatim (including any `---`-looking lines of its own — the
    closing fence is only ever searched for once, from the header side).
    """
    if not text.startswith("---\n") and text.strip() != "---":
        return {}, text

    lines = text.split("\n")
    closing_idx = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            closing_idx = i
            break
    if closing_idx is None:
        raise FrontmatterError(
            "frontmatter opening fence ('---') has no matching closing fence"
        )

    fields, consumed = _parse_mapping(lines, 1, 0, closing_idx)
    if consumed != closing_idx:
        raise FrontmatterError(
            f"unexpected content at line {consumed} of the frontmatter header"
        )
    body = "\n".join(lines[closing_idx + 1 :])
    return fields, body


def dump_frontmatter(fields: dict[str, Any], body: str) -> str:
    """The inverse of `parse_frontmatter`: `fields` (in insertion order)
    become a `---`-fenced header, followed by `body` verbatim."""
    header_lines = ["---"]
    for key, value in fields.items():
        header_lines.extend(_dump_value(key, value, indent=0))
    header_lines.append("---")
    return "\n".join(header_lines) + "\n" + body


def load_agent_definition(
    path: Path | str, source_scope: str, plugin_name: str | None = None
) -> AgentDefinition:
    """Load `path` (a Claude Code agent `.md` file) into an `AgentDefinition`.

    Malformed frontmatter degrades rather than propagating: `name` falls
    back to the filename stem, `description` becomes `FALLBACK_DESCRIPTION`,
    and every other field stays unset (`None`) — the file is still usable,
    just anonymous. A file that parses cleanly but omits `name:`/
    `description:` only degrades the one missing field (stem / empty
    string), never both.

    `qualified_name` (one chain, no short-circuit): `base = name or
    filename stem`; `f"{plugin_name}:{base}"` at `source_scope == "plugin"`
    with a `plugin_name`, else `base` — so a plugin agent with no `name:`
    is discovered as `<plugin_name>:<stem>`.
    """
    path = Path(path)
    stem = path.stem
    text = path.read_text()

    try:
        fields, body = parse_frontmatter(text)
    except FrontmatterError:
        base = stem
        qualified_name = _qualified_name(base, source_scope, plugin_name)
        return AgentDefinition(
            name=base,
            description=FALLBACK_DESCRIPTION,
            body=text,
            source_scope=source_scope,
            path=path,
            qualified_name=qualified_name,
        )

    name = fields.get("name") or stem
    description = fields.get("description")
    if description is None:
        description = ""
    qualified_name = _qualified_name(name, source_scope, plugin_name)

    kwargs: dict[str, Any] = {}
    for frontmatter_key, attr in _FIELD_MAP.items():
        if frontmatter_key in fields:
            kwargs[attr] = fields[frontmatter_key]

    return AgentDefinition(
        name=name,
        description=description,
        body=body,
        source_scope=source_scope,
        path=path,
        qualified_name=qualified_name,
        **kwargs,
    )


def _qualified_name(base: str, source_scope: str, plugin_name: str | None) -> str:
    if source_scope == "plugin" and plugin_name:
        return f"{plugin_name}:{base}"
    return base


# -- the hand-rolled grammar --------------------------------------------


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_mapping(
    lines: list[str], start: int, indent: int, limit: int
) -> tuple[dict[str, Any], int]:
    """Parse `lines[start:limit]` as a mapping whose keys sit at exactly
    `indent` spaces. Returns `(mapping, next_index)`, where `next_index` is
    the first line not consumed (either past `limit`, blank-exhausted, or a
    line at a shallower indent than `indent`)."""
    result: dict[str, Any] = {}
    i = start
    while i < limit:
        raw = lines[i]
        if raw.strip() == "":
            i += 1
            continue
        cur_indent = _indent_of(raw)
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise FrontmatterError(f"unexpected indent at line {i}: {raw!r}")

        line = raw.strip()
        if ":" not in line:
            raise FrontmatterError(f"expected 'key: value' at line {i}: {raw!r}")
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()

        if rest == "":
            j = i + 1
            while j < limit and lines[j].strip() == "":
                j += 1
            if j >= limit or _indent_of(lines[j]) <= indent:
                result[key] = None
                i = j
                continue
            next_indent = _indent_of(lines[j])
            if lines[j].strip().startswith("- "):
                seq, i = _parse_sequence(lines, j, next_indent, limit)
            else:
                mapping, i = _parse_mapping(lines, j, next_indent, limit)
                seq = mapping
            result[key] = seq
            continue

        if rest in ("|", ">"):
            value, i = _parse_block_scalar(lines, i + 1, indent, limit)
            result[key] = value
            continue

        result[key] = _parse_scalar(rest)
        i += 1

    return result, i


def _parse_sequence(
    lines: list[str], start: int, indent: int, limit: int
) -> tuple[list[Any], int]:
    result: list[Any] = []
    i = start
    while i < limit:
        raw = lines[i]
        if raw.strip() == "":
            i += 1
            continue
        cur_indent = _indent_of(raw)
        if cur_indent < indent:
            break
        if cur_indent != indent or not raw.strip().startswith("- "):
            break
        item_text = raw.strip()[2:].strip()
        result.append(_parse_scalar(item_text))
        i += 1
    return result, i


def _parse_block_scalar(
    lines: list[str], start: int, parent_indent: int, limit: int
) -> tuple[str, int]:
    i = start
    block_lines: list[str] = []
    base_indent: int | None = None
    while i < limit:
        raw = lines[i]
        if raw.strip() == "":
            block_lines.append("")
            i += 1
            continue
        li = _indent_of(raw)
        if li <= parent_indent:
            break
        if base_indent is None:
            base_indent = li
        block_lines.append(raw[base_indent:])
        i += 1
    value = "\n".join(block_lines)
    if not value.endswith("\n"):
        value += "\n"
    return value, i


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in inner.split(",")]
    if text == "true":
        return True
    if text == "false":
        return False
    if _INT_RE.fullmatch(text):
        return int(text)
    return text


def _needs_quoting(text: str) -> bool:
    if text == "":
        return False
    if text != text.strip():
        return True
    if text in ("true", "false"):
        return True
    if _INT_RE.fullmatch(text):
        return True
    if ":" in text:
        return True
    if text[0] in ("'", '"', "[", "-") :
        return True
    return False


def _dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return '""'
    text = str(value)
    if _needs_quoting(text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _dump_value(key: str, value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for sub_key, sub_value in value.items():
            lines.extend(_dump_value(sub_key, sub_value, indent + 2))
        return lines
    if isinstance(value, list):
        lines = [f"{prefix}{key}:"]
        for item in value:
            lines.append(f"{prefix}  - {_dump_scalar(item)}")
        return lines
    if isinstance(value, str) and "\n" in value:
        lines = [f"{prefix}{key}: |"]
        body_lines = value.split("\n")
        if body_lines and body_lines[-1] == "":
            body_lines = body_lines[:-1]
        for block_line in body_lines:
            lines.append(f"{prefix}  {block_line}")
        return lines
    return [f"{prefix}{key}: {_dump_scalar(value)}"]
