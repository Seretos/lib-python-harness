# lib-python-harness

Provider-independent subagent engine: lifecycle, dispatch and transport abstraction.

A pure Python library — no binary, no MCP, no marketplace. Consumed as
source by downstream projects via a git pin.

## Install

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

## Usage

```python
import lib_python_harness

print(lib_python_harness.__version__)
```

See `src/lib_python_harness/__init__.py` for the public API (`__all__`).

## Develop

```bash
pip install -e ".[test]"
python -m pytest
```

## Versioning

Semantic versioning. The `version` in `pyproject.toml` is a placeholder
on `main` — the release workflow stamps it onto the `release/Nx` branch
and the `vX.Y.Z` tag. Don't hand-bump it.
