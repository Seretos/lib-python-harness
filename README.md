# lib-python-harness

Provider-independent subagent engine: lifecycle, dispatch and transport abstraction.

A pure Python library — no binary, no MCP, no marketplace. Consumed as
source by downstream projects via a git pin.

## Install lib-python-harness

Pin an exact tag (recommended) or the floating major-release branch:

```bash
# exact tag
pip install "git+https://github.com/Seretos/lib-python-harness@v0.1.0"

# floating: latest 0.x.y release
pip install "git+https://github.com/Seretos/lib-python-harness@release/0.x"
```

Or in a consumer's `pyproject.toml`:

```toml
dependencies = [
  "lib-python-harness @ git+https://github.com/Seretos/lib-python-harness@v0.1.0",
]
```

## Run API

`lib_python_harness` gives you one call that spawns a fresh, fully isolated
`claude` CLI process (no user/project settings, no plugins, no skills, no
MCP servers, no hooks, no CLAUDE.md, no auto-memory), sends it one prompt on
stdin, and returns a verified result — with an owned lifecycle
(start/poll/stop/cleanup), a per-run resumable session id, and a provenance
record plus an events log written to disk.

```python
from lib_python_harness import run, RunSpec, Isolation

result = run(RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku"))
print(result.text)
```

Every identifier below has its own section with a real, working example.

### run

The module-level convenience — a plain function, `Harness().run(spec)` with
nothing else in between. This is the surface form the ticket's own
acceptance criterion is written as: a bare `run(RunSpec(...))` call.

```python
from lib_python_harness import run, RunSpec, Isolation

result = run(RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku"))
print(result.text)
```

### Harness

The façade. `run(spec)` is `start(spec)` followed by `wait()` — one code
path, not two independent implementations of "run a prompt". `start`/`poll`
let a caller drive a long-running prompt without blocking; `stop` cancels a
run in flight; `cleanup` drops a finished run's bookkeeping record (never
the CLI transcript, never — by default — the run's cwd).

```python
from lib_python_harness import Harness, RunSpec, Isolation

harness = Harness()

result = harness.run(
    RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku")
)

record = harness.start(
    RunSpec(prompt="Count to one million, one number per line.",
            isolation=Isolation.CLEAN, model="haiku")
)
harness.poll(record.run_id)
harness.stop(record.run_id, timeout=10.0)
harness.cleanup(record.run_id, remove_cwd=False)
```

### RunSpec

What to run, and under what isolation. `cwd=None` (the default) means "spawn
in a fresh, empty temp directory the harness creates" — this is what
actually makes the `Isolation.CLEAN` no-auto-memory guarantee hold, since
auto-memory is keyed by cwd and a directory the harness just created has
never had `claude` run in it. A caller-supplied `cwd` must exist, must not
sit inside (or under) a git repository, and must be empty unless
`allow_nonempty_cwd=True` is set — the one recorded opt-out, meant for
diagnostics that need to plant files into the child's cwd, not for everyday
use (an *emptied* directory can still map onto a project whose auto-memory
is populated, since memory lives outside the cwd itself).

```python
from lib_python_harness import RunSpec, Isolation

spec = RunSpec(
    prompt="Reply with exactly OK",
    isolation=Isolation.CLEAN,
    model="haiku",
    effort="high",
    system_prompt="You are a terse assistant.",
)
```

### RunResult

The result envelope `Harness.run`/`start`/`poll`/`stop`/`wait` all return.
Content fields (`text`, `is_error`, `subtype`, `structured_output`, `usage`,
`cost`) come from the CLI's own terminal `result` event; `session_id`,
`transcript_path`, `state` and `duration_s` are the harness's own
run-identity/lifecycle bookkeeping, which no single stream event carries.

```python
from lib_python_harness import Harness, RunSpec, Isolation, RunResult


def describe(result: RunResult) -> str:
    return (
        f"session={result.session_id} "
        f"transcript={result.transcript_path} "
        f"state={result.state} "
        f"duration_s={result.duration_s}"
    )


harness = Harness()
result = harness.run(
    RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku")
)
print(describe(result))
```

### Isolation

The isolation profile a run is spawned under. Only `CLEAN` exists in this
ticket: no user/project settings, no plugins, no skills, no MCP servers, no
hooks, no CLAUDE.md, no auto-memory. A later ticket that wants a different
profile (e.g. one that keeps project settings) adds a new `Isolation`
member — it does not repurpose `CLEAN`.

```python
from lib_python_harness import RunSpec, Isolation

spec = RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku")
assert spec.isolation is Isolation.CLEAN
```

### RunState

The run lifecycle enum — not a free string. `CREATED`, `RUNNING`,
`COMPLETED`, `FAILED`, `CANCELLED`; an illegal transition (e.g. `stop()` on
an already-`COMPLETED` run) raises `IllegalTransitionError` rather than
silently no-op'ing. See `docs/run-lifecycle.md` for the full transition
table.

```python
from lib_python_harness import RunState


def is_finished(state: RunState) -> bool:
    return state in (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED)


assert not is_finished(RunState.CREATED)
assert not is_finished(RunState.RUNNING)
assert is_finished(RunState.COMPLETED)
```

### HarnessError

The base class every error this library raises on purpose inherits from.
Catch this to handle any harness-originated failure without enumerating the
concrete subclasses (`IllegalTransitionError`, `RunIdentityUnverifiedError`,
`UnsafeCwdError`).

```python
from lib_python_harness import HarnessError

try:
    raise HarnessError("something the harness itself raised on purpose")
except HarnessError as exc:
    print(f"harness error: {exc}")
```

### IllegalTransitionError

Raised when a `RunState` transition falls outside the documented table —
most visibly, `Harness.stop()` on a run whose record is already
`COMPLETED`/`FAILED`/`CANCELLED`. This is a typed error, not a silent no-op:
the check is the first thing `stop()` does, before any signal is ever sent.

```python
from lib_python_harness import Harness, IllegalTransitionError

harness = Harness()
try:
    harness.stop("a-run-id-that-is-already-completed")
except IllegalTransitionError:
    print("that run already finished; stop() is not a no-op here")
```

### RunIdentityUnverifiedError

Raised by `Harness.stop()` when the recorded pid's identity cannot be
verified (no `psutil`, `/proc` unreadable, ...) *and* this process no longer
holds the child's own `Popen` — signalling would risk killing an unrelated
process that happens to have reused the pid, so `stop()` refuses instead of
guessing.

```python
from lib_python_harness import Harness, RunIdentityUnverifiedError

harness = Harness()
try:
    harness.stop("a-run-whose-process-identity-cannot-be-verified")
except RunIdentityUnverifiedError:
    print("refusing to signal a possibly-recycled pid")
```

### UnsafeCwdError

Raised by the `claude` provider when a caller-supplied `RunSpec.cwd` fails
the `Isolation.CLEAN` recipe: it does not exist, it sits inside (or under) a
git repository, or it is non-empty without `allow_nonempty_cwd=True`.

```python
from lib_python_harness import run, RunSpec, Isolation, UnsafeCwdError

try:
    run(RunSpec(prompt="hi", isolation=Isolation.CLEAN, model="haiku", cwd="/some/git/repo"))
except UnsafeCwdError:
    print("cwd is inside a git repo, or not empty, or does not exist")
```

### __version__

The installed package version.

```python
import lib_python_harness

print(lib_python_harness.__version__)
```

### Provider

The seam a CLI adapter implements: `build_launch_plan(spec, *, session_id,
run_dir)` turns a `RunSpec` into a `LaunchPlan`, and `parse_events(lines)`
turns the adapter's own event stream into a `RunResult`. `ClaudeCliProvider`
is the only implementation this release ships; `Harness(provider=...)` is
the documented swap seam for a future adapter.

```python
from pathlib import Path

from lib_python_harness import LaunchPlan, Provider, RunResult, RunSpec


def describe(provider: Provider, spec: RunSpec) -> LaunchPlan:
    return provider.build_launch_plan(spec, session_id="example-session", run_dir=Path("/tmp"))
```

### LaunchPlan

The fully-built command line a `Provider` wants spawned: `argv` (never
including the binary itself — `Harness.claude_argv` is prepended at spawn
time), `cwd`, `env`, and `stdin` (the prompt travels on stdin, never argv).

```python
from lib_python_harness import LaunchPlan

plan = LaunchPlan(argv=["-p", "--model", "haiku"], cwd="/tmp/example", env={}, stdin="hi")
print(plan.argv, plan.cwd)
```

### ClaudeCliProvider

The `Provider` implementation that drives the real `claude` CLI, enforcing
the `Isolation.CLEAN` recipe (scrubbed env, `--setting-sources ""`,
`--strict-mcp-config`, no tools, no slash commands) when it builds a
`LaunchPlan`.

```python
from pathlib import Path
import uuid

from lib_python_harness import ClaudeCliProvider, Isolation, RunSpec

provider = ClaudeCliProvider()
plan = provider.build_launch_plan(
    RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku"),
    session_id=str(uuid.uuid4()),
    run_dir=Path("/tmp/example-run"),
)
print(plan.argv)
```

### RunStore

The protocol `Harness` uses to persist a run's *record* (metadata — state,
pid, paths — not its artifacts, which always land on real disk regardless of
store choice). `Harness(store=...)` takes any `RunStore`; `InMemoryRunStore`
(the default) and `FileRunStore` are the two implementations this release
ships.

```python
from lib_python_harness import InMemoryRunStore, RunStore


def run_count(store: RunStore) -> int:
    return len(store.list())


print(run_count(InMemoryRunStore()))
```

### InMemoryRunStore

The default `RunStore`: no disk I/O, records live only as long as the
process does. What a plain `Harness()` call uses so it never leaves a stray
`record.json` around, while still writing a real `provenance.json` file.

```python
from lib_python_harness import InMemoryRunStore

store = InMemoryRunStore()
store.put("run-1", {"state": "RUNNING"})
print(store.get("run-1"))
```

### FileRunStore

A `RunStore` that persists each run's record to
`<artifacts_dir>/<run_id>/record.json`, needed when a record living only in
one process's memory cannot satisfy "the run is inspectable across process
boundaries".

```python
import tempfile

from lib_python_harness import FileRunStore

store = FileRunStore(tempfile.mkdtemp())
store.put("run-1", {"state": "RUNNING"})
print(store.list())
```

## Agent dispatch (Isolation.INHERIT)

Ticket #2's surface: discover every Claude Code subagent definition
available in this session (project `.claude/agents/*.md`, user
`<config>/agents/*.md`, enabled-plugin `agents/*.md`), and dispatch one as a
child `claude` process under `Isolation.INHERIT` — the parent's own cwd,
CLAUDE.md discovery, settings, permission mode and MCP servers, plus the
definition's own fields.

```python
from lib_python_harness import HostContext, discover, resolve, run

context = HostContext(cwd="/path/to/project")
context.complete()

definitions = discover(context)
definition = definitions["reviewer"]

spec = resolve(definition, context)
result = run(spec)
print(result.text)
```

### AgentDefinition

One subagent, normalized from its `.md` frontmatter: the documented
camelCase fields as snake_case attributes, plus `body` (everything after
the frontmatter fence), `source_scope` (`"project"` | `"user"` |
`"plugin"`), `path`, and `qualified_name` (`name` at project/user scope,
`f"{plugin}:{name}"` at plugin scope — the key `discover()` returns).

```python
from pathlib import Path

from lib_python_harness import AgentDefinition

definition = AgentDefinition(
    name="reviewer",
    description="Reviews code",
    body="You are a careful code reviewer.",
    source_scope="project",
    path=Path("/repo/.claude/agents/reviewer.md"),
    qualified_name="reviewer",
)
print(definition.qualified_name)
```

### DefinitionSource

The protocol `discover()` walks: anything with an `iter_definitions()`
method yielding `AgentDefinition`s. `ClaudeMarkdownSource` is the only
implementation this release ships.

```python
from lib_python_harness import AgentDefinition, DefinitionSource


def count_definitions(source: DefinitionSource) -> int:
    return len(list(source.iter_definitions()))
```

### ClaudeMarkdownSource

Walks one directory (non-recursively, sorted) for `*.md` agent-definition
files. `discover()` builds one per scope (project/user/each enabled
plugin); a missing directory yields nothing, not an error.

```python
from lib_python_harness import ClaudeMarkdownSource

source = ClaudeMarkdownSource("/repo/.claude/agents", scope="project")
for definition in source.iter_definitions():
    print(definition.qualified_name)
```

### HostContext

A snapshot of the parent Claude Code session: `cwd`, `model`,
`permission_mode`, `effort`, `mcp_servers`, `enabled_plugins`.
`complete()` fills `model` (from the session transcript's last assistant
turn) and `enabled_plugins` (from the merged settings files) when unset —
fields already set are never overwritten. `mcp_servers` is caller-supplied
only; `complete()` never populates it (collecting the parent's actually
active MCP servers is a later ticket's job).

```python
from lib_python_harness import HostContext

context = HostContext(cwd="/repo", session_id="example-session-id")
context.complete()
print(context.model, context.enabled_plugins)
```

### discover

Every subagent Claude Code would offer in this session, keyed by
`qualified_name` — project, then user, then each enabled plugin, first
writer of a name wins (so a project agent shadows a same-named user or
plugin one).

```python
from lib_python_harness import HostContext, discover

context = HostContext(cwd="/repo")
for qualified_name, definition in discover(context).items():
    print(qualified_name, definition.description)
```

### resolve

Turns one `AgentDefinition` plus a `HostContext` into a `RunSpec` under
`Isolation.INHERIT`, once: `model`/`permission_mode`/`effort` are
definition-else-context; `tools`/`disallowed_tools`/`skills`/`max_turns`/
`description` always come from the definition; `omit_claude_md`/`hooks`/
`mcp_servers` come from the definition too, but are dropped at plugin scope
(a documented assumption about how the parent Claude Code loads plugin
agents, not independently verified). The returned `RunSpec` is ready for
`run()`.

```python
from lib_python_harness import HostContext, discover, resolve

context = HostContext(cwd="/repo")
context.complete()
definition = next(iter(discover(context).values()))
spec = resolve(definition, context)
print(spec.agent_name, spec.isolation)
```

#### Frontmatter field → dispatch carrier

`resolve()`'s `RunSpec` is emitted one of two ways
(`providers.claude_cli.dispatch_mode`, whole-definition, never per-field):
**payload** (`--agents '{"<name>": {...}}'` + `--agent <name>`) when every
field the definition sets fits the `--agents` JSON schema; **materialized**
(`--add-dir <dir>` + `--agent <stem>`, a real `.md` file with full
frontmatter under `<dir>/.claude/agents/<stem>.md`) the moment one field
does not (verified against the real CLI: `hooks`/`mcpServers` are always
rejected by the JSON schema, and `tools`/`disallowedTools` need a JSON
array rather than the scalar frontmatter carries — both cases still work,
just through the materialized path or a converted array).

| Frontmatter field | `payload` carrier            | `materialized` carrier | Notes                                   |
| ------------------ | ----------------------------- | ----------------------- | ---------------------------------------- |
| `description`       | `--agents` `description`      | `description:`           | never dropped/defaulted by `resolve()` — the real frontmatter value flows through unchanged; `payload` mode simply omits the JSON key when the definition has none, while `materialized` mode substitutes a synthesized filler in that case (its own loader silently drops a description-less file from discovery, live-verified) |
| `model`             | top-level `--model`           | `model:`                 | `model: inherit` passes through literally |
| `permissionMode`    | top-level `--permission-mode` | `permissionMode:`        | dropped at plugin scope                  |
| `effort`            | top-level `--effort`          | (not carried)            | definition-else-context                  |
| `tools`             | `--agents` `tools` (as array) | `tools:` (scalar)        | never a top-level `--allowedTools`       |
| `disallowedTools`   | `--agents` `disallowedTools`  | `disallowedTools:`       | never a top-level `--disallowedTools`    |
| `skills`            | `--agents` `skills`           | `skills:`                |                                           |
| `maxTurns`          | `--agents` `maxTurns`         | `maxTurns:`              | never a top-level `--max-turns` (no such flag) |
| `hooks`             | (forces `materialized`)       | `hooks:`                 | dropped at plugin scope                  |
| `mcpServers`        | (forces `materialized`)       | `mcpServers:`            | dropped at plugin scope; also drives top-level `--mcp-config` when non-empty |
| `omitClaudeMd`      | top-level `--setting-sources` | `omitClaudeMd:`          | drops `project` from `--setting-sources` (`user,local` instead of `user,project,local`); live-verified — no `--settings instructionFiles` key has any observable effect on CLAUDE.md loading against the real CLI; dropped at plugin scope. Known trade-off: also drops project-level `.claude/settings.json`, since "project" carries both |
| `memory`, `background`, `color`, `initialPrompt`, `isolation` | not carried | not carried | parsed by the frontmatter reader, silently dropped by `load_agent_definition` — no `RunSpec` field exists for them |

### FrontmatterError

Raised by the hand-rolled frontmatter parser when a `.md` file's `---`
header is genuinely malformed (e.g. an opening fence with no closing
fence) — never for a file that merely omits recognised fields, which loads
with a fallback description instead.

```python
from lib_python_harness import FrontmatterError

try:
    raise FrontmatterError("frontmatter fence not closed")
except FrontmatterError as exc:
    print(f"malformed agent definition: {exc}")
```

## Development

```bash
pip install -e ".[test]"
python -m pytest

# live tests: needs the installed `claude` CLI + subscription auth
python -m pytest -m requires_claude
```

## Version policy

Semantic versioning. The `version` in `pyproject.toml` is a placeholder
on `main` — the release workflow stamps it onto the `release/Nx` branch
and the `vX.Y.Z` tag. Don't hand-bump it.
