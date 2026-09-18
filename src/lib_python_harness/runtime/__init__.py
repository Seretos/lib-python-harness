"""Runtime: lifecycle (`RunState` + transitions), process control (spawn,
signal, reap) and the run store (`RunStore` protocol + implementations).

Nothing here is re-exported at the top level; import from the submodules
directly (`lib_python_harness.runtime.lifecycle`, `.process`, `.store`).
"""
from __future__ import annotations
