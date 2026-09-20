# Run lifecycle

Every run moves through `RunState` (`src/lib_python_harness/runtime/lifecycle.py`)
under one validated transition table. A transition outside this table raises
`IllegalTransitionError` — there is no silent no-op, not even for a
already-finished run (`Harness.stop()` on a `COMPLETED` run raises here,
before any signal is ever sent).

`RunState` has five members: `CREATED`, `RUNNING`, `COMPLETED`, `FAILED`,
`CANCELLED`. The illustrative "starting" state some designs use is
deliberately absent: `Harness.start()` spawns the child synchronously and
only returns once it is already running, so no caller could ever observe a
run in a "starting" state between `CREATED` and `RUNNING`.

## Transitions

- `CREATED` -> `RUNNING`
- `CREATED` -> `FAILED`
- `RUNNING` -> `COMPLETED`
- `RUNNING` -> `FAILED`
- `RUNNING` -> `CANCELLED`

`COMPLETED`, `FAILED` and `CANCELLED` are terminal: none of them has an
outgoing edge. `tests/test_lifecycle_doc.py` parses the list above and
diffs it structurally against `runtime.lifecycle._TRANSITIONS` — the two
are required to describe exactly the same edge set, nothing missing or
extra.

## Provider selection

`Harness.start()` resolves `RunSpec.provider` (`"claude"` by default,
`"codex"`, `"mistral"`) to a provider instance before anything else: an unknown name
raises `HarnessError`, and a provider that cannot honour a set field raises
`UnsupportedByProvider` from `build_launch_plan()` — in both cases before any
record is written, so no run ever reaches `CREATED`. One provider instance
serves one run (it may keep per-run state between `build_launch_plan` and
`parse_events`). On native Windows `stop()` has no graceful signal: it goes
straight to a whole-tree force kill (`taskkill /T /F`).

## What causes each edge

- `CREATED -> RUNNING`: `Harness.start()` successfully spawned the child
  process (`_spawn_detached` returned a live `Popen`).
- `CREATED -> FAILED`: `Harness.start()` raised while spawning (e.g. the
  `claude` binary is not on `PATH`) — the run never reached `RUNNING`.
- `RUNNING -> COMPLETED`: the child exited 0 and its stream-json output
  ended with a terminal `result` event that `ClaudeCliProvider.parse_events`
  could parse.
- `RUNNING -> FAILED`: the child exited non-zero, or its stream ended
  without a terminal `result` event (a truncated stream never counts as
  success).
- `RUNNING -> CANCELLED`: `Harness.stop()` was called on a still-`RUNNING`
  run: graceful signal (`SIGTERM`) -> bounded wait -> force kill (`SIGKILL`)
  -> reap, all identity-checked against the pid's captured start time so a
  recycled pid is never signalled.

## Resume after `cleanup()`

`cleanup(run_id, remove_cwd=False)` drops the run's record from the store
and stops tracking its process handle; it never touches the CLI transcript,
and by default (`remove_cwd=False`) never removes the run's cwd either,
because whether `claude --resume <session_id>` needs its original cwd is
unverified rather than known-safe to break. `tests/test_harness_end_to_end.py::test_resume_after_cleanup`
drives an actual `claude --resume <id> -p "..."` round trip after
`cleanup()` and prints (does not assert) whether resume also works from an
unrelated cwd — that measurement is what would eventually justify defaulting
`remove_cwd=True`, and it has not been made yet, so the default stays
`False`.
