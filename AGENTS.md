<!-- AGENTS.md authoring rule (keep this comment in the template; delete it in a real lib):
     Document ONLY what an agent cannot derive by reading the code and the file tree.
     - DO capture: cross-file / cross-repo contracts, non-obvious conventions, gotchas and
       their "why", external requirements, and deliberate design choices.
     - DON'T restate: the directory layout, what a workflow YAML does step-by-step, or how a
       build script works line-by-line — an agent reads those directly. If a sentence only
       narrates a file the reader already has in front of them, cut it.
     A lean AGENTS.md the agent trusts beats an exhaustive one it has to re-verify. -->

# lib-python-harness — agent guide

Provider-independent subagent engine: lifecycle, dispatch and transport abstraction.

A pure Python utility library: it supplies the *mechanism*; any *policy*
(names, paths, env-vars) is caller-supplied. This file tells any AI coding
agent how to operate in this repo. Keep it generic — behaviour lives in
the code and in skills.

## Tool priority

Tool priority: see the ecosystem root AGENTS.md — skills and MCP tools
before raw file tools.

## Working on a ticket

Ticket work is driven by the ecosystem orchestrator
(`agent-ticket-orchestrator`), which prepares the worktree and branch and
dispatches the work package. It is never done by hand on `main`.

## Repo specifics (minimal by design)

- **Language:** Python (≥ 3.11), src-layout under `src/`, package
  `lib_python_harness`.
- **What it is:** a leaf dependency — a small, pure-Python library with no
  side effects on import. Keep the dependency surface small; this library
  is consumed by other projects via `git+https://.../@vX.Y.Z`.
- **Public API:** re-exported from `src/lib_python_harness/__init__.py`. Any
  change to those exports, their signatures, or their behaviour is a
  breaking change for consumers — keep `__all__`, the README, and the
  version in sync.
- **Tests:** `python -m pytest`. Install dev deps with
  `pip install -e ".[test]"`. Every behaviour change needs a test under
  `tests/` (one module per source module).
- **Version is pipeline-owned.** The `version` in `pyproject.toml` is a
  placeholder on `main`; `release.yml` stamps it onto the `release/Nx`
  branch and the `vX.Y.Z` tag. Never hand-bump it.
- **Branch discipline:** All feature work happens on a feature branch in a
  git worktree, never on `main`. Assume the worktree and branch already
  exist and that you are inside them.
- **AI attribution:** The project-issues MCP automatically prefixes every
  comment and PR body with `#ai-generated`. Never type that prefix yourself.

## Downstream dependency notifications

Each release opens a "bump me" ticket in every consumer repo automatically,
via one step in `.github/workflows/release.yml` that calls the central action
`seretos-agents/modular-software-factory-dev/.github/actions/notify-consumers@main`. The action
owns ticket title, body, labels and board placement; this repo only supplies
the facts (version, source repo, consumer list, token). A notification
failure fails the release run itself (no `continue-on-error`) — silently
missing bump tickets is worse than a red run.

- **Consumer list:** the `consumers:` input of that step in `release.yml`
  (one `owner/repo` per line). Add a line when a repo starts pinning this lib.
- **Human prerequisite — `ECOSYSTEM_TOKEN`:** a repository secret (Settings ->
  Secrets -> Actions) holding a classic PAT with `repo` and `project` scope.
  Without it the step fails the release run. Creating/rotating it is a
  human task.
- **Catch-up:** if a notification was skipped or failed, re-file it with the
  `open-dep-ticket` workflow in the meta-repo.
